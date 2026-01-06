#!/usr/bin/env python3
"""
Convert Obsidian-style wikilinks to GitHub-compatible Markdown links.

Obsidian format:
  [[Target]]                    -> Uses filename as display text
  [[Target|Display Text]]       -> Uses custom display text
  [[Target#Section]]            -> Links to heading
  [[Target#Section|Display]]    -> Links to heading with custom text

GitHub format:
  [Display Text](relative/path/to/Target.md)
  [Display Text](relative/path/to/Target.md#section)

Usage:
  python convert_wikilinks.py [--dry-run] [directory]

Options:
  --dry-run    Show what would be changed without modifying files
  directory    Directory to process (default: parent of tools/)
"""

import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def find_markdown_files(root_dir: Path) -> List[Path]:
    """Find all .md files in directory tree."""
    return list(root_dir.rglob("*.md"))


def build_file_index(root_dir: Path) -> Dict[str, List[Path]]:
    """Build index mapping filename (without extension) to file paths."""
    index: Dict[str, List[Path]] = {}
    for md_file in find_markdown_files(root_dir):
        name = md_file.stem  # filename without extension
        if name not in index:
            index[name] = []
        index[name].append(md_file)
    return index


def normalize_anchor(heading: str) -> str:
    """Convert heading text to GitHub-style anchor."""
    # GitHub anchor rules:
    # - lowercase
    # - spaces become hyphens
    # - remove punctuation except hyphens
    # - consecutive hyphens collapse to one
    anchor = heading.lower()
    anchor = re.sub(r'[^\w\s-]', '', anchor)  # remove punctuation
    anchor = re.sub(r'\s+', '-', anchor)       # spaces to hyphens
    anchor = re.sub(r'-+', '-', anchor)        # collapse multiple hyphens
    anchor = anchor.strip('-')
    return anchor


def resolve_target(
    target_name: str,
    file_index: Dict[str, List[Path]],
    source_file: Path,
    root_dir: Path
) -> Tuple[Optional[Path], Optional[str]]:
    """
    Resolve wikilink target to file path.
    
    Returns:
        (resolved_path, error_message)
        - If found uniquely: (path, None)
        - If not found: (None, "file not found")
        - If ambiguous: (None, "ambiguous link")
    """
    # Handle anchors
    anchor = ""
    if "#" in target_name:
        target_name, anchor = target_name.split("#", 1)
        anchor = "#" + normalize_anchor(anchor)
    
    # Normalize target name (replace spaces with underscores for lookup)
    lookup_names = [
        target_name,
        target_name.replace(" ", "_"),
        target_name.replace("_", " "),
        target_name.replace("-", "_"),
        target_name.replace("_", "-"),
    ]
    
    matches = []
    for name in lookup_names:
        if name in file_index:
            for path in file_index[name]:
                if path not in matches:
                    matches.append(path)
    
    if len(matches) == 0:
        return None, "file not found"
    elif len(matches) > 1:
        # Try to find best match based on proximity or exact name
        exact_matches = [m for m in matches if m.stem == target_name or m.stem == target_name.replace(" ", "_")]
        if len(exact_matches) == 1:
            matches = exact_matches
        else:
            return None, "ambiguous link"
    
    return matches[0], anchor if anchor else None


def compute_relative_path(source_file: Path, target_file: Path, root_dir: Path) -> str:
    """Compute relative path from source to target."""
    source_dir = source_file.parent
    try:
        rel_path = os.path.relpath(target_file, source_dir)
        # Normalize to forward slashes for markdown
        return rel_path.replace(os.sep, "/")
    except ValueError:
        # Different drives on Windows
        return target_file.as_posix()


def convert_wikilink(
    match: re.Match,
    file_index: Dict[str, List[Path]],
    source_file: Path,
    root_dir: Path
) -> Tuple[str, Optional[str]]:
    """
    Convert a single wikilink match to GitHub markdown.
    
    Returns:
        (converted_text, warning_message or None)
    """
    full_match = match.group(0)
    inner = match.group(1)  # Content between [[ and ]]
    
    # Parse target and display text
    if "|" in inner:
        target, display = inner.split("|", 1)
    else:
        target = inner
        # For display, use the part after # if present, else the target name
        if "#" in target:
            base, section = target.split("#", 1)
            display = section if not base else target.replace("#", " - ")
        else:
            display = target
    
    target = target.strip()
    display = display.strip()
    
    # Resolve target
    resolved_path, error_or_anchor = resolve_target(target, file_index, source_file, root_dir)
    
    if resolved_path is None:
        # Could not resolve - return original with TODO comment
        error = error_or_anchor
        return f"[{display}]({target.replace(' ', '_')}.md) <!-- TODO: {error} -->", error
    
    # Compute relative path
    rel_path = compute_relative_path(source_file, resolved_path, root_dir)
    
    # Add anchor if present
    anchor = error_or_anchor if error_or_anchor else ""
    
    return f"[{display}]({rel_path}{anchor})", None


def process_file(
    file_path: Path,
    file_index: Dict[str, List[Path]],
    root_dir: Path,
    dry_run: bool = False
) -> Tuple[int, List[str]]:
    """
    Process a single file, converting wikilinks.
    
    Returns:
        (number_of_conversions, list_of_warnings)
    """
    # Wikilink pattern: [[...]] but not already converted (not preceded by ])
    wikilink_pattern = re.compile(r'(?<!\])\[\[([^\[\]]+)\]\]')
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    conversions = 0
    warnings = []
    
    def replace_func(match: re.Match) -> str:
        nonlocal conversions, warnings
        converted, warning = convert_wikilink(match, file_index, file_path, root_dir)
        conversions += 1
        if warning:
            warnings.append(f"  {match.group(0)} -> {warning}")
        return converted
    
    content = wikilink_pattern.sub(replace_func, content)
    
    if content != original_content and not dry_run:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
    
    return conversions, warnings


def main():
    # Parse arguments
    dry_run = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    
    # Determine root directory
    if args:
        root_dir = Path(args[0]).resolve()
    else:
        # Default: parent of tools/ directory
        script_dir = Path(__file__).parent
        root_dir = script_dir.parent
    
    if not root_dir.exists():
        print(f"Error: Directory not found: {root_dir}")
        sys.exit(1)
    
    print(f"Processing directory: {root_dir}")
    if dry_run:
        print("DRY RUN - no files will be modified\n")
    
    # Build file index
    file_index = build_file_index(root_dir)
    print(f"Indexed {sum(len(v) for v in file_index.values())} markdown files\n")
    
    # Process all markdown files
    total_conversions = 0
    total_warnings = []
    files_modified = 0
    
    for md_file in find_markdown_files(root_dir):
        conversions, warnings = process_file(md_file, file_index, root_dir, dry_run)
        if conversions > 0:
            rel_path = md_file.relative_to(root_dir)
            print(f"{rel_path}: {conversions} link(s) converted")
            files_modified += 1
            total_conversions += conversions
            if warnings:
                total_warnings.extend([f"{rel_path}:{w}" for w in warnings])
    
    # Summary
    print(f"\n{'=' * 50}")
    print(f"Total: {total_conversions} links converted in {files_modified} files")
    
    if total_warnings:
        print(f"\nWarnings ({len(total_warnings)}):")
        for w in total_warnings:
            print(f"  {w}")
        print("\nMissing targets need to be created or links corrected.")
        print("Ambiguous links need manual resolution.")
    
    if dry_run:
        print("\nThis was a dry run. Run without --dry-run to apply changes.")


if __name__ == "__main__":
    main()

