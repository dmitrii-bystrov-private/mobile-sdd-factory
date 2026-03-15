#!/usr/bin/env bash
set -euo pipefail

# snapshot.sh — Prepare a Jira workspace: snapshot artifacts + git worktree.
#
# Usage:
#   bash scripts/snapshot.sh <PARENT-KEY>
#
# Required environment variables:
#   SDD_WORKDIR  — root directory for task workspaces
#   IOS_DIR      — path to iOS repo (mutually exclusive with ANDROID_DIR)
#   ANDROID_DIR  — path to Android repo (mutually exclusive with IOS_DIR)

# ---------------------------------------------------------------------------
# Stage 0: Validate environment and arguments
# ---------------------------------------------------------------------------

usage() {
  cat >&2 <<'EOF'
Usage: bash scripts/snapshot.sh <PARENT-KEY>

Required environment variables:
  SDD_WORKDIR   root directory for task workspaces (e.g. /path/to/workdir)
  IOS_DIR       path to iOS repo  } exactly one must be set and non-empty
  ANDROID_DIR   path to Android repo }
EOF
}

err() {
  echo "ERROR: $*" >&2
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { err "Missing required command: $1"; exit 1; }
}

# 1. Positional argument
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ -z "${1:-}" ]]; then
  err "Missing required argument: PARENT-KEY"
  usage
  exit 1
fi

PARENT_KEY="$1"

# 2. SDD_WORKDIR
if [[ -z "${SDD_WORKDIR:-}" ]]; then
  err "SDD_WORKDIR is not set or empty. Please export SDD_WORKDIR before running."
  exit 1
fi

# 3. Exactly one of IOS_DIR / ANDROID_DIR
IOS_SET=false
ANDROID_SET=false
[[ -n "${IOS_DIR:-}" ]]     && IOS_SET=true
[[ -n "${ANDROID_DIR:-}" ]] && ANDROID_SET=true

if $IOS_SET && $ANDROID_SET; then
  err "Both IOS_DIR and ANDROID_DIR are set. Exactly one must be set."
  exit 1
fi

if ! $IOS_SET && ! $ANDROID_SET; then
  err "Neither IOS_DIR nor ANDROID_DIR is set. Exactly one must be set."
  exit 1
fi

if $IOS_SET; then
  PLATFORM_DIR="$IOS_DIR"
  PLATFORM="ios"
else
  PLATFORM_DIR="$ANDROID_DIR"
  PLATFORM="android"
fi

# 4. Required CLI tools
need_cmd acli
need_cmd jq

echo "Snapshot: $PARENT_KEY  platform=$PLATFORM  workdir=$SDD_WORKDIR"

# ---------------------------------------------------------------------------
# Stage 1: Retrieve Jira data
# ---------------------------------------------------------------------------

TMPDIR_JIRA="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_JIRA"' EXIT

# Paths for parent JSON
PARENT_CORE_JSON="$TMPDIR_JIRA/parent.core.json"
PARENT_COMMENTS_JSON="$TMPDIR_JIRA/parent.comments.json"
SUBTASKS_LIST_JSON="$TMPDIR_JIRA/subtasks.list.json"

echo "Fetching parent $PARENT_KEY..."
if ! acli jira workitem view "$PARENT_KEY" \
    --fields key,issuetype,summary,status,description \
    --json > "$PARENT_CORE_JSON" 2>"$TMPDIR_JIRA/parent.core.err"; then
  err "Failed to retrieve parent issue $PARENT_KEY"
  cat "$TMPDIR_JIRA/parent.core.err" >&2
  exit 1
fi

if ! acli jira workitem view "$PARENT_KEY" \
    --fields key,comment \
    --json > "$PARENT_COMMENTS_JSON" 2>"$TMPDIR_JIRA/parent.comments.err"; then
  err "Failed to retrieve comments for parent issue $PARENT_KEY"
  cat "$TMPDIR_JIRA/parent.comments.err" >&2
  exit 1
fi

echo "Fetching subtask list for $PARENT_KEY..."
if ! acli jira workitem search \
    --jql "parent = $PARENT_KEY ORDER BY key ASC" \
    --fields key,issuetype,summary,status \
    --json --paginate > "$SUBTASKS_LIST_JSON" 2>"$TMPDIR_JIRA/subtasks.list.err"; then
  err "Failed to retrieve subtask list for $PARENT_KEY"
  cat "$TMPDIR_JIRA/subtasks.list.err" >&2
  exit 1
fi

SUBTASK_COUNT="$(jq -r 'length' "$SUBTASKS_LIST_JSON")"
echo "Found $SUBTASK_COUNT subtask(s)"

# Retrieve each subtask; collect failures instead of exiting immediately
FAILED_SUBTASKS=()

if (( SUBTASK_COUNT > 0 )); then
  while IFS= read -r SUBKEY; do
    [[ -n "$SUBKEY" ]] || continue
    echo "Fetching subtask $SUBKEY..."

    SUBKEY_CORE_JSON="$TMPDIR_JIRA/subtask.${SUBKEY}.core.json"
    SUBKEY_COMMENTS_JSON="$TMPDIR_JIRA/subtask.${SUBKEY}.comments.json"
    SUBKEY_OK=true

    if ! acli jira workitem view "$SUBKEY" \
        --fields key,issuetype,summary,status,description \
        --json > "$SUBKEY_CORE_JSON" 2>"$TMPDIR_JIRA/subtask.${SUBKEY}.core.err"; then
      err "Failed to retrieve subtask $SUBKEY (core)"
      cat "$TMPDIR_JIRA/subtask.${SUBKEY}.core.err" >&2
      SUBKEY_OK=false
    fi

    if $SUBKEY_OK; then
      if ! acli jira workitem view "$SUBKEY" \
          --fields key,comment \
          --json > "$SUBKEY_COMMENTS_JSON" 2>"$TMPDIR_JIRA/subtask.${SUBKEY}.comments.err"; then
        err "Failed to retrieve subtask $SUBKEY (comments)"
        cat "$TMPDIR_JIRA/subtask.${SUBKEY}.comments.err" >&2
        SUBKEY_OK=false
      fi
    fi

    if ! $SUBKEY_OK; then
      FAILED_SUBTASKS+=("$SUBKEY")
    fi
  done < <(jq -r '.[].key' "$SUBTASKS_LIST_JSON")
fi

if (( ${#FAILED_SUBTASKS[@]} > 0 )); then
  err "Failed to retrieve the following subtask(s): ${FAILED_SUBTASKS[*]}"
  exit 1
fi

echo "Jira retrieval complete."

# ---------------------------------------------------------------------------
# Stage 2: Create or reuse git worktree
# ---------------------------------------------------------------------------

# Determine branch name from issue type
PARENT_ISSUE_TYPE="$(jq -r '.fields.issuetype.name' "$PARENT_CORE_JSON")"
if [[ "$PARENT_ISSUE_TYPE" == "Bug" ]]; then
  BRANCH_NAME="bugfix/${PARENT_KEY}"
else
  BRANCH_NAME="feature/${PARENT_KEY}"
fi

WORKDIR="$SDD_WORKDIR/$PARENT_KEY"
WORKTREE_PATH="$WORKDIR/repo"

if git -C "$WORKTREE_PATH" rev-parse --is-inside-work-tree > /dev/null 2>&1; then
  echo "Worktree already exists at $WORKTREE_PATH — skipping creation."
  WORKTREE_CREATED=false
else
  echo "Creating worktree at $WORKTREE_PATH on branch $BRANCH_NAME..."
  mkdir -p "$WORKDIR"

  # Ensure master is up to date before branching
  echo "Updating master from origin..."
  git -C "$PLATFORM_DIR" checkout master
  git -C "$PLATFORM_DIR" pull origin master

  # Create worktree; clean up on failure
  if ! git -C "$PLATFORM_DIR" worktree add "$WORKTREE_PATH" -b "$BRANCH_NAME" 2>"$TMPDIR_JIRA/worktree.err"; then
    err "Failed to create worktree at $WORKTREE_PATH"
    cat "$TMPDIR_JIRA/worktree.err" >&2
    # Remove any partial directory left behind
    if [[ -d "$WORKTREE_PATH" ]]; then
      rm -rf "$WORKTREE_PATH"
      git -C "$PLATFORM_DIR" worktree prune 2>/dev/null || true
    fi
    exit 1
  fi

  echo "Worktree created: $WORKTREE_PATH (branch: $BRANCH_NAME)"
  WORKTREE_CREATED=true
fi

# ---------------------------------------------------------------------------
# Stage 3: iOS one-time bootstrap (new worktrees only)
# ---------------------------------------------------------------------------

if [[ "$PLATFORM" == "ios" ]] && $WORKTREE_CREATED; then
  echo "Running iOS bootstrap in $WORKTREE_PATH..."

  # 1. Symlink swift_format from the main iOS repo
  ln -sf "$IOS_DIR/swift_format" "$WORKTREE_PATH/swift_format"
  echo "  swift_format symlinked."

  # 2. mise trust
  if ! (cd "$WORKTREE_PATH" && mise trust); then
    err "iOS bootstrap: 'mise trust' failed in $WORKTREE_PATH"
    exit 1
  fi
  echo "  mise trust: OK"

  # 3. tuist generate
  if ! (cd "$WORKTREE_PATH" && mise exec -- tuist generate --no-open); then
    err "iOS bootstrap: 'tuist generate' failed in $WORKTREE_PATH"
    exit 1
  fi
  echo "  tuist generate: OK"

  # 4. pod install
  if ! (cd "$WORKTREE_PATH" && pod install); then
    err "iOS bootstrap: 'pod install' failed in $WORKTREE_PATH"
    exit 1
  fi
  echo "  pod install: OK"

  echo "iOS bootstrap complete."
elif [[ "$PLATFORM" == "ios" ]] && ! $WORKTREE_CREATED; then
  echo "iOS bootstrap skipped (worktree already existed)."
fi
