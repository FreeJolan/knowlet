"""Regression tests for the 2026-11 vault-data audit batch.

Each test class maps to one finding in the audit report. These are
written test-first: every test here fails against the pre-fix code.
"""

from __future__ import annotations

import os
import threading
import zipfile
from pathlib import Path

import pytest
import yaml

import knowlet.core.vault as vault_mod
from knowlet.core.backups import BackupStore
from knowlet.core.inline_tags import extract_inline_tags, merge_with_inline_tags
from knowlet.core.note import Note, new_id
from knowlet.core.portability import build_export_archive, merge_directory
from knowlet.core.vault import Vault


def _mk_vault(tmp_path: Path) -> Vault:
    v = Vault(tmp_path)
    v.init_layout()
    return v


def _write_valid_note(path: Path, note_id: str, title: str, body: str = "body") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nschema_version: 2\nid: {note_id}\ntitle: {title}\n---\n{body}\n",
        encoding="utf-8",
    )


# ------------------------------------------------------------------
# Finding 1 — vault.py delete_folder: non-.md files must not be
# permanently destroyed by rmtree; they must survive under .trash/.
# ------------------------------------------------------------------


def test_delete_folder_preserves_non_md_files(tmp_path: Path) -> None:
    v = _mk_vault(tmp_path)
    folder = v.notes_dir / "project"
    folder.mkdir()
    _write_valid_note(folder / f"{new_id()}.md", new_id(), "a note")
    binary = b"\x89PNG fake image bytes"
    (folder / "diagram.png").write_bytes(binary)
    (folder / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    v.delete_folder("project")

    assert not folder.exists()
    # The non-markdown files must still exist somewhere under .trash/.
    survivors = {p.name: p for p in v.trash_dir.rglob("*") if p.is_file()}
    assert "diagram.png" in survivors, "binary attachment was permanently deleted"
    assert survivors["diagram.png"].read_bytes() == binary
    assert "data.csv" in survivors


def test_delete_folder_with_only_notes_leaves_no_residue(tmp_path: Path) -> None:
    v = _mk_vault(tmp_path)
    folder = v.notes_dir / "clean"
    folder.mkdir()
    _write_valid_note(folder / f"{new_id()}.md", new_id(), "only note")

    trashed = v.delete_folder("clean")

    assert not folder.exists()
    assert len(trashed) == 1
    assert trashed[0].exists()


# ------------------------------------------------------------------
# Finding 2 — vault.py trash_note / restore_note must not rewrite a
# corrupted note with synthesized frontmatter (that permanently
# destroys the user's damaged-but-recoverable metadata text).
# ------------------------------------------------------------------

_CORRUPTED_RAW = '---\nid: 01ABC\ntitle: "unclosed\nbroken: : :\n---\nthe body\n'


def test_trash_note_preserves_corrupted_bytes(tmp_path: Path) -> None:
    v = _mk_vault(tmp_path)
    p = v.notes_dir / "broken.md"
    p.write_text(_CORRUPTED_RAW, encoding="utf-8")

    target = v.trash_note(p)

    assert target.exists()
    assert target.read_text(encoding="utf-8") == _CORRUPTED_RAW, (
        "trash_note rewrote a corrupted note; the damaged frontmatter "
        "text must survive into .trash/ byte-for-byte"
    )


def test_restore_note_preserves_corrupted_bytes(tmp_path: Path) -> None:
    v = _mk_vault(tmp_path)
    v.trash_dir.mkdir(parents=True, exist_ok=True)
    p = v.trash_dir / "broken.md"
    p.write_text(_CORRUPTED_RAW, encoding="utf-8")

    target = v.restore_note(p)

    assert target.read_text(encoding="utf-8") == _CORRUPTED_RAW, (
        "restore_note rewrote a corrupted note instead of moving the bytes"
    )


def test_trash_note_still_annotates_valid_notes(tmp_path: Path) -> None:
    v = _mk_vault(tmp_path)
    folder = v.notes_dir / "sub"
    nid = new_id()
    _write_valid_note(folder / f"{nid}.md", nid, "fine note")

    target = v.trash_note(folder / f"{nid}.md")

    restored = Note.from_file(target)
    assert restored.trashed_from == "sub"


# ------------------------------------------------------------------
# Finding 3 — trash filename collisions in the same second must not
# silently overwrite earlier trash entries.
# ------------------------------------------------------------------


def test_trash_same_name_same_second_does_not_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    v = _mk_vault(tmp_path)
    # Freeze the timestamp so every fallback name collides.
    monkeypatch.setattr(vault_mod, "now_iso", lambda: "2026-11-21T10:00:00Z")

    contents = []
    for i, sub in enumerate(("a", "b", "c")):
        p = v.notes_dir / sub / "readme.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        body = f"content-{i}"
        _write_valid_note(p, new_id(), f"readme {i}", body=body)
        contents.append(body)
        v.trash_note(p)

    trashed_files = [p for p in v.trash_dir.glob("*.md") if p.is_file()]
    assert len(trashed_files) == 3, (
        f"expected 3 distinct trash entries, got {len(trashed_files)} — "
        "a same-second collision silently overwrote an earlier entry"
    )
    joined = "\n".join(p.read_text(encoding="utf-8") for p in trashed_files)
    for body in contents:
        assert body in joined


# ------------------------------------------------------------------
# Finding 4 — write_note must not share one fixed tmp path between
# concurrent writers (torn files / FileNotFoundError on replace).
# ------------------------------------------------------------------


def test_write_note_concurrent_writers_do_not_share_tmp(tmp_path: Path) -> None:
    v = _mk_vault(tmp_path)
    nid = new_id()
    note = Note(id=nid, title="t", body="original")
    v.write_note(note)

    a_at_replace = threading.Event()
    b_done = threading.Event()
    orig_replace = Path.replace
    errors: list[BaseException] = []

    def gated_replace(self: Path, target):  # type: ignore[no-untyped-def]
        # Writer A pauses right before publishing its tmp file, long
        # enough for writer B to complete a full save of the same note.
        if threading.current_thread().name == "writer-A" and ".tmp" in self.name:
            a_at_replace.set()
            assert b_done.wait(10), "writer B never finished"
        return orig_replace(self, target)

    def writer_a() -> None:
        try:
            na = Note.from_file(v.notes_dir / f"{nid}.md")
            na.body = "version-A"
            v.write_note(na)
        except BaseException as exc:
            errors.append(exc)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Path, "replace", gated_replace)
        t = threading.Thread(target=writer_a, name="writer-A")
        t.start()
        assert a_at_replace.wait(10), "writer A never reached replace"
        nb = Note.from_file(v.notes_dir / f"{nid}.md")
        nb.body = "version-B"
        v.write_note(nb)  # writer B, runs to completion
        b_done.set()
        t.join(10)

    assert not errors, f"concurrent save crashed: {errors!r}"
    final = Note.from_file(v.notes_dir / f"{nid}.md")
    assert final.frontmatter_status == "valid"
    # Last publisher was writer A; its complete content must have landed.
    assert final.body in ("version-A", "version-B")
    assert final.body == "version-A"
    # No stale tmp files left behind.
    assert not list(v.notes_dir.glob("*.tmp"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_write_note_keeps_umask_default_permissions(tmp_path: Path) -> None:
    # The unique-tmp rewrite must not change file modes relative to a
    # plain write_text (mkstemp would publish 0600; a hard chmod would
    # ignore a restrictive umask).
    v = _mk_vault(tmp_path)
    old = os.umask(0o077)
    try:
        note = Note(id=new_id(), title="t", body="b")
        p = v.write_note(note)
        assert p.stat().st_mode & 0o777 == 0o600
        note.body = "b2"
        v.write_note(note)
        assert p.stat().st_mode & 0o777 == 0o600
    finally:
        os.umask(old)
    os.umask(0o022)
    try:
        note2 = Note(id=new_id(), title="t2", body="b")
        assert v.write_note(note2).stat().st_mode & 0o777 == 0o644
    finally:
        os.umask(old)


# ------------------------------------------------------------------
# Finding 5 — unknown (user-custom) frontmatter fields must survive a
# read → write round-trip instead of being silently dropped.
# ------------------------------------------------------------------


def test_roundtrip_preserves_unknown_frontmatter_fields(tmp_path: Path) -> None:
    nid = new_id()
    p = tmp_path / f"{nid}.md"
    p.write_text(
        "---\n"
        "schema_version: 2\n"
        f"id: {nid}\n"
        "title: obsidian note\n"
        "cssclasses:\n  - wide\n  - fancy\n"
        "publish: true\n"
        "rating: 4\n"
        "---\nbody text\n",
        encoding="utf-8",
    )
    note = Note.from_file(p)
    out = note.to_markdown()
    meta = yaml.safe_load(out.split("---")[1])
    assert meta.get("cssclasses") == ["wide", "fancy"], "custom list field dropped"
    assert meta.get("publish") is True, "custom bool field dropped"
    assert meta.get("rating") == 4, "custom int field dropped"
    # Canonical fields still win.
    assert meta["id"] == nid
    assert meta["title"] == "obsidian note"


def test_write_note_preserves_unknown_fields_on_disk(tmp_path: Path) -> None:
    v = _mk_vault(tmp_path)
    nid = new_id()
    p = v.notes_dir / f"{nid}.md"
    p.write_text(
        f"---\nschema_version: 2\nid: {nid}\ntitle: t\ncustom_key: keep-me\n---\nbody\n",
        encoding="utf-8",
    )
    note = v.read_note(p)
    note.body = "edited body"
    v.write_note(note)
    raw = p.read_text(encoding="utf-8")
    assert "custom_key: keep-me" in raw, "editing a note dropped the user's custom field"


# ------------------------------------------------------------------
# Finding 6 — a valid-frontmatter note that lacks `id` must get ONE
# stable id persisted to disk by read_note, not a fresh ULID per read.
# ------------------------------------------------------------------


def test_read_note_persists_assigned_id_when_missing(tmp_path: Path) -> None:
    v = _mk_vault(tmp_path)
    p = v.notes_dir / "obsidian-note.md"
    p.write_text("---\ntitle: from obsidian\ntags: [x]\n---\nhello\n", encoding="utf-8")

    first = v.read_note(p)
    assert first.frontmatter_status == "valid"
    # The assigned id must now be materialized in the file itself…
    raw = p.read_text(encoding="utf-8")
    assert f"id: {first.id}" in raw, "assigned id was not persisted to disk"
    # …so every later reader (including raw Note.from_file, which is
    # what reindex uses) sees the same identity.
    assert Note.from_file(p).id == first.id
    assert v.read_note(p).id == first.id
    # Original metadata survived the materialization.
    assert Note.from_file(p).title == "from obsidian"
    assert Note.from_file(p).tags == ["x"]


def test_read_note_missing_id_reuses_ulid_filename(tmp_path: Path) -> None:
    v = _mk_vault(tmp_path)
    nid = new_id()
    p = v.notes_dir / f"{nid}.md"
    p.write_text("---\ntitle: lost my id\n---\nhello\n", encoding="utf-8")
    note = v.read_note(p)
    assert note.id == nid, "ULID-shaped filename should be reused as the id"


def test_read_note_with_id_does_not_rewrite(tmp_path: Path) -> None:
    v = _mk_vault(tmp_path)
    nid = new_id()
    p = v.notes_dir / f"{nid}.md"
    raw = f"---\nschema_version: 2\nid: {nid}\ntitle: t\n---\nbody\n"
    p.write_text(raw, encoding="utf-8")
    v.read_note(p)
    assert p.read_text(encoding="utf-8") == raw, "read_note must not touch a complete note"


# ------------------------------------------------------------------
# Finding 7 — inline tag extraction must not treat issue numbers /
# hex colors as tags; merge must support previous_body so UI-deleted
# tags are not resurrected.
# ------------------------------------------------------------------


def test_extract_inline_tags_skips_numbers_and_hex_colors() -> None:
    body = "fix #108 and (#1), color #fff / #FFFFFF / #ffffff00 done"
    assert extract_inline_tags(body) == []


def test_extract_inline_tags_keeps_real_tags() -> None:
    body = "#v2 of #project-x, see #area/sub and #2024-plan"
    assert extract_inline_tags(body) == ["v2", "project-x", "area/sub", "2024-plan"]


def test_merge_previous_body_does_not_resurrect_deleted_tag() -> None:
    # The user deleted "old" from the chip UI; the body text still
    # contains #old from before. Only tags NEW relative to the previous
    # body may be merged in.
    out = merge_with_inline_tags(
        ["keep"],
        "body with #old and #new",
        previous_body="body with #old",
    )
    assert out == ["keep", "new"]


def test_merge_without_previous_body_keeps_old_behavior() -> None:
    assert merge_with_inline_tags(["a"], "body #b") == ["a", "b"]


# ------------------------------------------------------------------
# Finding 8 — import merge must not trust a traversal-shaped id from
# frontmatter as a write path.
# ------------------------------------------------------------------


def test_merge_rejects_path_traversal_id(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    live_id = new_id()
    live = vault_root / "notes" / f"{live_id}.md"
    _write_valid_note(live, live_id, "live note", body="live content")

    source = tmp_path / "evil-src"
    source.mkdir()
    (source / "evil.md").write_text(
        f"---\nschema_version: 2\nid: ../../{live_id}\ntitle: pwn\n---\npwned body\n",
        encoding="utf-8",
    )

    report = merge_directory(
        source_dir=source,
        vault_root=vault_root,
        subfolder="imported/x",
        existing_ids=[live_id],
    )

    # The live note must be untouched.
    assert "live content" in live.read_text(encoding="utf-8")
    # Nothing may land outside the import target directory.
    target = vault_root / "notes" / "imported" / "x"
    written = [p for p in vault_root.rglob("*.md") if p.is_file() and p != live]
    for p in written:
        assert target.resolve() in p.resolve().parents, f"file escaped import dir: {p}"
    assert report.notes_created <= 1


@pytest.mark.parametrize(
    "bad_id",
    ["../../01LIVE", "sub/dir", "..", ".hidden", "a\\b", "c:evil", "with space", ""],
)
def test_merge_reassigns_unsafe_id_and_keeps_content(tmp_path: Path, bad_id: str) -> None:
    vault_root = tmp_path / "vault"
    (vault_root / "notes").mkdir(parents=True)
    source = tmp_path / "src"
    source.mkdir()
    (source / "evil.md").write_text(
        f"---\nschema_version: 2\nid: {bad_id!r}\ntitle: kept title\n"
        "tags: [t1]\ncustom: yes\n---\nkept body\n",
        encoding="utf-8",
    )

    for dry_run in (True, False):
        report = merge_directory(
            source_dir=source, vault_root=vault_root, subfolder="imported/x", dry_run=dry_run
        )
        assert report.notes_created == 1
        (_, action, final_rel) = report.items[0]
        assert action == "create"
        assert final_rel is not None
        # Dry-run preview reports the real (safe) landing path.
        assert final_rel.startswith("notes/imported/x/")
        assert "/" not in final_rel.removeprefix("notes/imported/x/")

    target = vault_root / "notes" / "imported" / "x"
    written = [p for p in vault_root.rglob("*.md") if p.is_file()]
    assert len(written) == 1 and written[0].parent == target
    note = Note.from_file(written[0])
    assert note.id == written[0].stem and note.id != bad_id
    assert note.title == "kept title"
    assert note.tags == ["t1"]
    assert note.body.strip() == "kept body"
    assert note.extra_meta.get("custom") is True


def test_merge_rejects_subfolder_outside_notes(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    (vault_root / "notes").mkdir(parents=True)
    source = tmp_path / "src"
    source.mkdir()
    _write_valid_note(source / "a.md", new_id(), "a")
    with pytest.raises(ValueError):
        merge_directory(source_dir=source, vault_root=vault_root, subfolder="../../outside")
    assert not (tmp_path / "outside").exists()


def test_merge_never_overwrites_existing_file_in_import_folder(tmp_path: Path) -> None:
    # The CLI passes no existing_ids; a second import of the same file
    # into the same dated folder must not clobber the first copy.
    vault_root = tmp_path / "vault"
    nid = new_id()
    existing = vault_root / "notes" / "imported" / "x" / f"{nid}.md"
    _write_valid_note(existing, nid, "edited after first import", body="user edits")
    source = tmp_path / "src"
    source.mkdir()
    _write_valid_note(source / f"{nid}.md", nid, "original", body="stale")

    report = merge_directory(source_dir=source, vault_root=vault_root, subfolder="imported/x")

    assert report.notes_created == 0
    assert report.items == [(f"{nid}.md", "skip-duplicate-id", None)]
    assert "user edits" in existing.read_text(encoding="utf-8")


def test_is_safe_note_id() -> None:
    from knowlet.core.note import is_safe_note_id

    assert is_safe_note_id(new_id())
    assert is_safe_note_id("knowlet-today-note-template")
    for bad in ("../x", "a/b", "a\\b", "..", ".x", "", "a b", "a.md", None, 123, "x" * 200):
        assert not is_safe_note_id(bad), bad


def test_merge_keeps_trusting_safe_ulid_ids(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    (vault_root / "notes").mkdir(parents=True)
    source = tmp_path / "src"
    source.mkdir()
    nid = new_id()
    (source / "good.md").write_text(
        f"---\nschema_version: 2\nid: {nid}\ntitle: good\n---\nbody\n",
        encoding="utf-8",
    )
    report = merge_directory(source_dir=source, vault_root=vault_root, subfolder="imported/x")
    assert report.notes_created == 1
    assert (vault_root / "notes" / "imported" / "x" / f"{nid}.md").exists()


# ------------------------------------------------------------------
# Finding 9 — export must not pack .trash/; merge import must not
# resurrect .trash/ and _templates/ entries as live notes.
# ------------------------------------------------------------------


def test_export_excludes_trash(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    nid = new_id()
    _write_valid_note(vault_root / "notes" / f"{nid}.md", nid, "live")
    gone_id = new_id()
    _write_valid_note(vault_root / "notes" / ".trash" / f"{gone_id}.md", gone_id, "deleted")
    tpl = vault_root / "notes" / "_templates" / "daily.md"
    tpl.parent.mkdir(parents=True, exist_ok=True)
    tpl.write_text("# {{title}}\n", encoding="utf-8")

    out = tmp_path / "export.zip"
    result = build_export_archive(vault_root=vault_root, output_path=out)

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
    assert not any(".trash" in n for n in names), f"archive contains trash: {names}"
    # Templates are user content and still travel with the archive.
    assert "notes/_templates/daily.md" in names
    # Deleted notes are not counted as notes.
    assert result.manifest.note_count == 2  # live note + template


def test_merge_skips_trash_and_templates(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    (vault_root / "notes").mkdir(parents=True)
    source = tmp_path / "src"
    (source / ".trash").mkdir(parents=True)
    (source / "_templates").mkdir(parents=True)
    nid = new_id()
    _write_valid_note(source / "ok.md", nid, "ok note")
    _write_valid_note(source / ".trash" / "gone.md", new_id(), "deleted note")
    (source / "_templates" / "tpl.md").write_text("# {{title}}\n", encoding="utf-8")

    report = merge_directory(source_dir=source, vault_root=vault_root, subfolder="imported/x")

    assert report.notes_created == 1, "import resurrected .trash/_templates entries as live notes"
    imported = list((vault_root / "notes" / "imported" / "x").glob("*.md"))
    assert [p.stem for p in imported] == [nid]


def test_export_then_merge_roundtrip_does_not_resurrect_trash(tmp_path: Path) -> None:
    src_vault = tmp_path / "old"
    live_id = new_id()
    _write_valid_note(src_vault / "notes" / "proj" / f"{live_id}.md", live_id, "live")
    gone_id = new_id()
    _write_valid_note(src_vault / "notes" / ".trash" / f"{gone_id}.md", gone_id, "deleted")
    (src_vault / "notes" / ".DS_Store").write_bytes(b"junk")
    out = tmp_path / "export.zip"
    result = build_export_archive(vault_root=src_vault, output_path=out)
    assert result.manifest.note_count == 1

    unpacked = tmp_path / "unpacked"
    with zipfile.ZipFile(out) as zf:
        assert not any("/." in n for n in zf.namelist())
        zf.extractall(unpacked)
    # Even an archive produced by an older knowlet (trash inside) is safe.
    _write_valid_note(unpacked / "notes" / ".trash" / f"{gone_id}.md", gone_id, "deleted")

    new_vault = tmp_path / "new"
    (new_vault / "notes").mkdir(parents=True)
    report = merge_directory(
        source_dir=unpacked / "notes", vault_root=new_vault, subfolder="imported/x"
    )
    assert report.notes_created == 1
    assert [p.stem for p in (new_vault / "notes").rglob("*.md")] == [live_id]


def test_merge_keeps_nested_templates_folder_that_is_not_top_level(tmp_path: Path) -> None:
    # Only the vault's top-level system folder is special; a user folder
    # called `_templates` deeper in an Obsidian tree is ordinary content.
    vault_root = tmp_path / "vault"
    (vault_root / "notes").mkdir(parents=True)
    source = tmp_path / "src"
    _write_valid_note(source / "proj" / "_templates" / "n.md", new_id(), "nested")
    report = merge_directory(source_dir=source, vault_root=vault_root, subfolder="imported/x")
    assert report.notes_created == 1


# ------------------------------------------------------------------
# Finding 10 — per-save backup prune must be a targeted per-id scan,
# not a full walk over every note's backups.
# ------------------------------------------------------------------


def test_backup_prune_does_not_walk_all_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = BackupStore(tmp_path)
    src = tmp_path / "note.md"

    # Seed history for another id so a full-walk implementation has
    # something to trip over.
    src.write_text("x", encoding="utf-8")
    for _ in range(3):
        assert store.backup_before_overwrite("note", "OTHERID000000000000000000", src)

    def boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("prune must not use the full list_backups walk")

    monkeypatch.setattr(BackupStore, "list_backups", boom)
    for i in range(7):
        src.write_text(f"v{i}", encoding="utf-8")
        dest = store.backup_before_overwrite("note", "THISID0000000000000000000", src)
        assert dest is not None, "backup path failed (prune walked all ids and raised)"
    monkeypatch.undo()

    mine = store.list_backups(entity_type="note", entity_id="THISID0000000000000000000")
    assert len(mine) == 5, f"prune kept {len(mine)} backups, expected 5"
    others = store.list_backups(entity_type="note", entity_id="OTHERID000000000000000000")
    assert len(others) == 3, "prune touched another id's backups"


def test_backup_prune_ignores_ids_sharing_a_dotted_prefix(tmp_path: Path) -> None:
    store = BackupStore(tmp_path)
    src = tmp_path / "note.md"
    src.write_text("x", encoding="utf-8")
    # "ID.other" starts with "ID." — the prefix glob must not treat its
    # backups as ID's history (and must not prune them).
    for _ in range(3):
        store.backup_before_overwrite("note", "ID.other", src)
    for _ in range(7):
        store.backup_before_overwrite("note", "ID", src)
    assert len(store.list_backups(entity_type="note", entity_id="ID")) == 5
    assert len(store.list_backups(entity_type="note", entity_id="ID.other")) == 3
    assert store._list_for("note", "ID") == store.list_backups(entity_type="note", entity_id="ID")


def test_backup_same_millisecond_does_not_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import knowlet.core.backups as backups_mod

    monkeypatch.setattr(backups_mod, "_ts_for_filename", lambda: "2026-11-21T10-00-00-000Z")
    store = BackupStore(tmp_path)
    src = tmp_path / "note.md"
    for i in range(3):
        src.write_text(f"state-{i}", encoding="utf-8")
        assert store.backup_before_overwrite("note", "NID", src) is not None
    entries = store.list_backups(entity_type="note", entity_id="NID")
    assert sorted(e.path.read_text(encoding="utf-8") for e in entries) == [
        "state-0",
        "state-1",
        "state-2",
    ]
    # Newest first.
    assert entries[0].path.read_text(encoding="utf-8") == "state-2"
