#!/usr/bin/env python3
"""
convert_wikilinks.py - Convert Obsidian wikilinks to GitHub-compatible markdown.

This script converts Obsidian-style links to standard markdown links that work on GitHub.

USAGE:
    python3 convert_wikilinks.py --root /path/to/docs --report report.md [--apply]
    python3 convert_wikilinks.py --root /path/to/public --source-root /path/to/work --report report.md --apply

OPTIONS:
    --root DIR          Root directory containing markdown files to process (required)
    --source-root DIR   Original source directory for finding images (optional)
                        Used when images aren't copied to --root (base64 embedding)
    --report FILE       Output report file path (required)
    --apply             Apply changes to files (default: dry-run)
    --verbose           Show detailed progress

CONVERSION RULES:
    [[Note Name]]           -> [Note Name](Note_Name.md)
    [[path/to/note]]        -> [note](path/to/note.md)
    [[note|Alias]]          -> [Alias](note.md)
    [[note#Heading]]        -> [note](note.md#heading)
    
IMAGE EMBEDDING (when --source-root is provided):
    ![[image.png]]          -> ![](data:image/png;base64,...) if ≤300KB
    ![[image.png]]          -> Warning blockquote if >300KB
    ![[missing.png]]        -> Error blockquote if file not found

LINK RESOLUTION:
    1. Try exact path match first
    2. Fall back to basename search in published tree
    3. Prefer same-folder matches for ambiguous cases
    4. Log ambiguities to report
"""

import os
import re
import sys
import base64
import mimetypes
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from collections import defaultdict


# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

# Maximum image size for base64 embedding (300 KB)
MAX_IMAGE_SIZE_BYTES = 300 * 1024

# Image extensions and their MIME types
IMAGE_EXTENSIONS = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.webp': 'image/webp',
    '.bmp': 'image/bmp',
    '.ico': 'image/x-icon',
}


# -----------------------------------------------------------------------------
# Data classes
# -----------------------------------------------------------------------------

@dataclass
class FileIndex:
    """Index of all files in the published tree."""
    root: Path
    source_root: Optional[Path] = None  # Original source for finding images
    # Map: normalized basename -> list of relative paths
    by_basename: Dict[str, List[Path]] = field(default_factory=lambda: defaultdict(list))
    # Set of all relative paths (with extension)
    all_paths: Set[Path] = field(default_factory=set)
    # Index of source images (for base64 embedding)
    source_images: Dict[str, Path] = field(default_factory=dict)
    
    def build(self):
        """Build index from root directory."""
        for file_path in self.root.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(self.root)
                self.all_paths.add(rel_path)
                basename = file_path.stem
                normalized = self._normalize(basename)
                self.by_basename[normalized].append(rel_path)
        
        # Build source image index if source_root is provided
        if self.source_root and self.source_root.exists():
            for ext in IMAGE_EXTENSIONS.keys():
                for img_path in self.source_root.rglob(f"*{ext}"):
                    # Index by both full relative path and basename
                    rel_path = img_path.relative_to(self.source_root)
                    self.source_images[str(rel_path)] = img_path
                    self.source_images[img_path.name] = img_path
                    # Also index normalized basename
                    normalized = self._normalize(img_path.stem) + ext.lower()
                    self.source_images[normalized] = img_path
    
    @staticmethod
    def _normalize(name: str) -> str:
        """Normalize a name for matching."""
        return name.lower().replace(" ", "_").replace("-", "_")
    
    def find_source_image(self, target: str) -> Optional[Path]:
        """Find an image in the source directory."""
        if not self.source_root:
            return None
        
        # Try exact match first
        if target in self.source_images:
            return self.source_images[target]
        
        # Try normalized match
        normalized = self._normalize(Path(target).stem)
        ext = Path(target).suffix.lower()
        if normalized + ext in self.source_images:
            return self.source_images[normalized + ext]
        
        # Try just the filename
        filename = Path(target).name
        if filename in self.source_images:
            return self.source_images[filename]
        
        return None
    
    def resolve(self, target: str, source_file: Path) -> Tuple[Optional[Path], str]:
        """
        Resolve a wikilink target to a file path.
        
        Args:
            target: The wikilink target (e.g., "Note Name" or "path/to/note")
            source_file: The file containing the link (for relative resolution)
        
        Returns:
            (resolved_path, status) where status is 'ok', 'ambiguous', or 'not_found'
        """
        # Remove .md extension if present
        if target.lower().endswith('.md'):
            target = target[:-3]
        
        # Check for asset extensions (non-image assets)
        asset_ext = None
        for ext in ['.pdf', '.canvas']:
            if target.lower().endswith(ext):
                asset_ext = ext
                break
        
        # Try exact path match first
        if "/" in target:
            test_path = Path(target)
            if asset_ext:
                if test_path in self.all_paths:
                    return test_path, 'ok'
            else:
                test_path_md = Path(target + ".md")
                if test_path_md in self.all_paths:
                    return test_path_md, 'ok'
        
        # Extract basename for search
        if "/" in target:
            basename = target.split("/")[-1]
        else:
            basename = target
        
        # Remove extension from basename for matching
        if asset_ext:
            basename = basename[:-len(asset_ext)]
        
        normalized = self._normalize(basename)
        
        # Find matches
        candidates = self.by_basename.get(normalized, [])
        
        # Filter by extension
        if asset_ext:
            candidates = [c for c in candidates if c.suffix.lower() == asset_ext.lower()]
        else:
            candidates = [c for c in candidates if c.suffix.lower() == '.md']
        
        if len(candidates) == 0:
            return None, 'not_found'
        
        if len(candidates) == 1:
            return candidates[0], 'ok'
        
        # Multiple matches - prefer same folder
        source_dir = source_file.parent
        same_folder = [c for c in candidates if c.parent == source_dir]
        if len(same_folder) == 1:
            return same_folder[0], 'ok'
        
        # Prefer shortest path
        candidates.sort(key=lambda p: len(p.parts))
        return candidates[0], 'ambiguous'


@dataclass
class ConversionResult:
    """Result of converting a single wikilink."""
    original: str
    converted: str
    source_file: Path
    line_num: int
    status: str  # 'ok', 'ambiguous', 'not_found', 'embed_ok', 'embed_too_large', 'embed_missing'
    note: str = ""


@dataclass
class ConversionReport:
    """Aggregated report of all conversions."""
    results: List[ConversionResult] = field(default_factory=list)
    files_processed: int = 0
    files_modified: int = 0
    
    def add(self, result: ConversionResult):
        self.results.append(result)
    
    def to_markdown(self) -> str:
        """Generate markdown report."""
        lines = [
            "# Wikilink Conversion Report",
            "",
            f"**Generated:** {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Summary",
            "",
            f"- Files processed: {self.files_processed}",
            f"- Files modified: {self.files_modified}",
            f"- Total links converted: {len(self.results)}",
            "",
        ]
        
        # Group by status
        by_status = defaultdict(list)
        for r in self.results:
            by_status[r.status].append(r)
        
        lines.extend([
            "| Status | Count |",
            "|--------|-------|",
            f"| ✅ OK (links) | {len(by_status['ok'])} |",
            f"| ✅ Embedded (base64) | {len(by_status['embed_ok'])} |",
            f"| ⚠️ Ambiguous | {len(by_status['ambiguous'])} |",
            f"| ⚠️ Image too large | {len(by_status['embed_too_large'])} |",
            f"| ❌ Not Found (links) | {len(by_status['not_found'])} |",
            f"| ❌ Missing image | {len(by_status['embed_missing'])} |",
            "",
        ])
        
        # Embedded images
        if by_status['embed_ok']:
            lines.extend([
                "## ✅ Embedded Images (base64)",
                "",
                "These images were successfully embedded:",
                "",
            ])
            for r in by_status['embed_ok']:
                lines.append(f"- `{r.source_file}:{r.line_num}` - `{r.original}` ({r.note})")
            lines.append("")
        
        # Too large images
        if by_status['embed_too_large']:
            lines.extend([
                "## ⚠️ Images Too Large (>300KB)",
                "",
                "These images were replaced with warning placeholders:",
                "",
            ])
            for r in by_status['embed_too_large']:
                lines.append(f"- `{r.source_file}:{r.line_num}` - `{r.original}` ({r.note})")
            lines.append("")
        
        # Missing images
        if by_status['embed_missing']:
            lines.extend([
                "## ❌ Missing Images",
                "",
                "These image files were not found:",
                "",
            ])
            for r in by_status['embed_missing']:
                lines.append(f"- `{r.source_file}:{r.line_num}` - `{r.original}`")
            lines.append("")
        
        # Ambiguous links
        if by_status['ambiguous']:
            lines.extend([
                "## ⚠️ Ambiguous Links",
                "",
                "These links matched multiple files (first match used):",
                "",
            ])
            for r in by_status['ambiguous']:
                lines.append(f"- `{r.source_file}:{r.line_num}` - `{r.original}` → `{r.converted}`")
            lines.append("")
        
        # Not found links
        if by_status['not_found']:
            lines.extend([
                "## ❌ Not Found Links",
                "",
                "These links could not be resolved (converted to inline code):",
                "",
            ])
            by_target = defaultdict(list)
            for r in by_status['not_found']:
                by_target[r.original].append(r)
            
            for target, results in sorted(by_target.items()):
                lines.append(f"### `{target}`")
                for r in results:
                    lines.append(f"- `{r.source_file}:{r.line_num}`")
                lines.append("")
        
        return "\n".join(lines)


# -----------------------------------------------------------------------------
# Conversion functions
# -----------------------------------------------------------------------------

def normalize_anchor(heading: str) -> str:
    """Convert heading text to GitHub-compatible anchor."""
    anchor = heading.lower()
    anchor = re.sub(r'[^\w\s-]', '', anchor)
    anchor = re.sub(r'\s+', '-', anchor)
    anchor = re.sub(r'-+', '-', anchor)
    anchor = anchor.strip('-')
    return anchor


def url_encode_path(path: str) -> str:
    """URL-encode a path for use in markdown links."""
    parts = path.split('/')
    encoded_parts = [urllib.parse.quote(p, safe='.-_') for p in parts]
    return '/'.join(encoded_parts)


def get_image_mime_type(filename: str) -> str:
    """Get MIME type for an image file."""
    ext = Path(filename).suffix.lower()
    return IMAGE_EXTENSIONS.get(ext, 'application/octet-stream')


def is_image_file(filename: str) -> bool:
    """Check if filename is an image."""
    ext = Path(filename).suffix.lower()
    return ext in IMAGE_EXTENSIONS


def embed_image_as_base64(image_path: Path) -> Tuple[str, str, str]:
    """
    Read image and convert to base64 data URI.
    
    Returns:
        (data_uri, status, note)
        - status: 'ok', 'too_large', 'missing'
    """
    if not image_path.exists():
        return "", "missing", "File not found"
    
    file_size = image_path.stat().st_size
    
    if file_size > MAX_IMAGE_SIZE_BYTES:
        size_kb = file_size / 1024
        return "", "too_large", f"{size_kb:.1f} KB"
    
    try:
        with open(image_path, 'rb') as f:
            image_data = f.read()
        
        mime_type = get_image_mime_type(image_path.name)
        b64_data = base64.b64encode(image_data).decode('ascii')
        data_uri = f"data:{mime_type};base64,{b64_data}"
        size_kb = file_size / 1024
        return data_uri, "ok", f"{size_kb:.1f} KB"
    
    except Exception as e:
        return "", "missing", str(e)


def make_relative_path(from_file: Path, to_file: Path) -> str:
    """
    Compute the relative path from one file to another.
    
    Args:
        from_file: The source file (markdown file containing the link)
        to_file: The target file (file being linked to)
    
    Returns:
        Relative path string for use in markdown link
    """
    # Get directory of source file
    from_dir = from_file.parent
    
    # Compute relative path from source directory to target file
    try:
        rel_path = os.path.relpath(to_file, from_dir)
        # Normalize to forward slashes for markdown
        return rel_path.replace(os.sep, '/')
    except ValueError:
        # On Windows, relpath can fail across drives
        return str(to_file).replace(os.sep, '/')


def convert_wikilink(
    match: re.Match,
    source_file: Path,
    file_index: FileIndex,
    report: ConversionReport,
    line_num: int
) -> str:
    """Convert a single wikilink match to GitHub markdown."""
    full_match = match.group(0)
    is_embed = full_match.startswith('!')
    inner = match.group(1)
    
    # Parse target, display, anchor
    display = ""
    anchor = ""
    target = inner
    
    if "|" in target:
        target, display = target.split("|", 1)
    
    if "#" in target:
        target, anchor = target.split("#", 1)
    
    target = target.strip()
    anchor = anchor.strip()
    display = display.strip()
    
    # Default display text
    if not display:
        if "/" in target:
            display = target.split("/")[-1]
        else:
            display = target
    
    # Handle image embeds specially
    if is_embed and is_image_file(target):
        return convert_image_embed(target, source_file, file_index, report, line_num)
    
    # Regular link resolution
    resolved_path, status = file_index.resolve(target, source_file)
    
    if resolved_path is None:
        # Not found - convert to inline code
        result = ConversionResult(
            original=target,
            converted=f"`{display}`",
            source_file=source_file.relative_to(file_index.root),
            line_num=line_num,
            status='not_found'
        )
        report.add(result)
        return f"`{display}`"
    
    # Build relative path from source file to target file
    # GitHub resolves links relative to the file containing the link
    source_rel = source_file.relative_to(file_index.root)
    rel_path = make_relative_path(source_rel, resolved_path)
    encoded_path = url_encode_path(rel_path)
    
    if anchor:
        encoded_path += "#" + normalize_anchor(anchor)
    
    if is_embed:
        converted = f"![]({encoded_path})"
    else:
        converted = f"[{display}]({encoded_path})"
    
    result = ConversionResult(
        original=target,
        converted=converted,
        source_file=source_file.relative_to(file_index.root),
        line_num=line_num,
        status=status
    )
    report.add(result)
    
    return converted


def convert_image_embed(
    target: str,
    source_file: Path,
    file_index: FileIndex,
    report: ConversionReport,
    line_num: int
) -> str:
    """
    Convert an image embed to base64 or placeholder.
    
    ![[image.png]] -> ![](data:image/png;base64,...) or warning
    """
    # Try to find the image in source directory
    image_path = file_index.find_source_image(target)
    
    if image_path is None:
        # Image not found
        result = ConversionResult(
            original=target,
            converted=f"> ❌ Missing image: `{target}`",
            source_file=source_file.relative_to(file_index.root),
            line_num=line_num,
            status='embed_missing'
        )
        report.add(result)
        return f"\n> ❌ Missing image: `{target}`\n"
    
    # Try to embed as base64
    data_uri, status, note = embed_image_as_base64(image_path)
    
    if status == "ok":
        result = ConversionResult(
            original=target,
            converted="![](data:image/...;base64,...)",  # Truncated for report
            source_file=source_file.relative_to(file_index.root),
            line_num=line_num,
            status='embed_ok',
            note=note
        )
        report.add(result)
        return f"![]({data_uri})"
    
    elif status == "too_large":
        result = ConversionResult(
            original=target,
            converted=f"> ⚠ Image omitted: {target}",
            source_file=source_file.relative_to(file_index.root),
            line_num=line_num,
            status='embed_too_large',
            note=note
        )
        report.add(result)
        return f"\n> ⚠️ Image omitted in public version: `{target}` (too large: {note})\n"
    
    else:  # missing or error
        result = ConversionResult(
            original=target,
            converted=f"> ❌ Missing image: {target}",
            source_file=source_file.relative_to(file_index.root),
            line_num=line_num,
            status='embed_missing',
            note=note
        )
        report.add(result)
        return f"\n> ❌ Missing image: `{target}`\n"


# Global for line number tracking
_current_lines = []

def process_file(
    file_path: Path,
    file_index: FileIndex,
    report: ConversionReport,
    apply: bool = False
) -> bool:
    """
    Process a single markdown file.
    
    Returns True if the file was modified.
    """
    global _current_lines
    
    # Wikilink pattern: [[...]] or ![[...]] for embeds
    wikilink_pattern = re.compile(r'!?\[\[([^\[\]]+)\]\]')
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            _current_lines = content.split('\n')
    except Exception as e:
        print(f"Error reading {file_path}: {e}", file=sys.stderr)
        return False
    
    # Track positions for line number calculation
    def get_line_num(pos: int) -> int:
        return content[:pos].count('\n') + 1
    
    # Convert all wikilinks
    new_content = ""
    last_end = 0
    
    for match in wikilink_pattern.finditer(content):
        new_content += content[last_end:match.start()]
        line_num = get_line_num(match.start())
        converted = convert_wikilink(match, file_path, file_index, report, line_num)
        new_content += converted
        last_end = match.end()
    
    new_content += content[last_end:]
    
    _current_lines = []
    
    if new_content != content:
        if apply:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
        return True
    
    return False


def process_directory(
    root: Path,
    source_root: Optional[Path],
    report: ConversionReport,
    apply: bool = False,
    verbose: bool = False
):
    """Process all markdown files in directory."""
    # Build file index
    file_index = FileIndex(root=root, source_root=source_root)
    file_index.build()
    
    if verbose:
        print(f"Indexed {len(file_index.all_paths)} files in target", file=sys.stderr)
        if source_root:
            print(f"Indexed {len(file_index.source_images)} images in source", file=sys.stderr)
    
    # Process each markdown file
    md_files = list(root.rglob("*.md"))
    report.files_processed = len(md_files)
    
    for md_file in md_files:
        if verbose:
            print(f"Processing: {md_file.relative_to(root)}", file=sys.stderr)
        
        modified = process_file(md_file, file_index, report, apply)
        if modified:
            report.files_modified += 1


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Convert Obsidian wikilinks to GitHub markdown"
    )
    parser.add_argument(
        "--root", required=True,
        help="Root directory containing markdown files to process"
    )
    parser.add_argument(
        "--source-root",
        help="Original source directory for finding images (for base64 embedding)"
    )
    parser.add_argument(
        "--report", required=True,
        help="Output report file path"
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Apply changes to files (default: dry-run)"
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Show detailed progress"
    )
    
    args = parser.parse_args()
    
    root = Path(args.root).resolve()
    if not root.exists():
        print(f"Error: Directory not found: {root}", file=sys.stderr)
        sys.exit(1)
    
    source_root = None
    if args.source_root:
        source_root = Path(args.source_root).resolve()
        if not source_root.exists():
            print(f"Warning: Source directory not found: {source_root}", file=sys.stderr)
            source_root = None
    
    report = ConversionReport()
    
    mode = 'Converting' if args.apply else 'Analyzing'
    print(f"{mode} wikilinks in: {root}", file=sys.stderr)
    if source_root:
        print(f"Source images from: {source_root}", file=sys.stderr)
        print(f"Images ≤{MAX_IMAGE_SIZE_BYTES // 1024}KB will be embedded as base64", file=sys.stderr)
    
    process_directory(root, source_root, report, apply=args.apply, verbose=args.verbose)
    
    # Write report
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report.to_markdown())
    
    print(f"Report written to: {report_path}", file=sys.stderr)
    print(f"Files processed: {report.files_processed}", file=sys.stderr)
    print(f"Files modified: {report.files_modified}", file=sys.stderr)
    print(f"Links converted: {len(report.results)}", file=sys.stderr)
    
    # Summary of issues
    by_status = defaultdict(int)
    for r in report.results:
        by_status[r.status] += 1
    
    if by_status['embed_ok'] > 0:
        print(f"✅ {by_status['embed_ok']} images embedded as base64", file=sys.stderr)
    if by_status['embed_too_large'] > 0:
        print(f"⚠️  {by_status['embed_too_large']} images too large (>300KB)", file=sys.stderr)
    if by_status['embed_missing'] > 0:
        print(f"❌ {by_status['embed_missing']} images not found", file=sys.stderr)
    if by_status['not_found'] > 0:
        print(f"❌ {by_status['not_found']} links not found", file=sys.stderr)
    if by_status['ambiguous'] > 0:
        print(f"⚠️  {by_status['ambiguous']} ambiguous links", file=sys.stderr)


if __name__ == "__main__":
    main()
