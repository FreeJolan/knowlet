"""HTTP tests for Sync v2 realtime freshness gates."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from knowlet.config import KnowletConfig, save_config
from knowlet.core.audit_log import AuditEventStore
from knowlet.core.backups import BackupStore
from knowlet.core.sync.preflight import PreflightConflict, PreflightReport
from knowlet.core.sync.state import SyncStateStore
from knowlet.core.vault import Vault
from knowlet.web.server import create_app


def _client(tmp_path: Path) -> tuple[TestClient, Vault]:
    vault = Vault(
        tmp_path,
        audit_log=AuditEventStore(tmp_path),
        backups=BackupStore(tmp_path),
    )
    vault.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = "stub"
    save_config(vault.root, cfg)
    return TestClient(create_app(vault, cfg)), vault


def _clear_report() -> PreflightReport:
    return PreflightReport(
        conflicts=[],
        offline=[],
        auto_pulled_ids=[],
        synced_count=0,
        dirty_count=0,
        scanned=0,
        unauthenticated=False,
        alive_devices=[],
    )


def test_sync_mode_api_defaults_to_realtime(tmp_path: Path) -> None:
    client, _vault = _client(tmp_path)

    response = client.get("/api/sync/mode")

    assert response.status_code == 200
    assert response.json() == {
        "mode": "realtime",
        "effective_mode": "realtime",
        "device_count": 0,
    }


def test_sync_mode_api_accepts_backup_and_realtime_only(tmp_path: Path) -> None:
    client, _vault = _client(tmp_path)

    backup = client.put("/api/sync/mode", json={"mode": "backup"})
    assert backup.status_code == 200
    assert backup.json()["mode"] == "backup"
    assert backup.json()["effective_mode"] == "backup"

    realtime = client.put("/api/sync/mode", json={"mode": "realtime"})
    assert realtime.status_code == 200
    assert realtime.json()["mode"] == "realtime"

    invalid = client.put("/api/sync/mode", json={"mode": "strict"})
    assert invalid.status_code == 400


def test_sync_freshness_api_reports_backup_mode_without_blocking(tmp_path: Path) -> None:
    client, vault = _client(tmp_path)
    store = SyncStateStore(vault.root)
    try:
        store.set_sync_mode("backup")
    finally:
        store.close()

    response = client.get("/api/sync/freshness")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "backup"
    assert body["state"] == "backup"
    assert body["requires_sync"] is False


def test_sync_freshness_api_requires_initial_realtime_sync(tmp_path: Path) -> None:
    client, _vault = _client(tmp_path)

    response = client.get("/api/sync/freshness")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "realtime"
    assert body["state"] == "needs_sync"
    assert body["reason"] == "uninitialized"
    assert body["requires_sync"] is True


def test_preflight_advances_freshness_cursor_only_after_clean_sync(
    tmp_path: Path,
) -> None:
    client, _vault = _client(tmp_path)

    with (
        patch("knowlet.core.sync.preflight.preflight_scan", return_value=_clear_report()),
        patch("knowlet.core.sync.freshness.mark_freshness_synced") as mark_synced,
    ):
        response = client.post("/api/sync/preflight")

    assert response.status_code == 200
    mark_synced.assert_called_once()


def test_preflight_keeps_cursor_when_conflicts_remain(tmp_path: Path) -> None:
    client, _vault = _client(tmp_path)
    report = PreflightReport(
        conflicts=[
            PreflightConflict(
                note_id="01CONFLICT",
                note_title="Conflict",
                drive_file_id="drive-conflict",
                last_synced_at=None,
                last_known_revision="rev-1",
                current_drive_revision="rev-2",
                remote_modified_at=None,
                remote_modified_by=None,
            )
        ],
        offline=[],
        auto_pulled_ids=[],
        synced_count=0,
        dirty_count=0,
        scanned=1,
        unauthenticated=False,
        alive_devices=[],
    )

    with (
        patch("knowlet.core.sync.preflight.preflight_scan", return_value=report),
        patch("knowlet.core.sync.freshness.mark_freshness_synced") as mark_synced,
    ):
        response = client.post("/api/sync/preflight")

    assert response.status_code == 200
    mark_synced.assert_not_called()
