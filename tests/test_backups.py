"""Phase 2 E Slice 4.E — `.knowlet/backups/` (ADR-0018 §4)."""

from __future__ import annotations

import time
from pathlib import Path

from knowlet.core.backups import (
    DEFAULT_KEEP,
    BackupStore,
    backups_dir,
)
from knowlet.core.note import Note, new_id
from knowlet.core.quick_actions import (
    CreateNoteParams,
    QuickAction,
    QuickActionStore,
    new_action_id,
)
from knowlet.core.vault import Vault

# ----------------------------------------------------- store unit tests


def test_create_path_does_not_back_up(tmp_path: Path) -> None:
    """Backup is overwrite-only. A first write has nothing to preserve."""
    store = BackupStore(tmp_path)
    src = tmp_path / "missing.md"
    out = store.backup_before_overwrite("note", "abc", src)
    assert out is None
    assert not backups_dir(tmp_path).exists()


def test_overwrite_path_creates_backup(tmp_path: Path) -> None:
    store = BackupStore(tmp_path)
    src = tmp_path / "01ABC.md"
    src.write_text("v1", encoding="utf-8")
    out = store.backup_before_overwrite("note", "01ABC", src)
    assert out is not None
    assert out.exists()
    assert out.read_text(encoding="utf-8") == "v1"
    # Lives in `.knowlet/backups/note/`.
    assert out.parent == backups_dir(tmp_path) / "note"
    # Filename: 01ABC.<ts>.md
    assert out.name.startswith("01ABC.")
    assert out.name.endswith(".md")


def test_lru_keeps_at_most_default(tmp_path: Path) -> None:
    """Make 6 backups; only the most recent DEFAULT_KEEP survive."""
    store = BackupStore(tmp_path)
    src = tmp_path / "01ABC.md"
    src.write_text("init", encoding="utf-8")
    for i in range(6):
        src.write_text(f"v{i}", encoding="utf-8")
        store.backup_before_overwrite("note", "01ABC", src)
        # Sleep a hair so each call gets a unique second-resolution
        # timestamp in the filename.
        time.sleep(0.02)
    rows = store.list_backups(entity_type="note", entity_id="01ABC")
    assert len(rows) == DEFAULT_KEEP


def test_explicit_keep_overrides_default(tmp_path: Path) -> None:
    store = BackupStore(tmp_path)
    src = tmp_path / "01ABC.md"
    src.write_text("init", encoding="utf-8")
    for i in range(4):
        src.write_text(f"v{i}", encoding="utf-8")
        store.backup_before_overwrite("note", "01ABC", src, keep=2)
        time.sleep(0.02)
    rows = store.list_backups(entity_type="note", entity_id="01ABC")
    assert len(rows) == 2


def test_list_filters_by_entity_and_id(tmp_path: Path) -> None:
    store = BackupStore(tmp_path)
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text("a1", encoding="utf-8")
    b.write_text("b1", encoding="utf-8")
    store.backup_before_overwrite("note", "a", a)
    store.backup_before_overwrite("note", "b", b)
    only_a = store.list_backups(entity_type="note", entity_id="a")
    assert len(only_a) == 1
    assert only_a[0].entity_id == "a"
    only_note = store.list_backups(entity_type="note")
    assert {r.entity_id for r in only_note} == {"a", "b"}


def test_restore_refuses_to_clobber(tmp_path: Path) -> None:
    import pytest

    store = BackupStore(tmp_path)
    src = tmp_path / "01ABC.md"
    src.write_text("v1", encoding="utf-8")
    backup = store.backup_before_overwrite("note", "01ABC", src)
    assert backup is not None
    # `dest` already exists (live file). restore must refuse rather
    # than silently replace it.
    with pytest.raises(FileExistsError):
        store.restore(backup, src)


def test_restore_to_fresh_dest_succeeds(tmp_path: Path) -> None:
    store = BackupStore(tmp_path)
    src = tmp_path / "01ABC.md"
    src.write_text("v1", encoding="utf-8")
    backup = store.backup_before_overwrite("note", "01ABC", src)
    assert backup is not None
    src.unlink()  # Simulate the user moving the live file aside.
    out = store.restore(backup, src)
    assert out.read_text(encoding="utf-8") == "v1"


def test_no_mutation_api_other_than_known(tmp_path: Path) -> None:
    """Append-only-ish: the public surface should expose only
    backup_before_overwrite + queries + restore. No "delete by id"
    surface — pruning is automatic / via the prune CLI."""
    public = {m for m in dir(BackupStore) if not m.startswith("_")}
    forbidden = {"delete", "remove", "drop", "clear", "purge", "wipe"}
    leaks = public & forbidden
    assert not leaks, f"unexpected mutation methods: {leaks}"


# ----------------------------------------------------- Vault hook


def _vault_with_backups(tmp_path: Path) -> tuple[Vault, BackupStore]:
    bs = BackupStore(tmp_path / "v")
    (tmp_path / "v").mkdir()
    v = Vault(tmp_path / "v", backups=bs)
    return v, bs


def test_vault_first_write_no_backup(tmp_path: Path) -> None:
    v, bs = _vault_with_backups(tmp_path)
    v.write_note(Note(id=new_id(), title="x", body="b1"))
    assert bs.list_backups() == []


def test_vault_overwrite_creates_backup(tmp_path: Path) -> None:
    v, bs = _vault_with_backups(tmp_path)
    n = Note(id=new_id(), title="x", body="b1")
    v.write_note(n)
    n.body = "b2"
    v.write_note(n)
    rows = bs.list_backups()
    assert len(rows) == 1
    assert rows[0].entity_type == "note"
    assert rows[0].entity_id == n.id
    # The backup carries the OLD bytes (b1), not the new ones (b2).
    assert "b1" in rows[0].path.read_text(encoding="utf-8")
    assert "b2" not in rows[0].path.read_text(encoding="utf-8")


def test_vault_lru_caps_per_note(tmp_path: Path) -> None:
    v, bs = _vault_with_backups(tmp_path)
    n = Note(id=new_id(), title="x", body="b0")
    v.write_note(n)  # initial create — no backup yet
    for i in range(1, 8):
        n.body = f"b{i}"
        v.write_note(n)
        time.sleep(0.02)
    rows = bs.list_backups(entity_type="note", entity_id=n.id)
    assert len(rows) == DEFAULT_KEEP


def test_vault_backup_failure_does_not_block_save(tmp_path: Path) -> None:
    """If the backup store is broken, the user's save still goes through."""

    class Broken:
        def backup_before_overwrite(self, *_a: object, **_kw: object) -> None:
            raise RuntimeError("backups exploded")

    (tmp_path / "v").mkdir()
    v = Vault(tmp_path / "v", backups=Broken())  # type: ignore[arg-type]
    n = Note(id=new_id(), title="x", body="b1")
    v.write_note(n)
    n.body = "b2"
    # Without the catch in Vault.write_note this would propagate.
    # Vault.write_note already swallows audit failures the same way;
    # we delegate to the store's own try/except for backup.
    # The Broken stub mimics a user-facing `BackupStore` that DID the
    # exception swallowing internally — Vault treats it as None on
    # failure and proceeds. Here we assert the save still works.
    try:
        v.write_note(n)
    except RuntimeError:
        # Backup failures must not propagate; if they do, this test
        # surfaces it as a real bug in production code (we'd then
        # add explicit catching at the Vault layer).
        import pytest

        pytest.fail("backup failure must not propagate into write_note")


def test_quick_actions_save_creates_backup(tmp_path: Path) -> None:
    store = QuickActionStore(vault_root=tmp_path)
    a = QuickAction(
        id=new_action_id(),
        name="v1",
        params=CreateNoteParams(folder="x", title_template="t"),
    )
    store.upsert(a)  # first write → no backup (file didn't exist yet)
    a.name = "v2"
    store.upsert(a)  # overwrite → backup the v1 toml
    rows = BackupStore(tmp_path).list_backups(entity_type="quick-actions")
    assert len(rows) == 1
    text = rows[0].path.read_text(encoding="utf-8")
    assert "v1" in text and "v2" not in text
