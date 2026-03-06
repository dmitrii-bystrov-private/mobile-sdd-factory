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
check gws     "Install: npm install -g @googleworkspace/cli"
check glab    "Install: brew install glab"
check jira    "Install: brew install jira-cli"
check jq      "Install: brew install jq"

echo ""
echo "==> Auth setup (run these once if not done):"
echo "  gws auth setup     # Google Workspace OAuth"
echo "  glab auth login    # gitlab.com"
echo "  jira init          # jira.atlassian.net + API token"
echo ""
echo "==> Add alias to ~/.zshrc:"
echo "  alias a='cd ~/assistant && claude'"
echo ""
echo "==> Done. Run: source ~/.zshrc && a"