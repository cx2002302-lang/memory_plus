#!/usr/bin/env bash
# Memory Plus Quick Install — one command for AI Agent
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/cx2002302-lang/memory_plus/master/scripts/quick-install.sh | bash
set -euo pipefail

REPO_URL="https://github.com/cx2002302-lang/memory_plus.git"
TARGET="${1:-$HOME/.openclaw/memory-plus}"

echo "=========================================="
echo "  Memory Plus — Quick Install"
echo "=========================================="

command -v git     >/dev/null 2>&1 || { echo "Need git"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "Need Python ≥3.10"; exit 1; }
command -v pip3    >/dev/null 2>&1 || command -v pip >/dev/null 2>&1 || { echo "Need pip"; exit 1; }
PIP=$(command -v pip3 || command -v pip)

if [ -d "$TARGET/.git" ]; then
  echo "Updating existing install at $TARGET..."
  cd "$TARGET" && git pull --ff-only
  $PIP install -e . 2>/dev/null || $PIP install --break-system-packages -e .
else
  echo "Cloning to $TARGET..."
  git clone --depth 1 "$REPO_URL" "$TARGET"
  cd "$TARGET"
  $PIP install -e ".[test]" 2>/dev/null || $PIP install --break-system-packages -e ".[test]"
fi

echo ""
echo "=========================================="
echo "  Memory Plus installed!"
echo "=========================================="
echo ""
echo "Verify:  svm --version"
echo "Sync:    svm sync-status      (needs ZK database)"
echo ""
echo "For full stack (ZK + memory-plus + open-upsp):"
echo "  curl -fsSL https://raw.githubusercontent.com/cx2002302-lang/agent-stack/main/scripts/quick-install.sh | bash"
echo ""
