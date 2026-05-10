"""Phase 2 E Slice S2 — pull primitive (ADR-0027 redesign).

``pull_note_to_local`` is the bytes-mover behind the auto-pull glue
in ``status.py`` and the explicit ``POST /api/sync/note-pull/<id>``
endpoint. These tests lock down its three contracts:

1. Atomic local write + sync_state advance on success.
2. ``PullStateMissingError`` when the caller asks for a note we've
   never synced (logic-bug guard).
3. ``last_synced_at >= mtime`` after a successful pull, so the
   next ``_is_local_dirty`` check correctly reads False.

Drive interactions are mocked at the ``files.download_file`` /
``files.get_file_metadata`` seams.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from knowlet.core.note import new_id
from knowlet.core.sync.files import DriveFile
from knowlet.core.sync.pull import (
    PullStateMissingError,
    pull_note_to_local,
)
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


def test_pull_replaces_local_bytes_and_advances_state(tmp_path: Path) -> None:
    note_id = new_id()
    local_path = tmp_path / f"{note_id}.md"
    local_path.write_text("STALE local body", encoding="utf-8")

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
        with (
            patch(
                "knowlet.core.sync.pull.get_file_metadata",
                return_value=_meta("rev-NEW"),
            ),
            patch(
                "knowlet.core.sync.pull.download_file",
                return_value=b"REMOTE body fresh",
            ),
        ):
            result = pull_note_to_local(
                service=MagicMock(),
                state=store,
                note_id=note_id,
                local_path=local_path,
            )
        # Bytes replaced.
        assert local_path.read_bytes() == b"REMOTE body fresh"
        assert result.new_revision == "rev-NEW"
        # State advanced.
        rec = store.get_file_state("note", note_id)
        assert rec is not None
        assert rec.last_known_etag == "rev-NEW"
        assert rec.last_synced_at is not None
        assert rec.dirty is False
        # Crucially: last_synced_at must be >= the file's mtime, so
        # _is_local_dirty reads clean immediately post-pull.
        assert _is_local_dirty(local_path, rec.last_synced_at) is False
    finally:
        store.close()


def test_pull_creates_parent_dirs(tmp_path: Path) -> None:
    """Local path under a not-yet-created subfolder is supported —
    pull creates the parent dirs along the way (mirrors how
    Vault.write_note tolerates fresh folders)."""
    note_id = new_id()
    local_path = tmp_path / "deep" / "nest" / f"{note_id}.md"
    assert not local_path.parent.exists()

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
        with (
            patch(
                "knowlet.core.sync.pull.get_file_metadata",
                return_value=_meta("rev-NEW"),
            ),
            patch(
                "knowlet.core.sync.pull.download_file",
                return_value=b"x",
            ),
        ):
            pull_note_to_local(
                service=MagicMock(),
                state=store,
                note_id=note_id,
                local_path=local_path,
            )
        assert local_path.read_bytes() == b"x"
    finally:
        store.close()


def test_pull_raises_when_no_drive_id(tmp_path: Path) -> None:
    """Logic-bug guard: caller must verify there's a Drive id before
    invoking pull. We don't try to be clever and re-derive it."""
    note_id = new_id()
    local_path = tmp_path / f"{note_id}.md"
    store = SyncStateStore(tmp_path)
    try:
        # No upsert → no record.
        with pytest.raises(PullStateMissingError):
            pull_note_to_local(
                service=MagicMock(),
                state=store,
                note_id=note_id,
                local_path=local_path,
            )
        # Record with empty drive_file_id → still raises.
        store.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note_id,
                drive_file_id=None,
                last_known_etag=None,
                last_synced_at=None,
                dirty=True,
            )
        )
        with pytest.raises(PullStateMissingError):
            pull_note_to_local(
                service=MagicMock(),
                state=store,
                note_id=note_id,
                local_path=local_path,
            )
    finally:
        store.close()


def test_pull_does_not_corrupt_local_on_download_error(tmp_path: Path) -> None:
    """If the download blows up mid-flight, the local file must
    retain its pre-pull bytes — the .tmp+rename atomicity contract.
    sync_state must not advance either."""
    note_id = new_id()
    local_path = tmp_path / f"{note_id}.md"
    local_path.write_text("ORIGINAL local", encoding="utf-8")

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
        with (
            patch(
                "knowlet.core.sync.pull.get_file_metadata",
                return_value=_meta("rev-NEW"),
            ),
            patch(
                "knowlet.core.sync.pull.download_file",
                side_effect=ConnectionError("net down"),
            ),
            pytest.raises(ConnectionError),
        ):
            pull_note_to_local(
                service=MagicMock(),
                state=store,
                note_id=note_id,
                local_path=local_path,
            )
        # File content untouched.
        assert local_path.read_text(encoding="utf-8") == "ORIGINAL local"
        # State not advanced.
        rec = store.get_file_state("note", note_id)
        assert rec is not None
        assert rec.last_known_etag == "rev-OLD"
    finally:
        store.close()


def test_explicit_pull_endpoint(tmp_path: Path) -> None:
    """``POST /api/sync/note-pull/<id>`` — the manual handle. Used
    by S3's open-time fetch and by any "fetch now" UI affordance."""
    from tests.test_sync_status import _seed_creds
    from tests.test_web import StubLLM, _client_with_stub

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    runtime = client.app.state.web_state.runtime  # type: ignore[attr-defined]
    assert runtime is not None
    _seed_creds(tmp_path)

    from knowlet.core.note import Note

    note = Note(id=new_id(), title="alpha", body="local", tags=[])
    written_path = runtime.vault.write_note(note)
    runtime.index.upsert_note(note, chunk_size=64, chunk_overlap=0)

    store = SyncStateStore(tmp_path)
    try:
        store.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note.id,
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
            "knowlet.core.sync.pull.get_file_metadata",
            return_value=_meta("rev-NEW"),
        ),
        patch(
            "knowlet.core.sync.pull.download_file",
            return_value=b"new remote",
        ),
    ):
        r = client.post(f"/api/sync/note-pull/{note.id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["new_revision"] == "rev-NEW"
    assert body["bytes"] == len(b"new remote")
    assert written_path.read_bytes() == b"new remote"


def test_explicit_pull_endpoint_404_when_unknown(tmp_path: Path) -> None:
    """Asking to pull a note we don't have on disk → 404. Avoids
    silently creating phantom notes via the pull primitive."""
    from tests.test_sync_status import _seed_creds
    from tests.test_web import StubLLM, _client_with_stub

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    _seed_creds(tmp_path)
    r = client.post("/api/sync/note-pull/01NEVERHAPPENED0000000000")
    assert r.status_code == 404


def test_explicit_pull_endpoint_409_when_unauthenticated(tmp_path: Path) -> None:
    """No creds → 409 (not 404, since the note may exist locally;
    we just can't reach Drive)."""
    from tests.test_web import StubLLM, _client_with_stub

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    runtime = client.app.state.web_state.runtime  # type: ignore[attr-defined]
    assert runtime is not None
    from knowlet.core.note import Note

    note = Note(id=new_id(), title="alpha", body="x", tags=[])
    runtime.vault.write_note(note)
    runtime.index.upsert_note(note, chunk_size=64, chunk_overlap=0)

    r = client.post(f"/api/sync/note-pull/{note.id}")
    assert r.status_code == 409
