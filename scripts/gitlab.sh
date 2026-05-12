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
    count=$(printf '%s' "$mrs" | jq 'length')

    if [ "$count" -eq 0 ]; then
        echo "No merge requests found for $platform" >&2
        return
    fi

    for i in $(seq 0 $((count - 1))); do
        local id title
        id=$(printf '%s' "$mrs" | jq -r ".[$i].iid")
        title=$(printf '%s' "$mrs" | jq -r ".[$i].title")

        local approved
        approved=$(cd "$dir" && NO_COLOR=1 glab api "projects/$encoded/merge_requests/$id/approvals" 2>/dev/null \
            | jq -r "[.approved_by[].user.username] | contains([\"$ME\"])")

        if [ "$approved" = "false" ]; then
            echo "$platform|!$id|$title"
        fi
    done
}

fetch_my_mrs() {
    local dir="$1"
    local encoded="$2"
    local platform="$3"

    local mrs
    mrs=$(cd "$dir" && NO_COLOR=1 glab mr list --author @me --output json 2>/dev/null)

    local count
    count=$(printf '%s' "$mrs" | jq 'length')

    if [ "$count" -eq 0 ]; then
        echo "No merge requests found for $platform" >&2
        return
    fi

    for i in $(seq 0 $((count - 1))); do
        local id title
        id=$(printf '%s' "$mrs" | jq -r ".[$i].iid")
        title=$(printf '%s' "$mrs" | jq -r ".[$i].title")

        local approved
        approved=$(cd "$dir" && NO_COLOR=1 glab api "projects/$encoded/merge_requests/$id/approvals" 2>/dev/null \
            | jq -r "[.approved_by[].user.username] | length > 0")

        if [ "$approved" = "false" ]; then
            echo "$platform|!$id|$title"
        else
            echo "$platform|!$id|$title [approved]"
        fi
    done
}

echo "=== Review requested ==="
{
    fetch_unapproved "$IOS_DIR" "$IOS_PATH" "iOS" &
    fetch_unapproved "$ANDROID_DIR" "$ANDROID_PATH" "Android" &
    wait
} | sort -t'|' -k5

echo ""
echo "=== My merge requests ==="
{
    fetch_my_mrs "$IOS_DIR" "$IOS_PATH" "iOS" &
    fetch_my_mrs "$ANDROID_DIR" "$ANDROID_PATH" "Android" &
    wait
}
