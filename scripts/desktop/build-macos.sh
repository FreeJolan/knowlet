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
APP="$TAURI/target/universal-apple-darwin/release/bundle/macos/Knowlet.app"
DMG="$TAURI/target/universal-apple-darwin/release/bundle/dmg/Knowlet_0.0.1_universal.dmg"
SIGNING_IDENTITY="Developer ID Application: Junnan Guo (N8384H66R9)"

cd "$FRONTEND"
npx tauri build --target universal-apple-darwin --bundles app

codesign --verify --deep --strict --verbose=2 "$APP"
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
xcrun notarytool submit "$DMG" \
  --keychain-profile "$NOTARY_PROFILE" \
  --team-id "$TEAM_ID" \
  --wait
xcrun stapler staple "$DMG"
xcrun stapler validate "$DMG"
spctl --assess --type open --context context:primary-signature --verbose=2 "$DMG"

echo "$DMG"
