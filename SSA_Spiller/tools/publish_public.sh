#!/usr/bin/env bash
#
# publish_public.sh - Publish Obsidian docs to GitHub-compatible public branch
#
# USAGE:
#   cd /path/to/ssa-spiller-docs   # repo root, on branch "work"
#   ./SSA_Spiller/tools/publish_public.sh [--dry-run] [--no-push]
#
# OPTIONS:
#   --dry-run    Prepare files but don't commit or push
#   --no-push    Commit but don't push (skip push prompt)
#
# INTERACTIVE:
#   After committing, the script will ask if you want to push.
#   Git will handle authentication interactively (may prompt for credentials).
#
# REQUIREMENTS:
#   - Must be run from repo root
#   - Must be on branch "work"
#   - python3 must be available
#
# WHAT IT DOES:
#   1. Creates worktree for "public" branch at ../ssa-spiller-docs-public
#   2. Copies README.md and SSA_Spiller/** (excluding ignored paths)
#   3. Converts Obsidian wikilinks to GitHub markdown
#   4. Commits and pushes to "public" branch
#   5. Generates tools/publish_report.md with conversion summary
#
set -euo pipefail

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PUBLIC_WORKTREE="$REPO_ROOT/../ssa-spiller-docs-public"
PUBLIC_BRANCH="public"
WORK_BRANCH="work"

# Files/folders to include
INCLUDE_PATHS=(
    "README.md"
    "SSA_Spiller"
)

# Patterns to exclude (relative to repo root)
EXCLUDE_PATTERNS=(
    "_Archive_OldVault"
    "OpenAI.txt"
    ".obsidian"
    ".git"
    "*.tmp"
    ".DS_Store"
    # Exclude image files - they will be embedded as base64 during conversion
    "*.png"
    "*.jpg"
    "*.jpeg"
    "*.svg"
    "*.gif"
    "*.webp"
    "*.bmp"
)

# Timestamp for commit
TIMESTAMP="$(date '+%Y-%m-%d %H:%M:%S')"

# -----------------------------------------------------------------------------
# Parse arguments
# -----------------------------------------------------------------------------
DRY_RUN=false
NO_PUSH=false

for arg in "$@"; do
    case $arg in
        --dry-run)
            DRY_RUN=true
            ;;
        --no-push)
            NO_PUSH=true
            ;;
        *)
            echo "Unknown option: $arg"
            exit 1
            ;;
    esac
done

# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------
log() {
    echo "[publish] $*"
}

error() {
    echo "[ERROR] $*" >&2
    exit 1
}

# Check if we're on the work branch
check_branch() {
    local current_branch
    current_branch="$(git rev-parse --abbrev-ref HEAD)"
    if [[ "$current_branch" != "$WORK_BRANCH" ]]; then
        error "Must be on branch '$WORK_BRANCH', currently on '$current_branch'"
    fi
}

# Ensure public branch exists (as orphan if needed)
ensure_public_branch() {
    if ! git show-ref --verify --quiet "refs/heads/$PUBLIC_BRANCH"; then
        log "Creating orphan branch '$PUBLIC_BRANCH'..."
        git checkout --orphan "$PUBLIC_BRANCH"
        git rm -rf . 2>/dev/null || true
        git commit --allow-empty -m "Initial public branch"
        git checkout "$WORK_BRANCH"
    fi
}

# Setup or update public worktree
setup_worktree() {
    if [[ -d "$PUBLIC_WORKTREE" ]]; then
        log "Public worktree exists at $PUBLIC_WORKTREE"
        # Verify it's the right branch
        local wt_branch
        wt_branch="$(git -C "$PUBLIC_WORKTREE" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
        if [[ "$wt_branch" != "$PUBLIC_BRANCH" ]]; then
            log "Worktree is on wrong branch, removing and recreating..."
            git worktree remove --force "$PUBLIC_WORKTREE" 2>/dev/null || rm -rf "$PUBLIC_WORKTREE"
            git worktree add "$PUBLIC_WORKTREE" "$PUBLIC_BRANCH"
        fi
    else
        log "Creating public worktree at $PUBLIC_WORKTREE..."
        git worktree add "$PUBLIC_WORKTREE" "$PUBLIC_BRANCH"
    fi
}

# Build rsync exclude arguments
build_excludes() {
    local excludes=()
    for pattern in "${EXCLUDE_PATTERNS[@]}"; do
        excludes+=(--exclude="$pattern")
    done
    # Also exclude based on .gitignore
    excludes+=(--exclude-from="$REPO_ROOT/.gitignore" 2>/dev/null || true)
    echo "${excludes[@]}"
}

# Copy files to public worktree
copy_files() {
    log "Copying files to public worktree..."
    
    # Clear public worktree (except .git)
    find "$PUBLIC_WORKTREE" -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} +
    
    # Build exclude list
    local exclude_args=()
    for pattern in "${EXCLUDE_PATTERNS[@]}"; do
        exclude_args+=(--exclude="$pattern")
    done
    
    # Copy each include path
    for path in "${INCLUDE_PATHS[@]}"; do
        if [[ -e "$REPO_ROOT/$path" ]]; then
            if [[ -d "$REPO_ROOT/$path" ]]; then
                # Directory - use rsync
                mkdir -p "$PUBLIC_WORKTREE/$path"
                rsync -a "${exclude_args[@]}" "$REPO_ROOT/$path/" "$PUBLIC_WORKTREE/$path/"
            else
                # File - direct copy
                cp "$REPO_ROOT/$path" "$PUBLIC_WORKTREE/$path"
            fi
            log "  Copied: $path"
        else
            log "  Warning: $path not found, skipping"
        fi
    done
}

# Convert wikilinks in public worktree
convert_links() {
    log "Converting wikilinks to GitHub format..."
    log "  - Wikilinks will be converted to standard markdown"
    log "  - Images ≤300KB will be embedded as base64"
    log "  - Images >300KB will show warning placeholder"
    
    local report_file="$SCRIPT_DIR/publish_report.md"
    
    # Pass --source-root to find original images for base64 embedding
    python3 "$SCRIPT_DIR/convert_wikilinks.py" \
        --root "$PUBLIC_WORKTREE" \
        --source-root "$REPO_ROOT" \
        --report "$report_file" \
        --apply
    
    log "Conversion report written to: $report_file"
}

# Commit and push changes
commit_and_push() {
    log "Committing changes to public branch..."
    
    cd "$PUBLIC_WORKTREE"
    
    # Stage all changes
    git add -A
    
    # Check if there are changes to commit
    if git diff --cached --quiet; then
        log "No changes to commit"
        return 0
    fi
    
    # Show what will be committed
    echo ""
    log "Changes to be committed:"
    git diff --cached --stat
    echo ""
    
    # Commit
    git commit -m "Publish docs (auto) - $TIMESTAMP"
    log "Committed successfully."
    
    if [[ "$NO_PUSH" == "true" ]]; then
        log "Skipping push (--no-push specified)"
    else
        echo ""
        read -p "[publish] Push to origin/$PUBLIC_BRANCH? (y/N) " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            log "Pushing to origin/$PUBLIC_BRANCH..."
            log "(Git may prompt for credentials)"
            echo ""
            # Let git handle authentication interactively
            if git push origin "$PUBLIC_BRANCH"; then
                log "Push successful!"
            else
                log "Push failed. You can push manually later with:"
                log "  cd $PUBLIC_WORKTREE && git push origin $PUBLIC_BRANCH"
            fi
        else
            log "Push skipped. You can push manually later with:"
            log "  cd $PUBLIC_WORKTREE && git push origin $PUBLIC_BRANCH"
        fi
    fi
    
    cd "$REPO_ROOT"
}

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
main() {
    log "Starting publish process..."
    log "Repo root: $REPO_ROOT"
    log "Public worktree: $PUBLIC_WORKTREE"
    
    # Verify we're in the repo root
    if [[ ! -d "$REPO_ROOT/.git" ]] && [[ ! -f "$REPO_ROOT/.git" ]]; then
        error "Not in a git repository"
    fi
    
    cd "$REPO_ROOT"
    
    # Check we're on work branch
    check_branch
    
    # Ensure public branch exists
    ensure_public_branch
    
    # Setup worktree
    setup_worktree
    
    # Copy files
    copy_files
    
    # Convert links
    convert_links
    
    if [[ "$DRY_RUN" == "true" ]]; then
        log "Dry run complete. Files prepared in: $PUBLIC_WORKTREE"
        log "Review and run without --dry-run to commit."
    else
        # Commit and push
        commit_and_push
        log "Publish complete!"
    fi
}

main "$@"

