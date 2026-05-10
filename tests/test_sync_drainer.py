"""S4 / #112 — push drainer tests.

Locks the three terminal outcomes per dirty note:

- 200 OK → ``push_note`` returns a ``PushResult``; sync_state is
  advanced (dirty=False, last_known_etag bumped). on_synced fires.
- 412 / ConflictReport → ``push_note`` returns a ``ConflictReport``;
  sync_state stays dirty. on_conflict fires with the report.
- Network error → ``push_note`` raises; sync_state stays dirty;
  on_conflict / on_synced do NOT fire (we'll retry next tick).

Plus the no-op paths:

- No creds → drainer skips the tick entirely.
- Empty dirty list → drainer skips the tick entirely.
- DEV_FAKE_CONFLICT row → drainer skips that row (real Drive can't
  push to it).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from knowlet.core.note import Note, new_id
from knowlet.core.sync.credentials import (
    SyncCredentials,
    credentials_path,
    save_credentials,
)
from knowlet.core.sync.drainer import PushDrainer
from knowlet.core.sync.files import DriveFile
from knowlet.core.sync.oauth import SCOPES
from knowlet.core.sync.push import ConflictReport, PushResult
from knowlet.core.sync.state import FileState, SyncStateStore
from knowlet.core.sync.status import DEV_FAKE_DRIVE_FILE_ID


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


def _drive_file(rev: str) -> DriveFile:
    return DriveFile(
        id="DRIVE-FID-1",
        name="alpha.md",
        mime_type="text/markdown",
        modified_time="2026-05-11T12:00:00Z",
        head_revision_id=rev,
    )


def _stub_note(nid: str, body: str = "hello") -> Note:
    return Note(id=nid, title="alpha", body=body)


def test_drainer_noops_without_creds(tmp_path: Path) -> None:
    """Single-device user who never connected Drive: drainer must
    not crash, must not call out."""
    drainer = PushDrainer(
        vault_root=tmp_path,
        note_lookup=lambda _id: None,
    )
    # No creds, no error.
    drainer.tick_once()


def test_drainer_noops_with_empty_dirty_list(tmp_path: Path) -> None:
    _seed_creds(tmp_path)
    drainer = PushDrainer(
        vault_root=tmp_path,
        note_lookup=lambda _id: None,
    )
    with patch("knowlet.core.sync.drainer.push_note") as push_mock:
        drainer.tick_once()
    push_mock.assert_not_called()


def test_drainer_pushes_dirty_and_fires_synced(tmp_path: Path) -> None:
    """Dirty row + push returns 200 → on_synced callback fires."""
    _seed_creds(tmp_path)
    nid = new_id()
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=nid,
                drive_file_id="DRIVE-FID-1",
                last_known_etag="rev-OLD",
                last_synced_at="2024-01-01T00:00:00Z",
                dirty=True,
            )
        )
    finally:
        state.close()

    synced_seen: list[str] = []
    conflict_seen: list[tuple[str, ConflictReport]] = []
    note = _stub_note(nid)

    drainer = PushDrainer(
        vault_root=tmp_path,
        note_lookup=lambda _id: note if _id == nid else None,
        on_synced=synced_seen.append,
        on_conflict=lambda _i, r: conflict_seen.append((_i, r)),
    )

    push_result = PushResult(
        entity_type="note",
        entity_id=nid,
        drive_file=_drive_file("rev-NEW"),
        created=False,
    )
    with (
        patch(
            "knowlet.core.sync.drive_client.DriveClient.service",
            return_value=MagicMock(),
        ),
        patch("knowlet.core.sync.drainer.push_note", return_value=push_result),
    ):
        drainer.tick_once()

    assert synced_seen == [nid]
    assert conflict_seen == []


def test_drainer_412_fires_conflict_and_leaves_dirty(tmp_path: Path) -> None:
    """Drive moved between our last known revision and the push:
    drainer surfaces this immediately so the chip / Strict modal
    light up within seconds, without waiting for the next preflight."""
    _seed_creds(tmp_path)
    nid = new_id()
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=nid,
                drive_file_id="DRIVE-FID-1",
                last_known_etag="rev-OLD",
                last_synced_at="2024-01-01T00:00:00Z",
                dirty=True,
            )
        )
    finally:
        state.close()

    synced_seen: list[str] = []
    conflict_seen: list[tuple[str, ConflictReport]] = []
    note = _stub_note(nid)
    drainer = PushDrainer(
        vault_root=tmp_path,
        note_lookup=lambda _id: note if _id == nid else None,
        on_synced=synced_seen.append,
        on_conflict=lambda _i, r: conflict_seen.append((_i, r)),
    )

    conflict_report = ConflictReport(
        entity_type="note",
        entity_id=nid,
        drive_file_id="DRIVE-FID-1",
        expected_revision="rev-OLD",
        local_bytes=b"local body",
        remote_bytes=b"remote body",
        remote_metadata=_drive_file("rev-NEW"),
    )
    with (
        patch(
            "knowlet.core.sync.drive_client.DriveClient.service",
            return_value=MagicMock(),
        ),
        patch(
            "knowlet.core.sync.drainer.push_note", return_value=conflict_report
        ),
    ):
        drainer.tick_once()

    assert synced_seen == []
    assert len(conflict_seen) == 1
    assert conflict_seen[0][0] == nid
    # Sync state row must NOT have been mutated (push_note's contract
    # for ConflictReport is "leave state alone, caller resolves").
    state2 = SyncStateStore(tmp_path)
    try:
        rec = state2.get_file_state("note", nid)
    finally:
        state2.close()
    assert rec is not None
    assert rec.dirty is True
    assert rec.last_known_etag == "rev-OLD"


def test_drainer_swallows_network_errors_and_retries(tmp_path: Path) -> None:
    """A push raising ``ConnectionError`` should leave the row dirty
    so the next tick retries — not crash the drainer thread."""
    _seed_creds(tmp_path)
    nid = new_id()
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=nid,
                drive_file_id="DRIVE-FID-1",
                last_known_etag="rev-OLD",
                last_synced_at="2024-01-01T00:00:00Z",
                dirty=True,
            )
        )
    finally:
        state.close()

    synced_seen: list[str] = []
    conflict_seen: list[tuple[str, ConflictReport]] = []
    note = _stub_note(nid)
    drainer = PushDrainer(
        vault_root=tmp_path,
        note_lookup=lambda _id: note if _id == nid else None,
        on_synced=synced_seen.append,
        on_conflict=lambda _i, r: conflict_seen.append((_i, r)),
    )
    with (
        patch(
            "knowlet.core.sync.drive_client.DriveClient.service",
            return_value=MagicMock(),
        ),
        patch(
            "knowlet.core.sync.drainer.push_note",
            side_effect=ConnectionError("net dropped"),
        ),
    ):
        drainer.tick_once()
    # Neither callback fired.
    assert synced_seen == []
    assert conflict_seen == []
    # Still dirty, ready for the next tick.
    state2 = SyncStateStore(tmp_path)
    try:
        rec = state2.get_file_state("note", nid)
    finally:
        state2.close()
    assert rec is not None
    assert rec.dirty is True


def test_save_endpoint_marks_dirty_for_pushed_notes(tmp_path: Path) -> None:
    """End-to-end the server hook: PUT /api/notes/<id> on a note
    that already has a Drive id flips sync_state.dirty=True so the
    drainer picks it up next tick."""
    from tests.test_web import StubLLM, _client_with_stub

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    runtime = client.app.state.web_state.runtime  # type: ignore[attr-defined]
    assert runtime is not None
    note = Note(id=new_id(), title="alpha", body="initial")
    runtime.vault.write_note(note)
    runtime.index.upsert_note(
        note,
        chunk_size=runtime.config.retrieval.chunk_size,
        chunk_overlap=runtime.config.retrieval.chunk_overlap,
    )
    # Seed a synced sync_state row — note has been pushed before.
    store = SyncStateStore(tmp_path)
    try:
        store.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note.id,
                drive_file_id="DRIVE-FID-1",
                last_known_etag="rev-OLD",
                last_synced_at="2024-06-01T00:00:00Z",
                dirty=False,
            )
        )
    finally:
        store.close()
    # User saves — body changes, dirty should flip.
    r = client.put(
        f"/api/notes/{note.id}",
        json={"title": "alpha", "body": "edited content", "tags": []},
    )
    assert r.status_code == 200
    store2 = SyncStateStore(tmp_path)
    try:
        rec = store2.get_file_state("note", note.id)
    finally:
        store2.close()
    assert rec is not None
    assert rec.dirty is True


def test_save_endpoint_skips_never_pushed(tmp_path: Path) -> None:
    """A note that's never been pushed has no sync_state row; the
    save hook must be a no-op for it (first push goes through a
    different path, not the drainer)."""
    from tests.test_web import StubLLM, _client_with_stub

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    runtime = client.app.state.web_state.runtime  # type: ignore[attr-defined]
    assert runtime is not None
    note = Note(id=new_id(), title="alpha", body="initial")
    runtime.vault.write_note(note)
    runtime.index.upsert_note(
        note,
        chunk_size=runtime.config.retrieval.chunk_size,
        chunk_overlap=runtime.config.retrieval.chunk_overlap,
    )
    # No sync_state seed.
    r = client.put(
        f"/api/notes/{note.id}",
        json={"title": "alpha", "body": "edited", "tags": []},
    )
    assert r.status_code == 200
    store = SyncStateStore(tmp_path)
    try:
        rec = store.get_file_state("note", note.id)
    finally:
        store.close()
    assert rec is None  # no row materialized; first-push happens elsewhere


def test_drainer_skips_dev_fake_rows(tmp_path: Path) -> None:
    """DEV_FAKE_CONFLICT rows are dev-seeded conflicts with no real
    Drive backing; pushing them would 404. Drainer must skip them
    so they stay surfaced as test fixtures without polluting logs."""
    _seed_creds(tmp_path)
    nid = new_id()
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=nid,
                drive_file_id=DEV_FAKE_DRIVE_FILE_ID,
                last_known_etag="dev-rev-old",
                last_synced_at="2020-01-01T00:00:00Z",
                dirty=True,
            )
        )
    finally:
        state.close()
    drainer = PushDrainer(
        vault_root=tmp_path,
        note_lookup=lambda _id: _stub_note(nid),
    )
    with (
        patch(
            "knowlet.core.sync.drive_client.DriveClient.service",
            return_value=MagicMock(),
        ) as svc_mock,
        patch("knowlet.core.sync.drainer.push_note") as push_mock,
    ):
        drainer.tick_once()
    push_mock.assert_not_called()
    # Drive service was never even instantiated (lazy auth, no real
    # work to do).
    svc_mock.assert_not_called()
