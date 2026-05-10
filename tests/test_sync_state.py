"""Phase 2 E Slice 5.B — sync_state.sqlite (ADR-0027)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from knowlet.core.sync.state import (
    SYNC_STATE_SCHEMA_VERSION,
    FileState,
    SyncStateStore,
    sync_state_db_path,
)


# ----------------------------------------------------- lifecycle


def test_db_path_default(tmp_path: Path) -> None:
    assert (
        sync_state_db_path(tmp_path)
        == tmp_path / ".knowlet" / "sync_state.sqlite"
    )


def test_first_open_creates_db(tmp_path: Path) -> None:
    store = SyncStateStore(tmp_path)
    try:
        # Touching the device_id triggers connect.
        _ = store.device_id()
        assert sync_state_db_path(tmp_path).exists()
    finally:
        store.close()


def test_schema_version_persisted(tmp_path: Path) -> None:
    store = SyncStateStore(tmp_path)
    store.device_id()
    store.close()
    # Re-open — schema_version handshake must not crash.
    store2 = SyncStateStore(tmp_path)
    try:
        store2.device_id()
    finally:
        store2.close()
    # Tamper: future schema_version → must raise.
    conn = sqlite3.connect(sync_state_db_path(tmp_path))
    conn.execute(
        "UPDATE meta SET value=? WHERE key='schema_version'",
        (str(SYNC_STATE_SCHEMA_VERSION + 5),),
    )
    conn.commit()
    conn.close()
    store3 = SyncStateStore(tmp_path)
    with pytest.raises(RuntimeError, match="schema_version"):
        store3.device_id()
    store3.close()


# ----------------------------------------------------- device_id


def test_device_id_stable_across_calls(tmp_path: Path) -> None:
    store = SyncStateStore(tmp_path)
    try:
        a = store.device_id()
        b = store.device_id()
        assert a == b
        assert len(a) > 10  # ULID is 26 chars
    finally:
        store.close()


def test_device_id_persists_across_reopens(tmp_path: Path) -> None:
    store = SyncStateStore(tmp_path)
    a = store.device_id()
    store.close()
    store2 = SyncStateStore(tmp_path)
    try:
        b = store2.device_id()
        assert a == b
    finally:
        store2.close()


def test_device_label_defaults_to_hostname(tmp_path: Path) -> None:
    store = SyncStateStore(tmp_path)
    try:
        label = store.device_label()
        assert label  # non-empty
        # Stable on second call.
        assert store.device_label() == label
    finally:
        store.close()


# ----------------------------------------------------- start_page_token


def test_sync_mode_default_is_auto(tmp_path: Path) -> None:
    store = SyncStateStore(tmp_path)
    try:
        assert store.sync_mode() == "auto"
    finally:
        store.close()


def test_sync_mode_round_trip(tmp_path: Path) -> None:
    store = SyncStateStore(tmp_path)
    try:
        store.set_sync_mode("strict")
        assert store.sync_mode() == "strict"
        store.set_sync_mode("lax")
        assert store.sync_mode() == "lax"
        store.set_sync_mode("auto")
        assert store.sync_mode() == "auto"
    finally:
        store.close()


def test_sync_mode_rejects_invalid(tmp_path: Path) -> None:
    import pytest

    store = SyncStateStore(tmp_path)
    try:
        with pytest.raises(ValueError):
            store.set_sync_mode("paranoid")
        # Bogus value never written → still default.
        assert store.sync_mode() == "auto"
    finally:
        store.close()


def test_start_page_token_round_trip(tmp_path: Path) -> None:
    store = SyncStateStore(tmp_path)
    try:
        assert store.start_page_token() is None
        store.set_start_page_token("123abc")
        assert store.start_page_token() == "123abc"
        # Overwrite.
        store.set_start_page_token("456def")
        assert store.start_page_token() == "456def"
    finally:
        store.close()


# ----------------------------------------------------- file_state


def test_file_state_round_trip(tmp_path: Path) -> None:
    store = SyncStateStore(tmp_path)
    try:
        assert store.get_file_state("note", "01ABC") is None
        s = FileState(
            entity_type="note",
            entity_id="01ABC",
            drive_file_id="drive-fid-1",
            last_known_etag="etag-v1",
            last_synced_at="2026-05-10T12:00:00Z",
            dirty=False,
        )
        store.upsert_file_state(s)
        loaded = store.get_file_state("note", "01ABC")
        assert loaded == s
        # Update.
        s2 = FileState(
            entity_type="note",
            entity_id="01ABC",
            drive_file_id="drive-fid-1",
            last_known_etag="etag-v2",
            last_synced_at="2026-05-10T13:00:00Z",
            dirty=True,
        )
        store.upsert_file_state(s2)
        assert store.get_file_state("note", "01ABC") == s2
    finally:
        store.close()


def test_list_dirty_filters(tmp_path: Path) -> None:
    store = SyncStateStore(tmp_path)
    try:
        store.upsert_file_state(
            FileState("note", "a", None, None, None, False)
        )
        store.upsert_file_state(
            FileState("note", "b", None, None, None, True)
        )
        store.upsert_file_state(
            FileState("note", "c", None, None, None, True)
        )
        ids = {s.entity_id for s in store.list_dirty()}
        assert ids == {"b", "c"}
    finally:
        store.close()


def test_count_files(tmp_path: Path) -> None:
    store = SyncStateStore(tmp_path)
    try:
        assert store.count_files() == 0
        store.upsert_file_state(
            FileState("note", "x", None, None, None, False)
        )
        assert store.count_files() == 1
    finally:
        store.close()


# ----------------------------------------------------- clear (disconnect)


def test_clear_preserves_device_id(tmp_path: Path) -> None:
    store = SyncStateStore(tmp_path)
    try:
        original_id = store.device_id()
        original_label = store.device_label()
        store.set_start_page_token("token-xyz")
        store.upsert_file_state(
            FileState("note", "a", "fid", "etag", None, False)
        )
        assert store.start_page_token() == "token-xyz"
        assert store.count_files() == 1

        store.clear()

        # device_id + label survive...
        assert store.device_id() == original_id
        assert store.device_label() == original_label
        # ...but start_page_token + file_state are gone.
        assert store.start_page_token() is None
        assert store.count_files() == 0
    finally:
        store.close()
