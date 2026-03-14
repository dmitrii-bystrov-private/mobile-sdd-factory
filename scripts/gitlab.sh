#!/usr/bin/env bash

ME="dapper.chita"

: "${IOS_DIR:?IOS_DIR is not set}"
[ -d "$IOS_DIR" ] || { echo "IOS_DIR is not a directory: $IOS_DIR" >&2; exit 1; }
IOS_PATH="M69%2Fmobile%2Fios%2Ffinomcommon"

: "${ANDROID_DIR:?ANDROID_DIR is not set}"
[ -d "$ANDROID_DIR" ] || { echo "ANDROID_DIR is not a directory: $ANDROID_DIR" >&2; exit 1; }
ANDROID_PATH="M69%2Fmobile%2Fandroid%2Ffinom"

fetch_unapproved() {
    local dir="$1"
    local encoded="$2"
    local platform="$3"

    local mrs
    mrs=$(cd "$dir" && NO_COLOR=1 glab mr list --reviewer @me --output json 2>/dev/null)

    local count
    count=$(echo "$mrs" | jq 'length')

    for i in $(seq 0 $((count - 1))); do
        local id title author created
        id=$(echo "$mrs" | jq -r ".[$i].iid")
        title=$(echo "$mrs" | jq -r ".[$i].title")
        author=$(echo "$mrs" | jq -r ".[$i].author.username")
        created=$(echo "$mrs" | jq -r ".[$i].created_at" | cut -c1-10)

        local approved stats
        approved=$(cd "$dir" && NO_COLOR=1 glab api "projects/$encoded/merge_requests/$id/approvals" 2>/dev/null \
            | jq -r "[.approved_by[].user.username] | contains([\"$ME\"])")

        if [ "$approved" = "false" ]; then
            stats=$(cd "$dir" && NO_COLOR=1 glab api "projects/$encoded/merge_requests/$id" 2>/dev/null \
                | jq -r '"\(.changes_count) files"')
            echo "$platform|!$id|$title|$author|$created|$stats"
        fi
    done
}

fetch_my_mrs() {
    local dir="$1"
    local platform="$2"

    cd "$dir" && NO_COLOR=1 glab mr list --assignee @me --output json 2>/dev/null \
        | jq -r '.[] | "'"$platform"'|!\(.iid)|\(.title)|\([.reviewers[].username] | join(", "))"'
}

echo "=== На ревью (не аппрувнуто) ==="
{
    fetch_unapproved "$IOS_DIR" "$IOS_PATH" "iOS" &
    fetch_unapproved "$ANDROID_DIR" "$ANDROID_PATH" "Android" &
    wait
} | sort -t'|' -k5

echo ""
echo "=== Мои MR ==="
{
    fetch_my_mrs "$IOS_DIR" "iOS" &
    fetch_my_mrs "$ANDROID_DIR" "Android" &
    wait
}
