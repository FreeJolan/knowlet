# Desktop Vault Delete + Sync Namespace Tracking

Date: 2026-05-31

## Scope

Allow users to remove a vault from Knowlet's desktop launcher without deleting
local files by default, optionally moving the local vault folder to the system
Trash. At the same time, scope Google Drive appData sync objects by stable
vault id so multiple local vaults can use the same Google account safely.

## Path Checklist

P1 Remove a recent vault record only  
☑ implemented · ☑ tested · ✓ dogfooded

P2 Remove a recent vault and move local files to Trash  
☑ implemented · ☑ tested · ✓ dogfooded

P3 Delete current active vault  
☑ implemented · ☑ tested · ✓ dogfooded

P4 Keep startup and Open Recent menu consistent  
☑ implemented · ☑ tested · ✓ dogfooded

P5 Create or lazily backfill stable vault id  
☑ implemented · ☑ tested · ✓ dogfooded

P6 Write new Drive appData objects under a vault namespace  
☑ implemented · ☑ tested · ✓ dogfooded

P7 Materialize only current-vault remote additions  
☑ implemented · ☑ tested · ✓ dogfooded

P8 Preserve compatibility with already-tracked flat legacy files  
☑ implemented · ☑ tested · ✓ dogfooded

P9 Prepare v0.0.14 release metadata  
☑ implemented · ☑ tested · ✓ dogfooded

## Test Mapping

- P1/P2/P4 -> `frontend/scripts/e2e/desktop-vault-launcher.mjs` and
  `frontend/src-tauri/src/recent_vaults.rs` unit tests.
- P2/P3 -> `frontend/src-tauri/src/backend.rs` unit tests and desktop command path.
- P5 -> `tests/test_vault_identity.py`.
- P6/P8 -> `tests/test_sync_push.py` and existing sync drainer/push coverage.
- P7/P8 -> `tests/test_sync_preflight.py` and `tests/test_sync_freshness.py`.
- P9 -> `scripts/release/prepare-version.sh --allow-dirty v0.0.14`.

## Verification

- `uv run ruff check knowlet tests`
- `uv run ruff format --check knowlet tests`
- `uv run pytest tests/` -> 1051 passed
- `cd frontend && npm run lint`
- `cd frontend && npx tsc --noEmit`
- `cd frontend && npm run build`
- `cd frontend && npm run e2e` -> 48/48 suites passed
- `cd frontend && PATH=/opt/homebrew/Cellar/rustup/1.29.0_1/bin:$PATH npm run desktop:test`
- `scripts/release/prepare-version.sh --allow-dirty v0.0.14`
