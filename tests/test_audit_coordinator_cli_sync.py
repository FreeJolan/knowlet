"""CLI note changes must leave the same sync_state trail as the web UI, so
the push drainer propagates them to Drive (audit finding cli/notes.py:68)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from knowlet.cli.main import app
from knowlet.config import KnowletConfig, save_config
from knowlet.core.embedding import DummyBackend
from knowlet.core.index import Index
from knowlet.core.note import Note, new_id
from knowlet.core.sync.state import FileState, SyncStateStore, sync_state_db_path
from knowlet.core.vault import Vault

runner = CliRunner()
DIM = 32


def _vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Vault:
    vault = Vault(tmp_path)
    vault.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = DIM
    save_config(vault.root, cfg)
    monkeypatch.setenv("KNOWLET_VAULT", str(vault.root))
    return vault


def _add_note(vault: Vault, folder: str | None = None) -> Note:
    note = Note(id=new_id(), title="Synced", body="body\n")
    vault.write_note(note, folder=folder)
    idx = Index(vault.db_path, DummyBackend(dim=DIM))
    idx.connect()
    try:
        idx.upsert_note(note, chunk_size=800, chunk_overlap=100)
    finally:
        idx.close()
    return note


def _seed_synced_row(vault: Vault, note_id: str) -> None:
    store = SyncStateStore(vault.root)
    try:
        store.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note_id,
                drive_file_id="drive-123",
                last_known_etag="rev-1",
                last_synced_at="2026-11-01T00:00:00Z",
                dirty=False,
            )
        )
    finally:
        store.close()


def _row(vault: Vault, note_id: str) -> FileState | None:
    store = SyncStateStore(vault.root)
    try:
        return store.get_file_state("note", note_id)
    finally:
        store.close()


def test_cli_delete_records_drive_delete_intent(tmp_path, monkeypatch):
    vault = _vault(tmp_path, monkeypatch)
    note = _add_note(vault)
    _seed_synced_row(vault, note.id)

    result = runner.invoke(app, ["notes", "delete", note.id, "--yes"])

    assert result.exit_code == 0, result.output
    row = _row(vault, note.id)
    assert row is not None and row.delete_intent == "soft"


def test_cli_restore_clears_delete_intent_and_queues_push(tmp_path, monkeypatch):
    vault = _vault(tmp_path, monkeypatch)
    note = _add_note(vault)
    _seed_synced_row(vault, note.id)
    assert runner.invoke(app, ["notes", "delete", note.id, "--yes"]).exit_code == 0

    result = runner.invoke(app, ["notes", "restore", note.id[:12]])

    assert result.exit_code == 0, result.output
    row = _row(vault, note.id)
    assert row is not None and row.delete_intent is None and row.dirty is True


def test_cli_move_queues_push(tmp_path, monkeypatch):
    vault = _vault(tmp_path, monkeypatch)
    note = _add_note(vault)
    _seed_synced_row(vault, note.id)

    result = runner.invoke(app, ["notes", "mv", note.id, "archive"])

    assert result.exit_code == 0, result.output
    row = _row(vault, note.id)
    assert row is not None and row.dirty is True


def test_cli_folder_rename_queues_push_for_moved_notes(tmp_path, monkeypatch):
    vault = _vault(tmp_path, monkeypatch)
    note = _add_note(vault, folder="projects")
    _seed_synced_row(vault, note.id)

    result = runner.invoke(app, ["notes", "rnfolder", "projects", "work"])

    assert result.exit_code == 0, result.output
    row = _row(vault, note.id)
    assert row is not None and row.dirty is True


def test_cli_rmfolder_records_delete_intent(tmp_path, monkeypatch):
    vault = _vault(tmp_path, monkeypatch)
    note = _add_note(vault, folder="old")
    _seed_synced_row(vault, note.id)

    result = runner.invoke(app, ["notes", "rmfolder", "old", "--yes"])

    assert result.exit_code == 0, result.output
    row = _row(vault, note.id)
    assert row is not None and row.delete_intent == "soft"


def test_cli_changes_do_not_create_sync_state_without_sync(tmp_path, monkeypatch):
    vault = _vault(tmp_path, monkeypatch)
    note = _add_note(vault)

    assert runner.invoke(app, ["notes", "mv", note.id, "archive"]).exit_code == 0
    assert runner.invoke(app, ["notes", "delete", note.id, "--yes"]).exit_code == 0

    assert not sync_state_db_path(vault.root).exists()


def test_cli_draft_approve_queues_first_push_when_drive_connected(tmp_path, monkeypatch):
    from knowlet.core.drafts import Draft, DraftStore
    from knowlet.core.sync.credentials import (
        SyncCredentials,
        credentials_path,
        save_credentials,
    )

    vault = _vault(tmp_path, monkeypatch)
    save_credentials(credentials_path(vault.root), SyncCredentials(token={"a": 1}))
    draft = Draft(id=new_id(), title="From draft", body="drafted body\n")
    DraftStore(vault.drafts_dir).save(draft)

    result = runner.invoke(app, ["drafts", "approve", draft.id])

    assert result.exit_code == 0, result.output
    store = SyncStateStore(vault.root)
    try:
        rows = [r for r in store.list_all_files() if r.entity_type == "note"]
    finally:
        store.close()
    assert len(rows) == 1 and rows[0].dirty is True and rows[0].drive_file_id is None
