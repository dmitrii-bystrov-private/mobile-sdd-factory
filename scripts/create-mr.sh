#!/usr/bin/env bash
# Usage: bash scripts/create-mr.sh <TASK-KEY>
#
# Pushes the current branch and opens a GitLab MR to master.
# Determines the project directory from the task worktree or platform env vars.
#
# Required env: SDD_WORKDIR, and IOS_DIR or ANDROID_DIR
# Required CLI: acli, glab, jq, git
set -euo pipefail

KEY="${1:?Usage: create-mr.sh <TASK-KEY>}"

command -v acli >/dev/null 2>&1 || { echo "Missing required command: acli" >&2; exit 1; }
command -v glab >/dev/null 2>&1 || { echo "Missing required command: glab" >&2; exit 1; }
command -v jq   >/dev/null 2>&1 || { echo "Missing required command: jq"   >&2; exit 1; }
[[ -n "${SDD_WORKDIR:-}" ]] || { echo "SDD_WORKDIR is not set" >&2; exit 1; }

# Resolve story key (parent for subtasks, self otherwise)
json="$(acli jira workitem view "$KEY" --fields 'summary,issuetype,parent' --json)"
title="$(printf '%s' "$json"      | jq -r '.fields.summary')"
is_subtask="$(printf '%s' "$json" | jq -r '.fields.issuetype.subtask')"

if [[ "$is_subtask" == "true" ]]; then
  story_key="$(printf '%s' "$json" | jq -r '.fields.parent.key')"
else
  story_key="$KEY"
fi

# Determine project directory: worktree first, then platform fallback
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
  echo "ERROR: currently on master — refusing to push directly to master." >&2
  exit 1
fi

echo "Checking for uncommitted changes in $project_dir..."
if [[ -n "$(git -C "$project_dir" status --porcelain)" ]]; then
  echo "ERROR: uncommitted changes remain in $project_dir." >&2
  echo "Create workflow checkpoint commits before MR handoff." >&2
  exit 1
fi

# Push
echo "Pushing $branch to origin..."
git -C "$project_dir" push -u origin "$branch"

# Create MR (or print existing one if already open)
existing_mr="$(cd "$project_dir" && glab mr list --source-branch "$branch" --output json 2>/dev/null | jq -r '.[0].web_url // empty' 2>/dev/null || true)"

if [[ -n "$existing_mr" ]]; then
  echo "MR already exists: $existing_mr"
else
  echo "Creating MR: $KEY: $title"
  (
    cd "$project_dir"
    glab mr create \
      --title "$KEY: $title" \
      --description "" \
      --target-branch master \
      --remove-source-branch \
      --yes
  )
fi
