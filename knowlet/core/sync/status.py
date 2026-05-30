"""Phase 2 E Slice S1 + S2 — per-note sync status (ADR-0027 redesign).

Computes the user-facing state of a single note's sync relationship
with Drive. Inner enum carries six states; the wire / UI only see
five — the endpoint maps the sixth (``stale``) onto ``synced`` via
auto-pull before responding.

States, listed by what the UI ultimately renders:

- ``unauthenticated``   user hasn't connected Drive yet.
- ``offline``           we have credentials but couldn't reach Drive.
- ``synced``            local matches Drive (revisions equal).
- ``dirty``             local exists but never pushed yet, OR the
                        sync_state has no Drive id (first push pending).
- ``conflict``          local last_known revision differs from
                        Drive's current revision **and** the local
                        file has been edited since last sync (mtime
                        proves there's local work to lose). Real
                        conflict; user must resolve.
- ``stale``             revisions differ but the local file is clean
                        relative to ``last_synced_at`` — safe to
                        auto-pull. Internal-only: the API endpoint
                        pulls + recomputes before responding, so the
                        UI sees ``synced`` directly. Kept distinct so
                        S3's open-time orchestrator and future tests
                        can branch on it explicitly.

Sync conflict-vs-stale discrimination uses **file mtime + a 0.5s
tolerance** vs ``last_synced_at``. We pick mtime over a hook into
``Vault.write_note`` because:

1. mtime catches edits made outside knowlet (Finder-level paste,
   rsync, an external editor pointed at the vault), which a
   knowlet-side hook would silently miss.
2. No coupling: ``vault.py`` stays sync-agnostic.
3. ``pull_note_to_local`` and ``push_note`` are designed to leave
   ``last_synced_at >= mtime`` after a successful operation, so the
   "is clean" predicate is robust to the racy moments around saves.

"syncing" and "editing" are FRONTEND-only transient states the
client manages over our base state during in-flight mutations and
unsaved-edit windows. Not exposed by this module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
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

# Tolerance for the mtime-vs-last_synced_at comparison. We pick
# half a second because:
#   - APFS/HFS+ stores mtime at sub-second granularity, so true
#     ordering should be preserved across most write paths.
#   - But network filesystems and some test fixtures normalize to
#     full seconds. 0.5s is enough to absorb that without missing
#     any user-perceptible edit (a human takes >0.5s between saves).
_MTIME_TOLERANCE_SEC = 0.5

NoteSyncState = Literal[
    "unauthenticated",
    "offline",
    "synced",
    "dirty",
    "conflict",
    "stale",
]

# Sentinel drive_file_id used by the dev seed-conflict endpoint
# (knowlet/web/server.py). When status / bundle / resolve see this
# value, they short-circuit Drive calls and read the synthetic
# remote text from ``.knowlet/dev_conflicts/<id>.md`` instead.
# Lets a developer dogfood the merge editor against their own
# vault content without having to set up real Drive auth or two
# devices.
DEV_FAKE_DRIVE_FILE_ID = "DEV_FAKE_CONFLICT"


@dataclass(frozen=True)
class NoteSyncStatus:
    """What ``compute_note_sync_status`` returns. The API layer maps
    ``stale`` → auto-pull → ``synced`` before serializing, so the
    wire never carries it. Other fields feed tooltips, the inbox,
    and S3's pre-flight gate."""

    state: NoteSyncState
    last_synced_at: str | None
    drive_file_id: str | None
    last_known_revision: str | None
    current_drive_revision: str | None
    detail: str | None


def compute_note_sync_status(
    *,
    vault_root: Path,
    note_id: str,
    state_store: SyncStateStore,
    local_path: Path | None = None,
) -> NoteSyncStatus:
    """One round trip's worth of work to figure out the state of one
    note. Loads credentials, optionally calls Drive ``files.get``,
    diffs against the sync_state record + the local file's mtime.
    Pure (no persistence side effects) — callers (the API endpoint,
    S3's orchestrator) decide when to act on a ``stale`` result."""
    # Dev seed-conflict short-circuit comes FIRST, before the auth
    # check — the whole point is to dogfood the merge editor on a
    # box without Drive credentials. See DEV_FAKE_DRIVE_FILE_ID
    # docstring for the rest of the contract.
    record = state_store.get_file_state("note", note_id)
    if record is not None and record.drive_file_id == DEV_FAKE_DRIVE_FILE_ID:
        return _make_status(
            "conflict",
            last_synced_at=record.last_synced_at,
            drive_file_id=record.drive_file_id,
            last_known_revision=record.last_known_etag,
            current_drive_revision="dev-rev-new",
            detail="dev seed conflict — see /api/sync/dev-seed-conflict",
        )

    creds = load_credentials(credentials_path(vault_root))
    if creds is None:
        return _make_status("unauthenticated")
    try:
        verify_scope(creds)
    except ScopeUpgradeRequiredError as exc:
        return _make_status("unauthenticated", detail=str(exc))

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
    except Exception as exc:
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

    # Revisions diverge. Distinguish real conflict from stale-remote
    # using sync_state.dirty + local file mtime. Either signal alone
    # is enough to treat as a real conflict — they're independent
    # paths to "local has work that hasn't been pushed yet".
    locally_dirty = bool(record.dirty) or _is_local_dirty(local_path, record.last_synced_at)
    return _make_status(
        "conflict" if locally_dirty else "stale",
        last_synced_at=record.last_synced_at,
        drive_file_id=record.drive_file_id,
        last_known_revision=record.last_known_etag,
        current_drive_revision=meta.head_revision_id,
    )


# --------------------------------------------------- helpers


def _is_local_dirty(local_path: Path | None, last_synced_at: str | None) -> bool:
    """True iff the local file has been touched since ``last_synced_at``.

    None / missing path → False (no local work to lose). Unparseable
    timestamp → True (better to be conservative and treat as dirty
    than to silently auto-pull over user edits).

    Tolerance: ``mtime > last_synced_at + 0.5s`` — covers the
    push-side race where ``upload_new_file`` returns just before
    ``now_iso()`` is captured, leaving ``mtime ≤ last_synced_at`` by
    a tiny margin. The 0.5s window is far below any human's
    inter-save cadence."""
    if local_path is None or not local_path.exists():
        return False
    if last_synced_at is None:
        # We have a local file but no record of ever syncing it
        # (shouldn't happen at this branch — we only call this once
        # we know there's a Drive id). Treat as dirty defensively.
        return True
    try:
        ts_synced = _iso_to_epoch(last_synced_at)
    except ValueError:
        logging.getLogger(__name__).warning(
            "unparseable last_synced_at %r — treating as dirty",
            last_synced_at,
        )
        return True
    try:
        ts_mtime = local_path.stat().st_mtime
    except OSError:
        return False
    return ts_mtime > ts_synced + _MTIME_TOLERANCE_SEC


def _iso_to_epoch(iso: str) -> float:
    """Parse one of the ISO-UTC strings produced by ``now_iso()``.
    Accepts both ``Z`` and ``+00:00`` suffixes; everything else
    raises so the caller treats the state as dirty."""
    s = iso.strip()
    # Python's fromisoformat does not accept the "Z" suffix until
    # 3.11. Normalize to "+00:00" first for compatibility with all
    # supported runtimes.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).timestamp()


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
