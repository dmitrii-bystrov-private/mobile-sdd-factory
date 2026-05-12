#!/usr/bin/env bash
# Fetch standup data from GitLab (sequential) and Jira

ME="dapper.chita"

: "${IOS_DIR:?IOS_DIR is not set}"
[ -d "$IOS_DIR" ] || { echo "IOS_DIR is not a directory: $IOS_DIR" >&2; exit 1; }
IOS_PATH="M69%2Fmobile%2Fios%2Ffinomcommon"

: "${ANDROID_DIR:?ANDROID_DIR is not set}"
[ -d "$ANDROID_DIR" ] || { echo "ANDROID_DIR is not a directory: $ANDROID_DIR" >&2; exit 1; }
ANDROID_PATH="M69%2Fmobile%2Fandroid%2Ffinom"

TMP=$(mktemp -d)

# Review MRs — filter out already approved
fetch_unapproved_review() {
    local dir="$1"
    local encoded="$2"
    local out="$3"

    local mrs err_file
    err_file=$(mktemp)
    mrs=$(cd "$dir" && NO_COLOR=1 glab mr list --reviewer @me --output json 2>"$err_file")

    if [ -z "$mrs" ] || ! printf '%s' "$mrs" | jq -e . >/dev/null 2>&1; then
        echo "ERROR: $(cat "$err_file")" > "$out"
        rm -f "$err_file"
        return
    fi
    rm -f "$err_file"

    local count
    count=$(printf '%s' "$mrs" | jq 'length')

    > "$out"
    for i in $(seq 0 $((count - 1))); do
        local id title branch
        id=$(printf '%s' "$mrs" | jq -r ".[$i].iid")
        title=$(printf '%s' "$mrs" | jq -r ".[$i].title")
        branch=$(printf '%s' "$mrs" | jq -r ".[$i].source_branch")

        local approved
        approved=$(cd "$dir" && NO_COLOR=1 glab api "projects/$encoded/merge_requests/$id/approvals" 2>/dev/null \
            | jq -r "[.approved_by[].user.username] | contains([\"$ME\"])")

        if [ "$approved" = "false" ]; then
            local my_comments
            my_comments=$(cd "$dir" && NO_COLOR=1 glab api "projects/$encoded/merge_requests/$id/notes?per_page=100" 2>/dev/null \
                | jq -r "[.[] | select(.author.username == \"$ME\" and (.system // false) == false)] | length")

            local status_tag=""
            if [ "${my_comments:-0}" -gt 0 ]; then
                status_tag=" [commented, waiting author]"
            fi

            echo "!$id $title ($branch)$status_tag" >> "$out"
        fi
    done

    if [ ! -s "$out" ]; then
        echo "No open merge requests available." >> "$out"
    fi
}

fetch_my_mrs() {
    local dir="$1"
    local encoded="$2"
    local out="$3"

    local mrs
    mrs=$(cd "$dir" && NO_COLOR=1 glab mr list --author @me --output json 2>/dev/null)

    local count
    count=$(printf '%s' "$mrs" | jq 'length')

    > "$out"
    for i in $(seq 0 $((count - 1))); do
        local id title
        id=$(printf '%s' "$mrs" | jq -r ".[$i].iid")
        title=$(printf '%s' "$mrs" | jq -r ".[$i].title")

        local approved
        approved=$(cd "$dir" && NO_COLOR=1 glab api "projects/$encoded/merge_requests/$id/approvals" 2>/dev/null \
            | jq -r "[.approved_by[].user.username] | length > 0")

        if [ "$approved" = "false" ]; then
            echo "!$id $title" >> "$out"
        else
            echo "!$id $title [approved]" >> "$out"
        fi
    done

    if [ ! -s "$out" ]; then
        echo "No open merge requests available." >> "$out"
    fi
}

# Run all glab calls sequentially to avoid keychain contention
fetch_my_mrs "$IOS_DIR" "$IOS_PATH" "$TMP/ios_mine.txt"
fetch_unapproved_review "$IOS_DIR" "$IOS_PATH" "$TMP/ios_review.txt"
fetch_my_mrs "$ANDROID_DIR" "$ANDROID_PATH" "$TMP/andr_mine.txt"
fetch_unapproved_review "$ANDROID_DIR" "$ANDROID_PATH" "$TMP/andr_review.txt"

# Jira can run independently (different tool, no keychain conflict)
acli jira workitem search --filter 10494 --fields key,summary,status,priority 2>&1 > "$TMP/jira.txt"

echo "=== iOS MRs (mine) ==="
cat "$TMP/ios_mine.txt"

echo ""
echo "=== iOS MRs (review) ==="
cat "$TMP/ios_review.txt"

echo ""
echo "=== Android MRs (mine) ==="
cat "$TMP/andr_mine.txt"

echo ""
echo "=== Android MRs (review) ==="
cat "$TMP/andr_review.txt"

echo ""
echo "=== Jira backlog ==="
cat "$TMP/jira.txt"

rm -rf "$TMP"

# On Mondays — check for tool updates
if [ "$(date +%u)" = "1" ]; then
    echo ""
    bash "$(dirname "$0")/check-updates.sh"
fi
