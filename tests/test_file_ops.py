"""Vault file-op tests (Phase 1 A, ADR-0021).

Vault-layer behavior only — `mkdir_folder`, `move_note`, `rename_folder`,
`move_folder`, `delete_folder`, `_resolve_subpath`, `purge_trashed`. Tests
that go through the FastAPI surface live in `test_web_file_ops.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from knowlet.core.note import Note
from knowlet.core.vault import Vault


def _vault(tmp_path: Path) -> Vault:
    v = Vault(tmp_path)
    v.init_layout()
    return v


def _make_note(v: Vault, title: str, *, folder: str | None = None) -> Note:
    n = Note(id=f"01HX{title.upper()}".ljust(26, "Z"), title=title, body=f"body of {title}")
    v.write_note(n, folder=folder)
    return n


# --------------------------------------------------------------- _resolve_subpath


def test_resolve_subpath_root_returns_notes_dir(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    assert v._resolve_subpath("") == v.notes_dir
    assert v._resolve_subpath("/") == v.notes_dir
    assert v._resolve_subpath("  ") == v.notes_dir


def test_resolve_subpath_simple(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    assert v._resolve_subpath("a/b") == v.notes_dir / "a" / "b"


def test_resolve_subpath_rejects_path_traversal(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    with pytest.raises(ValueError, match="invalid path segment"):
        v._resolve_subpath("a/../b")
    with pytest.raises(ValueError, match="invalid path segment"):
        v._resolve_subpath("..")


def test_resolve_subpath_rejects_dotdirs(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    with pytest.raises(ValueError, match="dotfiles"):
        v._resolve_subpath(".trash")
    with pytest.raises(ValueError, match="dotfiles"):
        v._resolve_subpath("ok/.hidden")


def test_resolve_subpath_rejects_attachments(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    with pytest.raises(ValueError, match="_attachments"):
        v._resolve_subpath("_attachments")
    with pytest.raises(ValueError, match="_attachments"):
        v._resolve_subpath("_attachments/sub")


# --------------------------------------------------------------- write_note + folder


def test_write_note_flat_root(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    n = Note(id="01HXAAAAAA", title="hi", body="b")
    p = v.write_note(n)
    assert p == v.notes_dir / "01HXAAAAAA.md"
    assert n.path == p


def test_write_note_with_folder_creates_dirs(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    n = Note(id="01HXBBBBBB", title="hi", body="b")
    p = v.write_note(n, folder="projects/knowlet")
    assert p == v.notes_dir / "projects" / "knowlet" / "01HXBBBBBB.md"
    assert (v.notes_dir / "projects" / "knowlet").is_dir()


def test_write_note_honors_existing_path(tmp_path: Path) -> None:
    """Re-writing an existing note (with .path set) preserves its folder."""
    v = _vault(tmp_path)
    n = Note(id="01HXCCCCCC", title="hi", body="b")
    v.write_note(n, folder="a")
    n.body = "body 2"
    v.write_note(n)  # no folder arg → uses note.path
    assert n.path == v.notes_dir / "a" / "01HXCCCCCC.md"


# --------------------------------------------------------------- mkdir + iter_folders


def test_mkdir_folder_creates(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    p = v.mkdir_folder("a/b/c")
    assert p.is_dir()
    assert p == v.notes_dir / "a" / "b" / "c"


def test_mkdir_folder_idempotent(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    v.mkdir_folder("a")
    v.mkdir_folder("a")  # no error


def test_iter_folders_skips_dotdirs_and_attachments(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    v.mkdir_folder("good")
    v.mkdir_folder("good/nested")
    (v.notes_dir / ".trash").mkdir()
    (v.notes_dir / "_attachments").mkdir()
    found = {p.relative_to(v.notes_dir).as_posix() for p in v.iter_folders()}
    assert found == {"good", "good/nested"}


# --------------------------------------------------------------- move_note


def test_move_note_to_subfolder(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    n = _make_note(v, "x")
    new_path = v.move_note(n.path, "projects")  # type: ignore[arg-type]
    assert new_path == v.notes_dir / "projects" / "01HXXZZZZZZZZZZZZZZZZZZZZZ.md"
    assert new_path.exists()
    assert not (v.notes_dir / "01HXXZZZZZZZZZZZZZZZZZZZZZ.md").exists()


def test_move_note_idempotent_when_already_there(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    n = _make_note(v, "x", folder="a")
    new_path = v.move_note(n.path, "a")  # type: ignore[arg-type]
    assert new_path == n.path


def test_move_note_to_root(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    n = _make_note(v, "x", folder="a")
    new_path = v.move_note(n.path, "")  # type: ignore[arg-type]
    assert new_path == v.notes_dir / n.filename


def test_move_note_collision_raises(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    n = _make_note(v, "x")
    # Pre-create a file at the destination with the same name.
    v.mkdir_folder("a")
    (v.notes_dir / "a" / n.filename).write_text("blocker")
    with pytest.raises(FileExistsError):
        v.move_note(n.path, "a")  # type: ignore[arg-type]


def test_move_note_missing_source_raises(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    with pytest.raises(FileNotFoundError):
        v.move_note(v.notes_dir / "ghost.md", "a")


# --------------------------------------------------------------- rename_folder


def test_rename_folder(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    v.mkdir_folder("old")
    n = _make_note(v, "x", folder="old")
    new_path = v.rename_folder("old", "new")
    assert new_path == v.notes_dir / "new"
    assert (v.notes_dir / "new" / n.filename).exists()
    assert not (v.notes_dir / "old").exists()


def test_rename_folder_rejects_slash_in_name(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    v.mkdir_folder("a")
    with pytest.raises(ValueError):
        v.rename_folder("a", "b/c")


def test_rename_folder_collision(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    v.mkdir_folder("a")
    v.mkdir_folder("b")
    with pytest.raises(FileExistsError):
        v.rename_folder("a", "b")


def test_rename_folder_root_rejected(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    with pytest.raises(ValueError, match="cannot rename"):
        v.rename_folder("", "new")


# --------------------------------------------------------------- move_folder


def test_move_folder_simple(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    v.mkdir_folder("src")
    v.mkdir_folder("dst")
    n = _make_note(v, "x", folder="src")
    new_path = v.move_folder("src", "dst")
    assert new_path == v.notes_dir / "dst" / "src"
    assert (v.notes_dir / "dst" / "src" / n.filename).exists()


def test_move_folder_into_descendant_rejected(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    v.mkdir_folder("a/b")
    with pytest.raises(ValueError, match="descendant"):
        v.move_folder("a", "a/b")


def test_move_folder_root_rejected(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    with pytest.raises(ValueError, match="cannot move"):
        v.move_folder("", "dst")


# --------------------------------------------------------------- delete_folder


def test_delete_folder_trashes_notes(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    n1 = _make_note(v, "a", folder="bin")
    n2 = _make_note(v, "b", folder="bin/sub")
    trashed = v.delete_folder("bin")
    assert len(trashed) == 2
    assert all(p.parent == v.trash_dir for p in trashed)
    assert not (v.notes_dir / "bin").exists()
    # Trash retains both files.
    trashed_names = {p.name for p in trashed}
    assert n1.filename in trashed_names
    assert n2.filename in trashed_names


def test_delete_folder_root_rejected(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    with pytest.raises(ValueError, match="cannot delete"):
        v.delete_folder("")


def test_delete_folder_missing_raises(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    with pytest.raises(FileNotFoundError):
        v.delete_folder("ghost")


# --------------------------------------------------------------- purge_trashed


def test_purge_trashed_removes_file(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    n = _make_note(v, "x")
    trashed_path = v.trash_note(n.path)  # type: ignore[arg-type]
    assert trashed_path.exists()
    v.purge_trashed(trashed_path.name)
    assert not trashed_path.exists()


def test_purge_trashed_rejects_path_with_slash(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    with pytest.raises(ValueError):
        v.purge_trashed("a/b.md")


def test_purge_trashed_missing_raises(tmp_path: Path) -> None:
    v = _vault(tmp_path)
    with pytest.raises(FileNotFoundError):
        v.purge_trashed("ghost.md")
