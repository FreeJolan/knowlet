from __future__ import annotations

from pathlib import Path

from knowlet.cli.sync import _is_restore_target_empty
from knowlet.core.note import Note
from knowlet.core.sync.files import DriveFileBrief
from knowlet.core.sync.restore import restore_vault_from_drive
from knowlet.core.sync.state import SyncStateStore
from knowlet.core.vault import Vault
from knowlet.core.vault_identity import write_vault_id


def test_restore_vault_from_drive_materializes_scoped_notes(monkeypatch, tmp_path: Path) -> None:
    vault = Vault(tmp_path / "Restored")
    vault.init_layout()
    write_vault_id(vault.root, "01REMOTEVAULTID000000000000")
    note = Note(
        id="01NOTE0000000000000000000",
        title="Remote Note",
        body="Pulled from Drive.",
        folder="Sources",
    )
    drive_files = {
        "DRIVE-NOTE": DriveFileBrief(
            name="vault-01REMOTEVAULTID000000000000__note__01NOTE0000000000000000000.md",
            head_revision_id="rev-note",
        ),
        "DRIVE-OTHER": DriveFileBrief(
            name="vault-01OTHERVAULTID000000000000__note__01OTHER.md",
            head_revision_id="rev-other",
        ),
    }

    monkeypatch.setattr(
        "knowlet.core.sync.restore.list_appdata_revisions",
        lambda _service: drive_files,
    )
    monkeypatch.setattr(
        "knowlet.core.sync.restore.download_file",
        lambda _service, file_id: (
            note.to_markdown().encode("utf-8") if file_id == "DRIVE-NOTE" else b""
        ),
    )

    report = restore_vault_from_drive(object(), vault_root=vault.root)

    assert report.materialized_count == 1
    restored = vault.notes_dir / "Sources" / "01NOTE0000000000000000000.md"
    assert restored.is_file()
    assert Note.from_file(restored).title == "Remote Note"
    state = SyncStateStore(vault.root)
    try:
        row = state.get_file_state("note", "01NOTE0000000000000000000")
    finally:
        state.close()
    assert row is not None
    assert row.drive_file_id == "DRIVE-NOTE"
    assert row.last_known_etag == "rev-note"
    assert row.dirty is False


def test_restore_target_empty_ignores_macos_metadata(tmp_path: Path) -> None:
    target = tmp_path / "Existing Empty"
    target.mkdir()
    (target / ".DS_Store").write_text("", encoding="utf-8")

    assert _is_restore_target_empty(target) is True

    (target / "real.md").write_text("content", encoding="utf-8")
    assert _is_restore_target_empty(target) is False
