#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FRONTEND="$ROOT/frontend"
TAURI="$FRONTEND/src-tauri"
SIDECAR_BUILD_ROOT="${KNOWLET_SIDECAR_BUILD_ROOT:-$TAURI/target/sidecars}"

export PATH="/opt/homebrew/opt/rustup/bin:$PATH"
export LANG="en_US.UTF-8"
export LC_ALL="en_US.UTF-8"
export LC_CTYPE="en_US.UTF-8"

TEAM_ID="${KNOWLET_APPLE_TEAM_ID:-N8384H66R9}"
NOTARY_PROFILE="${KNOWLET_NOTARY_PROFILE:-knowlet-notary}"
NOTARY_API_KEY="${APPLE_API_KEY:-}"
NOTARY_API_ISSUER="${APPLE_API_ISSUER:-}"
NOTARY_API_KEY_PATH="${APPLE_API_KEY_PATH:-}"
APP_VERSION="$(node -e 'const fs = require("fs"); const config = JSON.parse(fs.readFileSync(process.argv[1], "utf8")); console.log(config.version);' "$TAURI/tauri.conf.json")"
APP="$TAURI/target/universal-apple-darwin/release/bundle/macos/Knowlet.app"
DMG="$TAURI/target/universal-apple-darwin/release/bundle/dmg/Knowlet_${APP_VERSION}_universal.dmg"
SIGNING_IDENTITY="Developer ID Application: Junnan Guo (N8384H66R9)"
ENTITLEMENTS="$TAURI/entitlements.plist"
LOCAL_UPDATER_KEY="${KNOWLET_TAURI_SIGNING_PRIVATE_KEY_FILE:-$HOME/.tauri/knowlet-updater.key}"
LOCAL_UPDATER_PASSWORD="${KNOWLET_TAURI_SIGNING_PRIVATE_KEY_PASSWORD_FILE:-$HOME/.tauri/knowlet-updater.password}"

if [[ -z "${TAURI_SIGNING_PRIVATE_KEY:-}" && -f "$LOCAL_UPDATER_KEY" ]]; then
  export TAURI_SIGNING_PRIVATE_KEY="$LOCAL_UPDATER_KEY"
fi
if [[ -z "${TAURI_SIGNING_PRIVATE_KEY_PASSWORD:-}" && -f "$LOCAL_UPDATER_PASSWORD" ]]; then
  export TAURI_SIGNING_PRIVATE_KEY_PASSWORD="$(cat "$LOCAL_UPDATER_PASSWORD")"
fi

"$ROOT/scripts/desktop/build-backend-sidecars.sh"

cd "$FRONTEND"
(
  unset APPLE_API_KEY APPLE_API_ISSUER APPLE_API_KEY_PATH
  npx tauri build --target universal-apple-darwin --bundles app
)

test -x "$APP/Contents/MacOS/knowlet-backend"
test -f "$APP/Contents/Resources/frontend-dist/index.html"
test -x "$APP/Contents/Resources/knowlet-sidecars/knowlet-backend-aarch64-apple-darwin"
test -x "$APP/Contents/Resources/knowlet-sidecars/knowlet-backend-x86_64-apple-darwin"
file "$APP/Contents/MacOS/knowlet-backend"
file "$APP/Contents/Resources/knowlet-sidecars/knowlet-backend-aarch64-apple-darwin"
file "$APP/Contents/Resources/knowlet-sidecars/knowlet-backend-x86_64-apple-darwin"
codesign --force --options runtime --timestamp --entitlements "$ENTITLEMENTS" --sign "$SIGNING_IDENTITY" \
  "$APP/Contents/Resources/knowlet-sidecars/knowlet-backend-aarch64-apple-darwin"
codesign --force --options runtime --timestamp --entitlements "$ENTITLEMENTS" --sign "$SIGNING_IDENTITY" \
  "$APP/Contents/Resources/knowlet-sidecars/knowlet-backend-x86_64-apple-darwin"
codesign --force --options runtime --timestamp --sign "$SIGNING_IDENTITY" \
  "$APP/Contents/MacOS/knowlet-backend"
codesign --force --options runtime --timestamp --sign "$SIGNING_IDENTITY" \
  "$APP/Contents/MacOS/knowlet-desktop"
codesign --force --options runtime --timestamp --sign "$SIGNING_IDENTITY" "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"
"$APP/Contents/MacOS/knowlet-backend" --version
arch -x86_64 "$APP/Contents/MacOS/knowlet-backend" --version

# The universal app already contains the sidecars and merged Rust binary.
# Reclaim their large intermediate trees before hdiutil needs a second copy of
# the app while creating the DMG on space-constrained hosted runners.
case "$SIDECAR_BUILD_ROOT" in
  ""|/|"$ROOT"|"$FRONTEND"|"$TAURI"|"$TAURI/target")
    echo "Refusing to remove unsafe sidecar build root: $SIDECAR_BUILD_ROOT" >&2
    exit 1
    ;;
esac
rm -rf \
  "$SIDECAR_BUILD_ROOT" \
  "$TAURI/target/aarch64-apple-darwin" \
  "$TAURI/target/x86_64-apple-darwin"

rm -f "$DMG"
mkdir -p "$(dirname "$DMG")"
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/knowlet-dmg.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/Knowlet.app"
ln -s /Applications "$STAGE/Applications"
hdiutil create \
  -volname "Knowlet" \
  -srcfolder "$STAGE" \
  -ov \
  -format UDZO \
  "$DMG"
codesign --force --sign "$SIGNING_IDENTITY" "$DMG"
codesign --verify --deep --strict --verbose=2 "$DMG"
if [[ -n "$NOTARY_API_KEY" && -n "$NOTARY_API_ISSUER" && -n "$NOTARY_API_KEY_PATH" ]]; then
  xcrun notarytool submit "$DMG" \
    --key "$NOTARY_API_KEY_PATH" \
    --key-id "$NOTARY_API_KEY" \
    --issuer "$NOTARY_API_ISSUER" \
    --wait
else
  xcrun notarytool submit "$DMG" \
    --keychain-profile "$NOTARY_PROFILE" \
    --team-id "$TEAM_ID" \
    --wait
fi
xcrun stapler staple "$DMG"
xcrun stapler validate "$DMG"
spctl --assess --type open --context context:primary-signature --verbose=2 "$DMG"

echo "$DMG"
