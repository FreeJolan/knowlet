"""Sync v2 freshness probe tests.

The probe is the non-blocking part of realtime sync: it asks Drive
whether anything relevant changed, but it does not pull, merge, or advance
the cursor until the blocking sync gate runs.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from knowlet.core.sync.changes import DriveChange
from knowlet.core.sync.freshness import check_sync_freshness, mark_freshness_synced
from knowlet.core.sync.push import drive_appdata_name
from knowlet.core.sync.state import FileState, SyncStateStore


def test_backup_mode_skips_remote_probe(tmp_path: Path) -> None:
    store = SyncStateStore(tmp_path)
    try:
        store.set_sync_mode("backup")
        report = check_sync_freshness(
            state_store=store,
            client_factory=lambda: MagicMock(),
        )
    finally:
        store.close()

    assert report.state == "backup"
    assert report.requires_sync is False


def test_realtime_without_token_requires_initial_blocking_sync(tmp_path: Path) -> None:
    store = SyncStateStore(tmp_path)
    try:
        report = check_sync_freshness(
            state_store=store,
            client_factory=lambda: MagicMock(),
        )
    finally:
        store.close()

    assert report.mode == "realtime"
    assert report.state == "needs_sync"
    assert report.reason == "uninitialized"
    assert report.requires_sync is True


def test_no_relevant_remote_changes_does_not_block_or_advance_token(tmp_path: Path) -> None:
    store = SyncStateStore(tmp_path)
    try:
        store.set_start_page_token("tok-1")
        store.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id="01NOTE",
                drive_file_id="drive-note",
                last_known_etag="rev-2",
                last_synced_at="2026-05-30T00:00:00Z",
                dirty=False,
            )
        )
        changes = [
            DriveChange(
                file_id="heartbeat",
                removed=False,
                trashed=False,
                file={"name": "device.heartbeat.json", "headRevisionId": "hb-1"},
            ),
            DriveChange(
                file_id="drive-note",
                removed=False,
                trashed=False,
                file={"name": "01NOTE.md", "headRevisionId": "rev-2"},
            ),
        ]
        with patch(
            "knowlet.core.sync.freshness.list_all_changes",
            return_value=(changes, "tok-2"),
        ):
            report = check_sync_freshness(
                state_store=store,
                client_factory=lambda: MagicMock(),
            )
        assert store.start_page_token() == "tok-1"
    finally:
        store.close()

    assert report.state == "up_to_date"
    assert report.requires_sync is False
    assert report.changed_count == 0


def test_relevant_remote_change_requires_blocking_sync_without_advancing_token(
    tmp_path: Path,
) -> None:
    store = SyncStateStore(tmp_path)
    try:
        store.set_start_page_token("tok-1")
        changes = [
            DriveChange(
                file_id="remote-new",
                removed=False,
                trashed=False,
                file={
                    "name": drive_appdata_name("note", "01REMOTE.md", vault_root=tmp_path),
                    "headRevisionId": "rev-1",
                },
            )
        ]
        with patch(
            "knowlet.core.sync.freshness.list_all_changes",
            return_value=(changes, "tok-2"),
        ):
            report = check_sync_freshness(
                state_store=store,
                client_factory=lambda: MagicMock(),
            )
        assert store.start_page_token() == "tok-1"
    finally:
        store.close()

    assert report.state == "needs_sync"
    assert report.reason == "remote_changes"
    assert report.requires_sync is True
    assert report.changed_count == 1
    assert report.next_start_page_token == "tok-2"


def test_other_vault_remote_change_is_ignored_for_realtime_freshness(
    tmp_path: Path,
) -> None:
    current = tmp_path / "current"
    other = tmp_path / "other"
    current.mkdir()
    other.mkdir()
    store = SyncStateStore(current)
    try:
        store.set_start_page_token("tok-1")
        other_name = drive_appdata_name("note", "01OTHER.md", vault_root=other)
        changes = [
            DriveChange(
                file_id="drive-other",
                removed=False,
                trashed=False,
                file={
                    "name": other_name,
                    "headRevisionId": "rev-other",
                },
            )
        ]
        with patch(
            "knowlet.core.sync.freshness.list_all_changes",
            return_value=(changes, "tok-2"),
        ):
            report = check_sync_freshness(
                state_store=store,
                client_factory=lambda: object(),
            )

        assert report.state == "up_to_date"
        assert report.requires_sync is False
        assert report.changed_count == 0
    finally:
        store.close()


def test_mark_freshness_synced_bootstraps_cursor_to_now(tmp_path: Path) -> None:
    store = SyncStateStore(tmp_path)
    try:
        with patch(
            "knowlet.core.sync.freshness.get_initial_start_page_token",
            return_value="tok-now",
        ):
            mark_freshness_synced(
                state_store=store,
                client_factory=lambda: MagicMock(),
            )
        assert store.start_page_token() == "tok-now"
    finally:
        store.close()
