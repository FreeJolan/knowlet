"""Phase 2 E Slice S1 — per-note sync status (ADR-0027 redesign).

Five states the UI binds against; this test suite locks each one
under a controlled fixture. Drive interactions go through the
``_drive_service`` seam so we mock at a single point.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from knowlet.core.note import new_id
from knowlet.core.sync.credentials import (
    SyncCredentials,
    credentials_path,
    save_credentials,
)
from knowlet.core.sync.files import DriveFile
from knowlet.core.sync.oauth import SCOPES
from knowlet.core.sync.state import FileState, SyncStateStore
from knowlet.core.sync.status import compute_note_sync_status


def _seed_creds(tmp_path: Path) -> None:
    save_credentials(
        credentials_path(tmp_path),
        SyncCredentials(
            user_email="alice@example.com",
            token={
                "scopes": list(SCOPES),
                "token": "x",
                "refresh_token": "y",
                "client_id": "c",
                "client_secret": "s",
                "token_uri": "https://oauth2.googleapis.com/token",
            },
        ),
    )


def _drive_meta(rev: str) -> DriveFile:
    return DriveFile(
        id="DRIVE-FID-1",
        name="alpha.md",
        mime_type="text/markdown",
        modified_time="2026-05-10T12:00:00Z",
        head_revision_id=rev,
    )


def _patch_service():
    """Patch _drive_service so tests don't try to talk to Google."""
    return patch(
        "knowlet.core.sync.status._drive_service",
        return_value=MagicMock(),
    )


# ----------------------------------------------------- five states


def test_unauthenticated_when_no_credentials(tmp_path: Path) -> None:
    state = SyncStateStore(tmp_path)
    try:
        status = compute_note_sync_status(
            vault_root=tmp_path, note_id=new_id(), state_store=state
        )
    finally:
        state.close()
    assert status.state == "unauthenticated"


def test_unauthenticated_when_scope_stale(tmp_path: Path) -> None:
    save_credentials(
        credentials_path(tmp_path),
        SyncCredentials(
            token={"scopes": ["https://www.googleapis.com/auth/drive.file"]}
        ),
    )
    state = SyncStateStore(tmp_path)
    try:
        status = compute_note_sync_status(
            vault_root=tmp_path, note_id=new_id(), state_store=state
        )
    finally:
        state.close()
    assert status.state == "unauthenticated"
    assert status.detail and "scope" in status.detail.lower()


def test_dirty_when_no_drive_id_yet(tmp_path: Path) -> None:
    """A note that's never been pushed has no sync_state record (or
    has one with no drive_file_id). Treat as 'needs first push'."""
    _seed_creds(tmp_path)
    state = SyncStateStore(tmp_path)
    try:
        status = compute_note_sync_status(
            vault_root=tmp_path, note_id=new_id(), state_store=state
        )
    finally:
        state.close()
    assert status.state == "dirty"


def test_synced_when_revisions_match(tmp_path: Path) -> None:
    _seed_creds(tmp_path)
    note_id = new_id()
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note_id,
                drive_file_id="DRIVE-FID-1",
                last_known_etag="rev-MINE",
                last_synced_at="2026-05-10T00:00:00Z",
                dirty=False,
            )
        )
        with (
            _patch_service(),
            patch(
                "knowlet.core.sync.status.get_file_metadata",
                return_value=_drive_meta("rev-MINE"),
            ),
        ):
            status = compute_note_sync_status(
                vault_root=tmp_path,
                note_id=note_id,
                state_store=state,
            )
    finally:
        state.close()
    assert status.state == "synced"
    assert status.last_known_revision == "rev-MINE"
    assert status.current_drive_revision == "rev-MINE"


def test_conflict_when_revisions_diverge(tmp_path: Path) -> None:
    _seed_creds(tmp_path)
    note_id = new_id()
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note_id,
                drive_file_id="DRIVE-FID-1",
                last_known_etag="rev-MINE",
                last_synced_at="2026-05-10T00:00:00Z",
                dirty=False,
            )
        )
        with (
            _patch_service(),
            patch(
                "knowlet.core.sync.status.get_file_metadata",
                return_value=_drive_meta("rev-NEW"),
            ),
        ):
            status = compute_note_sync_status(
                vault_root=tmp_path,
                note_id=note_id,
                state_store=state,
            )
    finally:
        state.close()
    assert status.state == "conflict"
    assert status.last_known_revision == "rev-MINE"
    assert status.current_drive_revision == "rev-NEW"


def test_offline_when_drive_call_raises(tmp_path: Path) -> None:
    """Drive's API throws (network blip, 5xx, expired refresh token) —
    we mark offline rather than crashing. Detail carries the error
    repr for tooltips."""
    _seed_creds(tmp_path)
    note_id = new_id()
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note_id,
                drive_file_id="DRIVE-FID-1",
                last_known_etag="rev-MINE",
                last_synced_at="2026-05-10T00:00:00Z",
                dirty=False,
            )
        )
        with (
            _patch_service(),
            patch(
                "knowlet.core.sync.status.get_file_metadata",
                side_effect=ConnectionError("network down"),
            ),
        ):
            status = compute_note_sync_status(
                vault_root=tmp_path,
                note_id=note_id,
                state_store=state,
            )
    finally:
        state.close()
    assert status.state == "offline"
    assert status.detail and "network down" in status.detail


# ----------------------------------------------------- API integration


def test_api_endpoint_returns_status(tmp_path: Path) -> None:
    """End-to-end through the FastAPI surface: create a stub client,
    seed a synced sync_state record, mock Drive, hit the endpoint."""
    from tests.test_web import StubLLM, _client_with_stub

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    _seed_creds(tmp_path)
    note_id = new_id()
    store = SyncStateStore(tmp_path)
    try:
        store.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note_id,
                drive_file_id="DRIVE-FID-1",
                last_known_etag="rev-MINE",
                last_synced_at="2026-05-10T00:00:00Z",
                dirty=False,
            )
        )
    finally:
        store.close()
    with (
        _patch_service(),
        patch(
            "knowlet.core.sync.status.get_file_metadata",
            return_value=_drive_meta("rev-MINE"),
        ),
    ):
        r = client.get(f"/api/sync/note-status/{note_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "synced"
    assert body["last_known_revision"] == "rev-MINE"
    assert body["current_drive_revision"] == "rev-MINE"


def test_api_endpoint_dirty_for_unknown_note(tmp_path: Path) -> None:
    """Asking for status on a note that's never been pushed returns
    `dirty` rather than 404 — the UI handles 'this note has never
    talked to Drive' as a state, not an error."""
    from tests.test_web import StubLLM, _client_with_stub

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    _seed_creds(tmp_path)
    r = client.get("/api/sync/note-status/01NEVERPUSHED000000000000")
    assert r.status_code == 200
    assert r.json()["state"] == "dirty"


def test_api_endpoint_unauthenticated(tmp_path: Path) -> None:
    """No creds file → state=unauthenticated. UI hides the badge."""
    from tests.test_web import StubLLM, _client_with_stub

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.get("/api/sync/note-status/01ANYTHING000000000000000")
    assert r.status_code == 200
    assert r.json()["state"] == "unauthenticated"
