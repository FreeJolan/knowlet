# Changelog

## [0.0.6] - 2026-05-31

Desktop vault creation release.

- Add a first-run Vault Launcher for creating or opening a Knowlet vault when
  no valid vault is already selected.
- Add a native `Vault > New Vault...` action and a launcher flow that creates a
  new folder from the chosen parent directory and vault name.
- Handle existing-folder edge cases: empty folders require explicit
  confirmation, non-empty folders are blocked with a suggested alternate name,
  and already-initialized vaults are opened instead of re-created.
- Reject nested vaults during both creation and open-vault validation.

## [0.0.5] - 2026-05-31

Desktop startup hotfix release.

- Fix a Tauri startup crash caused by resolving the desktop config directory
  while the initial native menu is still being built.
- Keep the initial native menu path-free, then refresh recent-vault entries
  after desktop setup has initialized app path state.
- Add a regression test that guards the desktop bootstrap menu against
  reintroducing path-dependent initialization.

## [0.0.4] - 2026-05-31

Desktop updater ACL repair release.

- Allow the signed desktop shell to use updater and relaunch commands from the
  app's loopback backend URL.
- Add a regression test that prevents future updater releases from omitting the
  loopback Tauri capability.
- Keep the app version, desktop package version, and Python package version in
  sync for the repair release.

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
