"""Phase 2 E #107a — vault-wide pre-flight scan (ADR-0027).

Walks every tracked file_state row, computes its sync status, and
auto-resolves the safe cases so the user only sees the things that
actually need their attention.

Personas:

- **Bob (sequential multi-device)** opens device B in the evening.
  25 of 30 notes are ``stale`` (remote moved while he was offline);
  preflight pulls them silently. 3 are real ``conflict``; preflight
  surfaces just those 3. The "⚠️ 3" chip in the header is the
  user's whole sync UI for this round.

- **Dan (long pause)** comes back after a week. 30 stale auto-pull,
  3 real conflicts surface, 2 are ``offline`` (network glitch);
  inbox shows 3 + a collapsible "2 couldn't be reached" footer.

- **Alice (single device)** has no creds; preflight returns
  ``unauthenticated`` immediately, chip stays hidden.

What this module does NOT do:

- Persist the result. The endpoint layer holds the cache. Each
  scan is a pure computation; callers decide cadence (mount,
  manual refresh, post-resolve invalidation).
- Attempt to push dirty notes. ``conflict`` only covers
  remote-moved; "I have local edits I haven't pushed yet" is a
  separate state ``dirty`` that S4 will surface via save-time push.
- Run in parallel. Sequential scan keeps the Drive request rate
  predictable; future optimization can bound concurrency if vault
  size warrants it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from knowlet.core.sync.pull import PullStateMissingError, pull_note_to_local
from knowlet.core.sync.state import FileState, SyncStateStore
from knowlet.core.sync.status import (
    NoteSyncStatus,
    compute_note_sync_status,
)

NoteMetaLookup = Callable[[str], dict[str, Any] | None]
NotePathLookup = Callable[[str], Path | None]
ServiceFactory = Callable[[], Any | None]
# #119 — callbacks for the bidirectional sync pass.
# ``MaterializeCallback`` receives a Drive file_id + the brief
# metadata from list_appdata; returns the note_id we ended up
# storing under (or None on failure — caller logs and continues).
# ``TrashLocalCallback`` receives a note_id whose Drive file
# disappeared since last preflight; impl moves local to trash.
MaterializeCallback = Callable[[str, Any], str | None]
TrashLocalCallback = Callable[[str], None]


@dataclass(frozen=True)
class PreflightConflict:
    """One row in the conflict inbox. The chip only shows the count;
    the inbox renders these to let the user click into each."""

    note_id: str
    note_title: str | None
    drive_file_id: str | None
    last_synced_at: str | None
    last_known_revision: str | None
    current_drive_revision: str | None
    remote_modified_at: str | None
    remote_modified_by: str | None


@dataclass(frozen=True)
class PreflightOffline:
    """One file we couldn't reach Drive for during this scan. Surfaced
    as a quieter section in the inbox so the user knows the count
    isn't authoritative until network recovers."""

    note_id: str
    note_title: str | None
    detail: str | None


@dataclass(frozen=True)
class PreflightReport:
    """Result of one scan pass. The endpoint serializes this and
    React Query caches it client-side; the chip reads
    ``len(conflicts)``, the inbox renders the lists, the
    ``unauthenticated`` flag tells the chip to stay hidden.

    #111 — ``alive_devices`` is the list of distinct knowlet
    installations seen on this vault's Drive appData within the
    heartbeat TTL. Auto mode reads ``len(alive_devices)`` to
    decide whether to promote to Strict; the chip / settings UI
    surface the count back to the user.

    #119 — ``cloned_from_drive_ids`` lists notes the scan
    materialized from Drive (first-connect bootstrap + remote-only
    new notes); ``trashed_for_drive_delete_ids`` lists notes the
    scan moved to local trash because Drive removed them."""

    conflicts: list[PreflightConflict]
    offline: list[PreflightOffline]
    auto_pulled_ids: list[str]
    synced_count: int
    dirty_count: int
    scanned: int
    unauthenticated: bool
    alive_devices: list[dict[str, str]]  # [{device_id, last_seen_at}]
    cloned_from_drive_ids: list[str] = field(default_factory=list)
    trashed_for_drive_delete_ids: list[str] = field(default_factory=list)


def preflight_scan(
    *,
    vault_root: Path,
    state_store: SyncStateStore,
    note_meta_lookup: NoteMetaLookup,
    note_path_lookup: NotePathLookup,
    auto_pull_service_factory: ServiceFactory,
    materialize_drive_file: MaterializeCallback | None = None,
    trash_local_for_drive_deleted: TrashLocalCallback | None = None,
) -> PreflightReport:
    """Run one pass over every tracked file.

    Parameters use callable seams so this module stays free of
    web/runtime imports — the API endpoint passes:

    - ``note_meta_lookup(note_id) -> dict | None``: returns the
      indexed title (and other meta) for a note id, or None if the
      note isn't in the index. Used to humanize the chip rows.
    - ``note_path_lookup(note_id) -> Path | None``: returns the
      on-disk path for that note id, or None.
    - ``auto_pull_service_factory() -> service``: returns a Drive
      service handle to pass through to ``pull_note_to_local``.
      Called only when at least one ``stale`` is detected, so the
      auth/network round trip happens once for the whole scan
      rather than per-note.
    """
    rows: list[FileState] = state_store.list_all_files()
    # #119 — even with empty sync_state, we still want to:
    #   - run heartbeat (so this device shows up in alive_devices)
    #   - scan Drive (first-connect case: local empty, Drive has notes)
    # So don't short-circuit on empty rows like before.

    conflicts: list[PreflightConflict] = []
    offline: list[PreflightOffline] = []
    auto_pulled: list[str] = []
    synced = 0
    dirty = 0
    unauthenticated = False
    drive_service: Any = None
    alive_devices: list[dict[str, str]] = []
    cloned_from_drive: list[str] = []
    trashed_for_drive_delete: list[str] = []

    # #111 — heartbeat write + scan happens BEFORE the per-note
    # loop so the alive_devices count is populated even if every
    # note short-circuits as unauthenticated. The auto-promotion
    # decision needs to be available regardless of whether there's
    # active sync work.
    drive_service = _maybe_heartbeat_pass(
        state_store=state_store,
        service_factory=auto_pull_service_factory,
        alive_devices_out=alive_devices,
    )

    # #119 — list Drive appData files ONCE per scan. Used twice
    # below: to detect Drive-side deletions (sync_state has the
    # file_id but Drive doesn't) and Drive-side additions (Drive
    # has the file but no sync_state row tracks it).
    drive_files: dict[str, Any] = {}
    if drive_service is not None:
        try:
            from knowlet.core.sync.files import list_appdata_revisions

            drive_files = list_appdata_revisions(drive_service)
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "preflight: Drive list failed; bidirectional sync "
                "skipped this tick",
                exc_info=True,
            )

    for row in rows:
        if row.entity_type != "note":
            continue
        local_path = note_path_lookup(row.entity_id)
        status = compute_note_sync_status(
            vault_root=vault_root,
            note_id=row.entity_id,
            state_store=state_store,
            local_path=local_path,
        )

        if status.state == "unauthenticated":
            # First row already revealed no creds — bail early. The
            # chip layer hides itself when this flag is set so the
            # user doesn't see a confusing "0 conflicts" UI on a
            # box that simply isn't connected to Drive.
            unauthenticated = True
            break

        if status.state == "synced":
            synced += 1
            continue
        if status.state == "dirty":
            dirty += 1
            continue
        if status.state == "offline":
            offline.append(_offline_row(row, status, note_meta_lookup))
            continue
        if status.state == "stale":
            # Auto-pull. Lazy-initialize the Drive service handle so
            # we only authenticate when there's actual stale work.
            if drive_service is None:
                drive_service = auto_pull_service_factory()
            if drive_service is None or local_path is None:
                # Couldn't get a service or the file vanished — treat
                # as offline rather than crashing the whole scan.
                offline.append(_offline_row(row, status, note_meta_lookup))
                continue
            try:
                pull_note_to_local(
                    service=drive_service,
                    state=state_store,
                    note_id=row.entity_id,
                    local_path=local_path,
                )
                auto_pulled.append(row.entity_id)
                synced += 1
            except PullStateMissingError:
                # Sync state malformed — surface as offline so it
                # doesn't get lost. Manual repair via the doctor
                # command can sort it.
                offline.append(_offline_row(row, status, note_meta_lookup))
            except Exception as exc:
                # Network blip mid-pull. The note is still stale; we
                # downgrade it to "offline" for THIS scan so the user
                # sees something rather than a silent miss.
                offline.append(
                    PreflightOffline(
                        note_id=row.entity_id,
                        note_title=_title(row.entity_id, note_meta_lookup),
                        detail=f"auto-pull failed: {exc!r}",
                    )
                )
            continue
        if status.state == "conflict":
            conflicts.append(_conflict_row(row, status, note_meta_lookup))
            continue
        # Unknown state — defensively classify as offline so it
        # surfaces somewhere rather than silently disappearing.
        offline.append(_offline_row(row, status, note_meta_lookup))

    # #119 bidirectional sync passes — only when we have a Drive
    # service (auth + reachable). The per-note loop above already
    # set ``unauthenticated`` if creds are missing.
    if (
        not unauthenticated
        and drive_service is not None
    ):
        # Pass A: Drive-side deletions. Any sync_state row whose
        # drive_file_id is missing from the current Drive list
        # gets its local file moved to trash. Skip dev-seeded rows
        # (no real Drive backing) and rows with pending delete
        # intent (those are OUR deletes, drainer handles them).
        if trash_local_for_drive_deleted is not None:
            from knowlet.core.sync.status import DEV_FAKE_DRIVE_FILE_ID

            for row in rows:
                if row.entity_type != "note":
                    continue
                if not row.drive_file_id:
                    continue
                if row.drive_file_id == DEV_FAKE_DRIVE_FILE_ID:
                    continue
                if row.delete_intent is not None:
                    continue
                if row.drive_file_id in drive_files:
                    continue
                try:
                    trash_local_for_drive_deleted(row.entity_id)
                    trashed_for_drive_delete.append(row.entity_id)
                except Exception:
                    import logging

                    logging.getLogger(__name__).warning(
                        "preflight: trash-local failed for %s",
                        row.entity_id,
                        exc_info=True,
                    )

        # Pass B: Drive-side additions. Any file_id in Drive's
        # appData not currently tracked in sync_state gets pulled
        # down. Skip heartbeat files (those aren't notes).
        if materialize_drive_file is not None:
            from knowlet.core.sync.heartbeat import HEARTBEAT_SUFFIX

            known_drive_ids = {
                row.drive_file_id
                for row in rows
                if row.drive_file_id
            }
            for file_id, brief in drive_files.items():
                if file_id in known_drive_ids:
                    continue
                if brief.name and brief.name.endswith(HEARTBEAT_SUFFIX):
                    continue
                try:
                    materialized_id = materialize_drive_file(file_id, brief)
                    if materialized_id:
                        cloned_from_drive.append(materialized_id)
                except Exception:
                    import logging

                    logging.getLogger(__name__).warning(
                        "preflight: materialize-from-Drive failed for %s",
                        file_id,
                        exc_info=True,
                    )

    return PreflightReport(
        conflicts=conflicts,
        offline=offline,
        auto_pulled_ids=auto_pulled,
        synced_count=synced,
        dirty_count=dirty,
        scanned=len(rows),
        unauthenticated=unauthenticated,
        alive_devices=alive_devices,
        cloned_from_drive_ids=cloned_from_drive,
        trashed_for_drive_delete_ids=trashed_for_drive_delete,
    )


def _maybe_heartbeat_pass(
    *,
    state_store: SyncStateStore,
    service_factory: ServiceFactory,
    alive_devices_out: list[dict[str, str]],
) -> Any:
    """Best-effort heartbeat write + alive-devices read. Returns the
    Drive service handle so the caller can reuse it for auto-pull
    work without re-authenticating.

    Failures (no creds, Drive unreachable, list returns garbage) are
    swallowed — the heartbeat is opt-in instrumentation; we don't
    want a flaky network call to make the whole preflight fail."""
    from knowlet.core.sync.heartbeat import (
        list_alive_devices,
        write_my_heartbeat,
    )

    service = service_factory()
    if service is None:
        return None
    try:
        write_my_heartbeat(
            service,
            device_id=state_store.device_id(),
            device_label=state_store.device_label(),
        )
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "preflight: heartbeat write failed", exc_info=True
        )
    try:
        devices = list_alive_devices(service)
        for d in devices:
            alive_devices_out.append(
                {"device_id": d.device_id, "last_seen_at": d.last_seen_at}
            )
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "preflight: heartbeat list failed", exc_info=True
        )
    return service


def _title(note_id: str, lookup: NoteMetaLookup) -> str | None:
    meta = lookup(note_id)
    if meta is None:
        return None
    title = meta.get("title")
    return str(title) if title else None


def _conflict_row(
    row: FileState,
    status: NoteSyncStatus,
    lookup: NoteMetaLookup,
) -> PreflightConflict:
    return PreflightConflict(
        note_id=row.entity_id,
        note_title=_title(row.entity_id, lookup),
        drive_file_id=row.drive_file_id,
        last_synced_at=status.last_synced_at,
        last_known_revision=status.last_known_revision,
        current_drive_revision=status.current_drive_revision,
        remote_modified_at=None,
        remote_modified_by=None,
    )


def _offline_row(
    row: FileState,
    status: NoteSyncStatus,
    lookup: NoteMetaLookup,
) -> PreflightOffline:
    return PreflightOffline(
        note_id=row.entity_id,
        note_title=_title(row.entity_id, lookup),
        detail=status.detail,
    )
