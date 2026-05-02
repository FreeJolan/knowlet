#!/usr/bin/env bash
# Run frontend unit tests via Node native test runner.
#
# Per ADR-0008 §"Update 2026-05-02": hand-rolled stream / parser logic
# (knowlet/web/static/lib/sse.js, palette.js) and UI state-machine
# behaviors must have unit tests. This is how we run them.
#
# No npm, no node_modules — just `node --test`. Node 20+ required (we
# tested with v24.15). Install via Homebrew if missing:
#   brew install node

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if ! command -v node >/dev/null 2>&1; then
  echo "node not found. Install via 'brew install node'." >&2
  exit 1
fi

# Glob expansion needs the shell to handle it; --test on a directory walks
# all *.test.* files automatically as of Node 20+.
node --test 'knowlet/web/static/lib/tests/*.test.mjs'
