#!/usr/bin/env bash
# Run the frontend checks for the React app in frontend/.
#
# The old static web UI under knowlet/web/ and its `node --test` unit tests
# were removed when frontend/ replaced them. This wrapper runs the real suites:
#   - TypeScript type check: npx tsc --noEmit
#   - Playwright e2e suites: npm run e2e (builds dist, then runs every suite)
# To run a single e2e suite against an existing build:
#   cd frontend && SKIP_BUILD=1 node scripts/e2e/<file>.mjs

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT/frontend"

if ! command -v npm >/dev/null 2>&1; then
  echo "npm not found. Install Node 22+ (e.g. 'brew install node')." >&2
  exit 1
fi
if [[ ! -d node_modules ]]; then
  echo "frontend/node_modules is missing. Run 'cd frontend && npm ci' first." >&2
  exit 1
fi

npx tsc --noEmit
npm run e2e
