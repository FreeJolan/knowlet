# Changelog

## [0.0.3] - 2026-05-30

Desktop daily dogfood release.

- Remember recent vaults and reopen the most recent valid vault on launch.
- Add native `Vault` menu actions for opening a vault, opening recent vaults,
  and switching vaults without restarting the desktop app.
- Add native `Digest` menu actions and status bridging for opening Digest and
  pulling sources from the macOS menu bar.
- Harden desktop backend lifecycle with readiness checks, per-vault backend
  startup logs, clearer startup diagnostics, and parent-process watchdog
  cleanup.
- Preserve normal macOS behavior by hiding the main window on close and
  restoring it from the Dock.

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
