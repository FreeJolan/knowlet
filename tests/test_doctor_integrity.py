"""Tests for the vault-integrity check inside `knowlet doctor`."""

from pathlib import Path

from knowlet.cli._doctor import _check_vault_integrity
from knowlet.core.note import Note, new_id
from knowlet.core.vault import Vault


def test_integrity_clean_vault_reports_zero_failures(tmp_path: Path):
    v = Vault(tmp_path)
    v.init_layout()
    n = Note(id=new_id(), title="hi", body="body")
    v.write_note(n)
    out = _check_vault_integrity(v)
    by_entity = {row[0]: row for row in out}
    assert by_entity["notes"][1] == 1  # one file
    assert by_entity["notes"][2] == []  # no failures


def test_integrity_detects_corrupt_note(tmp_path: Path):
    """A garbage file in notes/ should surface as a parse failure."""
    v = Vault(tmp_path)
    v.init_layout()
    bad = v.notes_dir / "01HXBAD.md"
    bad.write_text("not even close to YAML frontmatter\nrandom garbage", encoding="utf-8")
    out = _check_vault_integrity(v)
    by_entity = {row[0]: row for row in out}
    # Note: a fully garbage file may still parse with empty frontmatter — but
    # if the body is empty the parse succeeds with whatever it finds. So
    # write a frontmatter that's actually unparseable yaml.
    really_bad = v.notes_dir / "01HXREALLYBAD.md"
    really_bad.write_text(
        "---\n: : : not yaml\n  bad: [unclosed\n---\nbody",
        encoding="utf-8",
    )
    out = _check_vault_integrity(v)
    by_entity = {row[0]: row for row in out}
    # At least the really-bad file should fail
    note_failures = by_entity["notes"][2]
    assert "01HXREALLYBAD.md" in note_failures


def test_integrity_handles_empty_dirs(tmp_path: Path):
    """Vaults that haven't created cards/drafts/tasks should report 0/0
    not crash."""
    v = Vault(tmp_path)
    v.init_layout()
    out = _check_vault_integrity(v)
    by_entity = {row[0]: row for row in out}
    assert by_entity["cards"][1] == 0
    assert by_entity["cards"][2] == []
    assert by_entity["drafts"][1] == 0
    assert by_entity["mining_tasks"][1] == 0


def test_integrity_skips_trash_and_attachments(tmp_path: Path):
    """`.trash/` and `_attachments/` are skipped by `iter_note_paths` —
    integrity check inherits that behavior, doesn't report on them."""
    v = Vault(tmp_path)
    v.init_layout()
    # Stage a "deleted" note in .trash + an attachment
    v.trash_dir.mkdir(parents=True, exist_ok=True)
    (v.trash_dir / "01HXDELETED.md").write_text(
        "---\n  bad: [unclosed\n---\n", encoding="utf-8"
    )
    v.attachments_dir.mkdir(parents=True, exist_ok=True)
    (v.attachments_dir / "01HXIMG.md").write_text(
        "---\n  also: [unclosed\n---\n", encoding="utf-8"
    )
    out = _check_vault_integrity(v)
    by_entity = {row[0]: row for row in out}
    # Both bad files are in skipped dirs → not counted, not failed
    assert "01HXDELETED.md" not in by_entity["notes"][2]
    assert "01HXIMG.md" not in by_entity["notes"][2]
