#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/adf_to_md.sh
source "$SCRIPT_DIR/adf_to_md.sh"
# shellcheck source=scripts/snapshot_formatters.sh
source "$SCRIPT_DIR/snapshot_formatters.sh"

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
SUCCESSFUL_SUBTASKS=()

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
    else
      SUCCESSFUL_SUBTASKS+=("$SUBKEY")
    fi
  done < <(jq -r '.[].key' "$SUBTASKS_LIST_JSON")
fi

if (( ${#FAILED_SUBTASKS[@]} > 0 )); then
  err "Some subtask(s) could not be retrieved: ${FAILED_SUBTASKS[*]}. Continuing with available data..."
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

# ---------------------------------------------------------------------------
# Stage 4: Render ADF bodies to Markdown
# ---------------------------------------------------------------------------

echo "Rendering ADF content to Markdown..."

# Helper: transform raw acli comments JSON into [{id, created, body_md}] JSON array
_build_comments_md_json() {
  local raw_json="$1"
  local encoded_items
  encoded_items="$(printf '%s' "$raw_json" | jq -r '.fields.comment.comments // [] | .[] | @base64')"

  local result="["
  local first=true
  while IFS= read -r encoded; do
    [[ -n "$encoded" ]] || continue
    local comment id created body_adf body_md body_md_json
    comment="$(printf '%s' "$encoded" | base64 -d)"
    id="$(printf '%s' "$comment" | jq -r '.id')"
    created="$(printf '%s' "$comment" | jq -r '.created')"
    body_adf="$(printf '%s' "$comment" | jq '.body // "null"')"
    body_md="$(render_adf_to_markdown "$body_adf")"
    body_md_json="$(printf '%s' "$body_md" | jq -Rs .)"

    $first || result+=","
    result+="{\"id\":$(printf '%s' "$id" | jq -Rs .),\"created\":$(printf '%s' "$created" | jq -Rs .),\"body_md\":${body_md_json}}"
    first=false
  done < <(printf '%s\n' "$encoded_items")
  result+="]"
  printf '%s' "$result"
}

# Render parent description
PARENT_DESC_ADF="$(jq '.fields.description' "$PARENT_CORE_JSON")"
PARENT_DESC_MD="$(render_adf_to_markdown "$PARENT_DESC_ADF")"
PARENT_COMMENTS_MD_JSON="$(_build_comments_md_json "$(cat "$PARENT_COMMENTS_JSON")")"

# Render each successful subtask; store results in tmp files (bash 3 compatible)
RENDERED_DIR="$TMPDIR_JIRA/rendered"
mkdir -p "$RENDERED_DIR"
for SUBKEY in "${SUCCESSFUL_SUBTASKS[@]+"${SUCCESSFUL_SUBTASKS[@]}"}"; do
  echo "  Rendering $SUBKEY..."
  SUB_DESC_ADF="$(jq '.fields.description' "$TMPDIR_JIRA/subtask.${SUBKEY}.core.json")"
  render_adf_to_markdown "$SUB_DESC_ADF" > "$RENDERED_DIR/${SUBKEY}.desc.md"
  _build_comments_md_json "$(cat "$TMPDIR_JIRA/subtask.${SUBKEY}.comments.json")" \
    > "$RENDERED_DIR/${SUBKEY}.comments.json"
done

echo "ADF rendering complete."

# ---------------------------------------------------------------------------
# Stage 5: Write snapshot artifacts
# ---------------------------------------------------------------------------

echo "Writing snapshot artifacts to $WORKDIR..."

mkdir -p "$WORKDIR"

# Read parent metadata (PARENT_ISSUE_TYPE already set by worktree stage)
PARENT_ISSUE_TITLE="$(jq -r '.fields.summary' "$PARENT_CORE_JSON")"
PARENT_ISSUE_STATUS="$(jq -r '.fields.status.name' "$PARENT_CORE_JSON")"

# Write parent description.md
write_description_md \
  "$WORKDIR/description.md" \
  "$PARENT_KEY" \
  "$PARENT_ISSUE_TYPE" \
  "$PARENT_ISSUE_TITLE" \
  "$PARENT_ISSUE_STATUS" \
  "$PARENT_DESC_MD"
echo "  Wrote $WORKDIR/description.md"

# Write parent comments.md
write_comments_md \
  "$WORKDIR/comments.md" \
  "$PARENT_COMMENTS_MD_JSON"
echo "  Wrote $WORKDIR/comments.md"

# Prepare data for statuses.md
PARENT_STATUS_JSON="$(jq '{key: .key, type: .fields.issuetype.name, title: .fields.summary, status: .fields.status.name}' "$PARENT_CORE_JSON")"
SUBTASKS_STATUS_JSON="$(jq 'map({key: .key, type: (.fields.issuetype.name // ""), title: (.fields.summary // ""), status: (.fields.status.name // "")})' "$SUBTASKS_LIST_JSON")"

EXISTING_STATUSES_FILE=""
[[ -f "$WORKDIR/statuses.md" ]] && EXISTING_STATUSES_FILE="$WORKDIR/statuses.md"

# Skip statuses.md only when subtask failures occurred AND there's no existing file to carry forward
if (( ${#FAILED_SUBTASKS[@]} > 0 )) && [[ -z "$EXISTING_STATUSES_FILE" ]]; then
  err "Skipping statuses.md: subtask failures with no existing file to carry forward values."
else
  write_statuses_md \
    "$WORKDIR/statuses.md" \
    "$PARENT_STATUS_JSON" \
    "$SUBTASKS_STATUS_JSON" \
    "$EXISTING_STATUSES_FILE"
  echo "  Wrote $WORKDIR/statuses.md"
fi

# Write subtask artifacts
for SUBKEY in "${SUCCESSFUL_SUBTASKS[@]+"${SUCCESSFUL_SUBTASKS[@]}"}"; do
  SUB_WORKDIR="$WORKDIR/$SUBKEY"
  mkdir -p "$SUB_WORKDIR"

  SUB_KEY="$(jq -r '.key' "$TMPDIR_JIRA/subtask.${SUBKEY}.core.json")"
  SUB_TYPE="$(jq -r '.fields.issuetype.name' "$TMPDIR_JIRA/subtask.${SUBKEY}.core.json")"
  SUB_TITLE="$(jq -r '.fields.summary' "$TMPDIR_JIRA/subtask.${SUBKEY}.core.json")"
  SUB_STATUS="$(jq -r '.fields.status.name' "$TMPDIR_JIRA/subtask.${SUBKEY}.core.json")"

  write_description_md \
    "$SUB_WORKDIR/description.md" \
    "$SUB_KEY" \
    "$SUB_TYPE" \
    "$SUB_TITLE" \
    "$SUB_STATUS" \
    "$(cat "$RENDERED_DIR/${SUBKEY}.desc.md")"
  echo "  Wrote $SUB_WORKDIR/description.md"

  write_comments_md \
    "$SUB_WORKDIR/comments.md" \
    "$(cat "$RENDERED_DIR/${SUBKEY}.comments.json")"
  echo "  Wrote $SUB_WORKDIR/comments.md"
done

echo "Snapshot complete."

# Exit 2 if any subtasks failed retrieval (partial success: parent + available subtasks written)
if (( ${#FAILED_SUBTASKS[@]} > 0 )); then
  err "Completed with errors. Failed subtask(s): ${FAILED_SUBTASKS[*]}"
  exit 2
fi
