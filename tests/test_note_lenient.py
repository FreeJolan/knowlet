"""Task #108 — Note.from_file lenient frontmatter handling.

Two user-story scenarios:

A. **Auto-fill** — external markdown with no frontmatter at all.
   ``from_file`` synthesizes ``id`` (ULID-named filenames keep
   theirs), ``title`` (first heading or filename stem), and
   timestamps from file mtime/ctime. ``Vault.read_note`` then
   atomically materializes the synthesized frontmatter to disk so
   the next read is canonical.

B. **Corrupted** — file has frontmatter-shaped content but it's
   broken (missing opening ``---``, missing closing ``---``, or
   YAML parse error). ``from_file`` returns a Note whose
   ``frontmatter_status="corrupted"`` and whose body is the file
   content (or, when we can identify the broken FM block, the
   content after it). The Note still has reasonable id/title so
   the UI can render it; the warning chip routes the user to
   auto-repair.

These tests lock the classifier behaviour at the unit level + the
materialization side effect at the Vault level.
"""

from __future__ import annotations

from pathlib import Path

from knowlet.core.note import Note, _classify_frontmatter, new_id
from knowlet.core.vault import Vault

# ----------------------------------------------------- classifier


def test_classify_valid_frontmatter():
    raw = "---\nid: 01ABC\ntitle: hi\n---\nbody here"
    status, meta, body, detail = _classify_frontmatter(raw)
    assert status == "valid"
    assert meta == {"id": "01ABC", "title": "hi"}
    assert body == "body here"
    assert detail is None


def test_classify_no_frontmatter_at_all():
    raw = "# my external note\n\nsome paragraph"
    status, meta, body, detail = _classify_frontmatter(raw)
    assert status == "auto_filled"
    assert meta == {}
    assert body == raw
    assert detail is None


def test_classify_missing_opening_marker():
    """User deleted the opening ``---`` but left the keys + closing.
    Classic external-edit damage."""
    raw = "id: 01XYZ\ntitle: oops\n---\n\nthe body"
    status, _meta, body, detail = _classify_frontmatter(raw)
    assert status == "corrupted"
    assert "opening" in (detail or "").lower()
    assert body == "the body"


def test_classify_missing_closing_marker():
    """Opening is there but the closing ``---`` is gone — we can't
    tell where metadata stops, so we surface the whole file."""
    raw = "---\nid: 01XYZ\ntitle: oops\n\nthe body"
    status, _meta, body, detail = _classify_frontmatter(raw)
    assert status == "corrupted"
    assert "never closes" in (detail or "").lower()
    assert body == raw  # full file — we couldn't slice it


def test_classify_yaml_parse_error():
    raw = "---\nid: 01ABC\ntitle: \"unclosed quote\nbroken: : :\n---\nbody"
    status, _meta, body, detail = _classify_frontmatter(raw)
    assert status == "corrupted"
    assert "yaml" in (detail or "").lower()
    assert body == "body"


def test_classify_non_mapping_yaml():
    """frontmatter is a YAML list, not a mapping — semantic broken."""
    raw = "---\n- foo\n- bar\n---\nbody"
    status, _meta, body, detail = _classify_frontmatter(raw)
    assert status == "corrupted"
    assert "mapping" in (detail or "").lower()
    assert body == "body"


def test_classify_empty_file():
    status, meta, _body, _detail = _classify_frontmatter("")
    assert status == "auto_filled"
    assert meta == {}


def test_classify_whitespace_only_file():
    status, _meta, _body, _detail = _classify_frontmatter("\n\n\n")
    assert status == "auto_filled"


def test_classify_yaml_key_in_body_isnt_corrupted():
    """A line like ``URL: https://...`` at the top of an external
    markdown looks YAML-key-shaped but ISN'T damaged frontmatter.
    Distinguishing signal: no ``---`` marker anywhere nearby."""
    raw = "URL: https://example.com\n\nA cool article I want to remember."
    status, _meta, body, _detail = _classify_frontmatter(raw)
    assert status == "auto_filled"  # not corrupted
    assert body == raw


# ----------------------------------------------------- from_file


def test_from_file_auto_fill_uses_filename_ulid(tmp_path: Path):
    """ULID-named file with no frontmatter keeps its filename id —
    important for files that originated from knowlet but had their
    frontmatter accidentally stripped."""
    nid = new_id()
    p = tmp_path / f"{nid}.md"
    p.write_text("# salvaged note\n\nsome content", encoding="utf-8")
    n = Note.from_file(p)
    assert n.frontmatter_status == "auto_filled"
    assert n.id == nid
    assert n.title == "salvaged note"  # from first heading
    assert "some content" in n.body


def test_from_file_auto_fill_generates_ulid_for_external(tmp_path: Path):
    """Non-ULID filename → fresh ULID + filename stem as title."""
    p = tmp_path / "my-thoughts.md"
    p.write_text("just some markdown\nnothing fancy", encoding="utf-8")
    n = Note.from_file(p)
    assert n.frontmatter_status == "auto_filled"
    # ULID is 26 chars in Crockford base32.
    assert len(n.id) == 26
    assert n.title == "my-thoughts"


def test_from_file_corrupted_renders_with_warning(tmp_path: Path):
    # ULID-shaped filename so _id_from_filename keeps it. ULIDs
    # use Crockford base32 — no I, L, O, or U.
    nid = "01HXBR0KEN00000000000000XX"
    p = tmp_path / f"{nid}.md"
    p.write_text(
        "---\nid: 01ABC\ntitle: \"unclosed\nbroken: : :\n---\nthe body",
        encoding="utf-8",
    )
    n = Note.from_file(p)
    assert n.frontmatter_status == "corrupted"
    assert n.frontmatter_corruption is not None
    # The id falls back to the filename ULID; user's content is preserved.
    assert n.id == nid
    assert n.body == "the body"


# ----------------------------------------------------- read_note materialization


def test_read_note_materializes_auto_filled(tmp_path: Path):
    """The Vault read path persists the synthesized frontmatter so
    the second read sees a canonical ``valid`` Note rather than
    re-synthesizing (which would be slow + change ids on each read
    for non-ULID filenames)."""
    from knowlet.core.audit_log import AuditEventStore

    v = Vault(tmp_path, audit_log=AuditEventStore(tmp_path))
    v.init_layout()
    p = v.notes_dir / "external.md"
    p.write_text("# external note\n\nimported from elsewhere", encoding="utf-8")

    n = v.read_note(p)
    assert n.frontmatter_status == "valid"  # materialized
    # File now has a real frontmatter block on disk.
    new_text = p.read_text(encoding="utf-8")
    assert new_text.startswith("---\n")
    assert "schema_version:" in new_text
    # Second read shouldn't re-materialize.
    second = v.read_note(p)
    assert second.id == n.id  # stable across reads


def test_read_note_does_not_materialize_corrupted(tmp_path: Path):
    """Corrupted notes are returned as-is — we don't auto-mutate
    the user's content unprompted. Repair is an explicit user action."""
    from knowlet.core.audit_log import AuditEventStore

    v = Vault(tmp_path, audit_log=AuditEventStore(tmp_path))
    v.init_layout()
    nid = new_id()
    p = v.notes_dir / f"{nid}.md"
    raw = "---\nid: 01ABC\nbroken: : :\n---\nthe body"
    p.write_text(raw, encoding="utf-8")

    n = v.read_note(p)
    assert n.frontmatter_status == "corrupted"
    # File on disk is untouched.
    assert p.read_text(encoding="utf-8") == raw
