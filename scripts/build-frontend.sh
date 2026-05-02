#!/usr/bin/env bash
# Rebuild knowlet/web/static/tailwind.css from tailwind.input.css.
#
# tailwindcss CLI ships as a single Go-built binary. Install once:
#   brew install tailwindcss   # macOS
#   # or download from https://github.com/tailwindlabs/tailwindcss/releases
#
# Run after editing markup, tokens, or app.js. The output is committed
# to the repo so installs work offline (no Play CDN, no Node at runtime).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if ! command -v tailwindcss >/dev/null 2>&1; then
  echo "tailwindcss not found. Install via 'brew install tailwindcss'." >&2
  exit 1
fi

STATIC=knowlet/web/static
tailwindcss \
  -i "$STATIC/tailwind.input.css" \
  -o "$STATIC/tailwind.css" \
  --minify

echo "✓ $STATIC/tailwind.css rebuilt ($(wc -c < $STATIC/tailwind.css) bytes)"
