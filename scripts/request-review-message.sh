#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  request-review-message.sh <ios|android> <mr_iid> [--open|-o]

Options:
  --open, -o     Open browser with Slack-ready rich text (copy & paste)

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
open_browser=false

if [ "${3:-}" = "--open" ] || [ "${3:-}" = "-o" ]; then
  open_browser=true
elif [ -n "${3:-}" ]; then
  usage >&2
  exit 2
fi

if [ -z "$platform" ] || [ -z "$mr_iid" ]; then
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

title="$(printf '%s' "$mr_json" | jq -r '.title // empty')"
web_url="$(printf '%s' "$mr_json" | jq -r '.web_url // empty')"

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
  echo "${jira_key}: ${summary}"
else
  echo "${title}"
fi

web_url="${web_url%/}"
echo "${web_url}/diffs"

stats=""
source_branch="$(printf '%s' "$mr_json" | jq -r '.source_branch // empty')"
target_branch="$(printf '%s' "$mr_json" | jq -r '.target_branch // "master"')"
if [ -n "$source_branch" ]; then
  (cd "$project_dir" && git fetch --quiet origin "$target_branch" "$source_branch" 2>/dev/null) || true
  stat_line="$(cd "$project_dir" && git diff --stat "origin/$target_branch...origin/$source_branch" 2>/dev/null | tail -1)"
  # "27 files changed, 2287 insertions(+), 80 deletions(-)"
  if [[ "$stat_line" =~ ([0-9]+)\ file.*,\ ([0-9]+)\ insertion.*\(\+\),?\ ([0-9]+)\ deletion ]]; then
    stats="${BASH_REMATCH[1]} files +${BASH_REMATCH[2]} $(printf '\xe2\x88\x92')${BASH_REMATCH[3]}"
  elif [[ "$stat_line" =~ ([0-9]+)\ file.*,\ ([0-9]+)\ insertion ]]; then
    stats="${BASH_REMATCH[1]} files +${BASH_REMATCH[2]} $(printf '\xe2\x88\x92')0"
  elif [[ "$stat_line" =~ ([0-9]+)\ file.*,\ ([0-9]+)\ deletion ]]; then
    stats="${BASH_REMATCH[1]} files +0 $(printf '\xe2\x88\x92')${BASH_REMATCH[2]}"
  fi
fi

if [ -n "$stats" ]; then
  echo "$stats"
fi

if [ "$open_browser" = true ]; then
  tmp_html="/tmp/slack-msg-$jira_key.html"
  cat > "$tmp_html" <<EOF
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body>
<p>
  <a href="$jira_base_url$jira_key">$jira_key</a>: $title<br>
  <a href="web_url">$web_url</a><br>
  $stats
</p>
<script>
  window.onload = () => {
    const range = document.createRange();
    range.selectNode(document.body);
    window.getSelection().removeAllRanges();
    window.getSelection().addRange(range);
  }
</script>
</body>
</html>
EOF
  open "$tmp_html"
fi
