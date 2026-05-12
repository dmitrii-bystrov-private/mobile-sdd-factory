#!/usr/bin/env bash
# Usage: bash scripts/commit-and-resolve.sh <TASK-KEY>
#
# 1. Commits all uncommitted changes in the task worktree with message "<KEY>: <TITLE>"
# 2. Transitions the task to Ready for test.
#
# Required env: SDD_WORKDIR
# Required CLI: acli, jq, git
set -euo pipefail

KEY="${1:?Usage: commit-and-resolve.sh <TASK-KEY>}"

command -v acli >/dev/null 2>&1 || { echo "Missing required command: acli" >&2; exit 1; }
command -v jq   >/dev/null 2>&1 || { echo "Missing required command: jq"   >&2; exit 1; }
[[ -n "${SDD_WORKDIR:-}" ]] || { echo "SDD_WORKDIR is not set" >&2; exit 1; }

# Fetch issue metadata in one call
json="$(acli jira workitem view "$KEY" --fields 'summary,issuetype,status,parent' --json)"

title="$(echo "$json"          | jq -r '.fields.summary')"
is_subtask="$(echo "$json"     | jq -r '.fields.issuetype.subtask')"
type_name="$(echo "$json"      | jq -r '.fields.issuetype.name')"
current_status="$(echo "$json" | jq -r '.fields.status.name')"

# Resolve story key (parent for subtasks, self otherwise)
if [[ "$is_subtask" == "true" ]]; then
  story_key="$(echo "$json" | jq -r '.fields.parent.key')"
else
  story_key="$KEY"
fi

repo="$SDD_WORKDIR/$story_key/repo"

# Commit uncommitted changes
echo "Checking for uncommitted changes in $repo..."
git -C "$repo" add -A
if git -C "$repo" diff --cached --quiet; then
  echo "Nothing to commit."
else
  git -C "$repo" commit -m "$KEY: $title"
  echo "Committed: $KEY: $title"
fi

# Determine target status
target_status="Ready for test"

# Transition (go through In Progress first if currently To Do)
echo "Transitioning $KEY ($current_status) → $target_status..."
if [[ "$current_status" == "To Do" ]]; then
  acli jira workitem transition --key "$KEY" --status "In Progress"
fi
acli jira workitem transition --key "$KEY" --status "$target_status"
echo "Done: $KEY → $target_status"
