#!/usr/bin/env bash
# Rebuild frontend/tailwind.css from tailwind.input.css.
#
# tailwindcss CLI ships as a single Go-built binary. Install once:
#   brew install tailwindcss   # macOS
#   # or download from https://github.com/tailwindlabs/tailwindcss/releases
#
# This script is idempotent — run after editing markup, tokens, or app.js.
# The output `frontend/tailwind.css` is committed to the repo so installs
# work offline (no Play CDN, no Node toolchain at runtime).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if ! command -v tailwindcss >/dev/null 2>&1; then
  echo "tailwindcss not found. Install via 'brew install tailwindcss'." >&2
  exit 1
fi

tailwindcss \
  -i frontend/tailwind.input.css \
  -o frontend/tailwind.css \
  --minify

echo "✓ frontend/tailwind.css rebuilt ($(wc -c < frontend/tailwind.css) bytes)"
