"""Tests for vault snapshot / restore (data safety net).

The CLI commands shell out via typer; we test the core copy + skip
behavior through the helper functions and a typer CliRunner end-to-end.
"""

from pathlib import Path

import typer.testing

from knowlet.cli.vault import _SNAPSHOT_SKIP, app as vault_app
from knowlet.core.note import Note, new_id
from knowlet.core.vault import Vault


runner = typer.testing.CliRunner()


def _populate_vault(tmp_path: Path) -> Vault:
    """Create a minimal vault with one note + one fake conversation."""
    v = Vault(tmp_path)
    v.init_layout()
    n = Note(id=new_id(), title="hello", body="body content")
    v.write_note(n)
    # A fake conversation file so we test that auxiliary state is included.
    (v.conversations_dir / "01HXFAKE.json").write_text(
        '{"id": "01HXFAKE", "history": []}', encoding="utf-8"
    )
    # A fake index.sqlite — should be EXCLUDED from snapshots.
    (v.state_dir / "index.sqlite").write_text("not a real db", encoding="utf-8")
    # A fake config — should be INCLUDED.
    (v.state_dir / "config.toml").write_text("[llm]\nmodel='x'\n", encoding="utf-8")
    return v


def test_snapshot_creates_dir_with_expected_contents(tmp_path: Path, monkeypatch):
    v = _populate_vault(tmp_path)
    monkeypatch.setenv("KNOWLET_VAULT", str(tmp_path))

    result = runner.invoke(vault_app, ["snapshot"])
    assert result.exit_code == 0, result.output

    snap_root = v.state_dir / "snapshots"
    snaps = list(snap_root.iterdir())
    assert len(snaps) == 1
    snap = snaps[0]

    # Notes copied over
    assert (snap / "notes").exists()
    assert any((snap / "notes").glob("*.md"))
    # Conversation copied
    assert (snap / ".knowlet" / "conversations" / "01HXFAKE.json").exists()
    # Config copied
    assert (snap / ".knowlet" / "config.toml").exists()


def test_snapshot_excludes_index_and_recursive_snapshots(tmp_path: Path, monkeypatch):
    v = _populate_vault(tmp_path)
    monkeypatch.setenv("KNOWLET_VAULT", str(tmp_path))

    runner.invoke(vault_app, ["snapshot"])
    snap_root = v.state_dir / "snapshots"
    snap = next(snap_root.iterdir())

    # Index NOT copied
    assert not (snap / ".knowlet" / "index.sqlite").exists()
    # Snapshot dir itself NOT recursively copied
    assert not (snap / ".knowlet" / "snapshots").exists()


def test_snapshot_label_appears_in_dir_name(tmp_path: Path, monkeypatch):
    _populate_vault(tmp_path)
    monkeypatch.setenv("KNOWLET_VAULT", str(tmp_path))

    result = runner.invoke(vault_app, ["snapshot", "--label", "pre-m8-upgrade"])
    assert result.exit_code == 0
    snap_root = tmp_path / ".knowlet" / "snapshots"
    snap = next(snap_root.iterdir())
    assert snap.name.endswith("-pre-m8-upgrade")


def test_list_snapshots_empty_vault(tmp_path: Path, monkeypatch):
    Vault(tmp_path).init_layout()
    monkeypatch.setenv("KNOWLET_VAULT", str(tmp_path))
    result = runner.invoke(vault_app, ["list-snapshots"])
    assert result.exit_code == 0
    assert "no snapshots" in result.output.lower()


def test_list_snapshots_after_snapshot(tmp_path: Path, monkeypatch):
    _populate_vault(tmp_path)
    monkeypatch.setenv("KNOWLET_VAULT", str(tmp_path))
    runner.invoke(vault_app, ["snapshot", "--label", "first"])
    runner.invoke(vault_app, ["snapshot", "--label", "second"])
    result = runner.invoke(vault_app, ["list-snapshots"])
    assert result.exit_code == 0
    assert "first" in result.output
    assert "second" in result.output


def test_restore_overwrites_with_safety_pre_snapshot(tmp_path: Path, monkeypatch):
    """Restore creates a `<ts>-pre-restore` snapshot before overwriting."""
    v = _populate_vault(tmp_path)
    monkeypatch.setenv("KNOWLET_VAULT", str(tmp_path))

    # Snapshot the initial state
    runner.invoke(vault_app, ["snapshot", "--label", "v1"])

    # Modify a note (simulate "broken" state we want to revert from)
    note_path = next(v.notes_dir.glob("*.md"))
    note_path.write_text("# oops\n\nI broke this", encoding="utf-8")

    # Restore back to v1
    snap_root = v.state_dir / "snapshots"
    v1_snap = next(p for p in snap_root.iterdir() if p.name.endswith("-v1"))
    result = runner.invoke(vault_app, ["restore-snapshot", v1_snap.name, "--yes"])
    assert result.exit_code == 0, result.output

    # Pre-restore snapshot should exist
    pre_snaps = [p for p in snap_root.iterdir() if "pre-restore" in p.name]
    assert len(pre_snaps) == 1

    # The original note's content should be back (intact frontmatter, not "I broke this")
    restored_paths = list(v.notes_dir.glob("*.md"))
    assert len(restored_paths) == 1
    content = restored_paths[0].read_text(encoding="utf-8")
    assert "I broke this" not in content
    assert "title:" in content  # frontmatter intact

    # Index is wiped so next reindex rebuilds clean
    assert not (v.state_dir / "index.sqlite").exists()


def test_restore_ambiguous_prefix_errors_out(tmp_path: Path, monkeypatch):
    _populate_vault(tmp_path)
    monkeypatch.setenv("KNOWLET_VAULT", str(tmp_path))
    runner.invoke(vault_app, ["snapshot", "--label", "alpha"])
    runner.invoke(vault_app, ["snapshot", "--label", "beta"])
    snap_root = tmp_path / ".knowlet" / "snapshots"
    # Both snapshots start with "20" (year prefix); use that to make ambiguous.
    result = runner.invoke(vault_app, ["restore-snapshot", "20", "--yes"])
    assert result.exit_code == 2  # ambiguous


def test_snapshot_skip_set_includes_index_and_self():
    """Catch silent drift: the skip set must always exclude the snapshot
    dir + rebuildable indexes. Anything else risks data loss or runaway
    snapshot recursion."""
    assert "snapshots" in _SNAPSHOT_SKIP
    assert "index.sqlite" in _SNAPSHOT_SKIP
    assert "vectors.sqlite" in _SNAPSHOT_SKIP


def test_snapshot_skips_sqlite_wal_sidecars(tmp_path: Path, monkeypatch):
    """SQLite WAL mode produces `<db>-shm` and `<db>-wal` sidecar files
    holding in-flight transactions. They must be excluded from snapshots
    too — copying mid-transaction state into a snapshot is worse than
    just rebuilding from scratch on restore."""
    v = _populate_vault(tmp_path)
    # Simulate WAL sidecars
    (v.state_dir / "index.sqlite-shm").write_text("shm", encoding="utf-8")
    (v.state_dir / "index.sqlite-wal").write_text("wal", encoding="utf-8")
    monkeypatch.setenv("KNOWLET_VAULT", str(tmp_path))
    runner.invoke(vault_app, ["snapshot"])

    snap = next((v.state_dir / "snapshots").iterdir())
    assert not (snap / ".knowlet" / "index.sqlite-shm").exists()
    assert not (snap / ".knowlet" / "index.sqlite-wal").exists()
