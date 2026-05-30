# Changelog

## [0.0.2] - 2026-05-30

Desktop updater UX release.

- Add in-app update discovery, status, download progress, install, and restart flow for signed Tauri updater artifacts.
- Add a desktop settings panel for manual update checks while keeping update actions hidden in the plain browser runtime.
- Add the Tauri process plugin permission needed to relaunch Knowlet after update installation.
- Keep lint from scanning generated Tauri build assets after desktop builds.

## [0.0.1] - 2026-05-30

First Knowlet macOS desktop dogfood build.

- Universal macOS app for Apple Silicon and Intel Macs.
- Self-contained React frontend bundle.
- Self-contained Python backend sidecars packaged with the app.
- Developer ID signing, Apple notarization, stapling, and Gatekeeper verification.

Known gaps:

- Updater feed and signed updater artifacts are prepared; in-app update prompt/install UX is not implemented yet.
- No menu bar/background Stage C pull surface yet.
- LLM provider credentials remain user/vault configuration and are not bundled.
