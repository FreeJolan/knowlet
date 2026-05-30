#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ALLOW_DIRTY=0
ALLOW_EXISTING_TAG=0
ALLOW_EXISTING_RELEASE=0
CREATE_TAG=0
TAG=""

usage() {
  cat <<'EOF'
Usage: scripts/release/prepare-version.sh [options] vX.Y.Z

Checks that the release tag, desktop versions, git state, and GitHub release
state are safe before publishing.

Options:
  --allow-dirty              Skip the clean working tree check.
  --allow-existing-tag       Allow an existing local or remote tag.
  --allow-existing-release   Allow an existing GitHub release.
  --create-tag               Create an annotated tag after checks pass.
  -h, --help                 Show this help.
EOF
}

fail() {
  echo "prepare-version: $*" >&2
  exit 1
}

json_version() {
  node -e 'const fs = require("fs"); const doc = JSON.parse(fs.readFileSync(process.argv[1], "utf8")); console.log(doc.version);' "$1"
}

package_lock_root_version() {
  node -e 'const fs = require("fs"); const doc = JSON.parse(fs.readFileSync(process.argv[1], "utf8")); console.log(doc.packages[""].version);' "$1"
}

toml_package_version() {
  awk -F '"' '/^version = "/ { print $2; exit }' "$1"
}

check_version() {
  local source="$1"
  local actual="$2"
  [[ "$actual" == "$VERSION" ]] || fail "$source version is $actual, expected $VERSION"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --allow-dirty)
      ALLOW_DIRTY=1
      ;;
    --allow-existing-tag)
      ALLOW_EXISTING_TAG=1
      ;;
    --allow-existing-release)
      ALLOW_EXISTING_RELEASE=1
      ;;
    --create-tag)
      CREATE_TAG=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    v*)
      [[ -z "$TAG" ]] || fail "only one tag may be provided"
      TAG="$1"
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
  shift
done

[[ -n "$TAG" ]] || fail "missing release tag"
[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || fail "tag must look like v0.0.1 or v0.0.1-beta.1: $TAG"
VERSION="${TAG#v}"

cd "$ROOT"

command -v git >/dev/null || fail "git is required"
command -v node >/dev/null || fail "node is required"

if [[ "$ALLOW_DIRTY" -eq 0 ]]; then
  git diff --quiet || fail "working tree has unstaged changes"
  git diff --cached --quiet || fail "index has staged changes"
fi

check_version "frontend/package.json" "$(json_version frontend/package.json)"
check_version "frontend/package-lock.json" "$(json_version frontend/package-lock.json)"
check_version "frontend/package-lock.json packages.root" "$(package_lock_root_version frontend/package-lock.json)"
check_version "frontend/src-tauri/tauri.conf.json" "$(json_version frontend/src-tauri/tauri.conf.json)"
check_version "frontend/src-tauri/Cargo.toml" "$(toml_package_version frontend/src-tauri/Cargo.toml)"

if [[ "$ALLOW_EXISTING_TAG" -eq 0 ]]; then
  ! git rev-parse --verify --quiet "refs/tags/$TAG" >/dev/null || fail "local tag already exists: $TAG"
  if git ls-remote --exit-code --tags origin "refs/tags/$TAG" >/dev/null 2>&1; then
    fail "remote tag already exists: $TAG"
  fi
fi

if command -v gh >/dev/null && gh auth status >/dev/null 2>&1; then
  if [[ "$ALLOW_EXISTING_RELEASE" -eq 0 ]] && gh release view "$TAG" --repo FreeJolan/knowlet >/dev/null 2>&1; then
    fail "GitHub release already exists: $TAG"
  fi
fi

if [[ "$CREATE_TAG" -eq 1 ]]; then
  [[ "$ALLOW_EXISTING_TAG" -eq 0 ]] || fail "--create-tag cannot be combined with --allow-existing-tag"
  git tag -a "$TAG" -m "Knowlet $TAG"
fi

echo "Release preflight passed for $TAG."
