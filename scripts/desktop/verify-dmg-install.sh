#!/usr/bin/env bash
set -euo pipefail

DMG="${1:-}"
[[ -n "$DMG" ]] || {
  echo "Usage: scripts/desktop/verify-dmg-install.sh <Knowlet.dmg>" >&2
  exit 2
}
[[ -f "$DMG" ]] || {
  echo "DMG not found: $DMG" >&2
  exit 2
}

WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/knowlet-install-check.XXXXXX")"
MOUNT_DIR="$WORK_DIR/mount"
INSTALL_DIR="$WORK_DIR/install"
mkdir -p "$MOUNT_DIR" "$INSTALL_DIR"

cleanup() {
  hdiutil detach "$MOUNT_DIR" -quiet >/dev/null 2>&1 || true
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

hdiutil attach "$DMG" -nobrowse -readonly -mountpoint "$MOUNT_DIR" -quiet
ditto "$MOUNT_DIR/Knowlet.app" "$INSTALL_DIR/Knowlet.app"

APP="$INSTALL_DIR/Knowlet.app"
test -x "$APP/Contents/MacOS/knowlet-backend"
test -x "$APP/Contents/MacOS/knowlet-desktop"
test -x "$APP/Contents/Resources/knowlet-sidecars/knowlet-backend-aarch64-apple-darwin"
test -x "$APP/Contents/Resources/knowlet-sidecars/knowlet-backend-x86_64-apple-darwin"

codesign --verify --deep --strict --verbose=2 "$APP"
spctl --assess --type execute --verbose=2 "$APP"
"$APP/Contents/MacOS/knowlet-backend" --version
if [[ "$(uname -m)" == "arm64" ]]; then
  arch -x86_64 "$APP/Contents/MacOS/knowlet-backend" --version
fi

echo "DMG install verification passed: $DMG"
