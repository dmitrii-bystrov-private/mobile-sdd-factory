#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  request-review.sh <ios|android> <mr_iid>

Environment:
  IOS_DIR        Path to iOS repo (required for ios)
  ANDROID_DIR    Path to Android repo (required for android)
  JIRA_BASE_URL  Optional. Default: https://pnlfintech.atlassian.net/browse/

Output:
  Prints a 2–3 line Slack-ready message:
    <JIRA_URL|KEY>: <summary>
    <MR_URL/diffs>
    <N> files +<additions> −<deletions>
EOF
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi

platform="${1:-}"
mr_iid="${2:-}"

if [ -z "$platform" ] || [ -z "$mr_iid" ] || [ -n "${3:-}" ]; then
  usage >&2
  exit 2
fi

if ! command -v glab >/dev/null 2>&1; then
  echo "ERROR: glab is not installed or not on PATH" >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is not installed or not on PATH" >&2
  exit 1
fi

project_dir=""
encoded_project_path=""

case "$platform" in
  ios)
    : "${IOS_DIR:?IOS_DIR is not set}"
    [ -d "$IOS_DIR" ] || { echo "ERROR: IOS_DIR is not a directory: $IOS_DIR" >&2; exit 1; }
    project_dir="$IOS_DIR"
    encoded_project_path="M69%2Fmobile%2Fios%2Ffinomcommon"
    ;;
  android)
    : "${ANDROID_DIR:?ANDROID_DIR is not set}"
    [ -d "$ANDROID_DIR" ] || { echo "ERROR: ANDROID_DIR is not a directory: $ANDROID_DIR" >&2; exit 1; }
    project_dir="$ANDROID_DIR"
    encoded_project_path="M69%2Fmobile%2Fandroid%2Ffinom"
    ;;
  *)
    echo "ERROR: platform must be 'ios' or 'android' (got: $platform)" >&2
    exit 2
    ;;
esac

jira_base_url="${JIRA_BASE_URL:-https://pnlfintech.atlassian.net/browse/}"

mr_json="$(
  (cd "$project_dir" && glab api "projects/$encoded_project_path/merge_requests/$mr_iid" 2>/dev/null) \
    || { echo "ERROR: failed to fetch MR details (check auth and MR id)" >&2; exit 1; }
)"

title="$(echo "$mr_json" | jq -r '.title // empty')"
web_url="$(echo "$mr_json" | jq -r '.web_url // empty')"

if [ -z "$title" ] || [ -z "$web_url" ]; then
  echo "ERROR: MR response missing title/web_url" >&2
  exit 1
fi

jira_key=""
if [[ "$title" =~ ([A-Z]+-[0-9]+) ]]; then
  jira_key="${BASH_REMATCH[1]}"
fi

summary="$title"
if [ -n "$jira_key" ]; then
  summary="${summary#"$jira_key"}"
  summary="${summary#": "}"
  summary="${summary#": "}"
  summary="${summary#" - "}"
  summary="${summary#" "}"
fi

if [ -n "$jira_key" ]; then
  echo "<${jira_base_url}${jira_key}|${jira_key}>: ${summary}"
else
  echo "${title}"
fi

web_url="${web_url%/}"
echo "<${web_url}/diffs>"

diffs_json="$((cd "$project_dir" && glab api "projects/$encoded_project_path/merge_requests/$mr_iid/diffs" 2>/dev/null) || true)"
if [ -z "$diffs_json" ]; then
  exit 0
fi

stats="$(
  echo "$diffs_json" | jq -r '
    def add_del:
      {
        a: ([.diff | split("\n")[] | select(startswith("+") and (startswith("+++") | not))] | length),
        d: ([.diff | split("\n")[] | select(startswith("-") and (startswith("---") | not))] | length)
      };
    [ .[] | add_del ] as $xs
    | {
        files: ($xs | length),
        additions: ($xs | map(.a) | add // 0),
        deletions: ($xs | map(.d) | add // 0)
      }
    | "\(.files) files +\(.additions) \u2212\(.deletions)"
  ' 2>/dev/null || true
)"

if [ -n "$stats" ]; then
  echo "$stats"
fi
