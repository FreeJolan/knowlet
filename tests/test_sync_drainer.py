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
from knowlet.core.sync.push import (
    DIGEST_SOURCE_ENTITY_TYPE,
    ConflictReport,
    PushResult,
)
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
        patch("knowlet.core.sync.drainer.push_note", return_value=conflict_report),
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


def test_save_endpoint_skips_never_pushed_without_creds(tmp_path: Path) -> None:
    """Without Drive creds, the save hook stays a no-op even on a
    never-pushed note — we don't want to pile up dirty rows that
    can never push. (#117 — with creds, the same scenario DOES
    auto-track; covered by test_save_endpoint_auto_tracks_new_note.)"""
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
    # No sync_state seed AND no Drive creds.
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
    assert rec is None  # no row materialized; user hasn't connected Drive


def test_save_endpoint_auto_tracks_new_note(tmp_path: Path) -> None:
    """#117 — with Drive creds present, saving a never-pushed note
    creates a dirty sync_state row with drive_file_id=None so the
    drainer's first-push path picks it up next tick. Closes the
    "new notes never auto-push" silent bug."""
    from tests.test_sync_status import _seed_creds
    from tests.test_web import StubLLM, _client_with_stub

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    runtime = client.app.state.web_state.runtime  # type: ignore[attr-defined]
    assert runtime is not None
    _seed_creds(tmp_path)
    note = Note(id=new_id(), title="alpha", body="initial")
    runtime.vault.write_note(note)
    runtime.index.upsert_note(
        note,
        chunk_size=runtime.config.retrieval.chunk_size,
        chunk_overlap=runtime.config.retrieval.chunk_overlap,
    )
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
    assert rec is not None
    assert rec.drive_file_id is None  # first-push pending
    assert rec.dirty is True


def test_move_note_endpoint_marks_dirty_and_persists_folder_hint(tmp_path: Path) -> None:
    """Moving a synced note changes cross-device state, not just local IA.

    The endpoint must queue the note for push and persist the new folder hint
    so a fresh restore can rebuild the same tree from flat Drive appData.
    """
    from tests.test_web import StubLLM, _client_with_stub

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    runtime = client.app.state.web_state.runtime  # type: ignore[attr-defined]
    assert runtime is not None
    _seed_creds(tmp_path)
    note = Note(id=new_id(), title="movable", body="initial")
    runtime.vault.write_note(note)
    runtime.index.upsert_note(
        note,
        chunk_size=runtime.config.retrieval.chunk_size,
        chunk_overlap=runtime.config.retrieval.chunk_overlap,
    )
    store = SyncStateStore(tmp_path)
    try:
        store.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note.id,
                drive_file_id="DRIVE-FID-1",
                last_known_etag="rev-1",
                last_synced_at="2026-06-01T00:00:00Z",
                dirty=False,
            )
        )
    finally:
        store.close()

    r = client.post(f"/api/notes/{note.id}/move", json={"target_folder": "archive"})

    assert r.status_code == 200, r.text
    moved_path = runtime.vault.notes_dir / "archive" / note.filename
    assert Note.from_file(moved_path).folder == "archive"
    state = SyncStateStore(tmp_path)
    try:
        rec = state.get_file_state("note", note.id)
    finally:
        state.close()
    assert rec is not None
    assert rec.dirty is True


# ----------------------------------------------------- #121 attachments


def test_drainer_pushes_dirty_attachment_via_push_attachment(
    tmp_path: Path,
) -> None:
    """An attachment dirty row dispatches to ``push_attachment`` (not
    ``push_note``) and clears on success."""
    _seed_creds(tmp_path)
    att_dir = tmp_path / "_attachments"
    att_dir.mkdir()
    att_path = att_dir / "01HABC.png"
    att_path.write_bytes(b"PNG")

    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="attachment",
                entity_id="01HABC.png",
                drive_file_id=None,
                last_known_etag=None,
                last_synced_at=None,
                dirty=True,
            )
        )
    finally:
        state.close()

    synced_seen: list[str] = []
    drainer = PushDrainer(
        vault_root=tmp_path,
        note_lookup=lambda _id: None,
        attachment_lookup=lambda name: att_path if name == "01HABC.png" else None,
        on_synced=synced_seen.append,
    )

    push_result = PushResult(
        entity_type="attachment",
        entity_id="01HABC.png",
        drive_file=_drive_file("rev-NEW"),
        created=True,
    )
    with (
        patch(
            "knowlet.core.sync.drive_client.DriveClient.service",
            return_value=MagicMock(),
        ),
        patch(
            "knowlet.core.sync.drainer.push_attachment",
            return_value=push_result,
        ) as att_push,
        patch("knowlet.core.sync.drainer.push_note") as note_push,
    ):
        drainer.tick_once()

    note_push.assert_not_called()
    assert att_push.call_count == 1
    assert synced_seen == ["01HABC.png"]


def test_drainer_drops_attachment_row_when_file_vanishes(
    tmp_path: Path,
) -> None:
    """If the on-disk file is gone, the drainer drops the row instead
    of looping on it forever."""
    _seed_creds(tmp_path)
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="attachment",
                entity_id="01HGONE.png",
                drive_file_id=None,
                last_known_etag=None,
                last_synced_at=None,
                dirty=True,
            )
        )
    finally:
        state.close()

    drainer = PushDrainer(
        vault_root=tmp_path,
        note_lookup=lambda _id: None,
        attachment_lookup=lambda _name: None,
    )
    with (
        patch(
            "knowlet.core.sync.drive_client.DriveClient.service",
            return_value=MagicMock(),
        ),
        patch("knowlet.core.sync.drainer.push_attachment") as att_push,
    ):
        drainer.tick_once()
    att_push.assert_not_called()
    state2 = SyncStateStore(tmp_path)
    try:
        assert state2.get_file_state("attachment", "01HGONE.png") is None
    finally:
        state2.close()


def test_drainer_pushes_dirty_digest_source_file(
    tmp_path: Path,
) -> None:
    """Digest source configs are vault data too; the drainer should
    push them as appData JSON files so another device sees the same
    source list after realtime sync."""
    _seed_creds(tmp_path)
    source_path = tmp_path / "01SRC-ai-feed.json"
    source_path.write_text('{"name":"AI feed"}\n', encoding="utf-8")

    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type=DIGEST_SOURCE_ENTITY_TYPE,
                entity_id=source_path.name,
                drive_file_id=None,
                last_known_etag=None,
                last_synced_at=None,
                dirty=True,
            )
        )
    finally:
        state.close()

    synced_seen: list[str] = []
    drainer = PushDrainer(
        vault_root=tmp_path,
        note_lookup=lambda _id: None,
        synced_file_lookup=lambda entity_type, entity_id: (
            source_path
            if entity_type == DIGEST_SOURCE_ENTITY_TYPE and entity_id == source_path.name
            else None
        ),
        on_synced=synced_seen.append,
    )

    push_result = PushResult(
        entity_type=DIGEST_SOURCE_ENTITY_TYPE,
        entity_id=source_path.name,
        drive_file=_drive_file("digest-rev-1"),
        created=True,
    )
    with (
        patch(
            "knowlet.core.sync.drive_client.DriveClient.service",
            return_value=MagicMock(),
        ),
        patch(
            "knowlet.core.sync.drainer.push_vault_file",
            return_value=push_result,
        ) as file_push,
        patch("knowlet.core.sync.drainer.push_note") as note_push,
    ):
        drainer.tick_once()

    note_push.assert_not_called()
    file_push.assert_called_once()
    assert file_push.call_args.kwargs["entity_type"] == DIGEST_SOURCE_ENTITY_TYPE
    assert file_push.call_args.kwargs["entity_id"] == source_path.name
    assert file_push.call_args.kwargs["path"] == source_path
    assert synced_seen == [source_path.name]


def test_drainer_untracked_sweep_queues_notes_and_attachments(
    tmp_path: Path,
) -> None:
    """The untracked sweep callback returns ``(entity_type, id)``
    tuples; the drainer must insert dirty first-push rows for each
    on its first creds-positive tick."""
    _seed_creds(tmp_path)

    drainer = PushDrainer(
        vault_root=tmp_path,
        note_lookup=lambda _id: None,
        attachment_lookup=lambda _name: None,
        untracked_sweep=lambda: [
            ("note", "NID-1"),
            ("attachment", "01HABC.png"),
        ],
    )
    # No real Drive work happens because the rows we just queued
    # have no on-disk source (the note_lookup returns None and the
    # attachment_lookup returns None) — but the sync_state rows
    # should still get created.
    with patch(
        "knowlet.core.sync.drive_client.DriveClient.service",
        return_value=MagicMock(),
    ):
        drainer.tick_once()

    state = SyncStateStore(tmp_path)
    try:
        assert state.get_file_state("note", "NID-1") is not None
        assert state.get_file_state("attachment", "01HABC.png") is None
        # ^ removed by the vanish-handling branch in
        # _push_attachment_row, since attachment_lookup returned None.
    finally:
        state.close()


def test_drainer_marks_orphan_attachment_for_hard_delete(
    tmp_path: Path,
) -> None:
    """A1 — when a tracked attachment's local file is gone, the
    drainer sets delete_intent=hard on its sync_state row so the
    next _process_deletions tick tells Drive to clean up."""
    _seed_creds(tmp_path)
    # Pre-push state: row says it's on Drive, but file is missing.
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="attachment",
                entity_id="01HORPHAN.png",
                drive_file_id="DRIVE-ORPHAN",
                last_known_etag="rev-1",
                last_synced_at="2026-05-11T12:00:00Z",
                dirty=False,
            )
        )
    finally:
        state.close()

    fake_service = MagicMock()
    fake_service.files().delete().execute.return_value = {}

    drainer = PushDrainer(
        vault_root=tmp_path,
        note_lookup=lambda _id: None,
        attachment_lookup=lambda _name: None,  # file is gone
    )
    with patch(
        "knowlet.core.sync.drive_client.DriveClient.service",
        return_value=fake_service,
    ):
        drainer.tick_once()

    # Drive's hard-delete API was called with the correct file id.
    call_args = [c.kwargs for c in fake_service.files().delete.call_args_list]
    fileIds = [c.get("fileId") for c in call_args]
    assert "DRIVE-ORPHAN" in fileIds, f"expected hard-delete call for DRIVE-ORPHAN, got {fileIds}"
    # Row was removed after successful delete.
    state2 = SyncStateStore(tmp_path)
    try:
        assert state2.get_file_state("attachment", "01HORPHAN.png") is None
    finally:
        state2.close()


def test_drainer_drops_orphan_row_when_never_pushed(tmp_path: Path) -> None:
    """If an attachment row never made it to Drive (drive_file_id is
    None) and the local file is gone, just drop the row — no Drive
    work to do."""
    _seed_creds(tmp_path)
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="attachment",
                entity_id="01HONEVER.png",
                drive_file_id=None,
                last_known_etag=None,
                last_synced_at=None,
                dirty=False,
            )
        )
    finally:
        state.close()

    drainer = PushDrainer(
        vault_root=tmp_path,
        note_lookup=lambda _id: None,
        attachment_lookup=lambda _name: None,
    )
    with patch(
        "knowlet.core.sync.drive_client.DriveClient.service",
        return_value=MagicMock(),
    ):
        drainer.tick_once()

    state2 = SyncStateStore(tmp_path)
    try:
        assert state2.get_file_state("attachment", "01HONEVER.png") is None
    finally:
        state2.close()


def test_drainer_keeps_alive_attachment_when_file_present(
    tmp_path: Path,
) -> None:
    """Orphan sweep must not touch attachment rows whose file is
    still on disk. Negative-control for the false-positive case."""
    _seed_creds(tmp_path)
    att_dir = tmp_path / "_attachments"
    att_dir.mkdir()
    att = att_dir / "01HALIVE.png"
    att.write_bytes(b"alive")
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="attachment",
                entity_id="01HALIVE.png",
                drive_file_id="DRIVE-ALIVE",
                last_known_etag="rev-1",
                last_synced_at="2026-05-11T12:00:00Z",
                dirty=False,
            )
        )
    finally:
        state.close()

    drainer = PushDrainer(
        vault_root=tmp_path,
        note_lookup=lambda _id: None,
        attachment_lookup=lambda name: att if name == "01HALIVE.png" else None,
    )
    fake_service = MagicMock()
    with patch(
        "knowlet.core.sync.drive_client.DriveClient.service",
        return_value=fake_service,
    ):
        drainer.tick_once()

    # No Drive delete called, row still alive.
    assert fake_service.files().delete.call_count == 0
    state2 = SyncStateStore(tmp_path)
    try:
        rec = state2.get_file_state("attachment", "01HALIVE.png")
        assert rec is not None
        assert rec.delete_intent is None
    finally:
        state2.close()


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
