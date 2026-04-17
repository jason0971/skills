#!/bin/bash
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

if ! npm list -g @openai/codex --depth=0 &>/dev/null; then
  echo "Installing @openai/codex globally..."
  npm install -g @openai/codex
else
  echo "@openai/codex is already installed."
fi
