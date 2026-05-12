#!/usr/bin/env bash
# Usage: bash scripts/cleanup.sh
#
# Scans $SDD_WORKDIR for task directories that contain a git worktree (repo/).
# For each, fetches the Jira status. If Resolved:
#   1. Removes the git worktree via `git worktree remove`
#   2. Deletes the local branch from the main repo
#   3. Deletes the entire task directory (spec files, description.md, comments.md etc.)
#
# Required env: SDD_WORKDIR
# Required CLI: acli, jq, git

set -euo pipefail

command -v acli >/dev/null 2>&1 || { echo "Missing required command: acli" >&2; exit 1; }
command -v jq   >/dev/null 2>&1 || { echo "Missing required command: jq"   >&2; exit 1; }
[[ -n "${SDD_WORKDIR:-}" ]] || { echo "SDD_WORKDIR is not set" >&2; exit 1; }

# ---------------------------------------------------------------------------
# remove_worktree <repo_dir>
#
# Removes a git worktree and its associated local branch from the main repo.
# Safe to call even if the worktree directory is in a broken state.
# ---------------------------------------------------------------------------
remove_worktree() {
  local repo_dir="$1"
  local git_file="$repo_dir/.git"

  if [[ ! -f "$git_file" ]]; then
    rm -rf "$repo_dir"
    echo "  repo/ removed (no .git file — plain directory)."
    return
  fi

  # Derive branch name from issue type (same logic as snapshot.sh)
  local branch
  if [[ "$issue_type" == "Bug" ]]; then
    branch="bugfix/$key"
  else
    branch="feature/$key"
  fi

  # Resolve main repo from worktree's git common dir
  local common_git_dir main_repo
  common_git_dir="$(git -C "$repo_dir" rev-parse --git-common-dir)"
  main_repo="$(dirname "$common_git_dir")"

  # Remove worktree
  if git -C "$main_repo" worktree remove --force "$repo_dir" 2>/dev/null; then
    echo "  git worktree removed."
  else
    rm -rf "$repo_dir"
    echo "  repo/ removed (worktree remove failed — deleted manually)."
  fi

  # Delete local branch if it exists
  if git -C "$main_repo" rev-parse --verify "$branch" > /dev/null 2>&1; then
    git -C "$main_repo" branch -D "$branch"
    echo "  local branch '$branch' deleted."
  else
    echo "  branch '$branch' not found — skipping."
  fi
}

# ---------------------------------------------------------------------------

CLEANED=0
SKIPPED=0
ERRORS=0

for task_dir in "$SDD_WORKDIR"/*/; do
  [[ -d "$task_dir" ]] || continue
  repo_dir="${task_dir}repo"
  [[ -d "$repo_dir" ]] || continue

  key="$(basename "$task_dir")"

  local_json="$(acli jira workitem view "$key" --fields 'status,issuetype' --json 2>/dev/null || echo "ERROR")"

  if [[ "$local_json" == "ERROR" ]]; then
    echo "  WARN: Could not fetch status for $key — skipping."
    (( ERRORS++ )) || true
    continue
  fi

  status="$(echo "$local_json" | jq -r '.fields.status.name' 2>/dev/null || echo "")"
  issue_type="$(echo "$local_json" | jq -r '.fields.issuetype.name' 2>/dev/null || echo "")"

  if [[ -z "$status" ]]; then
    echo "  WARN: Could not parse status for $key — skipping."
    (( ERRORS++ )) || true
    continue
  fi

  echo "$key  →  $status"

  if [[ "$status" == "Resolved" ]]; then
    remove_worktree "$repo_dir"
    rm -rf "$task_dir"
    echo "  ✓ Cleaned up $key (entire directory removed)"
    (( CLEANED++ )) || true
  else
    (( SKIPPED++ )) || true
  fi
done

echo ""
echo "Done.  Cleaned: $CLEANED  Skipped: $SKIPPED  Errors: $ERRORS"
