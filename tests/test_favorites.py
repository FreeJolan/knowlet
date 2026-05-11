"""Phase 2 D B1 — FavoritesStore unit tests.

Endpoint-level tests live in test_server_favorites.py (HTTP path).
"""

from __future__ import annotations

import json
from pathlib import Path

from knowlet.core.favorites import FavoritesStore


def test_empty_when_file_missing(tmp_path: Path) -> None:
    store = FavoritesStore(vault_root=tmp_path)
    assert store.list() == []
    # No file created just by reading.
    assert not store.path.exists()


def test_add_creates_file_and_appends(tmp_path: Path) -> None:
    store = FavoritesStore(vault_root=tmp_path)
    store.add("01HX1")
    store.add("01HX2")
    assert store.list() == ["01HX1", "01HX2"]
    # Persisted on disk in the expected shape.
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload == {"ids": ["01HX1", "01HX2"]}


def test_add_is_idempotent(tmp_path: Path) -> None:
    store = FavoritesStore(vault_root=tmp_path)
    store.add("01HX1")
    store.add("01HX1")
    store.add("01HX1")
    assert store.list() == ["01HX1"]


def test_remove_drops_target_and_is_idempotent(tmp_path: Path) -> None:
    store = FavoritesStore(vault_root=tmp_path)
    store.add("a")
    store.add("b")
    store.add("c")
    store.remove("b")
    assert store.list() == ["a", "c"]
    store.remove("b")  # idempotent
    assert store.list() == ["a", "c"]
    store.remove("does-not-exist")  # idempotent
    assert store.list() == ["a", "c"]


def test_contains_reflects_current_state(tmp_path: Path) -> None:
    store = FavoritesStore(vault_root=tmp_path)
    assert not store.contains("a")
    store.add("a")
    assert store.contains("a")
    store.remove("a")
    assert not store.contains("a")


def test_prune_drops_dead_ids_and_rewrites(tmp_path: Path) -> None:
    """When the caller passes existing_ids that doesn't include a
    stored favorite, the store drops it AND rewrites the file."""
    store = FavoritesStore(vault_root=tmp_path)
    store.add("alive-1")
    store.add("dead-1")
    store.add("alive-2")
    store.add("dead-2")

    result = store.list(existing_ids={"alive-1", "alive-2"})
    assert result == ["alive-1", "alive-2"]
    # File was rewritten — re-reading without pruning sees the
    # pruned state.
    assert store.list() == ["alive-1", "alive-2"]


def test_prune_is_skipped_when_existing_ids_is_none(
    tmp_path: Path,
) -> None:
    store = FavoritesStore(vault_root=tmp_path)
    store.add("a")
    store.add("b")
    # No prune → raw on-disk content unchanged.
    assert store.list(existing_ids=None) == ["a", "b"]


def test_malformed_file_returns_empty_without_crashing(
    tmp_path: Path,
) -> None:
    store = FavoritesStore(vault_root=tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("this is not json", encoding="utf-8")
    assert store.list() == []


def test_atomic_write_via_tmp(tmp_path: Path) -> None:
    """Sanity-check that writes go through a tmp file then rename —
    a partially-written favorites.json should never be visible."""
    store = FavoritesStore(vault_root=tmp_path)
    store.add("a")
    # tmp file should not linger after write
    tmp_path_with_suffix = store.path.with_suffix(
        store.path.suffix + ".tmp"
    )
    assert not tmp_path_with_suffix.exists()
