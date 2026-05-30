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


def test_note_aliases_round_trip(tmp_path: Path):
    """Phase 1 D / D3 Properties UI: aliases land in frontmatter and
    survive a write/read cycle."""
    note = Note(
        id=new_id(),
        title="Attention",
        body="b",
        aliases=["Self-Attention", "注意力"],
    )
    path = tmp_path / note.filename
    path.write_text(note.to_markdown(), encoding="utf-8")
    assert "aliases:" in path.read_text(encoding="utf-8")
    loaded = Note.from_file(path)
    assert loaded.aliases == ["Self-Attention", "注意力"]


def test_note_no_aliases_key_when_empty(tmp_path: Path):
    """Empty aliases list MUST NOT pollute the YAML — keeps existing
    notes' frontmatter byte-identical for git diff hygiene."""
    note = Note(id=new_id(), title="Plain", body="b")
    path = tmp_path / note.filename
    path.write_text(note.to_markdown(), encoding="utf-8")
    assert "aliases" not in path.read_text(encoding="utf-8")


def test_note_legacy_files_load_with_empty_aliases(tmp_path: Path):
    """Pre-D3 notes (no `aliases:` key) load with aliases=[] — no
    schema_version bump needed."""
    legacy = (
        "---\n"
        "schema_version: 1\n"
        "id: 01TESTLEGACY00000000000000\n"
        "title: Legacy\n"
        "tags: []\n"
        "created_at: '2026-01-01T00:00:00Z'\n"
        "updated_at: '2026-01-01T00:00:00Z'\n"
        "---\nbody\n"
    )
    p = tmp_path / "01TESTLEGACY00000000000000.md"
    p.write_text(legacy, encoding="utf-8")
    loaded = Note.from_file(p)
    assert loaded.aliases == []


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


# ----------------------------------------------------- Phase 2 E Slice 4.C
# Note frontmatter v2 — `status` field + lazy migration from v1.


def test_status_defaults_to_active() -> None:
    """A fresh Note constructed without an explicit status starts
    in `active` (the only sensible default per ADR-0023 §7)."""
    n = Note(id=new_id(), title="x", body="b")
    assert n.status == "active"


def test_status_round_trips_via_frontmatter(tmp_path):
    from knowlet.core.vault import Vault

    v = Vault(tmp_path)
    v.init_layout()
    n = Note(id=new_id(), title="t", body="b", status="needs-update")
    path = v.write_note(n)
    raw = path.read_text(encoding="utf-8")
    assert "status: needs-update" in raw
    re_read = Note.from_file(path)
    assert re_read.status == "needs-update"


# ----------------------------------- kind (Phase 3 Stage 2 — ADR-0029 §4.5)


def test_kind_default_is_knowledge() -> None:
    """Per ADR-0029 §4.5: manual-create default = knowledge."""
    from knowlet.core.note import DEFAULT_NOTE_KIND

    n = Note(id=new_id(), title="t", body="b")
    assert n.kind == "knowledge"
    assert DEFAULT_NOTE_KIND == "knowledge"


def test_kind_round_trips_via_frontmatter(tmp_path):
    from knowlet.core.vault import Vault

    v = Vault(tmp_path)
    v.init_layout()
    n = Note(id=new_id(), title="t", body="b", kind="reference")
    path = v.write_note(n)
    raw = path.read_text(encoding="utf-8")
    assert "kind: reference" in raw
    re_read = Note.from_file(path)
    assert re_read.kind == "reference"


def test_legacy_v1_note_reads_kind_as_knowledge(tmp_path):
    """A note hand-written before the kind field existed (no kind in
    frontmatter) reads back as kind=knowledge — backward-compat default
    per ADR-0029 §4.5 (manual authoring path)."""
    legacy = tmp_path / "01ABC.md"
    legacy.write_text(
        "---\nid: 01ABC\ntitle: legacy\n---\nbody\n",
        encoding="utf-8",
    )
    n = Note.from_file(legacy)
    assert n.kind == "knowledge"


def test_invalid_kind_value_falls_back_to_knowledge(tmp_path):
    """Bogus kind value (hand-edit gone wrong / future schema typo) →
    log a warning and default to knowledge, same forward-compat shape
    as status. Next write rewrites with a clean value."""
    bogus = tmp_path / "01XYZ.md"
    bogus.write_text(
        "---\nid: 01XYZ\ntitle: bogus\nschema_version: 2\nkind: total-nonsense\n---\nbody\n",
        encoding="utf-8",
    )
    n = Note.from_file(bogus)
    assert n.kind == "knowledge"


def test_v2_emit_includes_schema_version(tmp_path):
    """to_markdown must always stamp the current schema_version on
    write — that's how lazy migration upgrades v1 files to v2 on the
    next edit (ADR-0018 §1)."""
    from knowlet.core.note import NOTE_SCHEMA_VERSION
    from knowlet.core.vault import Vault

    v = Vault(tmp_path)
    v.init_layout()
    n = Note(id=new_id(), title="t", body="b")
    path = v.write_note(n)
    raw = path.read_text(encoding="utf-8")
    assert f"schema_version: {NOTE_SCHEMA_VERSION}" in raw
    assert NOTE_SCHEMA_VERSION >= 2


def test_v1_file_reads_as_active_status(tmp_path):
    """A note hand-written with no `status` and no `schema_version`
    (legacy v1 shape) reads back with status=active. This is the
    forward-compat contract of ADR-0018 §1: code at N reads N-1."""
    legacy = tmp_path / "01ABC.md"
    legacy.write_text(
        "---\nid: 01ABC\ntitle: legacy\n---\nbody\n",
        encoding="utf-8",
    )
    n = Note.from_file(legacy)
    assert n.schema_version == 1  # preserved as-read
    assert n.status == "active"  # forward-compat default


def test_v1_file_writes_back_as_v2(tmp_path):
    """Lazy migration: open a v1 file (no status, no schema_version
    on disk), write it back via the normal Vault path, and observe
    that the saved file is now v2 with status stamped."""
    from knowlet.core.note import NOTE_SCHEMA_VERSION
    from knowlet.core.vault import Vault

    v = Vault(tmp_path)
    v.init_layout()
    legacy = v.notes_dir / "01ABC.md"
    legacy.write_text(
        "---\nid: 01ABC\ntitle: legacy\n---\nbody\n",
        encoding="utf-8",
    )
    n = Note.from_file(legacy)
    # Re-write via Vault.
    v.write_note(n)
    raw = legacy.read_text(encoding="utf-8")
    assert f"schema_version: {NOTE_SCHEMA_VERSION}" in raw
    assert "status: active" in raw


def test_invalid_status_value_falls_back_to_active(tmp_path):
    """A bogus status value (typo, hand-edit gone wrong) does NOT
    crash the read — it logs a warning and degrades to `active`.
    Next write rewrites with a clean valid value."""
    bogus = tmp_path / "01XYZ.md"
    bogus.write_text(
        "---\nid: 01XYZ\ntitle: bogus\nschema_version: 2\nstatus: total-nonsense\n---\nbody\n",
        encoding="utf-8",
    )
    n = Note.from_file(bogus)
    assert n.status == "active"


def test_all_status_values_round_trip(tmp_path):
    """Every NoteStatus value writes + reads identically."""
    from knowlet.core.note import NOTE_STATUSES
    from knowlet.core.vault import Vault

    v = Vault(tmp_path)
    v.init_layout()
    for s in NOTE_STATUSES:
        n = Note(id=new_id(), title=f"t-{s}", body="b", status=s)  # type: ignore[arg-type]
        path = v.write_note(n)
        re_read = Note.from_file(path)
        assert re_read.status == s, f"round-trip lost {s!r}"
