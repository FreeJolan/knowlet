"""S4 — background drainer that pushes locally-dirty notes to Drive.

The save endpoint marks ``sync_state.file_state.dirty=True`` after
each note write. Inline push from the save handler was rejected
because autosave fires every couple of seconds during typing — a
synchronous Drive round trip would block typing latency on
network. So we run a daemon thread that polls dirty rows every
``poll_interval`` seconds and pushes them.

Three outcomes per push:

- **200 OK**: ``push_note`` advances the sync_state row to
  ``dirty=False`` + new ``last_known_etag``. Optional ``on_synced``
  callback fires so the chip can drop this note from its conflict
  cache if it was there.
- **412 / ConflictReport**: Drive moved between our last known
  revision and now. ``push_note`` does NOT mutate sync_state on
  this path. Drainer fires ``on_conflict(note_id, report)`` so the
  chip / Strict modal lights up within seconds rather than waiting
  for the next manual preflight.
- **Network error**: leave dirty + log; tick will retry.

DEV_FAKE_CONFLICT rows are skipped — those are dev-seeded fake
conflicts that have no real Drive file behind them.

Lifecycle:

- ``start()`` boots the daemon thread. Idempotent.
- ``stop()`` signals the thread to exit and joins (with timeout).
- The thread no-ops while creds are absent (single-device users
  who never connected Drive).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from knowlet.core.note import Note
from knowlet.core.sync.credentials import (
    credentials_path,
    load_credentials,
)
from knowlet.core.sync.drive_client import DriveClient
from knowlet.core.sync.push import (
    ATTACHMENT_ENTITY_TYPE,
    AttachmentFileMissingError,
    ConflictReport,
    NoteFileMissingError,
    push_attachment,
    push_note,
)
from knowlet.core.sync.state import SyncStateStore
from knowlet.core.sync.status import DEV_FAKE_DRIVE_FILE_ID

logger = logging.getLogger(__name__)


NoteLookup = Callable[[str], Note | None]
# Resolves an attachment filename (e.g. ``01HX....png``) to its
# absolute path on disk, or None if it's missing.
AttachmentLookup = Callable[[str], Path | None]
ConflictCallback = Callable[[str, ConflictReport], None]
SyncedCallback = Callable[[str], None]
# Returns ``(entity_type, entity_id)`` pairs for items that exist on
# disk but have no ``sync_state`` row yet — the "I created stuff
# before connecting Drive" backlog. Includes both notes and
# attachments. Drainer calls this once per creds-available session.
UntrackedSweep = Callable[[], list[tuple[str, str]]]


class PushDrainer:
    def __init__(
        self,
        *,
        vault_root: Path,
        note_lookup: NoteLookup,
        attachment_lookup: AttachmentLookup | None = None,
        on_conflict: ConflictCallback | None = None,
        on_synced: SyncedCallback | None = None,
        untracked_sweep: UntrackedSweep | None = None,
        poll_interval: float = 5.0,
    ) -> None:
        self.vault_root = vault_root
        self.note_lookup = note_lookup
        self.attachment_lookup: AttachmentLookup = attachment_lookup or (lambda _id: None)
        self.on_conflict: ConflictCallback = on_conflict or (lambda _id, _rep: None)
        self.on_synced: SyncedCallback = on_synced or (lambda _id: None)
        self.untracked_sweep: UntrackedSweep = untracked_sweep or (lambda: [])
        self.poll_interval = poll_interval
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        # Serializes ``_tick`` runs. Without this the daemon thread's
        # auto-tick can collide with ``POST /api/sync/drain-now``
        # (called from the HTTP thread): both threads observe the
        # same dirty row before either flips it to clean, so first-push
        # creates *two* Drive files for one local file. Especially
        # dangerous for attachments since they don't have revisionId
        # OCC to catch the duplicate.
        self._tick_lock = threading.Lock()
        # #122 — in-memory map of currently-failing pushes. Note id
        # → {"count", "last_error", "last_attempt_at"}. Cleared
        # whenever a push succeeds (or returns ConflictReport,
        # which is a "the other side moved", not a failure). The
        # ``GET /api/sync/push-errors`` endpoint reads this; the
        # chip surfaces a red badge when it's non-empty.
        self.failures: dict[str, dict[str, Any]] = {}
        # Whether we've already run the untracked-sweep since creds
        # became available. Reset to False whenever we observe a
        # no-creds tick, so a disconnect → reconnect cycle re-sweeps.
        self._untracked_sweep_done: bool = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="knowlet-push-drainer",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def tick_once(self) -> None:
        """Public entry point — runs one iteration of the push loop
        synchronously. Used by tests and by ``POST /api/sync/drain-now``.
        Production callers should also use ``start()`` to keep the
        background poll running; ``tick_once`` is for "kick it now".

        Holds ``_tick_lock`` so a concurrent auto-tick can't double-push
        the same dirty row."""
        with self._tick_lock:
            self._tick()

    # --------------------------------------------------- internals

    def _run(self) -> None:
        # First wait gives the rest of the app a moment to come up
        # before we start hitting Drive. Subsequent ticks are at
        # ``poll_interval``.
        if self._stop.wait(self.poll_interval):
            return
        while not self._stop.is_set():
            try:
                with self._tick_lock:
                    self._tick()
            except Exception:
                logger.warning("drainer tick raised", exc_info=True)
            if self._stop.wait(self.poll_interval):
                return

    def _tick(self) -> None:
        creds = load_credentials(credentials_path(self.vault_root))
        if creds is None:
            # Reset the sweep latch so a reconnect re-runs it. Cheap.
            self._untracked_sweep_done = False
            return
        # First creds-positive tick after a connect (or after a
        # process restart): sweep notes that exist on disk but have
        # no sync_state row yet, and queue them as dirty so the
        # rest of this tick picks them up. Without this, notes
        # created before Drive was connected would sit in "N to
        # push" forever — the drainer's dirty-only filter never sees
        # them, and the user has to manually click "Push all".
        if not self._untracked_sweep_done:
            try:
                untracked = self.untracked_sweep()
            except Exception:
                logger.warning("untracked-sweep callback raised", exc_info=True)
                untracked = []
            if untracked:
                logger.info(
                    "drainer: queueing %d untracked item(s) for first push",
                    len(untracked),
                )
                self._queue_untracked(untracked)
            self._untracked_sweep_done = True
        store = SyncStateStore(self.vault_root)
        try:
            service: Any = None
            # Attachment orphan sweep — for every attachment row that
            # already lives on Drive (drive_file_id set) but whose
            # local file is gone, mark delete_intent=hard so the next
            # _process_deletions pass tells Drive to clean it up. Runs
            # every tick (cheap — one stat per tracked attachment) so
            # a Finder-side `rm` propagates within ~5s.
            self._sweep_for_attachment_orphans(store)
            # #118 — delete tombstones first. Cheap to process; gets
            # them out of the way so the chip stops counting them as
            # "unpushed" (the dirty list below excludes deleted=True
            # rows because we don't set dirty on them).
            service = self._process_deletions(store, creds, service)
            dirty = store.list_dirty()
            if not dirty:
                return
            for row in dirty:
                if row.drive_file_id == DEV_FAKE_DRIVE_FILE_ID:
                    # Dev seed — no real Drive file behind it; ignore.
                    continue
                if row.entity_type == ATTACHMENT_ENTITY_TYPE:
                    if service is None:
                        service = DriveClient(creds).service()
                    self._push_attachment_row(store, service, row)
                    continue
                if row.entity_type != "note":
                    # Unknown type — leave it alone so a future
                    # slice handling it doesn't have to back-fill.
                    continue
                note = self.note_lookup(row.entity_id)
                if note is None:
                    logger.warning(
                        "drainer: note %s in dirty list but unloadable; "
                        "leaving dirty for next tick",
                        row.entity_id,
                    )
                    continue
                # Force the tracked entity_id onto the in-memory Note.
                # For notes with corrupted / missing frontmatter +
                # non-ULID-shaped filenames, ``Note.from_file``
                # synthesizes a fresh ULID on every read; without
                # this override push_note would treat each tick as
                # a brand-new note and create a phantom Drive file
                # plus a phantom sync_state row. Same trick the
                # resolve-merge and repair endpoints already use.
                note.id = row.entity_id
                if service is None:
                    # Lazy: only authenticate when there's actually
                    # work to do. Saves a Drive handshake on idle.
                    service = DriveClient(creds).service()
                try:
                    result = push_note(service=service, state=store, note=note)
                except NoteFileMissingError:
                    logger.warning(
                        "drainer: note %s file missing on disk; clearing dirty",
                        row.entity_id,
                    )
                    # The note was deleted locally between save and
                    # push. Just drop the dirty flag; deletion sync
                    # is handled separately.
                    self._clear_failure(row.entity_id)
                    continue
                except Exception as exc:
                    logger.warning(
                        "drainer: push failed for note %s: %r — will retry",
                        row.entity_id,
                        exc,
                    )
                    self._record_failure(row.entity_id, exc)
                    continue
                if isinstance(result, ConflictReport):
                    self.on_conflict(row.entity_id, result)
                    # Conflict ≠ failure; clear so chip doesn't
                    # double-count.
                    self._clear_failure(row.entity_id)
                else:
                    self.on_synced(row.entity_id)
                    self._clear_failure(row.entity_id)
        finally:
            store.close()

    def _record_failure(self, note_id: str, exc: BaseException) -> None:
        from knowlet.core.note import now_iso

        prev = self.failures.get(note_id, {})
        self.failures[note_id] = {
            "count": int(prev.get("count", 0)) + 1,
            "last_error": repr(exc)[:500],
            "last_attempt_at": now_iso(),
        }

    def _clear_failure(self, note_id: str) -> None:
        self.failures.pop(note_id, None)

    def _queue_untracked(self, items: list[tuple[str, str]]) -> None:
        """Insert dirty first-push rows (drive_file_id=None) for
        entities that have never been tracked. Idempotent against
        the sweep firing twice."""
        from knowlet.core.sync.state import FileState

        store = SyncStateStore(self.vault_root)
        try:
            existing = {(fs.entity_type, fs.entity_id) for fs in store.list_all_files()}
            for entity_type, entity_id in items:
                if (entity_type, entity_id) in existing:
                    continue
                store.upsert_file_state(
                    FileState(
                        entity_type=entity_type,
                        entity_id=entity_id,
                        drive_file_id=None,
                        last_known_etag=None,
                        last_synced_at=None,
                        dirty=True,
                    )
                )
        finally:
            store.close()

    def _push_attachment_row(self, store: SyncStateStore, service: Any, row: Any) -> None:
        """Push a single attachment row. Attachments have no update /
        conflict path — they're immutable once written — so the
        outcome is success or transient failure (logged + retried
        next tick)."""
        path = self.attachment_lookup(row.entity_id)
        if path is None or not path.exists():
            logger.warning(
                "drainer: attachment %s missing on disk; dropping row",
                row.entity_id,
            )
            store.remove_file_state(ATTACHMENT_ENTITY_TYPE, row.entity_id)
            self._clear_failure(row.entity_id)
            return
        try:
            push_attachment(
                service=service,
                state=store,
                filename=row.entity_id,
                path=path,
            )
        except AttachmentFileMissingError:
            logger.warning(
                "drainer: attachment %s vanished between sweep and push; clearing row",
                row.entity_id,
            )
            store.remove_file_state(ATTACHMENT_ENTITY_TYPE, row.entity_id)
            self._clear_failure(row.entity_id)
            return
        except Exception as exc:
            logger.warning(
                "drainer: attachment push failed for %s: %r — will retry",
                row.entity_id,
                exc,
            )
            self._record_failure(row.entity_id, exc)
            return
        self.on_synced(row.entity_id)
        self._clear_failure(row.entity_id)

    def _sweep_for_attachment_orphans(self, store: SyncStateStore) -> None:
        """For every attachment row whose Drive copy exists
        (drive_file_id set, dirty=False, no delete_intent yet) but
        whose local file is gone, set delete_intent=hard. The next
        _process_deletions call drains it.

        Why hard: attachments are immutable, and the user explicitly
        deleted the local file — there's no "30-day undo" expectation
        here. (Notes go to local trash first, hence soft. Attachments
        live directly in _attachments/ with no trash bin; if the
        bytes are gone locally they should be gone on Drive too.)

        Rows with delete_intent already set are skipped (idempotent).
        Rows where drive_file_id is None (never pushed) are dropped
        directly — nothing to clean."""
        for fs in store.list_all_files():
            if fs.entity_type != ATTACHMENT_ENTITY_TYPE:
                continue
            if fs.delete_intent is not None:
                continue
            path = self.attachment_lookup(fs.entity_id)
            if path is not None and path.exists():
                continue
            # File is gone. Two cases:
            if not fs.drive_file_id:
                # Never made it to Drive — just drop the row.
                store.remove_file_state(ATTACHMENT_ENTITY_TYPE, fs.entity_id)
                continue
            # Already on Drive — mark for hard delete so the next
            # _process_deletions tick cleans it up.
            store.upsert_file_state(
                replace(
                    fs,
                    delete_intent="hard",
                    dirty=False,
                )
            )

    def _process_deletions(self, store: SyncStateStore, creds: Any, service: Any) -> Any:
        """Drain ``delete_intent`` rows. ``soft`` calls Drive's
        ``files.update`` with ``trashed=True`` (30-day grace via
        Drive's own trash); ``hard`` calls ``files.delete`` for
        permanent removal. On success, drop the sync_state row
        entirely so the chip / preflight forget about it.

        Failures are swallowed (logged) — the row stays in
        ``delete_intent`` state and the next tick retries. Returns
        the Drive service handle so the caller can reuse it
        without re-authenticating."""
        deletions = store.list_deletion_pending()
        for row in deletions:
            if row.entity_type not in ("note", ATTACHMENT_ENTITY_TYPE):
                # Unknown type — leave alone so a future slice can
                # handle it. The intent row stays, which is safe:
                # nothing reads it that doesn't also know about the
                # entity type.
                continue
            if row.drive_file_id is None or row.drive_file_id == DEV_FAKE_DRIVE_FILE_ID:
                # Never pushed → no Drive cleanup needed; just drop
                # the local row. Or dev-seeded fake → same treatment.
                store.remove_file_state(row.entity_type, row.entity_id)
                self.on_synced(row.entity_id)
                continue
            if service is None:
                service = DriveClient(creds).service()
            try:
                if row.delete_intent == "hard":
                    service.files().delete(fileId=row.drive_file_id).execute()
                else:
                    # default to soft trash for any other value
                    service.files().update(
                        fileId=row.drive_file_id,
                        body={"trashed": True},
                    ).execute()
            except Exception as exc:
                logger.warning(
                    "drainer: Drive %s-delete failed for %s: %r — will retry",
                    row.delete_intent,
                    row.entity_id,
                    exc,
                )
                self._record_failure(row.entity_id, exc)
                continue
            store.remove_file_state(row.entity_type, row.entity_id)
            self.on_synced(row.entity_id)
            self._clear_failure(row.entity_id)
        return service
