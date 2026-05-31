"""Sync v2 freshness probe.

Realtime sync has two separate phases:

1. A lightweight probe asks Drive whether anything relevant changed.
   This phase must not block the app and must not mutate local files.
2. If the probe finds relevant remote changes, the UI enters a blocking
   sync gate and runs the heavier preflight/pull path.

The probe deliberately does not advance ``start_page_token``. Advancing
the cursor before preflight completes would let a failed pull hide the
same remote change from the next attempt.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from knowlet.core.note import now_iso
from knowlet.core.sync.changes import (
    DriveChange,
    get_initial_start_page_token,
    list_all_changes,
)
from knowlet.core.sync.drive_client import DriveClient
from knowlet.core.sync.heartbeat import HEARTBEAT_SUFFIX
from knowlet.core.sync.namespace import name_belongs_to_vault
from knowlet.core.sync.state import SyncStateStore

SyncModeV2 = Literal["realtime", "backup"]
FreshnessState = Literal["backup", "up_to_date", "needs_sync", "offline"]
ClientFactory = Callable[[], DriveClient | Any | None]

SYSTEM_FILE_SUFFIXES = (
    HEARTBEAT_SUFFIX,
    ".digest-fetch-lease.json",
)


@dataclass(frozen=True)
class FreshnessReport:
    mode: SyncModeV2
    state: FreshnessState
    checked_at: str
    requires_sync: bool
    reason: str | None = None
    changed_count: int = 0
    next_start_page_token: str | None = None
    detail: str | None = None


def check_sync_freshness(
    *,
    state_store: SyncStateStore,
    client_factory: ClientFactory,
) -> FreshnessReport:
    """Run the non-blocking realtime-sync probe.

    Returns ``needs_sync`` only when a heavier preflight/pull should
    block user-visible content. ``offline`` is also blocking in realtime
    mode because Knowlet cannot prove the local vault is fresh.
    """
    mode = state_store.sync_mode()
    if mode == "backup":
        return FreshnessReport(
            mode="backup",
            state="backup",
            checked_at=now_iso(),
            requires_sync=False,
            reason="backup_mode",
        )

    token = state_store.start_page_token()
    if token is None:
        return FreshnessReport(
            mode="realtime",
            state="needs_sync",
            checked_at=now_iso(),
            requires_sync=True,
            reason="uninitialized",
        )

    client = client_factory()
    if client is None:
        return FreshnessReport(
            mode="realtime",
            state="offline",
            checked_at=now_iso(),
            requires_sync=True,
            reason="unreachable",
            detail="Drive client unavailable",
        )

    try:
        changes, next_token = list_all_changes(client, page_token=token)
    except Exception as exc:
        return FreshnessReport(
            mode="realtime",
            state="offline",
            checked_at=now_iso(),
            requires_sync=True,
            reason="probe_failed",
            detail=repr(exc),
        )

    relevant = _relevant_changes(changes, state_store)
    if not relevant:
        return FreshnessReport(
            mode="realtime",
            state="up_to_date",
            checked_at=now_iso(),
            requires_sync=False,
            changed_count=0,
            next_start_page_token=next_token,
        )

    return FreshnessReport(
        mode="realtime",
        state="needs_sync",
        checked_at=now_iso(),
        requires_sync=True,
        reason="remote_changes",
        changed_count=len(relevant),
        next_start_page_token=next_token,
    )


def mark_freshness_synced(
    *,
    state_store: SyncStateStore,
    client_factory: ClientFactory,
) -> str | None:
    """Advance the Drive changes cursor after a successful sync gate.

    Called after preflight/pull has reconciled the vault. We fetch a
    fresh token representing "now" instead of trusting a stale probe
    response, so changes that happen during preflight are not skipped.
    """
    if state_store.sync_mode() == "backup":
        return None
    client = client_factory()
    if client is None:
        return None
    token = get_initial_start_page_token(client)
    state_store.set_start_page_token(token)
    return token


def _relevant_changes(
    changes: list[DriveChange],
    state_store: SyncStateStore,
) -> list[DriveChange]:
    known_by_drive_id = {
        row.drive_file_id: row
        for row in state_store.list_all_files()
        if row.drive_file_id is not None
    }
    relevant: list[DriveChange] = []
    for change in changes:
        name = str((change.file or {}).get("name") or "")
        if _is_system_file(name):
            continue
        known = known_by_drive_id.get(change.file_id)
        if known is None and not name_belongs_to_vault(name, state_store.vault_root):
            continue
        if change.removed or change.trashed:
            if known is not None and known.delete_intent is None:
                relevant.append(change)
            continue
        if known is None:
            relevant.append(change)
            continue
        head = str((change.file or {}).get("headRevisionId") or "")
        if head and head == known.last_known_etag:
            continue
        relevant.append(change)
    return relevant


def _is_system_file(name: str) -> bool:
    return any(name.endswith(suffix) for suffix in SYSTEM_FILE_SUFFIXES)
