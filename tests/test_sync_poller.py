"""Phase 2 E Slice 5.D — background Drive Changes poller (ADR-0027).

The poller is the surface that turns "remote changed mid-edit" from
a surprise (hits at save time) into a banner-able event. The tests
mock all Drive calls; lifecycle (start/stop), the loop's resilience
to errors, and the in-memory pending dict are the load-bearing
contracts.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from knowlet.core.note import new_id
from knowlet.core.sync.changes import DriveChange
from knowlet.core.sync.credentials import (
    SyncCredentials,
    save_credentials,
)
from knowlet.core.sync.oauth import SCOPES
from knowlet.core.sync.poller import SyncPoller
from knowlet.core.sync.state import FileState, SyncStateStore


def _seed_creds(vault_root: Path) -> SyncCredentials:
    """Write a minimal creds file with the build's required scopes
    so verify_scope passes."""
    from knowlet.core.sync.credentials import credentials_path

    creds = SyncCredentials(
        user_email="alice@example.com",
        user_display_name="Alice",
        token={
            "token": "ACCESS",
            "refresh_token": "REFRESH",
            "scopes": list(SCOPES),
            "client_id": "x",
            "client_secret": "y",
            "token_uri": "https://oauth2.googleapis.com/token",
        },
    )
    save_credentials(credentials_path(vault_root), creds)
    return creds


# ----------------------------------------------------- _tick


def test_tick_skips_when_not_connected(tmp_path: Path) -> None:
    """No creds file → tick returns False (False = "didn't actually
    poll"), in-memory state stays empty, no error stored."""
    poller = SyncPoller(tmp_path)
    assert poller._tick() is False  # noqa: SLF001
    assert poller.pending_notifications() == []
    assert poller.health()["last_error"] is None


def test_tick_first_run_bootstraps_cursor(tmp_path: Path) -> None:
    _seed_creds(tmp_path)
    state = SyncStateStore(tmp_path)
    try:
        # No start_page_token yet.
        assert state.start_page_token() is None
    finally:
        state.close()
    poller = SyncPoller(tmp_path)
    with patch(
        "knowlet.core.sync.changes.get_initial_start_page_token",
        return_value="BOOTSTRAP-TOKEN",
    ):
        ok = poller._tick()  # noqa: SLF001
    assert ok is True
    state2 = SyncStateStore(tmp_path)
    try:
        assert state2.start_page_token() == "BOOTSTRAP-TOKEN"
    finally:
        state2.close()


def test_tick_records_pending_notifications(tmp_path: Path) -> None:
    """After bootstrap, the next tick lists Drive changes and
    attributes them to local notes via sync_state.file_state."""
    _seed_creds(tmp_path)
    note_id = new_id()
    drive_id = "DRIVE-FID-1"
    state = SyncStateStore(tmp_path)
    try:
        state.set_start_page_token("OLD-TOKEN")
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note_id,
                drive_file_id=drive_id,
                last_known_etag="rev-1",
                last_synced_at="2026-05-10T00:00:00Z",
                dirty=False,
            )
        )
    finally:
        state.close()

    poller = SyncPoller(tmp_path)
    fake_changes = [
        DriveChange(
            file_id=drive_id,
            removed=False,
            trashed=False,
            file={"name": "alpha.md", "headRevisionId": "rev-NEW"},
        ),
        # An untracked Drive file → must be ignored, not crash.
        DriveChange(
            file_id="UNTRACKED-FID",
            removed=False,
            trashed=False,
            file={"name": "stranger.md"},
        ),
    ]
    with patch(
        "knowlet.core.sync.changes.list_all_changes",
        return_value=(fake_changes, "NEW-TOKEN"),
    ):
        ok = poller._tick()  # noqa: SLF001
    assert ok is True
    pending = poller.pending_notifications()
    assert len(pending) == 1
    assert pending[0].note_id == note_id
    assert pending[0].drive_file_id == drive_id
    assert pending[0].new_revision == "rev-NEW"
    assert pending[0].drive_file_name == "alpha.md"
    assert pending[0].removed is False


def test_tick_marks_removed_changes(tmp_path: Path) -> None:
    _seed_creds(tmp_path)
    note_id = new_id()
    state = SyncStateStore(tmp_path)
    try:
        state.set_start_page_token("OLD-TOKEN")
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note_id,
                drive_file_id="GONE",
                last_known_etag="rev-1",
                last_synced_at="x",
                dirty=False,
            )
        )
    finally:
        state.close()
    poller = SyncPoller(tmp_path)
    with patch(
        "knowlet.core.sync.changes.list_all_changes",
        return_value=(
            [DriveChange(file_id="GONE", removed=True, trashed=False, file=None)],
            "NEW-TOKEN",
        ),
    ):
        poller._tick()  # noqa: SLF001
    pending = poller.pending_notifications()
    assert len(pending) == 1
    assert pending[0].removed is True


def test_clear_drops_notification(tmp_path: Path) -> None:
    _seed_creds(tmp_path)
    note_id = new_id()
    state = SyncStateStore(tmp_path)
    try:
        state.set_start_page_token("X")
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note_id,
                drive_file_id="DRIVE",
                last_known_etag="r",
                last_synced_at="x",
                dirty=False,
            )
        )
    finally:
        state.close()
    poller = SyncPoller(tmp_path)
    with patch(
        "knowlet.core.sync.changes.list_all_changes",
        return_value=(
            [DriveChange(file_id="DRIVE", removed=False, trashed=False, file={})],
            "NEW",
        ),
    ):
        poller._tick()  # noqa: SLF001
    assert len(poller.pending_notifications()) == 1
    assert poller.clear(note_id) is True
    assert poller.pending_notifications() == []
    # Idempotent.
    assert poller.clear(note_id) is False


def test_tick_skips_with_stale_scope(tmp_path: Path) -> None:
    """Token has wrong scope (drive.file instead of drive.appdata)
    → tick exits cleanly + records the error for /api/sync/health."""
    from knowlet.core.sync.credentials import credentials_path

    save_credentials(
        credentials_path(tmp_path),
        SyncCredentials(
            token={"scopes": ["https://www.googleapis.com/auth/drive.file"]}
        ),
    )
    poller = SyncPoller(tmp_path)
    ok = poller._tick()  # noqa: SLF001
    assert ok is False
    assert "scope upgrade" in (poller._last_error or "")  # noqa: SLF001


# ----------------------------------------------------- async lifecycle


def test_start_and_stop_cleanly(tmp_path: Path) -> None:
    """The loop must spin up + tear down without hanging the
    FastAPI lifespan. We use a 0.05s interval to make the test
    snappy; real runs use 30s."""

    async def go() -> None:
        poller = SyncPoller(tmp_path, interval_s=0.05)
        await poller.start()
        await asyncio.sleep(0.15)
        assert poller.health()["running"] is True
        await poller.stop()
        assert poller.health()["running"] is False

    asyncio.run(go())


def test_loop_keeps_going_when_tick_errors(tmp_path: Path) -> None:
    """A broken tick must not kill the loop — we keep retrying with
    backoff. ADR-0027 says the user must always know if polling is
    failing; we never silently die."""

    async def go() -> None:
        poller = SyncPoller(tmp_path, interval_s=0.05, max_backoff_s=0.1)
        with patch.object(poller, "_tick", side_effect=RuntimeError("boom")):
            await poller.start()
            await asyncio.sleep(0.2)
            assert poller.health()["running"] is True
            assert "boom" in (poller._last_error or "")  # noqa: SLF001
            await poller.stop()

    asyncio.run(go())
