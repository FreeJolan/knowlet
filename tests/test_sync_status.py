"""Phase 2 E Slice S1 + S2 — per-note sync status (ADR-0027 redesign).

S1 locks the five user-visible states (unauthenticated / offline /
synced / dirty / conflict). S2 adds the sixth internal state
``stale`` (revs differ + local clean) and the auto-pull glue that
maps it to ``synced`` before responding to the wire. Drive
interactions go through the ``_drive_service`` seam so we mock at
a single point.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any
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
from knowlet.core.sync.status import (
    _is_local_dirty,
    compute_note_sync_status,
)


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


def _patch_service() -> Any:
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


def test_conflict_when_local_mtime_post_sync(tmp_path: Path) -> None:
    """Revs differ + local file was edited AFTER last_synced_at →
    real conflict (S2 mtime path). The user has work to lose if we
    silently overwrite, so the badge surfaces 'conflict' and the UI
    routes them through the merge editor."""
    _seed_creds(tmp_path)
    note_id = new_id()
    note_path = tmp_path / f"{note_id}.md"
    note_path.write_text("local edits", encoding="utf-8")
    # Set mtime well after the recorded last_synced_at so the
    # tolerance window can't swallow it.
    os.utime(note_path, (time.time(), time.time()))
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note_id,
                drive_file_id="DRIVE-FID-1",
                last_known_etag="rev-MINE",
                last_synced_at="2020-01-01T00:00:00Z",
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
                local_path=note_path,
            )
    finally:
        state.close()
    assert status.state == "conflict"
    assert status.last_known_revision == "rev-MINE"
    assert status.current_drive_revision == "rev-NEW"


def test_conflict_when_sync_state_dirty_flag(tmp_path: Path) -> None:
    """sync_state.dirty=True is a sufficient signal even if mtime
    can't decide. Belt-and-braces: keeps the contract honest if a
    code path explicitly marks dirty (e.g. a previous failed push)."""
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
                last_synced_at="2030-01-01T00:00:00Z",  # in the future!
                dirty=True,
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
                local_path=None,
            )
    finally:
        state.close()
    assert status.state == "conflict"


def test_stale_when_revisions_diverge_but_local_clean(tmp_path: Path) -> None:
    """S2 path: revs differ + local file mtime ≤ last_synced_at
    (Bob persona). Internal state is 'stale'; the API endpoint will
    auto-pull + recompute before it ever leaves the wire."""
    _seed_creds(tmp_path)
    note_id = new_id()
    note_path = tmp_path / f"{note_id}.md"
    note_path.write_text("clean local", encoding="utf-8")
    # Mtime far in the past, last_synced_at is 'now-ish' → clean.
    past = time.time() - 86400  # one day ago
    os.utime(note_path, (past, past))
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note_id,
                drive_file_id="DRIVE-FID-1",
                last_known_etag="rev-MINE",
                last_synced_at="2030-01-01T00:00:00Z",  # future, beats mtime
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
                local_path=note_path,
            )
    finally:
        state.close()
    assert status.state == "stale"
    assert status.last_known_revision == "rev-MINE"
    assert status.current_drive_revision == "rev-NEW"


def test_stale_when_local_path_missing(tmp_path: Path) -> None:
    """No local file on disk + revs differ → can't be dirty
    (nothing to push), so we treat as stale. Edge case: a note
    tracked in sync_state whose local file got deleted out-of-band.
    Auto-pull will rematerialize it."""
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
                last_synced_at="2030-01-01T00:00:00Z",
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
                local_path=None,
            )
    finally:
        state.close()
    assert status.state == "stale"


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


# ----------------------------------------------------- S2 auto-pull glue


def test_api_endpoint_auto_pulls_stale_to_synced(tmp_path: Path) -> None:
    """Bob persona, end-to-end. compute returns stale; the endpoint
    invokes ``pull_note_to_local`` silently, recomputes, and the
    wire response is ``synced`` with the new revision recorded.
    The user's badge never flickers through 'stale' or 'conflict'."""
    from tests.test_web import StubLLM, _client_with_stub

    client, _v, _ = _client_with_stub(tmp_path, StubLLM([]))
    runtime = client.app.state.web_state.runtime  # type: ignore[attr-defined]
    assert runtime is not None
    _seed_creds(tmp_path)

    # Seed a real note in the vault so _resolve_note_local_path
    # finds it. Use the vault's write path so the index picks it up.
    from knowlet.core.note import Note

    note = Note(id=new_id(), title="alpha", body="local body", tags=[])
    written_path = runtime.vault.write_note(note)
    runtime.index.upsert_note(note, chunk_size=64, chunk_overlap=0)
    # Backdate the file so it's "older than last_synced_at" → clean.
    past = time.time() - 86400
    os.utime(written_path, (past, past))

    store = SyncStateStore(tmp_path)
    try:
        store.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note.id,
                drive_file_id="DRIVE-FID-1",
                last_known_etag="rev-MINE",
                last_synced_at="2030-01-01T00:00:00Z",
                dirty=False,
            )
        )
    finally:
        store.close()

    # The pull-then-recompute sequence calls ``get_file_metadata``
    # twice: once during compute (returns rev-NEW → stale), then
    # once during pull, then again during recompute. After pull
    # we've upserted last_known_etag=rev-NEW so recompute matches
    # → synced. download_file is patched to return remote bytes.
    with (
        _patch_service(),
        patch(
            "knowlet.core.sync.status.get_file_metadata",
            return_value=_drive_meta("rev-NEW"),
        ),
        patch(
            "knowlet.core.sync.pull.get_file_metadata",
            return_value=_drive_meta("rev-NEW"),
        ),
        patch(
            "knowlet.core.sync.pull.download_file",
            return_value=b"remote body fresh from drive",
        ),
    ):
        r = client.get(f"/api/sync/note-status/{note.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "synced", (
        "auto-pull should have resolved stale → synced before "
        "the response left the wire; got " + body["state"]
    )
    # Verify the local file actually got the remote bytes.
    assert written_path.read_bytes() == b"remote body fresh from drive"
    # Verify sync_state advanced.
    store2 = SyncStateStore(tmp_path)
    try:
        rec = store2.get_file_state("note", note.id)
    finally:
        store2.close()
    assert rec is not None
    assert rec.last_known_etag == "rev-NEW"


def test_api_endpoint_real_conflict_does_not_auto_pull(tmp_path: Path) -> None:
    """Carol persona: local edits + remote moved → real conflict.
    Endpoint must NOT auto-pull (would lose the user's local work).
    Wire response stays 'conflict'."""
    from tests.test_web import StubLLM, _client_with_stub

    client, _v, _ = _client_with_stub(tmp_path, StubLLM([]))
    runtime = client.app.state.web_state.runtime  # type: ignore[attr-defined]
    assert runtime is not None
    _seed_creds(tmp_path)

    from knowlet.core.note import Note

    note = Note(id=new_id(), title="alpha", body="my edits", tags=[])
    written_path = runtime.vault.write_note(note)
    runtime.index.upsert_note(note, chunk_size=64, chunk_overlap=0)
    # Mtime is "now-ish" — past last_synced_at, so dirty.
    os.utime(written_path, (time.time(), time.time()))

    store = SyncStateStore(tmp_path)
    try:
        store.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note.id,
                drive_file_id="DRIVE-FID-1",
                last_known_etag="rev-MINE",
                last_synced_at="2020-01-01T00:00:00Z",
                dirty=False,
            )
        )
    finally:
        store.close()

    pull_called = MagicMock()
    with (
        _patch_service(),
        patch(
            "knowlet.core.sync.status.get_file_metadata",
            return_value=_drive_meta("rev-NEW"),
        ),
        patch("knowlet.core.sync.pull.download_file", pull_called),
    ):
        r = client.get(f"/api/sync/note-status/{note.id}")
    assert r.status_code == 200
    assert r.json()["state"] == "conflict"
    # Local bytes preserved (no overwrite).
    pull_called.assert_not_called()


# ----------------------------------------------------- _is_local_dirty


def test_is_local_dirty_no_path() -> None:
    assert _is_local_dirty(None, "2026-05-10T12:00:00Z") is False


def test_is_local_dirty_missing_file(tmp_path: Path) -> None:
    assert (
        _is_local_dirty(tmp_path / "nope.md", "2026-05-10T12:00:00Z")
        is False
    )


def test_is_local_dirty_unparseable_iso(tmp_path: Path) -> None:
    """Garbage in last_synced_at → safe-by-default treats as dirty
    rather than risk auto-pulling over real edits."""
    p = tmp_path / "x.md"
    p.write_text("hello", encoding="utf-8")
    assert _is_local_dirty(p, "not-an-iso-string") is True


def test_is_local_dirty_mtime_after_sync(tmp_path: Path) -> None:
    p = tmp_path / "x.md"
    p.write_text("hello", encoding="utf-8")
    os.utime(p, (time.time(), time.time()))
    # Sync time was ages ago.
    assert _is_local_dirty(p, "2020-01-01T00:00:00Z") is True


def test_is_local_dirty_mtime_before_sync(tmp_path: Path) -> None:
    p = tmp_path / "x.md"
    p.write_text("hello", encoding="utf-8")
    past = time.time() - 86400
    os.utime(p, (past, past))
    # Sync timestamp in the future (after the mtime).
    assert _is_local_dirty(p, "2030-01-01T00:00:00Z") is False
