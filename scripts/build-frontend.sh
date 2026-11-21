#!/usr/bin/env bash
# Build the React frontend into frontend/dist.
#
# The old Tailwind bundle under knowlet/web/ no longer exists; the backend
# serves frontend/dist (KNOWLET_FRONTEND_DIST) and the desktop app bundles it.

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

npm run build
