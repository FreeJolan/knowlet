# Changelog

## [0.0.25] - 2026-08-03

Markdown editing fixes release.

- Restore ordered and unordered list markers in rendered Markdown while
  keeping task-list checkboxes free of duplicate bullets.
- Preserve rich clipboard formatting when pasting into the Markdown editor,
  including headings, emphasis, links, lists, tables, task lists, code, and
  images.
- Keep plain-text and image-file paste behavior unchanged, with regression
  coverage for rich text and the existing image upload flow.

## [0.0.24] - 2026-06-05

Drive trash restore hotfix release.

- Filter Drive appData file listings with `trashed=false` so notes that were
  deleted and synced to Drive trash are not materialized again by restore or
  preflight.
- Apply the same trash filter to remote Vault discovery and heartbeat lookups,
  preventing stale registry or heartbeat entries from influencing new-device
  recovery and multi-device presence.
- Add regressions for appData revision listing, remote Vault registry listing,
  and heartbeat lookup query shapes.

## [0.0.23] - 2026-06-04

Drive sync data boundary release.

- Expand Google Drive sync beyond notes and attachments to user profile, cards,
  drafts, mining tasks, digest sources/items, Quick Actions, favorites, quizzes,
  wiki schema, and a scrubbed public config snapshot.
- Keep device-specific and sensitive state local, including API keys, OAuth
  tokens, raw config secrets, indexes, caches, logs, backups, and local sync
  event databases.
- Restore synced vault files through the same Drive appData namespace so a
  recovered vault preserves non-note user data as well as the original note
  folder organization.
- Make `knowlet sync push` without a note id push the full syncable vault set,
  while preserving single-note push behavior when a note id is provided.
- Add regression coverage for syncable vault-file inventory, store dirty/delete
  hooks, config snapshot scrubbing, generic Drive restore, and Drive-side
  deletion materialization.

## [0.0.22] - 2026-06-04

Remote Drive Vault restore release.

- Add a desktop Restore from Drive flow so a new device can connect the same
  Google Drive account, discover existing remote Vaults, choose a local folder,
  bind the remote vault identity, and restore scoped appData before opening.
- Add a Drive appData Vault registry with legacy scoped-name discovery so
  existing synced Vaults can be found without copying `.knowlet/vault.json`.
- Add CLI parity with `knowlet sync vaults --json` and
  `knowlet sync restore-vault --remote-vault-id ... --to ...`.
- Improve the Discuss composer with a larger default input, drag resizing,
  long-form Markdown writing mode, and more stable long-form caret E2E
  coverage.
- Document that Vault identity is the stable sync id, not the folder name;
  creating a same-named Vault does not bind old remote data.

## [0.0.21] - 2026-06-03

Creation loading states release.

- Show explicit spinner and busy text while creating notes, templates, and
  Quick Actions so slow requests do not look stuck.
- Disable create dialogs, Quick Action rows, and command-palette action
  selection while the underlying create request is in flight.
- Add file-tree pending-row spinner feedback for newly submitted notes.
- Add E2E coverage for note creation, template creation, Quick Action save,
  Quick Action manager run, and command-palette Quick Action run loading states.

## [0.0.20] - 2026-06-03

Vault management and desktop data isolation release.

- Add a blocking Vault-switch progress overlay for desktop launcher and native
  menu switch paths so users can see that Knowlet is starting and checking the
  selected vault.
- Add a native `Manage Vaults...` menu entry that opens the desktop Vault
  manager for recent-vault management, creation, and opening flows.
- Keep production and developer/test desktop app state separate for recent
  vaults and restored window geometry.
- Add E2E coverage that Quick Actions created from a selected template apply
  the template body when run.

## [0.0.19] - 2026-06-02

Desktop right-click delete confirmation release.

- Replace the file-tree delete path's native browser confirmation with an
  app-owned confirmation dialog so the macOS desktop WebView can reliably
  complete right-click deletes.
- Prevent context-menu delete clicks from activating the note row underneath.
- Add E2E regressions for cancel, confirm, no native `window.confirm`, and
  no accidental note activation before deletion.

## [0.0.18] - 2026-06-02

Right-click delete hotfix release.

- Defer note and folder delete confirmation until after the file-tree context
  menu closes, avoiding the macOS desktop WebView no-response path.
- Add a Chinese UI E2E regression that verifies right-click delete sends the
  delete request only after confirmation runs outside the active context menu.

## [0.0.17] - 2026-06-02

AI diff application and sync visibility release.

- Add an `apply_current_note_edit` AI tool that can write the currently
  visible note diff only after the user explicitly asks to apply, accept,
  confirm, save, or commit the change.
- Pass the Discuss pane's pending diff into note chat requests so AI-driven
  application follows the same reviewed-diff contract as the manual button.
- Add a header sync overview showing whether local changes are still pending
  upload to Google Drive, with a "sync now" action that queues first-push notes
  and kicks the drainer immediately.
- Add backend and E2E regressions for explicit AI diff application and sync
  overview behavior.

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
