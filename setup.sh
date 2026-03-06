#!/usr/bin/env bash
# Initial project setup
set -euo pipefail

echo "==> Checking CLI tools..."

check() {
  if command -v "$1" &>/dev/null; then
    echo "  ✓ $1"
  else
    echo "  ✗ $1 — NOT FOUND. $2"
  fi
}

check claude  "Install: npm install -g @anthropic-ai/claude-code"
check glab    "Install: brew install glab"
check acli    "Install: brew tap atlassian/homebrew-acli && brew install acli"
check jq      "Install: brew install jq"

echo ""
echo "==> Auth setup (run these once if not done):"
echo "  glab auth login    # gitlab.com"
echo "  acli jira auth login  # Atlassian account OAuth"
echo ""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Add alias to ~/.zshrc:"
echo "  alias a='cd $SCRIPT_DIR && claude'"
echo ""
echo "==> Done. Run: source ~/.zshrc && a"