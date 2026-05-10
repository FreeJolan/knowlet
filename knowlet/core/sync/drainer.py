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
from pathlib import Path
from typing import Any

from knowlet.core.note import Note
from knowlet.core.sync.credentials import (
    credentials_path,
    load_credentials,
)
from knowlet.core.sync.drive_client import DriveClient
from knowlet.core.sync.push import (
    ConflictReport,
    NoteFileMissingError,
    push_note,
)
from knowlet.core.sync.state import SyncStateStore
from knowlet.core.sync.status import DEV_FAKE_DRIVE_FILE_ID

logger = logging.getLogger(__name__)


NoteLookup = Callable[[str], Note | None]
ConflictCallback = Callable[[str, ConflictReport], None]
SyncedCallback = Callable[[str], None]


class PushDrainer:
    def __init__(
        self,
        *,
        vault_root: Path,
        note_lookup: NoteLookup,
        on_conflict: ConflictCallback | None = None,
        on_synced: SyncedCallback | None = None,
        poll_interval: float = 5.0,
    ) -> None:
        self.vault_root = vault_root
        self.note_lookup = note_lookup
        self.on_conflict: ConflictCallback = on_conflict or (
            lambda _id, _rep: None
        )
        self.on_synced: SyncedCallback = on_synced or (lambda _id: None)
        self.poll_interval = poll_interval
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

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
        """Public entry point for tests — runs one iteration of the
        push loop synchronously without going through the daemon
        thread. Production callers should use ``start()``."""
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
                self._tick()
            except Exception:  # noqa: BLE001
                logger.warning("drainer tick raised", exc_info=True)
            if self._stop.wait(self.poll_interval):
                return

    def _tick(self) -> None:
        creds = load_credentials(credentials_path(self.vault_root))
        if creds is None:
            return
        store = SyncStateStore(self.vault_root)
        try:
            dirty = store.list_dirty()
            if not dirty:
                return
            service: Any = None
            for row in dirty:
                if row.entity_type != "note":
                    continue
                if row.drive_file_id == DEV_FAKE_DRIVE_FILE_ID:
                    # Dev seed — no real Drive file behind it; ignore.
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
                    continue
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "drainer: push failed for note %s: %r — will retry",
                        row.entity_id,
                        exc,
                    )
                    continue
                if isinstance(result, ConflictReport):
                    self.on_conflict(row.entity_id, result)
                else:
                    self.on_synced(row.entity_id)
        finally:
            store.close()
