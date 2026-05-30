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
  - Without `KNOWLET_VAULT`, the app opens a native folder picker and validates
    that the selected folder contains `.knowlet/`.
- Backend lifecycle:
  - The desktop shell picks a loopback port.
  - It starts the bundled backend sidecar on `127.0.0.1`.
  - It waits for `GET /api/health` to return HTTP 200 before opening the window.
  - It kills the backend process when the desktop app exits.
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
frontend/src-tauri/target/universal-apple-darwin/release/bundle/dmg/Knowlet_0.0.1_universal.dmg
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
spctl --assess --type open --context context:primary-signature --verbose=2 frontend/src-tauri/target/universal-apple-darwin/release/bundle/dmg/Knowlet_0.0.1_universal.dmg
xcrun stapler validate frontend/src-tauri/target/universal-apple-darwin/release/bundle/dmg/Knowlet_0.0.1_universal.dmg
codesign --verify --deep --strict --verbose=2 frontend/src-tauri/target/universal-apple-darwin/release/bundle/macos/Knowlet.app
frontend/src-tauri/target/universal-apple-darwin/release/bundle/macos/Knowlet.app/Contents/MacOS/knowlet-backend --version
arch -x86_64 frontend/src-tauri/target/universal-apple-darwin/release/bundle/macos/Knowlet.app/Contents/MacOS/knowlet-backend --version
```

Manual dogfood should cover both launch modes:

```bash
KNOWLET_VAULT=/path/to/vault frontend/src-tauri/target/universal-apple-darwin/release/bundle/macos/Knowlet.app/Contents/MacOS/knowlet-desktop
```

Then launch the same binary without `KNOWLET_VAULT` and select a vault from
the native folder picker.

For a self-contained launch probe, remove `uv` from `PATH` and confirm the
child backend process comes from `Knowlet.app/Contents/Resources/knowlet-sidecars/`:

```bash
PATH="/usr/bin:/bin" KNOWLET_VAULT=/path/to/vault \
  frontend/src-tauri/target/universal-apple-darwin/release/bundle/macos/Knowlet.app/Contents/MacOS/knowlet-desktop
```

## Current external-distribution gaps

- No auto-update or installer upgrade flow yet.
- No first-run vault onboarding beyond the native folder picker.
- No desktop menu-bar / background status surface for Stage C automatic pulls.
- Hard-killing the parent process with a signal can orphan the sidecar; normal
  app shutdown still goes through the desktop lifecycle guard.
