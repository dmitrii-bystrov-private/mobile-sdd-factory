#!/usr/bin/env bash
# Usage: bash scripts/commit-task-state.sh <TASK-KEY> [CONTEXT]
#
# Creates a workflow checkpoint commit for the current task branch when there
# are uncommitted changes. Used by the coordinator after successful coding
# passes so progress is preserved incrementally before later quality gates.
#
# Required env: SDD_WORKDIR, and IOS_DIR or ANDROID_DIR
# Required CLI: acli, jq, git
set -euo pipefail

KEY="${1:?Usage: commit-task-state.sh <TASK-KEY> [CONTEXT]}"
CONTEXT="${2:-}"

command -v acli >/dev/null 2>&1 || { echo "Missing required command: acli" >&2; exit 1; }
command -v jq   >/dev/null 2>&1 || { echo "Missing required command: jq" >&2; exit 1; }
command -v git  >/dev/null 2>&1 || { echo "Missing required command: git" >&2; exit 1; }
[[ -n "${SDD_WORKDIR:-}" ]] || { echo "SDD_WORKDIR is not set" >&2; exit 1; }

json="$(acli jira workitem view "$KEY" --fields 'summary,issuetype,parent' --json)"
title="$(printf '%s' "$json" | jq -r '.fields.summary')"
is_subtask="$(printf '%s' "$json" | jq -r '.fields.issuetype.subtask')"

if [[ "$is_subtask" == "true" ]]; then
  story_key="$(printf '%s' "$json" | jq -r '.fields.parent.key')"
else
  story_key="$KEY"
fi

worktree="$SDD_WORKDIR/$story_key/repo"
if [[ -d "$worktree" ]]; then
  project_dir="$worktree"
elif [[ "$KEY" == IOS-* ]]; then
  : "${IOS_DIR:?IOS_DIR is not set}"
  project_dir="$IOS_DIR"
elif [[ "$KEY" == ANDR-* ]]; then
  : "${ANDROID_DIR:?ANDROID_DIR is not set}"
  project_dir="$ANDROID_DIR"
else
  echo "Cannot determine project directory for key: $KEY" >&2
  exit 1
fi

branch="$(git -C "$project_dir" branch --show-current)"
if [[ "$branch" == "master" ]]; then
  echo "ERROR: currently on master — refusing to commit task state on master." >&2
  exit 1
fi

echo "Checking for uncommitted changes in $project_dir..."
git -C "$project_dir" add -A
if git -C "$project_dir" diff --cached --quiet; then
  echo "Nothing to commit."
  exit 0
fi

commit_message="$KEY: $title"
if [[ -n "$CONTEXT" ]]; then
  commit_message="$commit_message ($CONTEXT)"
fi

git -C "$project_dir" commit -m "$commit_message"
echo "Committed: $commit_message"
