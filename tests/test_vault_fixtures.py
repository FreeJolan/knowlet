"""Phase 2 E Slice 4.F — Vault fixtures regression suite (ADR-0018 §3).

Locks in "current code can read every historical fixture vault" — the
1-major-backward-compat clause. Every schema_version bump must add a
new fixture under tests/fixtures/vaults/ and keep this suite green.

Each fixture is copied to a tmp dir before exercising, so the frozen
files in-tree never get mutated by lazy-migration writes.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from knowlet.core.note import (
    DEFAULT_NOTE_STATUS,
    NOTE_SCHEMA_VERSION,
    NOTE_STATUSES,
    Note,
)
from knowlet.core.vault import Vault

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "vaults"


def _copy_fixture(name: str, tmp_path: Path) -> Path:
    """Copy a frozen fixture vault into tmp_path. Returns the new
    vault root."""
    src = FIXTURES_ROOT / name
    dst = tmp_path / name
    shutil.copytree(src, dst)
    return dst


def _all_fixtures() -> list[str]:
    if not FIXTURES_ROOT.exists():
        return []
    return sorted(
        d.name for d in FIXTURES_ROOT.iterdir() if d.is_dir() and (d / "metadata.json").exists()
    )


def test_at_least_one_fixture_exists() -> None:
    """If this fails, someone deleted the fixtures and forgot the
    contract. Every release should ship at least the most recent
    schema's fixture."""
    fixtures = _all_fixtures()
    assert fixtures, "tests/fixtures/vaults/ is empty — did you delete fixtures?"
    # Sanity check that the metadata files are valid JSON.
    for name in fixtures:
        meta_path = FIXTURES_ROOT / name / "metadata.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta.get("name") == name, f"{name}/metadata.json name mismatch"
        assert "covers" in meta and isinstance(meta["covers"], list)
        assert "regression_target" in meta


@pytest.mark.parametrize("name", _all_fixtures())
def test_fixture_notes_load_without_error(name: str, tmp_path: Path) -> None:
    """The minimum viable contract: every note in every fixture loads
    via Note.from_file without raising. This catches the case where a
    new schema bump introduces a parse path that crashes on legacy
    data — the exact failure mode ADR-0018 §1 is preventing."""
    root = _copy_fixture(name, tmp_path)
    notes_dir = root / "notes"
    if not notes_dir.exists():
        pytest.skip(f"{name} has no notes/ subdir")
    md_files = list(notes_dir.rglob("*.md"))
    assert md_files, f"{name} has no .md files in notes/"
    for f in md_files:
        note = Note.from_file(f)
        # Every loaded note must have a valid status — even if the
        # source file pre-dated the field. This is the forward-compat
        # contract per ADR-0018 §1.
        assert note.status in NOTE_STATUSES, f"{f}: invalid status {note.status!r}"


def test_v1_minimal_lazy_migrates_on_write(tmp_path: Path) -> None:
    """Open every v1 note → save → expect file on disk now stamped
    schema_version=NOTE_SCHEMA_VERSION + status=active."""
    root = _copy_fixture("v1-minimal", tmp_path)
    v = Vault(root)
    notes_dir = root / "notes"
    for f in notes_dir.glob("*.md"):
        n = Note.from_file(f)
        assert n.schema_version == 1, f"{f}: should start at v1"
        # Write back via the Vault path (same path as the user pressing save).
        v.write_note(n)
        # Re-read the file, expect upgrade.
        re_read = Note.from_file(f)
        assert re_read.schema_version == NOTE_SCHEMA_VERSION
        assert re_read.status == DEFAULT_NOTE_STATUS
        # Round-trip preserves identity-defining fields.
        assert re_read.id == n.id
        assert re_read.title == n.title
        assert re_read.tags == n.tags


def test_v2_with_status_round_trip_preserves_status(tmp_path: Path) -> None:
    """v2 notes carry their status across read+write."""
    root = _copy_fixture("v2-with-status", tmp_path)
    v = Vault(root)
    notes_dir = root / "notes"
    for f in notes_dir.rglob("*.md"):
        n = Note.from_file(f)
        original_status = n.status
        assert original_status in NOTE_STATUSES
        v.write_note(n)
        re_read = Note.from_file(f)
        assert re_read.status == original_status, (
            f"{f}: status flipped from {original_status} to {re_read.status}"
        )


def test_v1_with_trash_restore_uses_trashed_from(tmp_path: Path) -> None:
    """v1 trash entries carry `trashed_from`; restore must respect it."""
    root = _copy_fixture("v1-with-trash", tmp_path)
    v = Vault(root)
    trash_dir = root / "notes" / ".trash"
    trashed_files = list(trash_dir.glob("*.md"))
    assert trashed_files, "fixture must contain at least one trashed note"
    for tf in trashed_files:
        n_pre = Note.from_file(tf)
        target_folder = n_pre.trashed_from
        if not target_folder:
            continue
        restored_path = v.restore_note(tf)
        assert restored_path.parent.name == target_folder, (
            f"restored to {restored_path.parent.name!r}, expected {target_folder!r}"
        )


def test_no_fixture_pretends_to_be_newer_than_current() -> None:
    """Sanity guard: a fixture must not claim a schema_version higher
    than the current code understands. Otherwise the regression suite
    is pinning us to a version we can't actually emit."""
    for name in _all_fixtures():
        notes_dir = FIXTURES_ROOT / name / "notes"
        if not notes_dir.exists():
            continue
        for f in notes_dir.rglob("*.md"):
            n = Note.from_file(f)
            assert n.schema_version <= NOTE_SCHEMA_VERSION, (
                f"{f}: claims schema_version={n.schema_version} "
                f"but current code is at {NOTE_SCHEMA_VERSION}"
            )
