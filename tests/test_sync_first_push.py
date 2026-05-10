"""#113 — first-push (never-synced notes) entry tests.

Two endpoints:

- GET /api/sync/unpushed-status — returns count of indexed notes
  that don't have a synced ``sync_state.file_state`` row yet.
  Authenticated flag separately so the UI can hide the button on
  pre-auth boxes.
- POST /api/sync/push-all-unpushed — flips each unsynced note into
  a dirty ``sync_state.file_state`` row with ``drive_file_id=None``,
  which queues it for the drainer's first-push path
  (``push_note`` → ``upload_new_file``).

Both rely on the index for "notes on disk"; we mock Drive and
just verify the bookkeeping side effects.
"""

from __future__ import annotations

from pathlib import Path

from knowlet.core.note import Note, new_id
from knowlet.core.sync.credentials import (
    SyncCredentials,
    credentials_path,
    save_credentials,
)
from knowlet.core.sync.oauth import SCOPES
from knowlet.core.sync.state import FileState, SyncStateStore


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


def _plant_notes(client, count: int) -> list[str]:
    runtime = client.app.state.web_state.runtime  # type: ignore[attr-defined]
    assert runtime is not None
    ids: list[str] = []
    for i in range(count):
        note = Note(id=new_id(), title=f"note-{i}", body=f"body {i}")
        runtime.vault.write_note(note)
        runtime.index.upsert_note(
            note,
            chunk_size=runtime.config.retrieval.chunk_size,
            chunk_overlap=runtime.config.retrieval.chunk_overlap,
        )
        ids.append(note.id)
    return ids


def test_unpushed_status_unauthenticated(tmp_path: Path) -> None:
    """Single-device user, never connected Drive — endpoint reports
    authenticated=False + count=0 so the Settings UI hides the
    button without trying to enumerate."""
    from tests.test_web import StubLLM, _client_with_stub

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    _plant_notes(client, 3)
    r = client.get("/api/sync/unpushed-status")
    assert r.status_code == 200
    body = r.json()
    assert body["authenticated"] is False
    assert body["count"] == 0


def test_unpushed_status_counts_unsynced_notes(tmp_path: Path) -> None:
    """3 notes on disk, 1 already in sync_state with a drive_file_id
    → 2 unpushed."""
    from tests.test_web import StubLLM, _client_with_stub

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    ids = _plant_notes(client, 3)
    _seed_creds(tmp_path)

    store = SyncStateStore(tmp_path)
    try:
        store.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=ids[0],
                drive_file_id="DRIVE-FID-1",
                last_known_etag="rev-1",
                last_synced_at="2026-01-01T00:00:00Z",
                dirty=False,
            )
        )
    finally:
        store.close()

    r = client.get("/api/sync/unpushed-status")
    assert r.status_code == 200
    body = r.json()
    assert body["authenticated"] is True
    assert body["count"] == 2


def test_push_all_unpushed_queues_them(tmp_path: Path) -> None:
    """The POST endpoint creates dirty sync_state rows for each
    unsynced note. drainer picks them up on its next tick (tested
    separately in test_sync_drainer.py)."""
    from tests.test_web import StubLLM, _client_with_stub

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    ids = _plant_notes(client, 3)
    _seed_creds(tmp_path)

    r = client.post("/api/sync/push-all-unpushed")
    assert r.status_code == 200, r.text
    assert r.json()["queued"] == 3

    store = SyncStateStore(tmp_path)
    try:
        rows = {fs.entity_id: fs for fs in store.list_all_files()}
    finally:
        store.close()
    for nid in ids:
        assert nid in rows
        assert rows[nid].dirty is True
        assert rows[nid].drive_file_id is None  # first-push pending


def test_push_all_unpushed_skips_already_synced(tmp_path: Path) -> None:
    """Notes already with a drive_file_id stay put — the endpoint
    is idempotent on subsequent calls."""
    from tests.test_web import StubLLM, _client_with_stub

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    ids = _plant_notes(client, 2)
    _seed_creds(tmp_path)

    store = SyncStateStore(tmp_path)
    try:
        store.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=ids[0],
                drive_file_id="DRIVE-FID-EXISTING",
                last_known_etag="rev-1",
                last_synced_at="2026-01-01T00:00:00Z",
                dirty=False,
            )
        )
    finally:
        store.close()

    r = client.post("/api/sync/push-all-unpushed")
    assert r.json()["queued"] == 1  # only the unsynced one

    # First note untouched.
    store2 = SyncStateStore(tmp_path)
    try:
        rec = store2.get_file_state("note", ids[0])
    finally:
        store2.close()
    assert rec is not None
    assert rec.drive_file_id == "DRIVE-FID-EXISTING"
    assert rec.dirty is False


def test_push_all_unpushed_409_when_unauthenticated(tmp_path: Path) -> None:
    from tests.test_web import StubLLM, _client_with_stub

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    _plant_notes(client, 1)
    r = client.post("/api/sync/push-all-unpushed")
    assert r.status_code == 409
