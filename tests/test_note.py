from pathlib import Path

from knowlet.core.note import Note, new_id, slugify


def test_slugify_basic():
    assert slugify("Hello World") == "hello-world"
    assert slugify("RAG: hybrid retrieval!") == "rag-hybrid-retrieval"


def test_slugify_cjk_kept():
    assert slugify("注意力机制") == "注意力机制"
    assert slugify("attention 注意力 paper").startswith("attention-注意力-paper")


def test_slugify_empty_falls_back():
    assert slugify("") == "note"
    assert slugify("---") == "note"


def test_note_round_trip(tmp_path: Path):
    note = Note(id=new_id(), title="Hello", body="some body\n\nmore body", tags=["a", "b"])
    path = tmp_path / note.filename
    path.write_text(note.to_markdown(), encoding="utf-8")

    loaded = Note.from_file(path)
    assert loaded.id == note.id
    assert loaded.title == note.title
    assert loaded.body.strip() == note.body.strip()
    assert loaded.tags == note.tags


def test_content_hash_stable():
    a = Note(id="x", title="T", body="B")
    b = Note(id="y", title="T", body="B")  # different id, same content
    assert a.content_hash == b.content_hash
    c = Note(id="x", title="T2", body="B")
    assert a.content_hash != c.content_hash


def test_filename_is_ulid_only():
    """B3: filenames are `<id>.md` — no title slug. Title changes don't
    rename the file, so iCloud / Syncthing don't see delete+create."""
    note = Note(id="01HX0000000000000000000000", title="Hello World", body="b")
    assert note.filename == "01HX0000000000000000000000.md"
    # Rename the title — filename stays the same.
    note.title = "Completely different title"
    assert note.filename == "01HX0000000000000000000000.md"


# ---------------------------------------------------------------- M7.0.1 trash


def test_trash_note_moves_to_dot_trash(tmp_path):
    """`Vault.trash_note` moves the file under notes/.trash/ — recoverable."""
    from knowlet.core.vault import Vault

    v = Vault(tmp_path)
    v.init_layout()
    n = Note(id=new_id(), title="Goodbye", body="bye")
    p = v.write_note(n)
    assert p.exists()

    trashed = v.trash_note(p)
    assert not p.exists()
    assert trashed.exists()
    assert trashed.parent.name == ".trash"
    # Frontmatter is intact — could be re-read.
    reloaded = Note.from_file(trashed)
    assert reloaded.id == n.id


def test_iter_note_paths_skips_trash(tmp_path):
    """The main Notes listing must not surface trashed files."""
    from knowlet.core.vault import Vault

    v = Vault(tmp_path)
    v.init_layout()
    a = Note(id=new_id(), title="kept", body="x")
    b = Note(id=new_id(), title="goner", body="y")
    pa = v.write_note(a)
    pb = v.write_note(b)
    v.trash_note(pb)

    visible = list(v.iter_note_paths())
    assert pa in visible
    assert pb not in visible
    trashed = list(v.iter_trashed_paths())
    assert len(trashed) == 1


def test_restore_note_returns_to_notes_dir(tmp_path):
    from knowlet.core.vault import Vault

    v = Vault(tmp_path)
    v.init_layout()
    n = Note(id=new_id(), title="oops", body="z")
    p = v.write_note(n)
    trashed = v.trash_note(p)

    restored = v.restore_note(trashed)
    assert restored.exists()
    assert restored.parent.name == "notes"
    assert not trashed.exists()


def test_iter_note_paths_is_recursive(tmp_path):
    """M7.0.2: notes/ supports user-organized subdirectories."""
    from knowlet.core.vault import Vault

    v = Vault(tmp_path)
    v.init_layout()

    # top-level
    a = Note(id=new_id(), title="root note", body="r")
    pa = v.write_note(a)

    # Manually place files in subdirs (the user does this in Finder).
    sub = v.notes_dir / "AI papers"
    sub.mkdir(parents=True, exist_ok=True)
    deep = sub / "transformer"
    deep.mkdir(parents=True, exist_ok=True)
    b = Note(id=new_id(), title="attention", body="b")
    pb = sub / b.filename
    pb.write_text(b.to_markdown(), encoding="utf-8")
    c = Note(id=new_id(), title="positional", body="c")
    pc = deep / c.filename
    pc.write_text(c.to_markdown(), encoding="utf-8")

    found = set(v.iter_note_paths())
    assert found == {pa, pb, pc}


def test_iter_note_paths_skips_dotdirs(tmp_path):
    """`.trash/` and any other dot-prefixed dir are excluded."""
    from knowlet.core.vault import Vault

    v = Vault(tmp_path)
    v.init_layout()
    n = Note(id=new_id(), title="kept", body="x")
    p = v.write_note(n)

    # .trash/ created via trash_note
    trashed = Note(id=new_id(), title="gone", body="y")
    pt = v.write_note(trashed)
    v.trash_note(pt)

    # An arbitrary user-created dotdir
    hidden = v.notes_dir / ".scratch"
    hidden.mkdir()
    h = Note(id=new_id(), title="scratch", body="z")
    (hidden / h.filename).write_text(h.to_markdown(), encoding="utf-8")

    found = set(v.iter_note_paths())
    assert p in found
    assert all(".trash" not in part for fp in found for part in fp.parts)
    assert all(".scratch" not in part for fp in found for part in fp.parts)


def test_folder_of_returns_relative_dir(tmp_path):
    from knowlet.core.vault import Vault

    v = Vault(tmp_path)
    v.init_layout()
    top = v.notes_dir / "01HX0000000000000000000001.md"
    sub = v.notes_dir / "AI papers" / "01HX0000000000000000000002.md"
    deep = v.notes_dir / "AI papers" / "transformer" / "01HX0000000000000000000003.md"

    assert v.folder_of(top) == ""
    assert v.folder_of(sub) == "AI papers"
    assert v.folder_of(deep) == "AI papers/transformer"


def test_write_attachment_creates_dir_and_returns_path(tmp_path):
    """M7.0.3: write_attachment lazy-creates _attachments/ and saves bytes
    under a ULID name with the given ext."""
    from knowlet.core.vault import Vault

    v = Vault(tmp_path)
    v.init_layout()

    p = v.write_attachment(b"\x89PNG\r\n\x1a\n...", "png")
    assert p.exists()
    assert p.parent == v.attachments_dir
    assert p.suffix == ".png"
    assert p.read_bytes().startswith(b"\x89PNG")
    rel = v.attachment_relpath(p)
    assert rel.startswith("_attachments/")
    assert rel.endswith(".png")


def test_write_attachment_normalizes_ext(tmp_path):
    """`.png` and `PNG` should both end up as `.png`."""
    from knowlet.core.vault import Vault

    v = Vault(tmp_path)
    v.init_layout()
    p = v.write_attachment(b"x", ".PNG")
    assert p.suffix == ".png"


def test_iter_note_paths_skips_attachments_dir(tmp_path):
    """M7.0.3: even if a stray .md ended up in `_attachments/`, the notes
    listing must not pick it up. The dir holds binaries, not Notes."""
    from knowlet.core.vault import Vault

    v = Vault(tmp_path)
    v.init_layout()
    n = Note(id=new_id(), title="real", body="x")
    p = v.write_note(n)

    v.attachments_dir.mkdir(parents=True, exist_ok=True)
    stray = v.attachments_dir / "01HX0000000000000000000099.md"
    stray.write_text("body", encoding="utf-8")

    found = list(v.iter_note_paths())
    assert p in found
    assert stray not in found


def test_restore_note_collision_raises(tmp_path):
    """If a Note with the same filename already exists in notes/, restore
    must refuse rather than silently overwrite."""
    from knowlet.core.vault import Vault

    v = Vault(tmp_path)
    v.init_layout()
    n = Note(id=new_id(), title="x", body="b")
    p = v.write_note(n)
    trashed = v.trash_note(p)

    # Re-create a fresh file at the same name (e.g. user new-noted with the
    # same id, which shouldn't happen with ULIDs but the contract is hard).
    v.write_note(Note(id=n.id, title="something else", body="b2"))

    import pytest
    with pytest.raises(FileExistsError):
        v.restore_note(trashed)
