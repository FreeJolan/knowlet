# macOS desktop distribution notes

Status: self-contained Developer ID DMG is working for local dogfood. The
bundle includes the React frontend, a universal backend launcher, and signed
PyInstaller backend sidecars for both Apple Silicon and Intel Macs.

## Current slice

- Framework: Tauri 2 desktop shell around the existing React/Vite web UI.
- Bundle ID: `com.meowjolan.knowlet`.
- Signing identity: `Developer ID Application: Junnan Guo (N8384H66R9)`.
- Notary profile: `knowlet-notary`.
- Build target: universal macOS app (`x86_64` + `arm64`).
- Runtime vault selection:
  - `KNOWLET_VAULT=/path/to/vault` is honored for tests and developer runs.
  - Valid vaults are remembered in the app config directory as
    `recent-vaults.json` with atomic write-then-rename updates.
  - Without `KNOWLET_VAULT`, the app first reopens the most recent valid vault.
    If all remembered paths are stale, it drops them and opens the native
    folder picker.
  - The native folder picker validates that the selected folder contains
    `.knowlet/`.
- Runtime vault switching:
  - The native Vault menu exposes `Open Vault...` with `CmdOrCtrl+O`.
  - The native Vault menu also exposes `Open Recent`, populated from the same
    valid recent-vault list used by startup auto-reopen. Stale paths are pruned
    before display, and the menu is refreshed after startup and after each
    vault switch.
  - Choosing another valid vault starts a fresh backend on a new loopback port,
    navigates the main window to it, stops the previous backend, and records the
    vault as most recent.
- Digest lifecycle:
  - The bundled backend starts the existing Stage C auto-pull loop after web
    bootstrap. It checks immediately when the desktop app comes online, then
    checks periodically so a cross-day online session pulls the next day's
    sources.
  - The main header Digest icon still polls `/api/digest/status` and animates
    while a pull is running.
  - The native Digest menu exposes a disabled status row plus `Open Digest` and
    `Pull Digest Now`. Menu actions are bridged into React with Tauri events,
    and React writes the latest status back to the native menu.
- Backend lifecycle:
  - The desktop shell picks a loopback port.
  - It starts the bundled backend sidecar on `127.0.0.1`.
  - It waits for `GET /api/health` to return HTTP 200 before opening the window.
  - It kills the backend process when the desktop app exits.
  - Backend stdout/stderr are written to `<vault>/.knowlet/desktop-backend.log`.
    The file is truncated for each launch so startup diagnostics only show the
    current attempt. Normal Python logging still goes to
    `<vault>/.knowlet/knowlet.log`.
  - If readiness fails, the desktop startup error includes the recent backend
    log tail and the full log path.
  - The desktop shell passes `KNOWLET_DESKTOP_PARENT_PID` to `knowlet web`; the
    backend exits itself if the desktop parent process disappears, reducing
    orphan sidecars after force-kill or crash cases.
- Bundle contents:
  - `Contents/MacOS/knowlet-backend` is a small universal launcher.
  - `Contents/Resources/knowlet-sidecars/` contains the real `arm64` and
    `x86_64` PyInstaller backend binaries.
  - `Contents/Resources/frontend-dist/` contains the production web assets.
- LLM credentials and endpoints are still user/vault configuration. The app
  does not bundle `cliproxyapi`, API keys, or model credentials.

## Build

Prerequisites on the signing machine:

- Full Xcode installed and selected.
- Rust targets installed:
  - `aarch64-apple-darwin`
  - `x86_64-apple-darwin`
- `uv` available for building thin Python sidecar environments.
- Apple notary keychain profile named `knowlet-notary`.

Command:

```bash
cd frontend
PATH="/opt/homebrew/opt/rustup/bin:$PATH" npm run desktop:build
```

Expected artifact:

```text
frontend/src-tauri/target/universal-apple-darwin/release/bundle/dmg/Knowlet_0.0.2_universal.dmg
```

The build script creates a simple DMG, signs it, submits it for notarization,
staples the ticket, and verifies it with Gatekeeper.

The backend sidecar build intentionally uses fresh thin Python environments and
`PyInstaller==6.20.0`, not the development virtualenv. Optional local-ML stacks
such as `torch`, `transformers`, `scipy`, and `sklearn` are explicitly excluded.
`sqlite_vec` binaries are explicitly collected because the web server needs
`vec0.dylib` at runtime.

## Verification commands

```bash
uv run pytest tests/
cd frontend
PATH="/opt/homebrew/opt/rustup/bin:$PATH" npm run desktop:test
npx tsc --noEmit
```

```bash
uv run pytest tests/test_web.py::test_frontend_dist_env_override
spctl --assess --type open --context context:primary-signature --verbose=2 frontend/src-tauri/target/universal-apple-darwin/release/bundle/dmg/Knowlet_0.0.2_universal.dmg
xcrun stapler validate frontend/src-tauri/target/universal-apple-darwin/release/bundle/dmg/Knowlet_0.0.2_universal.dmg
codesign --verify --deep --strict --verbose=2 frontend/src-tauri/target/universal-apple-darwin/release/bundle/macos/Knowlet.app
frontend/src-tauri/target/universal-apple-darwin/release/bundle/macos/Knowlet.app/Contents/MacOS/knowlet-backend --version
arch -x86_64 frontend/src-tauri/target/universal-apple-darwin/release/bundle/macos/Knowlet.app/Contents/MacOS/knowlet-backend --version
```

Manual dogfood should cover both launch modes:

```bash
KNOWLET_VAULT=/path/to/vault frontend/src-tauri/target/universal-apple-darwin/release/bundle/macos/Knowlet.app/Contents/MacOS/knowlet-desktop
```

Then launch the same binary without `KNOWLET_VAULT`. If the previous vault is
still valid, the app should reopen it without showing the picker. To verify the
first-run picker again, remove the app config `recent-vaults.json` file or point
it at stale paths.

For a self-contained launch probe, remove `uv` from `PATH` and confirm the
child backend process comes from `Knowlet.app/Contents/Resources/knowlet-sidecars/`:

```bash
PATH="/usr/bin:/bin" KNOWLET_VAULT=/path/to/vault \
  frontend/src-tauri/target/universal-apple-darwin/release/bundle/macos/Knowlet.app/Contents/MacOS/knowlet-desktop
```

## Current external-distribution gaps

- No first-run vault onboarding beyond the native folder picker.
- No Dock affordance yet.
- Parent-process watchdog is best-effort: an immediate signal-level kill is
  handled after the backend watchdog wakes up, not synchronously.
