#!/usr/bin/env bash
# Fetch standup data from GitLab (sequential) and Jira

ME="dapper.chita"

IOS_DIR=~"/Projects/Finom/finomcommon"
IOS_PATH="M69%2Fmobile%2Fios%2Ffinomcommon"

ANDROID_DIR=~"/Projects/Finom/finom"
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

    if [ -z "$mrs" ] || ! echo "$mrs" | jq -e . >/dev/null 2>&1; then
        echo "ERROR: $(cat "$err_file")" > "$out"
        rm -f "$err_file"
        return
    fi
    rm -f "$err_file"

    local count
    count=$(echo "$mrs" | jq 'length')

    > "$out"
    for i in $(seq 0 $((count - 1))); do
        local id title branch
        id=$(echo "$mrs" | jq -r ".[$i].iid")
        title=$(echo "$mrs" | jq -r ".[$i].title")
        branch=$(echo "$mrs" | jq -r ".[$i].source_branch")

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

# Run all glab calls sequentially to avoid keychain contention
(cd "$IOS_DIR" && NO_COLOR=1 glab mr list --assignee @me 2>&1) > "$TMP/ios_mine.txt"
fetch_unapproved_review "$IOS_DIR" "$IOS_PATH" "$TMP/ios_review.txt"
(cd "$ANDROID_DIR" && NO_COLOR=1 glab mr list --assignee @me 2>&1) > "$TMP/andr_mine.txt"
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
