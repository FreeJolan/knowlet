"""knowlet.core.sync.note_bookkeeping — the sync_state trail every
interface leaves when it writes / deletes / restores a note. Tested
directly (no web runtime) plus one check that the web wrappers still
produce the same rows."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from knowlet.config import KnowletConfig, save_config
from knowlet.core.note import Note, new_id
from knowlet.core.sync.note_bookkeeping import (
    mark_note_delete_intent,
    mark_note_dirty_for_push,
    unmark_note_delete_intent,
)
from knowlet.core.sync.state import FileState, SyncStateStore
from knowlet.core.sync.status import DEV_FAKE_DRIVE_FILE_ID
from knowlet.core.vault import Vault
from knowlet.web.server import create_app


def _row(root: Path, note_id: str) -> FileState | None:
    store = SyncStateStore(root)
    try:
        return store.get_file_state("note", note_id)
    finally:
        store.close()


def _put(root: Path, note_id: str, **kw) -> None:
    store = SyncStateStore(root)
    try:
        store.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note_id,
                drive_file_id=kw.get("drive_file_id", "drive-1"),
                last_known_etag=kw.get("etag", "rev-1"),
                last_synced_at="2020-01-01T00:00:00Z",
                dirty=kw.get("dirty", False),
                dismissed_until=kw.get("dismissed_until"),
                delete_intent=kw.get("delete_intent"),
            )
        )
    finally:
        store.close()


@pytest.fixture()
def with_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    import knowlet.core.sync.credentials as creds_mod

    monkeypatch.setattr(creds_mod, "load_credentials", lambda _p: object())


def test_dirty_without_row_or_creds_is_noop(tmp_path: Path) -> None:
    assert mark_note_dirty_for_push(tmp_path, "n1") is False
    assert _row(tmp_path, "n1") is None


def test_dirty_without_row_creates_first_push_row_when_connected(
    tmp_path: Path, with_creds: None
) -> None:
    assert mark_note_dirty_for_push(tmp_path, "n1") is True
    row = _row(tmp_path, "n1")
    assert row is not None and row.dirty and row.drive_file_id is None


def test_dirty_flips_existing_row_and_keeps_drive_handle(tmp_path: Path) -> None:
    _put(tmp_path, "n1", dismissed_until="2030-01-01T00:00:00Z")
    assert mark_note_dirty_for_push(tmp_path, "n1") is True
    row = _row(tmp_path, "n1")
    assert row is not None
    assert row.dirty and row.drive_file_id == "drive-1" and row.last_known_etag == "rev-1"
    assert row.dismissed_until == "2030-01-01T00:00:00Z"
    # Already dirty → unchanged.
    assert mark_note_dirty_for_push(tmp_path, "n1") is False


def test_dirty_skips_dev_seeded_rows(tmp_path: Path) -> None:
    _put(tmp_path, "n1", drive_file_id=DEV_FAKE_DRIVE_FILE_ID)
    assert mark_note_dirty_for_push(tmp_path, "n1") is False
    assert _row(tmp_path, "n1").dirty is False


def test_delete_intent_records_kind_and_preserves_handle(tmp_path: Path) -> None:
    _put(tmp_path, "n1", dirty=True)
    assert mark_note_delete_intent(tmp_path, "n1", "soft") is True
    row = _row(tmp_path, "n1")
    assert row.delete_intent == "soft" and row.dirty is False
    assert row.drive_file_id == "drive-1" and row.last_known_etag == "rev-1"


def test_delete_intent_drops_never_pushed_and_dev_rows(tmp_path: Path) -> None:
    _put(tmp_path, "local", drive_file_id=None)
    _put(tmp_path, "dev", drive_file_id=DEV_FAKE_DRIVE_FILE_ID)
    assert mark_note_delete_intent(tmp_path, "local", "soft") is False
    assert mark_note_delete_intent(tmp_path, "dev", "hard") is False
    assert mark_note_delete_intent(tmp_path, "missing", "soft") is False
    assert _row(tmp_path, "local") is None
    assert _row(tmp_path, "dev") is None


def test_delete_intent_rejects_unknown_kind(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        mark_note_delete_intent(tmp_path, "n1", "maybe")


def test_unmark_clears_intent_and_requeues_push(tmp_path: Path) -> None:
    _put(tmp_path, "n1", delete_intent="soft")
    assert unmark_note_delete_intent(tmp_path, "n1") is True
    row = _row(tmp_path, "n1")
    assert row.delete_intent is None and row.dirty is True
    assert unmark_note_delete_intent(tmp_path, "n1") is False
    assert unmark_note_delete_intent(tmp_path, "missing") is False


def test_reuses_a_caller_supplied_store(tmp_path: Path) -> None:
    _put(tmp_path, "n1")
    store = SyncStateStore(tmp_path)
    try:
        assert mark_note_dirty_for_push(tmp_path, "n1", store=store) is True
        # Still usable: the function must not close a store it didn't open.
        assert store.get_file_state("note", "n1").dirty is True
    finally:
        store.close()


def test_web_delete_and_restore_use_the_same_trail(tmp_path: Path) -> None:
    v = Vault(tmp_path)
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = "stub"
    save_config(v.root, cfg)
    app = create_app(v, cfg)
    runtime = app.state.web_state.runtime_or_init()
    client = TestClient(app)
    note = Note(id=new_id(), title="T", body="b")
    v.write_note(note)
    runtime.index.upsert_note(note, chunk_size=400, chunk_overlap=40)
    _put(v.root, note.id)

    assert client.delete(f"/api/notes/{note.id}").status_code == 200
    assert _row(v.root, note.id).delete_intent == "soft"
    trash_name = next(v.iter_trashed_paths()).name
    assert client.post(f"/api/trash/{trash_name}/restore").status_code == 200
    row = _row(v.root, note.id)
    assert row.delete_intent is None and row.dirty is True
