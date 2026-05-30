# macOS desktop distribution notes

Status: first signed dogfood shell is working, but the Python backend is not
yet bundled as an app sidecar.

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
  - It starts `knowlet web` on `127.0.0.1`.
  - It waits for `GET /api/health` to return HTTP 200 before opening the window.
  - It kills the backend process when the desktop app exits.

## Build

Prerequisites on the signing machine:

- Full Xcode installed and selected.
- Rust targets installed:
  - `aarch64-apple-darwin`
  - `x86_64-apple-darwin`
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

## Verification commands

```bash
cd frontend
PATH="/opt/homebrew/opt/rustup/bin:$PATH" npm run desktop:test
npx tsc --noEmit
```

```bash
uv run pytest tests/test_web.py::test_frontend_dist_env_override
spctl --assess --type open --context context:primary-signature --verbose=2 frontend/src-tauri/target/universal-apple-darwin/release/bundle/dmg/Knowlet_0.0.1_universal.dmg
xcrun stapler validate frontend/src-tauri/target/universal-apple-darwin/release/bundle/dmg/Knowlet_0.0.1_universal.dmg
codesign --verify --deep --strict --verbose=2 frontend/src-tauri/target/universal-apple-darwin/release/bundle/macos/Knowlet.app
```

Manual dogfood should cover both launch modes:

```bash
KNOWLET_VAULT=/path/to/vault frontend/src-tauri/target/universal-apple-darwin/release/bundle/macos/Knowlet.app/Contents/MacOS/knowlet-desktop
```

Then launch the same binary without `KNOWLET_VAULT` and select a vault from
the native folder picker.

## Known gap before external distribution

The current app starts the backend with:

```text
uv run --directory <repo-root> knowlet web ...
```

That means the notarized DMG is suitable for local dogfood on the signing
machine, but not yet a self-contained installer for other users. The next
distribution slice should replace this developer backend launcher with a
bundled sidecar.

Do not package the current Python environment directly with PyInstaller. A
probe showed that the existing development venv pulls optional ML dependencies
such as `torch`, `transformers`, `scipy`, and `sklearn` into analysis. Build a
thin backend environment first, explicitly excluding optional embedding/ML
stacks unless a future product decision makes local embedding mandatory.
