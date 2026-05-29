"""Phase 2 E Slice S2 — pull a single note from Drive (ADR-0027 redesign).

Pairs with ``push.py``: that one ships local → Drive; this one ships
Drive → local. Used in two situations:

1. **Auto-pull-when-safe** (S2): the per-note status check sees
   ``local-clean + remote-moved`` and silently pulls so the user
   doesn't have to think about it. The check is the trigger; this
   module is the action.
2. **Open-time fetch** (S3, future): when the user opens a note,
   pull first if the cached state is stale, then render. Same
   primitive, different trigger.

The function is intentionally **explicit and conditional-free**: the
caller decides whether pulling is safe (no local edits to lose). We
do not double-check here — that would duplicate the ``status.py``
logic and create a contract surface where two modules have to agree
on "what counts as dirty".

Atomicity matches Vault.write_note: download to bytes, write to a
``<id>.md.tmp`` sibling, then ``os.replace`` to swap. Either the
old file remains (download or write failed before the rename) or
the new file is fully present (rename happened). Power-loss-safe
via the underlying filesystem rename guarantees.
"""

from __future__ import annotations

import os
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from knowlet.core.note import now_iso
from knowlet.core.sync.files import download_file, get_file_metadata
from knowlet.core.sync.state import FileState, SyncStateStore


@dataclass(frozen=True)
class PullResult:
    """Returned from a successful pull. Carries the post-pull
    revision so the caller can log + the freshly-applied bytes for
    callers that want to push them onward (rare; mostly debug)."""

    entity_type: str
    entity_id: str
    drive_file_id: str
    new_revision: str | None
    new_bytes: bytes


class PullStateMissingError(RuntimeError):
    """No sync_state row, or no drive_file_id on it. The caller asked
    us to pull a note we've never synced — probably a logic bug."""


def pull_note_to_local(
    *,
    service: Any,
    state: SyncStateStore,
    note_id: str,
    local_path: Path,
) -> PullResult:
    """Download remote bytes and atomically replace ``local_path``,
    advancing sync_state to the post-pull revision.

    Caller contract:
      - The local file is "clean" relative to last_synced_at — no
        unsaved local edits to lose. Verify upstream via
        ``status.py`` before invoking; we do not re-check here.
      - sync_state has a row for ("note", note_id) with a non-null
        ``drive_file_id``. If absent, ``PullStateMissingError``.

    Side effects:
      - Writes ``local_path`` (overwrites if present, creates parent
        dirs if missing).
      - Upserts the sync_state row with ``last_known_etag`` advanced
        to the freshly-fetched ``headRevisionId``, ``last_synced_at``
        bumped to now, ``dirty=False``.

    Note: order matters. We capture ``now_iso()`` AFTER ``tmp.replace``
    so ``last_synced_at >= file_mtime`` always holds — that way the
    next ``_is_local_dirty`` check post-pull reliably reads False.
    Reverse the order and a microsecond-granularity OS would race
    itself."""
    record = state.get_file_state("note", note_id)
    if record is None or not record.drive_file_id:
        raise PullStateMissingError(
            f"cannot pull note {note_id}: no Drive id in sync_state"
        )

    # Fetch metadata first so we know the post-pull revision; do
    # the bytes download next. Two round trips, but they're cheap
    # and the metadata also doubles as a "remote still exists"
    # check before we go to the trouble of downloading.
    meta = get_file_metadata(service, record.drive_file_id)
    body = download_file(service, record.drive_file_id)

    local_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = local_path.with_suffix(local_path.suffix + ".tmp")
    tmp.write_bytes(body)
    tmp.replace(local_path)

    # Pin mtime to last_synced_at exactly. ``now_iso()`` truncates to
    # whole seconds, while ``tmp.replace`` stamps mtime at sub-second
    # precision — without this snap, mtime can lead last_synced_at by
    # up to ~1s and ``_is_local_dirty`` would falsely flag the
    # freshly-pulled file as dirty (which would in turn trigger a
    # phantom conflict on the next status poll).
    synced_iso = now_iso()
    synced_epoch = _iso_to_epoch(synced_iso)
    with suppress(OSError):
        os.utime(local_path, (synced_epoch, synced_epoch))

    state.upsert_file_state(
        FileState(
            entity_type="note",
            entity_id=note_id,
            drive_file_id=record.drive_file_id,
            last_known_etag=meta.head_revision_id,
            last_synced_at=synced_iso,
            dirty=False,
        )
    )
    return PullResult(
        entity_type="note",
        entity_id=note_id,
        drive_file_id=record.drive_file_id,
        new_revision=meta.head_revision_id,
        new_bytes=body,
    )


def _iso_to_epoch(iso: str) -> float:
    """Mirror of ``status._iso_to_epoch`` — kept private here to
    avoid an import cycle (status imports from this module's sibling
    ``files``, and pulling status into pull would re-cross). Cheap
    enough to duplicate."""
    s = iso.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).timestamp()
