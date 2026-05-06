"""Trash → restore preserves the original folder, even when an
ancestor folder was deleted between trash + restore.

Phase 1 B slice 8 v2 follow-up: dogfood found that restoring a note
from `notes/.trash/` always landed it at the vault root, losing
folder context. Fix is `Note.trashed_from` frontmatter + cascade
mkdir on restore. The "delete ancestor folder, then restore leaf"
case is the interesting one — we have to recreate the folder.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from knowlet.config import KnowletConfig, save_config
from knowlet.core.note import Note, new_id
from knowlet.core.vault import Vault
from knowlet.web.server import create_app


def _ready_vault(tmp_path: Path) -> tuple[Vault, KnowletConfig]:
    v = Vault(tmp_path)
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = "stub"
    save_config(v.root, cfg)
    return v, cfg


def _client(tmp_path: Path) -> tuple[TestClient, Vault]:
    v, cfg = _ready_vault(tmp_path)
    app = create_app(v, cfg)
    client = TestClient(app)
    state = app.state.web_state
    state.runtime_or_init()
    return client, v


def _seed_note(v: Vault, *, title: str, folder: str | None = None) -> Note:
    n = Note(id=new_id(), title=title, body=f"body of {title}")
    v.write_note(n, folder=folder)
    return n


def test_trash_records_original_folder(tmp_path: Path) -> None:
    v, _ = _ready_vault(tmp_path)
    n = _seed_note(v, title="leaf", folder="proj/sub")
    trashed = v.trash_note(n.path)  # type: ignore[arg-type]
    # Frontmatter of the trashed file remembers the folder.
    parsed = Note.from_file(trashed)
    assert parsed.trashed_from == "proj/sub"


def test_restore_recreates_folder_after_ancestor_delete(tmp_path: Path) -> None:
    """The headline dogfood scenario: delete a leaf note, then delete
    its parent folder, then restore the leaf — should land back at
    `notes/proj/sub/<id>.md`, not at root."""
    v, _ = _ready_vault(tmp_path)
    n = _seed_note(v, title="leaf", folder="proj/sub")
    note_path = n.path
    assert note_path is not None
    v.trash_note(note_path)
    # Now delete the entire `proj/` subtree (sub/ is empty + proj/sub/
    # is too). delete_folder cascades into trash for any remaining
    # notes (none here) and rmdirs the empty tree.
    # Use shutil directly because the leaf is already gone.
    import shutil

    shutil.rmtree(v.notes_dir / "proj")
    assert not (v.notes_dir / "proj").exists()
    # Restore — vault should recreate proj/sub/ and put the note back.
    trashed_paths = list(v.iter_trashed_paths())
    assert len(trashed_paths) == 1
    restored = v.restore_note(trashed_paths[0])
    assert restored == v.notes_dir / "proj" / "sub" / f"{n.id}.md"
    assert restored.exists()
    # Frontmatter no longer carries trashed_from after restore.
    parsed = Note.from_file(restored)
    assert parsed.trashed_from is None


def test_restore_legacy_entry_without_metadata_falls_back_to_root(
    tmp_path: Path,
) -> None:
    """A trash entry written by an older version (no `trashed_from`
    in frontmatter) should still restore — to the root, since we
    have no way to recover the original location."""
    v, _ = _ready_vault(tmp_path)
    # Seed the trash directly with a note that has NO trashed_from.
    v.trash_dir.mkdir(parents=True, exist_ok=True)
    n = Note(id=new_id(), title="legacy", body="x")
    n.path = v.trash_dir / n.filename
    v.trash_dir.joinpath(n.filename).write_text(n.to_markdown(), encoding="utf-8")
    trashed = v.trash_dir / n.filename
    restored = v.restore_note(trashed)
    assert restored == v.notes_dir / n.filename


def test_restore_corrupt_trashed_from_falls_back_to_root(
    tmp_path: Path,
) -> None:
    """A malformed `trashed_from` (path traversal, dotfiles, etc.)
    must NOT escape the vault. Falls back to root."""
    v, _ = _ready_vault(tmp_path)
    v.trash_dir.mkdir(parents=True, exist_ok=True)
    n = Note(id=new_id(), title="evil", body="x", trashed_from="../../escape")
    (v.trash_dir / n.filename).write_text(n.to_markdown(), encoding="utf-8")
    restored = v.restore_note(v.trash_dir / n.filename)
    # Restored at root, not above the vault.
    assert restored == v.notes_dir / n.filename


def test_list_trash_surfaces_original_folder(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    n = _seed_note(v, title="x", folder="alpha/beta")
    v.trash_note(n.path)  # type: ignore[arg-type]
    r = client.get("/api/trash")
    assert r.status_code == 200
    rows = r.json()["entries"]
    assert len(rows) == 1
    assert rows[0]["original_folder"] == "alpha/beta"


def test_post_restore_all_processes_every_entry(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    a = _seed_note(v, title="a", folder="proj")
    b = _seed_note(v, title="b")  # at root
    v.trash_note(a.path)  # type: ignore[arg-type]
    v.trash_note(b.path)  # type: ignore[arg-type]
    r = client.post("/api/trash/restore-all")
    assert r.status_code == 200
    body = r.json()
    assert body["restored_count"] == 2
    assert body["skipped"] == []
    # Both back in their original folders.
    assert (v.notes_dir / "proj" / a.filename).exists()
    assert (v.notes_dir / b.filename).exists()
    assert list(v.iter_trashed_paths()) == []


def test_post_restore_all_skips_collision(tmp_path: Path) -> None:
    """If a live note already occupies the original folder + name
    (rare — same id collision), restore-all marks that one skipped
    and continues with the rest."""
    client, v = _client(tmp_path)
    a = _seed_note(v, title="a")
    b = _seed_note(v, title="b")
    v.trash_note(a.path)  # type: ignore[arg-type]
    v.trash_note(b.path)  # type: ignore[arg-type]
    # Re-seed a "live" note with the SAME filename as `a`'s trash entry,
    # forcing a collision when restore-all picks `a`.
    (v.notes_dir / a.filename).write_text("collision", encoding="utf-8")
    r = client.post("/api/trash/restore-all")
    assert r.status_code == 200
    body = r.json()
    assert body["restored_count"] == 1
    assert body["skipped"] == [a.filename]
