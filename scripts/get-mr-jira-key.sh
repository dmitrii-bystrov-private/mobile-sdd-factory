#!/usr/bin/env bash
# Extracts the Jira key (IOS-XXXX or ANDR-XXXX) from a GitLab MR title/description.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  get-mr-jira-key.sh <ios|android> <mr_iid>

Prints the first Jira key found in the MR title or description to stdout.

Environment:
  IOS_DIR        Path to iOS repo (required for ios)
  ANDROID_DIR    Path to Android repo (required for android)

Exit codes:
  0  Success — key printed to stdout
  1  Fatal error (bad args, missing env, API failure, key not found)
EOF
}

err() { echo "ERROR: $*" >&2; }

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage; exit 0
fi

platform="${1:-}"
mr_iid="${2:-}"

if [ -z "$platform" ] || [ -z "$mr_iid" ]; then
  usage >&2; exit 1
fi

command -v glab >/dev/null 2>&1 || { err "glab is not installed or not on PATH"; exit 1; }
command -v jq   >/dev/null 2>&1 || { err "jq is not installed or not on PATH";   exit 1; }

case "$platform" in
  ios)
    : "${IOS_DIR:?IOS_DIR is not set}"
    [ -d "$IOS_DIR" ] || { err "IOS_DIR is not a directory: $IOS_DIR"; exit 1; }
    project_dir="$IOS_DIR"
    encoded_path="M69%2Fmobile%2Fios%2Ffinomcommon"
    ;;
  android)
    : "${ANDROID_DIR:?ANDROID_DIR is not set}"
    [ -d "$ANDROID_DIR" ] || { err "ANDROID_DIR is not a directory: $ANDROID_DIR"; exit 1; }
    project_dir="$ANDROID_DIR"
    encoded_path="M69%2Fmobile%2Fandroid%2Ffinom"
    ;;
  *)
    err "platform must be 'ios' or 'android' (got: $platform)"; exit 1
    ;;
esac

mr_json="$(
  (cd "$project_dir" && glab api "projects/$encoded_path/merge_requests/$mr_iid" 2>/dev/null) \
    || { err "failed to fetch MR (check auth and MR id)"; exit 1; }
)"

# Search title first, then description
title="$(printf '%s' "$mr_json" | jq -r '.title // ""')"
description="$(printf '%s' "$mr_json" | jq -r '.description // ""')"

key="$(printf '%s\n%s' "$title" "$description" \
  | grep -oE '(IOS|ANDR)-[0-9]+' \
  | head -1 || true)"

if [ -z "$key" ]; then
  err "no Jira key (IOS-XXXX or ANDR-XXXX) found in MR !$mr_iid title or description"
  exit 1
fi

echo "$key"
