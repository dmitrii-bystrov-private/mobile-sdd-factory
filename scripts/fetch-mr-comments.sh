#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  fetch-mr-comments.sh <ios|android> <mr_iid>

Fetches all unresolved review discussions from a GitLab MR and prints them
as Markdown, suitable for grouping and creating Jira subtasks.

Environment:
  IOS_DIR        Path to iOS repo (required for ios)
  ANDROID_DIR    Path to Android repo (required for android)

Exit codes:
  0  Success (output may be empty if all discussions are resolved)
  1  Fatal error (bad args, missing env, API failure)
  2  No unresolved discussions found
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

# Paginate through all discussions (GitLab returns max 100 per page)
all_discussions="[]"
page=1
while true; do
  batch="$(
    (cd "$project_dir" && glab api \
      "projects/$encoded_path/merge_requests/$mr_iid/discussions?per_page=100&page=$page" \
      2>/dev/null) \
      || { err "failed to fetch discussions (check auth and MR id)"; exit 1; }
  )"
  count="$(printf '%s' "$batch" | jq 'length')"
  [ "$count" -eq 0 ] && break
  all_discussions="$(printf '%s\n%s' "$all_discussions" "$batch" | jq -s 'add')"
  page=$((page + 1))
done

# Filter to discussions that have at least one unresolved resolvable note
unresolved="$(
  printf '%s' "$all_discussions" | jq '[
    .[] |
    select(
      .notes | any(.resolvable == true and .resolved == false)
    )
  ]'
)"

count="$(printf '%s' "$unresolved" | jq 'length')"
if [ "$count" -eq 0 ]; then
  echo "No unresolved discussions found in MR !$mr_iid." >&2
  exit 2
fi

echo "# Unresolved MR discussions: !$mr_iid ($count total)"
echo ""

printf '%s' "$unresolved" | jq -r '
  to_entries[] |
  .key as $idx |
  .value as $disc |
  ($disc.notes | map(select(.resolvable == true and .resolved == false))) as $notes |
  ($notes[0].position.new_path // "") as $path |
  ($notes[0].position.new_line // $notes[0].position.line_range.end.new_line // "") as $line |
  (
    if $path != "" then
      if $line != "" then "## Discussion \($idx + 1) — \($path):\($line)"
      else "## Discussion \($idx + 1) — \($path)"
      end
    else "## Discussion \($idx + 1) — General comment"
    end
  ),
  "",
  ($notes[] |
    "**\(.author.name):** \(.body)",
    ""
  ),
  "---",
  ""
'
