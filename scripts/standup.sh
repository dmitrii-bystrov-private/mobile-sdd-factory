#!/usr/bin/env bash
# Fetch standup data from GitLab and Jira in parallel

IOS_DIR="/Users/d.bystrov/Projects/Finom/finomcommon"
ANDROID_DIR="/Users/d.bystrov/Projects/Finom/finom"

TMP=$(mktemp -d)

(cd "$IOS_DIR" && glab mr list --assignee @me 2>&1)   > "$TMP/ios_mine.txt"   &
(cd "$IOS_DIR" && glab mr list --reviewer @me 2>&1)   > "$TMP/ios_review.txt" &
(cd "$ANDROID_DIR" && glab mr list --assignee @me 2>&1) > "$TMP/andr_mine.txt"   &
(cd "$ANDROID_DIR" && glab mr list --reviewer @me 2>&1) > "$TMP/andr_review.txt" &
acli jira workitem search --filter 10494 --fields key,summary,status,priority 2>&1 > "$TMP/jira.txt" &

wait

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
