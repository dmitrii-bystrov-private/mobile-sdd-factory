#!/usr/bin/env bash
# check-updates.sh — check for updates to dev tools and print changelogs

set -euo pipefail

BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RESET="\033[0m"

section() { echo -e "\n${BOLD}=== $1 ===${RESET}"; }

# ── Brew tools ───────────────────────────────────────────────────────────────
section "Brew tools"

check_brew_tool() {
    local tool=$1
    local is_cask=${2:-false}
    local cask_flag=""
    [[ "$is_cask" == "true" ]] && cask_flag="--cask"

    CURRENT=$(brew list --versions $cask_flag "$tool" 2>/dev/null | awk '{print $2}')
    OUTDATED_LINE=$(brew outdated --verbose $cask_flag "$tool" 2>/dev/null || true)
    if [[ -n "$OUTDATED_LINE" ]]; then
        LATEST=$(echo "$OUTDATED_LINE" | awk '{print $NF}')
        echo -e "${YELLOW}$tool${RESET}: $CURRENT → ${BOLD}$LATEST${RESET}"
        echo "  Update: brew upgrade $cask_flag $tool"
    else
        echo -e "${GREEN}$tool${RESET}: $CURRENT (up to date)"
    fi
}

check_brew_tool glab
check_brew_tool acli
check_brew_tool codex true

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

# ── npm global packages ───────────────────────────────────────────────────────
section "npm global packages"

OUTDATED=$(npm outdated -g --json 2>/dev/null || true)
if [[ -z "$OUTDATED" || "$OUTDATED" == "{}" ]]; then
    echo -e "${GREEN}All npm global packages are up to date${RESET}"
else
    echo "$OUTDATED" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for pkg, info in data.items():
    print(f'\033[33m{pkg}\033[0m: {info[\"current\"]} → \033[1m{info[\"latest\"]}\033[0m')
print('  Update: npm update -g')
"
fi
