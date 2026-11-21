"""AI edits made from CLI chat sessions (REPL, `knowlet discuss`) must be
queued for Drive like web edits: the chat bootstrap's ToolContext needs a
mark_note_dirty callback, but it used to be None outside the web server."""

from __future__ import annotations

from pathlib import Path

from knowlet.chat.bootstrap import bootstrap_chat
from knowlet.config import KnowletConfig
from knowlet.core.note import new_id
from knowlet.core.sync.state import FileState, SyncStateStore, sync_state_db_path
from knowlet.core.vault import Vault


def _runtime(tmp_path: Path):
    vault = Vault(tmp_path)
    vault.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    runtime, _ = bootstrap_chat(vault, cfg, rescan=False, require_llm=False)
    return vault, runtime


def test_bootstrap_ctx_queues_ai_edits_for_push(tmp_path):
    vault, runtime = _runtime(tmp_path)
    note_id = new_id()
    store = SyncStateStore(vault.root)
    try:
        store.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note_id,
                drive_file_id="drive-1",
                last_known_etag="rev-1",
                last_synced_at="2026-11-01T00:00:00Z",
                dirty=False,
            )
        )
    finally:
        store.close()

    try:
        assert runtime.ctx.mark_note_dirty is not None
        runtime.ctx.mark_note_dirty(note_id)
    finally:
        runtime.close()

    store = SyncStateStore(vault.root)
    try:
        row = store.get_file_state("note", note_id)
    finally:
        store.close()
    assert row is not None and row.dirty is True


def test_bootstrap_ctx_does_not_create_sync_state_without_sync(tmp_path):
    vault, runtime = _runtime(tmp_path)
    try:
        assert runtime.ctx.mark_note_dirty is not None
        runtime.ctx.mark_note_dirty(new_id())
    finally:
        runtime.close()

    assert not sync_state_db_path(vault.root).exists()
