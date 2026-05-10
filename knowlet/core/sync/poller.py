"""Phase 2 E Slice 5.D.3.A — state-reconciliation poller (ADR-0027).

Replaces 5.D's transient-Changes-events approach. The old design
read Drive Changes API + cached "what just happened" in an in-memory
dict, then advanced the cursor. Two failure modes that came out of
dogfood:

1. Server restart → cursor advances naturally + the in-memory dict
   is empty → unresolved conflicts disappear from the user's view.
2. User dismisses without resolving → in-memory entry removed →
   no further alerts, even though the actual Drive ↔ local
   divergence is still live.

The fix is conceptual: stop treating "conflict" as an event. It's a
**state** — local sync_state.last_known_etag vs current Drive
headRevisionId. So every poll cycle re-derives the truth from
state comparison; mutations (resolve / snooze / accept) feed back
into state and the next cycle reflects them automatically.

Snooze handling: ``file_state.dismissed_until`` (Slice 5.D.3.A
schema bump) holds an ISO timestamp; conflicts whose snooze hasn't
yet expired are filtered out of notifications. When the user clicks
"dismiss" in the UI we set this to now+24h, so the conflict does
NOT permanently disappear — it just goes quiet for one day.

Lifecycle is unchanged from 5.D: ``start()`` creates an asyncio
task, ``stop()`` cancels + awaits, the loop is resilient to all
common failure modes (no creds / scope mismatch / network blip /
Drive 5xx).
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
    """One pending conflict surfaced to the UI. Now derived from
    state diff, not Drive Changes events."""

    note_id: str
    drive_file_id: str
    detected_at: str
    new_revision: str | None
    drive_file_name: str | None
    removed: bool


class SyncPoller:
    """One instance per running server. Wakes every ``interval_s``;
    on each tick: reconcile sync_state vs Drive metadata, cache the
    resulting list, expose it via ``pending_notifications()``.
    """

    def __init__(
        self,
        vault_root: Path,
        *,
        interval_s: float = 30.0,
        max_backoff_s: float = 300.0,
    ) -> None:
        self.vault_root = vault_root
        self.interval_s = interval_s
        self.max_backoff_s = max_backoff_s
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._cached: list[RemoteChangeNotification] = []
        self._last_success_at: str | None = None
        self._last_error: str | None = None

    # --------------------------------------------------- lifecycle

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop_event = asyncio.Event()
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
        """Snapshot of the most recent reconciliation. Empty list
        when not connected, when reconciliation hasn't run yet, or
        when nothing diverges."""
        return list(self._cached)

    def health(self) -> dict[str, Any]:
        return {
            "running": self._task is not None and not self._task.done(),
            "interval_s": self.interval_s,
            "last_success_at": self._last_success_at,
            "last_error": self._last_error,
            "pending_count": len(self._cached),
        }

    def force_recompute_sync(self) -> None:
        """Synchronous one-shot recompute. Endpoints that mutate
        state (resolve / snooze / accept) call this so the cache
        reflects the change immediately rather than waiting up to
        ``interval_s`` for the next loop iteration. Failures are
        swallowed; next loop tick will retry."""
        try:
            self._tick()
        except Exception as exc:  # noqa: BLE001
            self._last_error = repr(exc)
            logger.warning("force_recompute_sync failed: %s", exc)

    # --------------------------------------------------- loop body

    async def _loop(self) -> None:
        backoff = self.interval_s
        while not self._stop_event.is_set():
            try:
                worked = await asyncio.to_thread(self._tick)
                if worked:
                    backoff = self.interval_s
                    self._last_success_at = now_iso()
                    self._last_error = None
            except Exception as exc:  # noqa: BLE001
                self._last_error = repr(exc)
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
        """Single reconciliation cycle. Returns True if it actually
        ran (creds present + scope OK); False is "skipped, try
        next time"."""
        from knowlet.core.sync.credentials import (
            credentials_path,
            load_credentials,
        )
        from knowlet.core.sync.drive_client import DriveClient
        from knowlet.core.sync.files import list_appdata_revisions
        from knowlet.core.sync.oauth import (
            ScopeUpgradeRequiredError,
            verify_scope,
        )
        from knowlet.core.sync.state import SyncStateStore

        creds = load_credentials(credentials_path(self.vault_root))
        if creds is None:
            self._cached = []
            return False
        try:
            verify_scope(creds)
        except ScopeUpgradeRequiredError as exc:
            self._last_error = f"scope upgrade needed: {exc.missing}"
            self._cached = []
            return False

        client = DriveClient(creds)
        service = client.service()
        # Bulk fetch — one (or rarely two) round trips.
        drive_revisions = list_appdata_revisions(service)
        state = SyncStateStore(self.vault_root)
        try:
            now = now_iso()
            new_pending: list[RemoteChangeNotification] = []
            for row in state.list_all_files():
                if not row.drive_file_id or not row.last_known_etag:
                    continue
                # Snooze filter — user pressed "dismiss = snooze 24h"
                # earlier; honor it until expiry.
                if (
                    row.dismissed_until
                    and row.dismissed_until > now
                ):
                    continue
                current_rev = drive_revisions.get(row.drive_file_id)
                if current_rev is None:
                    # Drive says this file no longer exists. Treat
                    # as a removed-on-remote conflict so the user
                    # decides whether to push back from local or
                    # accept the deletion.
                    new_pending.append(
                        RemoteChangeNotification(
                            note_id=row.entity_id,
                            drive_file_id=row.drive_file_id,
                            detected_at=now,
                            new_revision=None,
                            drive_file_name=None,
                            removed=True,
                        )
                    )
                    continue
                if current_rev == row.last_known_etag:
                    continue  # in sync
                # Real divergence. We don't have the remote name in
                # the bulk listing's minimal fields; the conflict
                # dialog will fetch it on demand.
                new_pending.append(
                    RemoteChangeNotification(
                        note_id=row.entity_id,
                        drive_file_id=row.drive_file_id,
                        detected_at=now,
                        new_revision=current_rev,
                        drive_file_name=None,
                        removed=False,
                    )
                )
            self._cached = new_pending
        finally:
            state.close()
        return True
