"""Phase 2 E Slice 5.D.3.A — state-reconciliation poller (ADR-0027).

Replaces 5.D's transient-event tests with state-comparison ones. The
poller no longer caches "what just happened on Drive"; it reconciles
sync_state.file_state against a bulk fetch of current Drive metadata
each cycle. Mutations (resolve / snooze / accept) update sync_state
and the next tick reflects them automatically.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from knowlet.core.note import new_id
from knowlet.core.sync.credentials import (
    SyncCredentials,
    save_credentials,
)
from knowlet.core.sync.oauth import SCOPES
from knowlet.core.sync.poller import SyncPoller
from knowlet.core.sync.state import FileState, SyncStateStore


def _seed_creds(vault_root: Path) -> SyncCredentials:
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


def _patch_drive(revs: dict[str, str | None]):
    """Patches DriveClient + list_appdata_revisions so _tick runs
    without touching Google."""
    from contextlib import ExitStack
    from unittest.mock import MagicMock

    stack = ExitStack()
    fake_service = MagicMock()
    fake_client = MagicMock()
    fake_client.service.return_value = fake_service
    # Patch at the source modules — _tick imports these lazily, so
    # patching `knowlet.core.sync.poller.X` doesn't work (X never
    # appears as an attribute on the poller module).
    stack.enter_context(
        patch(
            "knowlet.core.sync.drive_client.DriveClient",
            return_value=fake_client,
        )
    )
    stack.enter_context(
        patch(
            "knowlet.core.sync.files.list_appdata_revisions",
            return_value=revs,
        )
    )
    return stack


# ----------------------------------------------------- gates


def test_tick_skips_when_not_connected(tmp_path: Path) -> None:
    poller = SyncPoller(tmp_path)
    # No creds file → tick returns False, cache empty.
    with patch(
        "knowlet.core.sync.files.list_appdata_revisions"
    ) as drive_call:
        assert poller._tick() is False  # noqa: SLF001
    drive_call.assert_not_called()
    assert poller.pending_notifications() == []


def test_tick_skips_with_stale_scope(tmp_path: Path) -> None:
    """Token has wrong scope → tick exits cleanly + records the
    error for /api/sync/health, doesn't call Drive."""
    from knowlet.core.sync.credentials import credentials_path

    save_credentials(
        credentials_path(tmp_path),
        SyncCredentials(
            token={"scopes": ["https://www.googleapis.com/auth/drive.file"]}
        ),
    )
    poller = SyncPoller(tmp_path)
    with patch(
        "knowlet.core.sync.files.list_appdata_revisions"
    ) as drive_call:
        ok = poller._tick()  # noqa: SLF001
    assert ok is False
    drive_call.assert_not_called()
    assert "scope upgrade" in (poller._last_error or "")  # noqa: SLF001


# ----------------------------------------------------- in-sync


def test_tick_emits_no_pending_when_local_matches_drive(
    tmp_path: Path,
) -> None:
    """The whole point of state-reconciliation: if last_known equals
    current, no conflict. Even if there were Drive Changes events
    in the past for this file, we don't surface them."""
    _seed_creds(tmp_path)
    note_id = new_id()
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note_id,
                drive_file_id="DRIVE-FID-1",
                last_known_etag="rev-MINE",
                last_synced_at="2026-05-10T00:00:00Z",
                dirty=False,
            )
        )
    finally:
        state.close()
    poller = SyncPoller(tmp_path)
    with _patch_drive({"DRIVE-FID-1": "rev-MINE"}):
        assert poller._tick() is True  # noqa: SLF001
    assert poller.pending_notifications() == []


# ----------------------------------------------------- divergence


def test_tick_records_diverged_files(tmp_path: Path) -> None:
    _seed_creds(tmp_path)
    note_id = new_id()
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note_id,
                drive_file_id="DRIVE-FID-1",
                last_known_etag="rev-MINE",
                last_synced_at="2026-05-10T00:00:00Z",
                dirty=False,
            )
        )
    finally:
        state.close()
    poller = SyncPoller(tmp_path)
    with _patch_drive({"DRIVE-FID-1": "rev-NEW"}):
        assert poller._tick() is True  # noqa: SLF001
    pending = poller.pending_notifications()
    assert len(pending) == 1
    assert pending[0].note_id == note_id
    assert pending[0].new_revision == "rev-NEW"
    assert pending[0].removed is False


def test_tick_marks_files_removed_from_drive(tmp_path: Path) -> None:
    """Tracked file isn't in Drive's listing → treated as removed
    (user / other device deleted it on remote)."""
    _seed_creds(tmp_path)
    note_id = new_id()
    state = SyncStateStore(tmp_path)
    try:
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
    # Drive's listing returns {} — our file isn't there anymore.
    with _patch_drive({}):
        poller._tick()  # noqa: SLF001
    pending = poller.pending_notifications()
    assert len(pending) == 1
    assert pending[0].removed is True


# ----------------------------------------------------- snooze


def test_tick_filters_snoozed_conflicts(tmp_path: Path) -> None:
    """If file_state.dismissed_until is in the future, the conflict
    is hidden until then. ADR-0027 §UX: dismiss is snooze, not
    permanent silence — but during the snooze window we DO honor
    the user's wish for quiet."""
    _seed_creds(tmp_path)
    note_id = new_id()
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note_id,
                drive_file_id="DRIVE-FID-1",
                last_known_etag="rev-MINE",
                last_synced_at="x",
                dirty=False,
                dismissed_until="2099-01-01T00:00:00Z",  # far future
            )
        )
    finally:
        state.close()
    poller = SyncPoller(tmp_path)
    with _patch_drive({"DRIVE-FID-1": "rev-NEW"}):
        poller._tick()  # noqa: SLF001
    assert poller.pending_notifications() == []


def test_tick_resurfaces_conflict_after_snooze_expires(tmp_path: Path) -> None:
    """Past-due dismissed_until = snooze expired = conflict is back.
    This is the central data-safety property of 5.D.3.A: dismissals
    are temporary, not permanent."""
    _seed_creds(tmp_path)
    note_id = new_id()
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note_id,
                drive_file_id="DRIVE-FID-1",
                last_known_etag="rev-MINE",
                last_synced_at="x",
                dirty=False,
                dismissed_until="1970-01-01T00:00:00Z",  # past
            )
        )
    finally:
        state.close()
    poller = SyncPoller(tmp_path)
    with _patch_drive({"DRIVE-FID-1": "rev-NEW"}):
        poller._tick()  # noqa: SLF001
    assert len(poller.pending_notifications()) == 1


# ----------------------------------------------------- async lifecycle


def test_start_and_stop_cleanly(tmp_path: Path) -> None:
    async def go() -> None:
        poller = SyncPoller(tmp_path, interval_s=0.05)
        await poller.start()
        await asyncio.sleep(0.15)
        assert poller.health()["running"] is True
        await poller.stop()
        assert poller.health()["running"] is False

    asyncio.run(go())


def test_loop_keeps_going_when_tick_errors(tmp_path: Path) -> None:
    async def go() -> None:
        poller = SyncPoller(tmp_path, interval_s=0.05, max_backoff_s=0.1)
        with patch.object(poller, "_tick", side_effect=RuntimeError("boom")):
            await poller.start()
            await asyncio.sleep(0.2)
            assert poller.health()["running"] is True
            assert "boom" in (poller._last_error or "")  # noqa: SLF001
            await poller.stop()

    asyncio.run(go())
