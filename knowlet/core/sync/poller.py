"""Phase 2 E Slice 5.D — background poller for Drive Changes (ADR-0027).

Runs as a long-lived asyncio task started by the FastAPI lifespan.
Every ``interval_s`` seconds it asks Drive what's changed since the
last cursor and stamps any matching local notes as "remote-changed
since you last looked". The web layer reads that state via
``/api/sync/notifications`` and the frontend renders a banner.

Why keep state in memory rather than persisting to sync_state:

- The whole point is "did anything happen between page-load and
  now?" — that's a runtime question, not a durable one.
- Server restart simply re-bootstraps the cursor and the next poll
  rediscovers anything still ahead of our last sync. No data lost.
- Avoids a sync_state schema bump for what's effectively a cache.

Lifecycle:

- ``start()`` schedules the loop; non-blocking.
- The loop is resilient: missing creds, network blips, scope errors,
  and Drive 5xxs all just back off and retry. Any of those failure
  modes leaving the loop dead would silently break notifications
  for the rest of the session — far worse than an extra log line.
- ``stop()`` cancels + awaits the task; safe to call from
  FastAPI lifespan exit.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from knowlet.core.note import now_iso

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RemoteChangeNotification:
    """One row in the in-memory pending-notifications dict.

    `note_id` is the local Note ULID we mapped this Drive change
    to via sync_state.file_state. `drive_file_id` is recorded so
    the frontend can deep-link if needed later.
    """

    note_id: str
    drive_file_id: str
    detected_at: str
    new_revision: str | None
    drive_file_name: str | None
    removed: bool  # True if Drive reports the file is gone (delete/trash)


class SyncPoller:
    """Single instance per running server. Owns one asyncio task
    and one in-memory pending-notifications dict keyed by Note id.
    """

    def __init__(
        self,
        vault_root: Path,
        *,
        interval_s: float = 30.0,
        # Cap on how often we hit Drive when actively-failing. Without
        # this, OAuth failure loops would keep beating the network at
        # the configured interval. We back off up to 5 min on errors.
        max_backoff_s: float = 300.0,
    ) -> None:
        self.vault_root = vault_root
        self.interval_s = interval_s
        self.max_backoff_s = max_backoff_s
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._pending: dict[str, RemoteChangeNotification] = {}
        # Track whether the last cycle succeeded — exposed via API so
        # the frontend can warn "polling failing — last success at X".
        self._last_success_at: str | None = None
        self._last_error: str | None = None

    # --------------------------------------------------- lifecycle

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="sync-poller")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    # --------------------------------------------------- public reads

    def pending_notifications(self) -> list[RemoteChangeNotification]:
        return list(self._pending.values())

    def clear(self, note_id: str) -> bool:
        """Used when the user has acknowledged / resolved the change.
        Returns True if there was a notification to clear."""
        return self._pending.pop(note_id, None) is not None

    def health(self) -> dict[str, Any]:
        return {
            "running": self._task is not None and not self._task.done(),
            "interval_s": self.interval_s,
            "last_success_at": self._last_success_at,
            "last_error": self._last_error,
            "pending_count": len(self._pending),
        }

    # --------------------------------------------------- loop body

    async def _loop(self) -> None:
        backoff = self.interval_s
        while not self._stop_event.is_set():
            try:
                worked = await asyncio.to_thread(self._tick)
                if worked:
                    backoff = self.interval_s  # reset
                    self._last_success_at = now_iso()
                    self._last_error = None
            except Exception as exc:  # noqa: BLE001
                self._last_error = repr(exc)
                # Exponential-ish backoff capped at max_backoff_s.
                backoff = min(backoff * 2, self.max_backoff_s)
                logger.warning(
                    "sync poller cycle failed (next retry in %ss): %s",
                    backoff,
                    exc,
                )
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=backoff
                )
            except asyncio.TimeoutError:
                pass

    def _tick(self) -> bool:
        """Single poll cycle. Returns True if it actually ran (creds
        present + scope OK + cursor available). Synchronous because
        googleapiclient is sync; the loop runs us via ``to_thread``."""
        from knowlet.core.sync.credentials import (
            credentials_path,
            load_credentials,
        )
        from knowlet.core.sync.changes import (
            get_initial_start_page_token,
            list_all_changes,
        )
        from knowlet.core.sync.drive_client import DriveClient
        from knowlet.core.sync.oauth import (
            ScopeUpgradeRequiredError,
            verify_scope,
        )
        from knowlet.core.sync.state import SyncStateStore

        creds_path = credentials_path(self.vault_root)
        creds = load_credentials(creds_path)
        if creds is None:
            # Not connected yet — skip silently; user will start
            # noticing notifications after `sync connect`.
            return False
        try:
            verify_scope(creds)
        except ScopeUpgradeRequiredError as exc:
            self._last_error = f"scope upgrade needed: {exc.missing}"
            return False

        client = DriveClient(creds)
        state = SyncStateStore(self.vault_root)
        try:
            cursor = state.start_page_token()
            if cursor is None:
                # First-time bootstrap — capture token, no replay.
                cursor = get_initial_start_page_token(client)
                state.set_start_page_token(cursor)
                return True
            changes, new_token = list_all_changes(
                client, page_token=cursor
            )
            state.set_start_page_token(new_token)
            # Build a Drive-file-id → Note-id map from sync_state so
            # we can attribute changes back to local notes.
            id_map: dict[str, str] = {}
            for entry in self._iter_file_state(state):
                if entry.drive_file_id:
                    id_map[entry.drive_file_id] = entry.entity_id
            for change in changes:
                note_id = id_map.get(change.file_id)
                if not note_id:
                    # Drive change for a file knowlet doesn't track
                    # (corrupt sync_state, race during the very
                    # first push, etc.) — skip rather than guess.
                    continue
                self._pending[note_id] = RemoteChangeNotification(
                    note_id=note_id,
                    drive_file_id=change.file_id,
                    detected_at=now_iso(),
                    new_revision=(change.file or {}).get("headRevisionId"),
                    drive_file_name=(change.file or {}).get("name"),
                    removed=change.removed or change.trashed,
                )
        finally:
            state.close()
        return True

    @staticmethod
    def _iter_file_state(state: Any) -> list[Any]:
        """Yield every file_state row. SyncStateStore.list_all_files
        doesn't exist yet (sync surface has stayed minimal); we read
        directly. Keeps this private so the sync_state public API
        stays narrow."""
        conn = state._connect()  # noqa: SLF001
        with state._lock:  # noqa: SLF001
            rows = conn.execute(
                "SELECT entity_type, entity_id, drive_file_id, "
                "last_known_etag, last_synced_at, dirty "
                "FROM file_state"
            ).fetchall()
        from knowlet.core.sync.state import FileState

        return [
            FileState(
                entity_type=r[0],
                entity_id=r[1],
                drive_file_id=r[2],
                last_known_etag=r[3],
                last_synced_at=r[4],
                dirty=bool(r[5]),
            )
            for r in rows
        ]
