#!/usr/bin/env bash
# check-updates.sh — check for updates to dev tools and print changelogs

set -euo pipefail

BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RESET="\033[0m"

section() { echo -e "\n${BOLD}=== $1 ===${RESET}"; }

# ── Brew tools (glab, acli) ──────────────────────────────────────────────────
section "Brew tools"

for tool in glab acli; do
    CURRENT=$(brew list --versions "$tool" 2>/dev/null | awk '{print $2}')
    OUTDATED_LINE=$(brew outdated --verbose "$tool" 2>/dev/null || true)
    if [[ -n "$OUTDATED_LINE" ]]; then
        LATEST=$(echo "$OUTDATED_LINE" | awk '{print $NF}')
        echo -e "${YELLOW}$tool${RESET}: $CURRENT → ${BOLD}$LATEST${RESET}"
        echo "  Changelog: $(brew info "$tool" --json | python3 -c "import sys,json; d=json.load(sys.stdin)[0]; print(d.get('urls',{}).get('homepage',''))" 2>/dev/null)"
        echo "  Update: brew upgrade $tool"
    else
        echo -e "${GREEN}$tool${RESET}: $CURRENT (up to date)"
    fi
done

# ── Claude Code ──────────────────────────────────────────────────────────────
section "Claude Code CLI"

CURRENT=$(claude --version 2>/dev/null | awk '{print $1}')
LATEST=$(npm view @anthropic-ai/claude-code version 2>/dev/null || echo "unknown")

if [[ "$CURRENT" == "$LATEST" ]]; then
    echo -e "${GREEN}claude${RESET}: $CURRENT (up to date)"
else
    echo -e "${YELLOW}claude${RESET}: $CURRENT → ${BOLD}$LATEST${RESET}"
    echo "  Changelog: https://github.com/anthropics/claude-code/releases/tag/$LATEST"
    echo "  Update: claude update"
fi
