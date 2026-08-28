#!/usr/bin/env bash
#
# publish_public.sh - Publish Obsidian docs to GitHub-compatible public branch
#
# USAGE:
#   cd /path/to/ssa-spiller-docs   # repo root, on branch "work"
#   ./SSARA/tools/publish_public.sh [--dry-run] [--no-push]
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
PUBLIC_BRANCH="public"
WORK_BRANCH="work"

# Resolve REPO_ROOT to the worktree that actually has WORK_BRANCH checked out,
# regardless of which copy of this script was invoked. The tools/ dir is rsync'd
# into the public branch, so running that stale copy would otherwise point
# REPO_ROOT at the public worktree and fail the branch check.
work_root="$(git -C "$SCRIPT_DIR" worktree list --porcelain 2>/dev/null \
    | awk -v b="refs/heads/$WORK_BRANCH" '
        /^worktree /{wt=substr($0,10)}
        $0=="branch "b{print wt; exit}')"
if [[ -n "$work_root" ]]; then
    REPO_ROOT="$work_root"
else
    REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
fi
PUBLIC_WORKTREE="$REPO_ROOT/../ssa-spiller-docs-public"

# Files/folders to include
INCLUDE_PATHS=(
    "README.md"
    "SHARED_CONTEXT.md"
    "SSARA"
)

# Patterns to exclude (relative to repo root)
EXCLUDE_PATTERNS=(
    "_Archive_OldVault"
    "OpenAI.txt"
    ".obsidian"
    ".git"
    "*.tmp"
    ".DS_Store"
    # Internal worklog — not for the public docs
    "08-Worklog"
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

show_help() {
    cat << 'EOF'
publish_public.sh - Publish Obsidian docs to GitHub-compatible public branch

USAGE:
    cd /path/to/ssa-spiller-docs     # repo root, on branch "work"
    ./SSARA/tools/publish_public.sh [OPTIONS]

OPTIONS:
    --help       Show this help message and exit
    --dry-run    Prepare files but don't commit or push
                 (useful to inspect the generated output)
    --no-push    Commit but skip the push prompt

WHAT IT DOES:
    1. Creates a git worktree for "public" branch at ../ssa-spiller-docs-public
    2. Copies README.md, SHARED_CONTEXT.md and SSARA/** (excludes .obsidian, images, 11-Temp, etc.)
    3. Converts Obsidian wikilinks [[Note]] to GitHub markdown [Note](path.md)
    4. Embeds images ≤300KB as base64; larger images show warning placeholder
    5. Prompts to commit and push to "public" branch

PREREQUISITES:
    - Must be run from repository root
    - Must be on branch "work"
    - python3 must be available
    - rsync must be available

OUTPUT:
    - ../ssa-spiller-docs-public/    Generated public-ready files
    - tools/publish_report.md        Conversion report (links, images, warnings)

EXAMPLES:
    # Preview what will be published (no changes committed)
    ./SSARA/tools/publish_public.sh --dry-run

    # Publish and commit, but don't push (review first)
    ./SSARA/tools/publish_public.sh --no-push

    # Full publish with interactive push prompt
    ./SSARA/tools/publish_public.sh

EOF
    exit 0
}

for arg in "$@"; do
    case $arg in
        --help|-h)
            show_help
            ;;
        --dry-run)
            DRY_RUN=true
            ;;
        --no-push)
            NO_PUSH=true
            ;;
        *)
            echo "Unknown option: $arg"
            echo "Use --help for usage information."
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
    # Also exclude based on .gitignore if it exists
    if [[ -f "$REPO_ROOT/.gitignore" ]]; then
        excludes+=(--exclude-from="$REPO_ROOT/.gitignore")
    fi
    echo "${excludes[@]}"
}

# Copy files to public worktree.
#
# Sources from `git archive HEAD` so ONLY committed content is published —
# uncommitted or untracked files in the work tree never leak to the public repo.
# EXCLUDE_PATTERNS are translated into git exclude pathspecs.
copy_files() {
    log "Copying committed files (HEAD) to public worktree..."

    # Clear public worktree (except .git)
    find "$PUBLIC_WORKTREE" -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} +

    # Translate exclude patterns into git pathspecs. A bare name (no glob char)
    # is treated as a path segment to drop anywhere in the tree; a glob pattern
    # is matched against the full path.
    local pathspecs=()
    for pattern in "${EXCLUDE_PATTERNS[@]}"; do
        if [[ "$pattern" == *"*"* ]]; then
            pathspecs+=(":(exclude,glob)**/$pattern")
        else
            pathspecs+=(":(exclude)**/$pattern" ":(exclude)**/$pattern/**")
        fi
    done

    # Keep only include paths that are actually committed at HEAD.
    local include_committed=()
    for path in "${INCLUDE_PATHS[@]}"; do
        if git -C "$REPO_ROOT" cat-file -e "HEAD:$path" 2>/dev/null; then
            include_committed+=("$path")
            log "  Including: $path"
        else
            log "  Warning: $path not committed at HEAD, skipping"
        fi
    done

    if [[ ${#include_committed[@]} -eq 0 ]]; then
        error "No committed include paths found at HEAD"
    fi

    # Stream the committed subset straight into the public worktree.
    git -C "$REPO_ROOT" archive --format=tar HEAD -- \
        "${include_committed[@]}" "${pathspecs[@]}" \
        | tar -x -C "$PUBLIC_WORKTREE"
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

# Count local commits on PUBLIC_BRANCH not yet on origin/PUBLIC_BRANCH.
# Echoes an integer (0 if the remote ref is unknown or fully in sync).
unpushed_count() {
    # Best-effort refresh of the remote-tracking ref so "ahead" is accurate.
    git -C "$PUBLIC_WORKTREE" fetch --quiet origin "$PUBLIC_BRANCH" 2>/dev/null || true
    if git -C "$PUBLIC_WORKTREE" rev-parse --verify --quiet \
            "refs/remotes/origin/$PUBLIC_BRANCH" >/dev/null; then
        git -C "$PUBLIC_WORKTREE" rev-list --count \
            "origin/$PUBLIC_BRANCH..$PUBLIC_BRANCH"
    else
        # Remote branch doesn't exist yet: everything local is unpushed.
        git -C "$PUBLIC_WORKTREE" rev-list --count "$PUBLIC_BRANCH"
    fi
}

# Push PUBLIC_BRANCH to origin, tolerating failure so the caller can resume.
# Returns 0 on success, non-zero on failure.
push_public() {
    if [[ "$NO_PUSH" == "true" ]]; then
        log "Skipping push (--no-push specified)"
        return 0
    fi

    local ahead
    ahead="$(unpushed_count)"
    if [[ "$ahead" -eq 0 ]]; then
        log "origin/$PUBLIC_BRANCH is up to date; nothing to push"
        return 0
    fi

    echo ""
    log "$ahead local commit(s) not yet on origin/$PUBLIC_BRANCH:"
    git -C "$PUBLIC_WORKTREE" log --oneline "origin/$PUBLIC_BRANCH..$PUBLIC_BRANCH" 2>/dev/null \
        || git -C "$PUBLIC_WORKTREE" log --oneline -n "$ahead" "$PUBLIC_BRANCH"
    echo ""

    read -p "[publish] Push to origin/$PUBLIC_BRANCH? (y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log "Push skipped. Re-run this script (or push manually) to retry:"
        log "  cd $PUBLIC_WORKTREE && git push origin $PUBLIC_BRANCH"
        return 1
    fi

    # Retry loop: auth failures (mistyped password) are recoverable in place.
    while true; do
        log "Pushing to origin/$PUBLIC_BRANCH... (git may prompt for credentials)"
        echo ""
        if git -C "$PUBLIC_WORKTREE" push origin "$PUBLIC_BRANCH"; then
            log "Push successful!"
            return 0
        fi
        echo ""
        log "Push failed (auth or network?). The commit is safe locally."
        read -p "[publish] Retry push now? (y/N) " -n 1 -r
        echo ""
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            log "Push aborted. Re-run this script (or push manually) to retry:"
            log "  cd $PUBLIC_WORKTREE && git push origin $PUBLIC_BRANCH"
            return 1
        fi
    done
}

# Commit staged changes (if any), then push. Resumes cleanly when a prior run
# already committed but its push failed: no new diff, but push_public still
# detects the unpushed commit and offers to send it.
commit_and_push() {
    cd "$PUBLIC_WORKTREE"

    # Stage all changes
    git add -A

    if git diff --cached --quiet; then
        log "No new changes to commit"
        # A prior run may have committed but failed to push — resume that.
        if [[ "$(unpushed_count)" -gt 0 ]]; then
            log "But local $PUBLIC_BRANCH is ahead of origin — resuming push."
            push_public || true
        fi
        cd "$REPO_ROOT"
        return 0
    fi

    echo ""
    log "Changes to be committed:"
    git diff --cached --stat
    echo ""

    git commit -m "Publish docs (auto) - $TIMESTAMP"
    log "Committed successfully."

    push_public || true

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

