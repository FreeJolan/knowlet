#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TAG="${1:-}"
[[ -n "$TAG" ]] || {
  echo "Usage: scripts/release/release-notes.sh vX.Y.Z" >&2
  exit 2
}
VERSION="${TAG#v}"
CHANGELOG="$ROOT/CHANGELOG.md"
[[ -f "$CHANGELOG" ]] || {
  echo "Missing CHANGELOG.md" >&2
  exit 2
}

awk -v version="$VERSION" '
  BEGIN { in_section = 0; found = 0 }
  $0 ~ "^## \\[" version "\\]" {
    in_section = 1
    found = 1
    next
  }
  in_section && /^## \[/ {
    exit
  }
  in_section {
    print
  }
  END {
    if (!found) {
      exit 1
    }
  }
' "$CHANGELOG" | sed '/./,$!d'
