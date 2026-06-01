# Changelog

## [0.0.16] - 2026-06-02

Note deletion hotfix release.

- Make note deletion tolerate legacy `notes/...` index paths, stale index
  paths, and already-missing files so the UI can always clear the row and
  propagate the delete intent to sync.
- Add regressions for dirty index-path deletion and stale-row cleanup.

## [0.0.15] - 2026-06-02

Creation and template UX release.

- Add a dedicated template creation flow with template-specific title, body,
  and default kind controls instead of reusing the normal new-note dialog.
- Let Quick Actions inherit note kind from their selected template, defaulting
  to knowledge when no template is selected.
- Make the built-in today-note Quick Action use a reference-kind daily
  template, so today's default note is classified as reference material.
- Add centered empty-state creation affordances for fresh note vaults and
  empty template libraries.
- Fix deletion for nested index-path notes so notes can reliably be moved to
  trash from the UI.

## [0.0.14] - 2026-05-31

Desktop vault deletion and sync namespace release.

- Add a desktop vault deletion flow that removes a vault from the recent list
  by default, with an explicit opt-in checkbox to move local files to the
  system Trash.
- Scope new Google Drive appData files by stable vault id so multiple Knowlet
  vaults can share one Google account without mixing notes, Raw Info, digest
  source configs, attachments, or heartbeats.
- Preserve tracked legacy sync files while ignoring unrelated remote appData
  objects from other vaults during freshness checks and preflight materializing.

## [0.0.13] - 2026-05-31

Desktop sync OAuth hotfix release.

- Fix the Google Drive realtime freshness gate after OAuth connect by passing
  the `DriveClient` wrapper to the freshness layer instead of the raw Google
  Drive service object.
- Add regressions for the post-connect preflight bootstrap and the existing
  Drive changes freshness probe.

## [0.0.12] - 2026-05-31

Desktop window restoration release.

- Remember and restore the desktop main window and vault launcher size,
  position, maximized state, and fullscreen state across app restarts and
  updater relaunches.
- Restore windows before showing them to avoid visible default-position jumps.
- Keep window visibility out of persisted state so macOS close-to-hide does not
  make the next launch invisible.

## [0.0.11] - 2026-05-31

Desktop sync dependency hotfix release.

- Bundle the Google Drive sync extra into desktop backend sidecars so Drive
  OAuth can import `google_auth_oauthlib` inside the signed app.
- Add a packaging regression test that prevents future desktop releases from
  omitting the sync extra.

## [0.0.10] - 2026-05-31

Sync v2 CI repair release.

- Interpret digest source success timestamps using the user's local calendar
  day so daily auto-pull checks behave correctly near UTC/local midnight.
- Stabilize the daily digest auto-pull regression test so CI no longer depends
  on the date the suite happens to run.

## [0.0.9] - 2026-05-31

Sync v2 multi-device release.

- Default Google Drive sync to multi-device realtime mode, with a separate
  backup-only mode for single-device users.
- Add a lightweight Drive freshness probe that only blocks the app after
  remote changes are detected or the app cannot prove local data is current.
- Add blocking sync UX for confirmed remote updates and an offline fallback
  path when Drive cannot be reached.
- Sync Digest Source configuration and Raw Info inbox JSON through Drive
  appData alongside notes and attachments.
- Update sync docs and roadmap to retire the old Auto / Strict / Lax model.

## [0.0.8] - 2026-05-31

Desktop new-vault tree hotfix release.

- Default fresh vaults to the bundled embedding backend so the self-contained
  desktop sidecar can open a new vault without optional ML dependencies.
- Fall back to the bundled embedding backend when an older vault is configured
  for `sentence_transformers` but the optional package is not installed.
- Make config writes use unique temporary files so parallel config updates do
  not collide on `.knowlet/config.toml.tmp`.

## [0.0.7] - 2026-05-31

Desktop vault open hotfix release.

- Allow the desktop/web backend to start when a vault has no LLM API key.
- Keep local note browsing and the file tree available while AI credentials are
  unconfigured.
- Preserve the stricter API-key requirement for the chat-first CLI bootstrap.

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
