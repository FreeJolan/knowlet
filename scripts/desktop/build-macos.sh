#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FRONTEND="$ROOT/frontend"
TAURI="$FRONTEND/src-tauri"

export PATH="/opt/homebrew/opt/rustup/bin:$PATH"
export LANG="en_US.UTF-8"
export LC_ALL="en_US.UTF-8"
export LC_CTYPE="en_US.UTF-8"

TEAM_ID="${KNOWLET_APPLE_TEAM_ID:-N8384H66R9}"
NOTARY_PROFILE="${KNOWLET_NOTARY_PROFILE:-knowlet-notary}"
NOTARY_API_KEY="${APPLE_API_KEY:-}"
NOTARY_API_ISSUER="${APPLE_API_ISSUER:-}"
NOTARY_API_KEY_PATH="${APPLE_API_KEY_PATH:-}"
APP="$TAURI/target/universal-apple-darwin/release/bundle/macos/Knowlet.app"
DMG="$TAURI/target/universal-apple-darwin/release/bundle/dmg/Knowlet_0.0.1_universal.dmg"
SIGNING_IDENTITY="Developer ID Application: Junnan Guo (N8384H66R9)"
ENTITLEMENTS="$TAURI/entitlements.plist"

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
