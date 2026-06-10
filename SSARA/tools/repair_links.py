#!/usr/bin/env python3
"""
Analyze and repair Obsidian wikilink structure.

This script analyzes wikilinks in markdown files and attempts to find
the correct target files, accounting for:
- Spaces vs underscores in filenames
- Different path prefixes (partial paths)
- Case differences
- Missing file extensions
- Images and other assets

It outputs a report and can optionally fix the wikilinks in-place.

Usage:
  python repair_links.py [options] [directory]

Options:
  --fix              Apply fixes to wikilinks (default: report only)
  --report FILE      Write report to file (default: stdout)
  --ignore PATTERN   Ignore directories matching pattern (can be repeated)
                     Example: --ignore 11-Temp --ignore Archive
  directory          Directory to process (default: parent of tools/)

Examples:
  python repair_links.py --ignore 11-Temp
  python repair_links.py --ignore 11-Temp --ignore Archive --fix
  python repair_links.py --report report.md /path/to/docs
"""

import os
import re
import sys
import fnmatch
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass, field
from collections import defaultdict


# File extensions for different asset types
IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.bmp', '.ico']
DOCUMENT_EXTENSIONS = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx']
OTHER_EXTENSIONS = ['.canvas', '.json', '.xml', '.csv', '.txt']
ASSET_EXTENSIONS = IMAGE_EXTENSIONS + DOCUMENT_EXTENSIONS + OTHER_EXTENSIONS


@dataclass
class WikiLink:
    """Represents a wikilink found in a file."""
    source_file: Path
    target: str           # Original target text
    display: str          # Display text (after |)
    anchor: str           # Section anchor (after #)
    line_num: int
    full_match: str       # Original [[...]] text
    
    def target_normalized(self) -> str:
        """Normalize target for matching."""
        t = self.target
        # Remove path prefixes like "SSA_Spiller/"
        if "/" in t:
            t = t.split("/")[-1]
        # Remove extension if present
        for ext in ASSET_EXTENSIONS + ['.md']:
            if t.lower().endswith(ext):
                t = t[:-len(ext)]
                break
        # Normalize spaces/underscores
        return t.lower().replace(" ", "_").replace("-", "_")
    
    def get_extension(self) -> Optional[str]:
        """Get file extension from target if present."""
        target_lower = self.target.lower()
        for ext in ASSET_EXTENSIONS:
            if target_lower.endswith(ext):
                return ext
        return None
    
    def is_asset(self) -> bool:
        """Check if this links to an asset (image, pdf, etc)."""
        return self.get_extension() is not None


@dataclass 
class FileInfo:
    """Information about a file."""
    path: Path
    stem: str             # Filename without extension
    stem_normalized: str  # Normalized for matching
    extension: str        # File extension
    is_markdown: bool
    

@dataclass
class LinkAnalysis:
    """Analysis result for a wikilink."""
    link: WikiLink
    status: str           # 'ok', 'fixable', 'ambiguous', 'not_found', 'external'
    matches: List[Path] = field(default_factory=list)
    suggested_target: Optional[str] = None
    note: str = ""


def should_ignore(path: Path, ignore_patterns: List[str]) -> bool:
    """Check if path should be ignored based on patterns."""
    path_str = str(path)
    for pattern in ignore_patterns:
        # Check if any part of the path matches the pattern
        for part in path.parts:
            if fnmatch.fnmatch(part, pattern) or fnmatch.fnmatch(part, f"*{pattern}*"):
                return True
        # Also check full path
        if fnmatch.fnmatch(path_str, f"*{pattern}*"):
            return True
    return False


def find_all_files(root_dir: Path, ignore_patterns: List[str]) -> List[FileInfo]:
    """Find all relevant files (markdown and assets) and build file info list."""
    files = []
    
    # Find markdown files
    for md_file in root_dir.rglob("*.md"):
        if should_ignore(md_file, ignore_patterns):
            continue
        stem = md_file.stem
        normalized = stem.lower().replace(" ", "_").replace("-", "_")
        files.append(FileInfo(
            path=md_file, 
            stem=stem, 
            stem_normalized=normalized,
            extension='.md',
            is_markdown=True
        ))
    
    # Find asset files
    for ext in ASSET_EXTENSIONS:
        for asset_file in root_dir.rglob(f"*{ext}"):
            if should_ignore(asset_file, ignore_patterns):
                continue
            stem = asset_file.stem
            normalized = stem.lower().replace(" ", "_").replace("-", "_")
            files.append(FileInfo(
                path=asset_file,
                stem=stem,
                stem_normalized=normalized,
                extension=ext,
                is_markdown=False
            ))
    
    return files


def extract_wikilinks(file_path: Path) -> List[WikiLink]:
    """Extract all wikilinks from a file."""
    wikilink_pattern = re.compile(r'\[\[([^\[\]]+)\]\]')
    links = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                for match in wikilink_pattern.finditer(line):
                    inner = match.group(1)
                    
                    # Parse target, display, anchor
                    display = ""
                    anchor = ""
                    target = inner
                    
                    if "|" in target:
                        target, display = target.split("|", 1)
                    
                    if "#" in target:
                        target, anchor = target.split("#", 1)
                    
                    if not display:
                        display = target
                    
                    links.append(WikiLink(
                        source_file=file_path,
                        target=target.strip(),
                        display=display.strip(),
                        anchor=anchor.strip(),
                        line_num=line_num,
                        full_match=match.group(0)
                    ))
    except Exception as e:
        print(f"Error reading {file_path}: {e}", file=sys.stderr)
    
    return links


def find_matching_files(link: WikiLink, files: List[FileInfo], root_dir: Path) -> List[Path]:
    """Find files that match the wikilink target."""
    target = link.target
    target_normalized = link.target_normalized()
    target_ext = link.get_extension()
    
    # Extract just the filename part (last component of path)
    if "/" in target:
        target_filename = target.split("/")[-1]
    else:
        target_filename = target
    
    # Remove extension from filename for matching
    for ext in ASSET_EXTENSIONS + ['.md']:
        if target_filename.lower().endswith(ext):
            target_filename = target_filename[:-len(ext)]
            break
    
    target_filename_norm = target_filename.lower().replace(" ", "_").replace("-", "_")
    
    matches = []
    
    for f in files:
        # If link specifies an extension, only match files with that extension
        if target_ext and f.extension.lower() != target_ext.lower():
            continue
        
        # If link is for markdown (no extension), only match markdown files
        if not target_ext and not f.is_markdown:
            continue
        
        # Exact stem match
        if f.stem == target_filename or f.stem == target:
            matches.append(f.path)
            continue
        
        # Normalized match
        if f.stem_normalized == target_filename_norm or f.stem_normalized == target_normalized:
            matches.append(f.path)
            continue
    
    # Remove duplicates while preserving order
    seen = set()
    unique_matches = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            unique_matches.append(m)
    
    return unique_matches


def compute_relative_target(source_file: Path, target_file: Path, root_dir: Path) -> str:
    """Compute the wikilink target path from source to target."""
    # Get paths relative to root
    target_rel = target_file.relative_to(root_dir)
    
    # Build path: folder/filename (without .md extension for markdown)
    target_parts = list(target_rel.parts)
    filename = target_parts[-1]
    
    # Remove .md extension for markdown files
    if filename.endswith('.md'):
        target_parts[-1] = filename[:-3]
    
    return "/".join(target_parts)


def analyze_link(link: WikiLink, files: List[FileInfo], root_dir: Path) -> LinkAnalysis:
    """Analyze a single wikilink and determine its status."""
    target = link.target
    
    # Skip external links
    if target.startswith('http://') or target.startswith('https://'):
        return LinkAnalysis(link=link, status='external', note='External link')
    
    # Find matching files
    matches = find_matching_files(link, files, root_dir)
    
    if len(matches) == 0:
        asset_type = ""
        if link.is_asset():
            ext = link.get_extension()
            if ext in IMAGE_EXTENSIONS:
                asset_type = " (image)"
            elif ext in DOCUMENT_EXTENSIONS:
                asset_type = " (document)"
            else:
                asset_type = " (asset)"
        return LinkAnalysis(
            link=link, 
            status='not_found',
            note=f'No matching file found for "{target}"{asset_type}'
        )
    
    if len(matches) == 1:
        # Single match - check if it needs fixing
        match_path = matches[0]
        suggested = compute_relative_target(link.source_file, match_path, root_dir)
        
        # Check if current target already works
        current_norm = link.target_normalized()
        match_norm = match_path.stem.lower().replace(" ", "_").replace("-", "_")
        
        if current_norm == match_norm or link.target == match_path.stem:
            return LinkAnalysis(
                link=link,
                status='ok',
                matches=matches,
                suggested_target=suggested,
                note='Link is valid'
            )
        else:
            return LinkAnalysis(
                link=link,
                status='fixable',
                matches=matches,
                suggested_target=suggested,
                note=f'Can be fixed to: {suggested}'
            )
    
    # Multiple matches - ambiguous
    return LinkAnalysis(
        link=link,
        status='ambiguous',
        matches=matches,
        note=f'Multiple matches: {", ".join(m.stem for m in matches)}'
    )


def generate_report(analyses: List[LinkAnalysis], root_dir: Path, ignore_patterns: List[str]) -> str:
    """Generate a markdown report of the analysis."""
    lines = [
        "# Wikilink Analysis Report",
        "",
        f"**Root directory:** `{root_dir}`",
    ]
    
    if ignore_patterns:
        lines.append(f"**Ignored patterns:** {', '.join(f'`{p}`' for p in ignore_patterns)}")
    
    lines.append("")
    
    # Group by status
    by_status = defaultdict(list)
    for a in analyses:
        by_status[a.status].append(a)
    
    # Summary
    lines.extend([
        "## Summary",
        "",
        "| Status | Count |",
        "|--------|-------|",
        f"| ✅ OK | {len(by_status['ok'])} |",
        f"| 🔧 Fixable | {len(by_status['fixable'])} |",
        f"| ⚠️ Ambiguous | {len(by_status['ambiguous'])} |",
        f"| ❌ Not Found | {len(by_status['not_found'])} |",
        f"| 🔗 External | {len(by_status['external'])} |",
        f"| **Total** | **{len(analyses)}** |",
        "",
    ])
    
    # Fixable links
    if by_status['fixable']:
        lines.extend([
            "## 🔧 Fixable Links",
            "",
            "These links can be automatically fixed:",
            "",
            "| Source File | Line | Current Target | Suggested Fix |",
            "|-------------|------|----------------|---------------|",
        ])
        for a in by_status['fixable']:
            src = a.link.source_file.relative_to(root_dir)
            lines.append(f"| `{src}` | {a.link.line_num} | `{a.link.target}` | `{a.suggested_target}` |")
        lines.append("")
    
    # Ambiguous links
    if by_status['ambiguous']:
        lines.extend([
            "## ⚠️ Ambiguous Links",
            "",
            "These links match multiple files and need manual resolution:",
            "",
        ])
        for a in by_status['ambiguous']:
            src = a.link.source_file.relative_to(root_dir)
            lines.append(f"- **`{src}`:{a.link.line_num}** - `[[{a.link.target}]]`")
            lines.append(f"  - Matches: {', '.join(f'`{m.relative_to(root_dir)}`' for m in a.matches)}")
        lines.append("")
    
    # Not found links - separate by type
    not_found = by_status['not_found']
    if not_found:
        # Separate images/assets from markdown links
        images = [a for a in not_found if a.link.get_extension() in IMAGE_EXTENSIONS]
        documents = [a for a in not_found if a.link.get_extension() in DOCUMENT_EXTENSIONS]
        other_assets = [a for a in not_found if a.link.get_extension() in OTHER_EXTENSIONS]
        markdown = [a for a in not_found if not a.link.is_asset()]
        
        if markdown:
            lines.extend([
                "## ❌ Not Found - Markdown Links",
                "",
                "These links have no matching markdown file:",
                "",
            ])
            by_target = defaultdict(list)
            for a in markdown:
                by_target[a.link.target].append(a)
            
            for target, analyses_for_target in sorted(by_target.items()):
                lines.append(f"### `{target}`")
                lines.append("")
                lines.append("Referenced from:")
                for a in analyses_for_target:
                    src = a.link.source_file.relative_to(root_dir)
                    lines.append(f"- `{src}`:{a.link.line_num}")
                lines.append("")
        
        if images:
            lines.extend([
                "## 🖼️ Not Found - Images",
                "",
                "These image links have no matching file:",
                "",
            ])
            by_target = defaultdict(list)
            for a in images:
                by_target[a.link.target].append(a)
            
            for target, analyses_for_target in sorted(by_target.items()):
                sources = [f"`{a.link.source_file.relative_to(root_dir)}`:{a.link.line_num}" 
                          for a in analyses_for_target]
                lines.append(f"- `{target}` - from: {', '.join(sources)}")
            lines.append("")
        
        if documents:
            lines.extend([
                "## 📄 Not Found - Documents",
                "",
                "These document links have no matching file:",
                "",
            ])
            by_target = defaultdict(list)
            for a in documents:
                by_target[a.link.target].append(a)
            
            for target, analyses_for_target in sorted(by_target.items()):
                sources = [f"`{a.link.source_file.relative_to(root_dir)}`:{a.link.line_num}" 
                          for a in analyses_for_target]
                lines.append(f"- `{target}` - from: {', '.join(sources)}")
            lines.append("")
        
        if other_assets:
            lines.extend([
                "## 📎 Not Found - Other Assets",
                "",
            ])
            for a in other_assets:
                src = a.link.source_file.relative_to(root_dir)
                lines.append(f"- `{a.link.target}` - from: `{src}`:{a.link.line_num}")
            lines.append("")
    
    return "\n".join(lines)


def apply_fixes(analyses: List[LinkAnalysis], root_dir: Path) -> int:
    """Apply fixable link corrections to files."""
    # Group fixes by source file
    fixes_by_file = defaultdict(list)
    for a in analyses:
        if a.status == 'fixable' and a.suggested_target:
            fixes_by_file[a.link.source_file].append(a)
    
    fixed_count = 0
    
    for file_path, fixes in fixes_by_file.items():
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            for fix in fixes:
                old_link = fix.link.full_match
                # Reconstruct new link
                new_target = fix.suggested_target
                if fix.link.anchor:
                    new_target += "#" + fix.link.anchor
                if fix.link.display and fix.link.display != fix.link.target:
                    new_link = f"[[{new_target}|{fix.link.display}]]"
                else:
                    new_link = f"[[{new_target}]]"
                
                if old_link in content:
                    content = content.replace(old_link, new_link, 1)
                    fixed_count += 1
            
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
                
        except Exception as e:
            print(f"Error fixing {file_path}: {e}", file=sys.stderr)
    
    return fixed_count


def main():
    # Parse arguments
    apply_fix = False
    report_file = None
    ignore_patterns = []
    directory = None
    
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--fix":
            apply_fix = True
            i += 1
        elif arg == "--report" and i + 1 < len(sys.argv):
            report_file = sys.argv[i + 1]
            i += 2
        elif arg == "--ignore" and i + 1 < len(sys.argv):
            ignore_patterns.append(sys.argv[i + 1])
            i += 2
        elif not arg.startswith("--"):
            directory = arg
            i += 1
        else:
            print(f"Unknown option: {arg}", file=sys.stderr)
            i += 1
    
    # Determine root directory
    if directory:
        root_dir = Path(directory).resolve()
    else:
        script_dir = Path(__file__).parent
        root_dir = script_dir.parent
    
    if not root_dir.exists():
        print(f"Error: Directory not found: {root_dir}", file=sys.stderr)
        sys.exit(1)
    
    print(f"Analyzing wikilinks in: {root_dir}", file=sys.stderr)
    if ignore_patterns:
        print(f"Ignoring patterns: {', '.join(ignore_patterns)}", file=sys.stderr)
    
    # Build file index (including assets)
    files = find_all_files(root_dir, ignore_patterns)
    md_count = sum(1 for f in files if f.is_markdown)
    asset_count = len(files) - md_count
    print(f"Found {md_count} markdown files, {asset_count} assets", file=sys.stderr)
    
    # Extract and analyze all wikilinks (only from non-ignored markdown files)
    all_analyses = []
    
    for f in files:
        if not f.is_markdown:
            continue
        links = extract_wikilinks(f.path)
        for link in links:
            analysis = analyze_link(link, files, root_dir)
            all_analyses.append(analysis)
    
    print(f"Analyzed {len(all_analyses)} wikilinks", file=sys.stderr)
    
    # Generate report
    report = generate_report(all_analyses, root_dir, ignore_patterns)
    
    if report_file:
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"Report written to: {report_file}", file=sys.stderr)
    else:
        print(report)
    
    # Apply fixes if requested
    if apply_fix:
        fixed = apply_fixes(all_analyses, root_dir)
        print(f"\nApplied {fixed} fixes", file=sys.stderr)
    else:
        fixable = sum(1 for a in all_analyses if a.status == 'fixable')
        if fixable > 0:
            print(f"\nRun with --fix to apply {fixable} automatic fixes", file=sys.stderr)


if __name__ == "__main__":
    main()
