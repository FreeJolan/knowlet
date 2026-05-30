# Changelog

## [0.0.1] - 2026-05-30

First Knowlet macOS desktop dogfood build.

- Universal macOS app for Apple Silicon and Intel Macs.
- Self-contained React frontend bundle.
- Self-contained Python backend sidecars packaged with the app.
- Developer ID signing, Apple notarization, stapling, and Gatekeeper verification.

Known gaps:

- No auto-update flow yet.
- No menu bar/background Stage C pull surface yet.
- LLM provider credentials remain user/vault configuration and are not bundled.
