#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/adf-to-md.sh
source "$SCRIPT_DIR/adf-to-md.sh"
# shellcheck source=scripts/snapshot-formatters.sh
source "$SCRIPT_DIR/snapshot-formatters.sh"

# snapshot.sh — Prepare a Jira workspace: snapshot artifacts + git worktree.
#
# Usage:
#   bash scripts/snapshot.sh <PARENT-KEY>
#
# Required environment variables:
#   SDD_WORKDIR  — root directory for task workspaces
#   IOS_DIR      — path to iOS repo
#   ANDROID_DIR  — path to Android repo

# ---------------------------------------------------------------------------
# Stage 0: Validate environment and arguments
# ---------------------------------------------------------------------------

usage() {
  cat >&2 <<'EOF'
Usage: bash scripts/snapshot.sh <PARENT-KEY>

Required environment variables:
  SDD_WORKDIR   root directory for task workspaces (e.g. /path/to/workdir)
  IOS_DIR       path to iOS repo
  ANDROID_DIR   path to Android repo
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

# 3. Determine platform from key prefix
if [[ "$PARENT_KEY" == IOS-* ]]; then
  PLATFORM="ios"
  if [[ -z "${IOS_DIR:-}" ]]; then
    err "IOS_DIR is not set but key $PARENT_KEY requires it."
    exit 1
  fi
  PLATFORM_DIR="$IOS_DIR"
elif [[ "$PARENT_KEY" == ANDR-* ]]; then
  PLATFORM="android"
  if [[ -z "${ANDROID_DIR:-}" ]]; then
    err "ANDROID_DIR is not set but key $PARENT_KEY requires it."
    exit 1
  fi
  PLATFORM_DIR="$ANDROID_DIR"
else
  err "Cannot determine platform from key '$PARENT_KEY'. Expected prefix IOS- or ANDR-."
  exit 1
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

# ---------------------------------------------------------------------------
# Early Resolved check — avoid fetching subtasks for already-done tasks
# ---------------------------------------------------------------------------

_early_type="$(jq -r '.fields.issuetype.name' "$PARENT_CORE_JSON")"
_early_status="$(jq -r '.fields.status.name' "$PARENT_CORE_JSON")"
if [[ "$_early_type" == "Bug" ]]; then
  _early_branch="bugfix/${PARENT_KEY}"
else
  _early_branch="feature/${PARENT_KEY}"
fi
_early_workdir="$SDD_WORKDIR/$PARENT_KEY"
_early_worktree="$_early_workdir/repo"

if [[ "$_early_status" == "Resolved" ]]; then
  echo "Task $PARENT_KEY is Resolved — cleaning up worktree, branch, and workspace."

  if git -C "$_early_worktree" rev-parse --is-inside-work-tree > /dev/null 2>&1; then
    git -C "$PLATFORM_DIR" worktree remove "$_early_worktree" 2>/dev/null || \
      git -C "$PLATFORM_DIR" worktree remove --force "$_early_worktree"
    echo "  Worktree removed: $_early_worktree"
  else
    echo "  Worktree not found at $_early_worktree — skipping."
  fi

  if git -C "$PLATFORM_DIR" rev-parse --verify "$_early_branch" > /dev/null 2>&1; then
    git -C "$PLATFORM_DIR" branch -D "$_early_branch"
    echo "  Branch deleted: $_early_branch"
  else
    echo "  Branch $_early_branch not found — skipping."
  fi

  if [[ -d "$_early_workdir" ]]; then
    rm -rf "$_early_workdir"
    echo "  Workspace removed: $_early_workdir"
  fi

  echo "Cleanup complete."
  exit 0
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

  # Fetch so we have an up-to-date view of remote branches
  echo "Fetching origin..."
  git -C "$PLATFORM_DIR" fetch origin

  _branch_local=false
  _branch_remote=false
  git -C "$PLATFORM_DIR" rev-parse --verify "$BRANCH_NAME" > /dev/null 2>&1 && _branch_local=true
  git -C "$PLATFORM_DIR" rev-parse --verify "origin/$BRANCH_NAME" > /dev/null 2>&1 && _branch_remote=true

  _worktree_add_failed=false
  if $_branch_local; then
    echo "Branch $BRANCH_NAME exists locally — reusing it."
    git -C "$PLATFORM_DIR" worktree add "$WORKTREE_PATH" "$BRANCH_NAME" 2>"$TMPDIR_JIRA/worktree.err" || _worktree_add_failed=true
  elif $_branch_remote; then
    echo "Branch $BRANCH_NAME found on origin — checking out with tracking."
    git -C "$PLATFORM_DIR" worktree add "$WORKTREE_PATH" --track -b "$BRANCH_NAME" "origin/$BRANCH_NAME" 2>"$TMPDIR_JIRA/worktree.err" || _worktree_add_failed=true
  else
    echo "Branch $BRANCH_NAME does not exist — creating from master."
    git -C "$PLATFORM_DIR" checkout master
    git -C "$PLATFORM_DIR" pull origin master
    git -C "$PLATFORM_DIR" worktree add "$WORKTREE_PATH" -b "$BRANCH_NAME" 2>"$TMPDIR_JIRA/worktree.err" || _worktree_add_failed=true
  fi

  if $_worktree_add_failed; then
    err "Failed to create worktree at $WORKTREE_PATH"
    cat "$TMPDIR_JIRA/worktree.err" >&2
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
# Stage 3: Platform one-time bootstrap (new worktrees only)
# ---------------------------------------------------------------------------

if [[ "$PLATFORM" == "ios" ]] && $WORKTREE_CREATED; then
  echo "Running iOS bootstrap in $WORKTREE_PATH..."

  # 1. mise trust
  if ! (cd "$WORKTREE_PATH" && mise trust); then
    err "iOS bootstrap: 'mise trust' failed in $WORKTREE_PATH"
    exit 1
  fi
  echo "  mise trust: OK"

  # 3. mise install (installs pinned toolchain versions before tuist generate)
  if ! (cd "$WORKTREE_PATH" && mise install); then
    err "iOS bootstrap: 'mise install' failed in $WORKTREE_PATH"
    exit 1
  fi
  echo "  mise install: OK"

  # 4. tuist install (fetches SPM dependencies for this worktree)
  if ! (cd "$WORKTREE_PATH" && GIT_TERMINAL_PROMPT=0 mise exec -- tuist install); then
    err "iOS bootstrap: 'tuist install' failed in $WORKTREE_PATH"
    exit 1
  fi
  echo "  tuist install: OK"

  # 5. tuist generate — load .env.local first so Tuist receives TUIST_* variables
  if [[ -f "$WORKTREE_PATH/.env.local" ]]; then
    while IFS= read -r line || [ -n "$line" ]; do
      [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
      if [[ $line =~ ^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
        key=${BASH_REMATCH[2]}
        val=${BASH_REMATCH[3]}
        if [[ ${val:0:1} == '"' && ${val: -1} == '"' ]]; then
          val=${val:1:-1}
        fi
        export "TUIST_${key}=${val}"
      fi
    done < "$WORKTREE_PATH/.env.local"
    echo "  Loaded .env.local for Tuist generation"
  fi
  if ! (cd "$WORKTREE_PATH" && mise exec -- tuist generate --no-open); then
    err "iOS bootstrap: 'tuist generate' failed in $WORKTREE_PATH"
    exit 1
  fi
  echo "  tuist generate: OK"

  # 6. pod install
  if ! (cd "$WORKTREE_PATH" && pod install); then
    err "iOS bootstrap: 'pod install' failed in $WORKTREE_PATH"
    exit 1
  fi
  echo "  pod install: OK"

  echo "iOS bootstrap complete."
elif [[ "$PLATFORM" == "ios" ]] && ! $WORKTREE_CREATED; then
  echo "iOS bootstrap skipped (worktree already existed)."
fi

if [[ "$PLATFORM" == "android" ]] && $WORKTREE_CREATED; then
  echo "Running Android bootstrap in $WORKTREE_PATH..."

  # 1. Copy .gradle cache from the main Android repo to avoid re-downloading dependencies.
  # Copying (not symlinking) so parallel worktree builds don't share mutable lock files.
  if [[ -d "$ANDROID_DIR/.gradle" ]]; then
    cp -r "$ANDROID_DIR/.gradle" "$WORKTREE_PATH/.gradle"
    echo "  .gradle copied from $ANDROID_DIR/.gradle"
  else
    echo "  WARN: $ANDROID_DIR/.gradle not found — skipping copy (dependencies will be downloaded on first build)."
  fi

  # 2. Symlink local.properties from the main Android repo (contains SDK path required for builds)
  if [[ -f "$ANDROID_DIR/local.properties" ]]; then
    ln -sf "$ANDROID_DIR/local.properties" "$WORKTREE_PATH/local.properties"
    echo "  local.properties symlinked from $ANDROID_DIR/local.properties"
  else
    echo "  WARN: $ANDROID_DIR/local.properties not found — skipping symlink (build may fail without SDK path)."
  fi

  # 3. Clean stale build artifacts so the copied .gradle cache is consistent for this worktree
  echo "  Running ./gradlew clean..."
  (cd "$WORKTREE_PATH" && ./gradlew clean --quiet) && echo "  ./gradlew clean done." || echo "  WARN: ./gradlew clean failed — check the worktree before building."

  echo "Android bootstrap complete."
elif [[ "$PLATFORM" == "android" ]] && ! $WORKTREE_CREATED; then
  echo "Android bootstrap skipped (worktree already existed)."
fi

# ---------------------------------------------------------------------------
# Stage 4: Transition to In Progress (Bugs only, when status is To Do)
#
# Stories require "Dev finish date" and "Story Points" to be set before
# transitioning — these are set manually during sprint planning.
# ---------------------------------------------------------------------------

_parent_status_now="$(jq -r '.fields.status.name' "$PARENT_CORE_JSON")"
if [[ "$PARENT_ISSUE_TYPE" == "Bug" && "$_parent_status_now" == "To Do" ]]; then
  echo "Transitioning $PARENT_KEY to In Progress..."
  _transition_output="$(acli jira workitem transition --key "$PARENT_KEY" --status "In Progress" 2>&1)"
  _transition_exit=$?
  if [[ $_transition_exit -eq 0 && "$_transition_output" != *"Failure"* && "$_transition_output" != *"Error"* ]]; then
    echo "  Transitioned to In Progress."
  else
    echo "  WARN: could not transition $PARENT_KEY to In Progress." >&2
    echo "  $TRANSITION_OUTPUT" >&2
  fi
fi

# ---------------------------------------------------------------------------
# Stage 5: Render ADF bodies to Markdown
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
# Stage 6: Write snapshot artifacts
# ---------------------------------------------------------------------------

echo "Writing snapshot artifacts to $WORKDIR..."

mkdir -p "$WORKDIR"

# Create directory structure based on issue type
if [[ "$PARENT_ISSUE_TYPE" != "Bug" ]]; then
  mkdir -p "$WORKDIR/spec/context" "$WORKDIR/plan"
  echo "  Created story directories: spec/context/, plan/"
else
  mkdir -p "$WORKDIR/spec"
  echo "  Created bug directories: spec/"
fi

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

# Create symlink spec/context/project.md → platform CLAUDE.md (stories only)
if [[ "$PARENT_ISSUE_TYPE" != "Bug" ]]; then
  ln -sf "$PLATFORM_DIR/CLAUDE.md" "$WORKDIR/spec/context/project.md"
  echo "  Symlinked spec/context/project.md → $PLATFORM_DIR/CLAUDE.md"
fi

echo "Snapshot complete."

# Exit 2 if any subtasks failed retrieval (partial success: parent + available subtasks written)
if (( ${#FAILED_SUBTASKS[@]} > 0 )); then
  err "Completed with errors. Failed subtask(s): ${FAILED_SUBTASKS[*]}"
  exit 2
fi
