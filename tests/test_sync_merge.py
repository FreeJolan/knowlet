"""Phase 2 E Slice S5 — merge editor backend (ADR-0027 redesign).

Tests cover:

1. ``resolve_with_merge`` (push.py) — atomic local write + force push
   + state advance + mtime pin.
2. ``GET /api/sync/conflict-bundle/<id>`` — returns local + remote
   text plus the revision metadata the frontend renders.
3. ``POST /api/sync/resolve-merge/<id>`` — accepts the user's
   merged text, writes it locally, force-pushes to Drive, advances
   sync_state to the post-merge revision.

End-to-end auth + Drive interactions are mocked at the
``DriveClient.service`` and ``files.{download_file, force_overwrite,
get_file_metadata}`` seams.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from knowlet.core.note import Note, new_id
from knowlet.core.sync.files import DriveFile
from knowlet.core.sync.push import resolve_with_merge
from knowlet.core.sync.state import FileState, SyncStateStore
from knowlet.core.sync.status import _is_local_dirty


def _meta(rev: str) -> DriveFile:
    return DriveFile(
        id="DRIVE-FID-1",
        name="alpha.md",
        mime_type="text/markdown",
        modified_time="2026-05-10T12:00:00Z",
        head_revision_id=rev,
    )


# ----------------------------------------------------- push helper


def test_resolve_with_merge_writes_local_and_advances_state(
    tmp_path: Path,
) -> None:
    note_id = new_id()
    local_path = tmp_path / f"{note_id}.md"
    local_path.write_text("LOCAL pre-merge", encoding="utf-8")
    store = SyncStateStore(tmp_path)
    try:
        store.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note_id,
                drive_file_id="DRIVE-FID-1",
                last_known_etag="rev-OLD",
                last_synced_at="2020-01-01T00:00:00Z",
                dirty=True,
            )
        )
        with patch(
            "knowlet.core.sync.push.force_overwrite",
            return_value=_meta("rev-MERGED"),
        ):
            result = resolve_with_merge(
                service=MagicMock(),
                state=store,
                note_id=note_id,
                drive_file_id="DRIVE-FID-1",
                local_path=local_path,
                merged_bytes=b"MERGED bytes go here",
            )
        # Local file got the merged bytes.
        assert local_path.read_bytes() == b"MERGED bytes go here"
        assert result.drive_file.head_revision_id == "rev-MERGED"
        assert result.created is False
        # Sync state advanced + dirty cleared.
        rec = store.get_file_state("note", note_id)
        assert rec is not None
        assert rec.last_known_etag == "rev-MERGED"
        assert rec.dirty is False
        # Mtime pinned, so the post-merge note shows up as synced
        # rather than flickering through "conflict" on the next poll.
        assert _is_local_dirty(local_path, rec.last_synced_at) is False
    finally:
        store.close()


# ----------------------------------------------------- API endpoints


def _seed_creds_and_note(tmp_path: Path) -> tuple[Any, str, Path]:
    """Helper: seed creds, write a real note via the runtime, return
    (runtime, note_id, written_path)."""
    from tests.test_sync_status import _seed_creds
    from tests.test_web import StubLLM, _client_with_stub

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    runtime = client.app.state.web_state.runtime  # type: ignore[attr-defined]
    assert runtime is not None
    _seed_creds(tmp_path)
    note = Note(id=new_id(), title="alpha", body="local body", tags=[])
    written_path = runtime.vault.write_note(note)
    runtime.index.upsert_note(note, chunk_size=64, chunk_overlap=0)
    return client, note.id, written_path


def test_conflict_bundle_returns_local_and_remote_text(tmp_path: Path) -> None:
    client, note_id, written_path = _seed_creds_and_note(tmp_path)
    written_path.write_text("LOCAL fork", encoding="utf-8")

    store = SyncStateStore(tmp_path)
    try:
        store.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note_id,
                drive_file_id="DRIVE-FID-1",
                last_known_etag="rev-OLD",
                last_synced_at="2020-01-01T00:00:00Z",
                dirty=False,
            )
        )
    finally:
        store.close()

    with (
        patch(
            "knowlet.core.sync.drive_client.DriveClient.service",
            return_value=MagicMock(),
        ),
        patch(
            "knowlet.web.server.get_file_metadata",
            return_value=_meta("rev-NEW"),
            create=True,
        ),
        patch(
            "knowlet.core.sync.files.get_file_metadata",
            return_value=_meta("rev-NEW"),
        ),
        patch(
            "knowlet.core.sync.files.download_file",
            return_value=b"REMOTE fork",
        ),
    ):
        r = client.get(f"/api/sync/conflict-bundle/{note_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["note_id"] == note_id
    assert body["local_text"] == "LOCAL fork"
    assert body["remote_text"] == "REMOTE fork"
    assert body["current_drive_revision"] == "rev-NEW"
    assert body["last_known_revision"] == "rev-OLD"
    assert body["drive_file_id"] == "DRIVE-FID-1"


def test_conflict_bundle_404_when_note_missing(tmp_path: Path) -> None:
    from tests.test_sync_status import _seed_creds
    from tests.test_web import StubLLM, _client_with_stub

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    _seed_creds(tmp_path)
    r = client.get("/api/sync/conflict-bundle/01NEVERHAPPENED0000000000")
    assert r.status_code == 404


def test_conflict_bundle_409_when_unauthenticated(tmp_path: Path) -> None:
    """No creds → 409. The note may exist locally; we just can't
    reach Drive to populate the remote pane."""
    from tests.test_web import StubLLM, _client_with_stub

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    runtime = client.app.state.web_state.runtime  # type: ignore[attr-defined]
    assert runtime is not None
    note = Note(id=new_id(), title="alpha", body="x", tags=[])
    runtime.vault.write_note(note)
    runtime.index.upsert_note(note, chunk_size=64, chunk_overlap=0)
    r = client.get(f"/api/sync/conflict-bundle/{note.id}")
    assert r.status_code == 409


def test_conflict_bundle_409_when_no_drive_id(tmp_path: Path) -> None:
    """Note has never been pushed → no drive_file_id in sync_state.
    There's nothing to fetch from Drive → 409 rather than fabricating
    an empty remote pane."""
    client, note_id, _ = _seed_creds_and_note(tmp_path)
    # Don't seed sync_state at all.
    r = client.get(f"/api/sync/conflict-bundle/{note_id}")
    assert r.status_code == 409


def test_resolve_merge_writes_locally_and_force_pushes(
    tmp_path: Path,
) -> None:
    """End-to-end: user's merged text lands on disk and Drive
    advances to the post-merge revision. Sync state catches up."""
    client, note_id, written_path = _seed_creds_and_note(tmp_path)
    store = SyncStateStore(tmp_path)
    try:
        store.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note_id,
                drive_file_id="DRIVE-FID-1",
                last_known_etag="rev-OLD",
                last_synced_at="2020-01-01T00:00:00Z",
                dirty=False,
            )
        )
    finally:
        store.close()

    with (
        patch(
            "knowlet.core.sync.drive_client.DriveClient.service",
            return_value=MagicMock(),
        ),
        patch(
            "knowlet.core.sync.push.force_overwrite",
            return_value=_meta("rev-MERGED"),
        ),
    ):
        r = client.post(
            f"/api/sync/resolve-merge/{note_id}",
            json={"merged_text": "MERGED final text"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["new_revision"] == "rev-MERGED"
    assert body["drive_file_id"] == "DRIVE-FID-1"
    assert written_path.read_text(encoding="utf-8") == "MERGED final text"
    # State advanced + dirty cleared.
    store2 = SyncStateStore(tmp_path)
    try:
        rec = store2.get_file_state("note", note_id)
    finally:
        store2.close()
    assert rec is not None
    assert rec.last_known_etag == "rev-MERGED"
    assert rec.dirty is False


def test_resolve_merge_404_when_note_missing(tmp_path: Path) -> None:
    from tests.test_sync_status import _seed_creds
    from tests.test_web import StubLLM, _client_with_stub

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    _seed_creds(tmp_path)
    r = client.post(
        "/api/sync/resolve-merge/01NEVERHAPPENED0000000000",
        json={"merged_text": "x"},
    )
    assert r.status_code == 404


def test_resolve_merge_409_when_no_drive_id(tmp_path: Path) -> None:
    """Note exists locally but has never been pushed → can't merge
    with a non-existent remote. 409 rather than silently first-pushing."""
    client, note_id, _ = _seed_creds_and_note(tmp_path)
    r = client.post(
        f"/api/sync/resolve-merge/{note_id}",
        json={"merged_text": "x"},
    )
    assert r.status_code == 409
