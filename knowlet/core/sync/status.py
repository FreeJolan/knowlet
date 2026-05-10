"""Phase 2 E Slice S1 — per-note sync status (ADR-0027 redesign).

Computes the user-facing state of a single note's sync relationship
with Drive. Five terminal states feed the UI badge:

- ``unauthenticated``   user hasn't connected Drive yet.
- ``offline``           we have credentials but couldn't reach Drive.
- ``synced``            local matches Drive (revisions equal).
- ``dirty``             local exists but never pushed yet, OR the
                        sync_state has no Drive id (first push pending).
- ``conflict``           local last_known revision differs from Drive's
                        current revision — both sides moved.

"syncing" and "editing" are FRONTEND-only transient states that the
client manages over our base state during in-flight mutations and
unsaved-edit windows. Not exposed by this module.

Implementation note: this is the core primitive — fast-path-only, no
caching. Callers (the API endpoint, future S2 reconciliation) decide
how often to invoke it. Drive metadata fetch is one ``files.get``
call (~150ms); acceptable for per-note polls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from knowlet.core.sync.credentials import (
    SyncCredentials,
    credentials_path,
    load_credentials,
)
from knowlet.core.sync.drive_client import DriveClient
from knowlet.core.sync.files import get_file_metadata
from knowlet.core.sync.oauth import (
    ScopeUpgradeRequiredError,
    verify_scope,
)
from knowlet.core.sync.state import SyncStateStore

NoteSyncState = Literal[
    "unauthenticated", "offline", "synced", "dirty", "conflict"
]


@dataclass(frozen=True)
class NoteSyncStatus:
    """What the API hands back. The UI binds icon + color + label
    off ``state``; the other fields are for tooltips, debug, and
    the future inbox row rendering."""

    state: NoteSyncState
    last_synced_at: str | None
    drive_file_id: str | None
    last_known_revision: str | None
    current_drive_revision: str | None
    detail: str | None


def compute_note_sync_status(
    *,
    vault_root,  # type: ignore[no-untyped-def]
    note_id: str,
    state_store: SyncStateStore,
) -> NoteSyncStatus:
    """One round trip's worth of work to figure out the state of one
    note. Loads credentials, optionally calls Drive ``files.get``,
    diffs against the sync_state record. Pure function (no
    persistence side effects)."""
    creds = load_credentials(credentials_path(vault_root))
    if creds is None:
        return _make_status("unauthenticated")
    try:
        verify_scope(creds)
    except ScopeUpgradeRequiredError as exc:
        return _make_status("unauthenticated", detail=str(exc))

    record = state_store.get_file_state("note", note_id)
    if record is None or not record.drive_file_id:
        # First push hasn't happened. The note is local-only;
        # treat as "dirty" since pushing would make it match.
        return _make_status(
            "dirty",
            last_synced_at=record.last_synced_at if record else None,
        )

    # We have a Drive id; ask Drive for the current revision.
    try:
        meta = get_file_metadata(_drive_service(creds), record.drive_file_id)
    except Exception as exc:  # noqa: BLE001
        # Network / Drive-side error. Don't crash; mark offline +
        # surface the reason in detail for the tooltip.
        return _make_status(
            "offline",
            last_synced_at=record.last_synced_at,
            drive_file_id=record.drive_file_id,
            last_known_revision=record.last_known_etag,
            detail=repr(exc),
        )

    if meta.head_revision_id == record.last_known_etag:
        return _make_status(
            "synced",
            last_synced_at=record.last_synced_at,
            drive_file_id=record.drive_file_id,
            last_known_revision=record.last_known_etag,
            current_drive_revision=meta.head_revision_id,
        )
    return _make_status(
        "conflict",
        last_synced_at=record.last_synced_at,
        drive_file_id=record.drive_file_id,
        last_known_revision=record.last_known_etag,
        current_drive_revision=meta.head_revision_id,
    )


# --------------------------------------------------- helpers


def _drive_service(creds: SyncCredentials) -> object:
    """Single seam for tests to patch — DriveClient instances are
    cheap, so we don't bother caching at this layer."""
    return DriveClient(creds).service()


def _make_status(
    state: NoteSyncState,
    *,
    last_synced_at: str | None = None,
    drive_file_id: str | None = None,
    last_known_revision: str | None = None,
    current_drive_revision: str | None = None,
    detail: str | None = None,
) -> NoteSyncStatus:
    return NoteSyncStatus(
        state=state,
        last_synced_at=last_synced_at,
        drive_file_id=drive_file_id,
        last_known_revision=last_known_revision,
        current_drive_revision=current_drive_revision,
        detail=detail,
    )
