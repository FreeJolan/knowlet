"""Phase 2 E Slice 5.B — local sync state (ADR-0027).

Backs the read/write coordination between knowlet and Drive. Stored
at ``<vault>/.knowlet/sync_state.sqlite`` (kept separate from
``index.sqlite`` so a "rebuild index" command can never lose sync
state, and from ``events.sqlite`` so audit history doesn't bloat
the high-mutation sync table).

Tables:

- ``meta(key, value)`` — schema_version, this device's stable id,
  the cached Drive ``startPageToken`` for resumable change polling.
- ``file_state(entity_type, entity_id, drive_file_id,
   last_known_etag, last_synced_at, dirty)`` — per-entity
  coordination. Slice 5.B doesn't write into it yet; the schema
  ships now so 5.C (write path) doesn't have to also re-do the
  table layout dance.

This module is **append-only**ish: there's a `clear()` for
disconnect, but no public mutation methods beyond explicit upserts /
single-key sets. SQLite locking handles concurrency; we add a
Python-level mutex so concurrent test threads don't race the cache.

Lazy imports of Google libs are NOT needed here — this module is
local-only.
"""

from __future__ import annotations

import socket
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from knowlet.core.note import new_id

# v1 → v2 (Slice 5.D.3.A): file_state gains `dismissed_until` for
# the user-visible "Snooze 24h" semantics. Conflict detection now
# computes from state-vs-Drive comparison (per ADR-0027 §UX); the
# in-memory transient-event approach was losing notifications when
# the cursor advanced past unresolved conflicts.
# v2 → v3 (#118): file_state gains `delete_intent` for tombstones
# pending Drive-side deletion. Values: None (alive), "soft" (will
# be Drive-trashed by drainer), "hard" (will be Drive-deleted).
SYNC_STATE_SCHEMA_VERSION = 3


def sync_state_db_path(vault_root: Path) -> Path:
    return vault_root / ".knowlet" / "sync_state.sqlite"


@dataclass(frozen=True)
class FileState:
    """One row of file_state — Drive-side handle for a vault entity."""

    entity_type: str
    entity_id: str
    drive_file_id: str | None
    last_known_etag: str | None
    last_synced_at: str | None  # ISO; None = never synced
    dirty: bool
    # Slice 5.D.3.A — user-driven snooze. None = no active snooze;
    # ISO timestamp = ignore conflict reports until this moment.
    # "Accept current as synced" advances last_known_etag instead
    # of using this field (semantically distinct from snooze).
    dismissed_until: str | None = None
    # #118 — Drive-side deletion tombstone. None = alive; "soft" =
    # drainer will Drive-trash next tick (30-day grace via Drive's
    # own trash); "hard" = drainer will Drive-permanently-delete.
    delete_intent: str | None = None


class SyncStateStore:
    """Thin SQLite wrapper. Connection opens lazily; closes via
    ``close()`` so pytest doesn't trip the "DB still open" warning.
    """

    def __init__(self, vault_root: Path) -> None:
        self.vault_root = vault_root
        self._path = sync_state_db_path(vault_root)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    # --------------------------------------------------- lifecycle

    def _connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS file_state (
                entity_type     TEXT NOT NULL,
                entity_id       TEXT NOT NULL,
                drive_file_id   TEXT,
                last_known_etag TEXT,
                last_synced_at  TEXT,
                dirty           INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (entity_type, entity_id)
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS file_state_drive_id_idx ON file_state(drive_file_id)"
        )
        # Lazy column add (Slice 5.D.3.A v1→v2 migration). CREATE
        # TABLE IF NOT EXISTS is a no-op on existing tables, so we
        # need explicit ALTER for any new column. Cheap: SQLite
        # ADD COLUMN is metadata-only.
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(file_state)")}
        if "dismissed_until" not in existing_cols:
            conn.execute("ALTER TABLE file_state ADD COLUMN dismissed_until TEXT")
        if "delete_intent" not in existing_cols:
            conn.execute("ALTER TABLE file_state ADD COLUMN delete_intent TEXT")
        # Schema version handshake.
        row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SYNC_STATE_SCHEMA_VERSION),),
            )
            conn.commit()
        else:
            stored = int(row[0])
            if stored > SYNC_STATE_SCHEMA_VERSION:
                raise RuntimeError(
                    f"sync_state.sqlite schema_version {stored} "
                    f"is newer than this build supports "
                    f"({SYNC_STATE_SCHEMA_VERSION}). Upgrade knowlet."
                )
            if stored < SYNC_STATE_SCHEMA_VERSION:
                # We added the column above; just stamp the new
                # version so future opens skip the ALTER attempt.
                conn.execute(
                    "UPDATE meta SET value=? WHERE key='schema_version'",
                    (str(SYNC_STATE_SCHEMA_VERSION),),
                )
        self._conn = conn
        return conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # --------------------------------------------------- meta keys

    def _get_meta(self, key: str) -> str | None:
        conn = self._connect()
        with self._lock:
            row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def _set_meta(self, key: str, value: str) -> None:
        conn = self._connect()
        with self._lock:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            conn.commit()

    def device_id(self) -> str:
        """Stable per-machine identifier. Generated as a ULID on
        first call; persisted thereafter. ADR-0027's Auto-mode
        device-detection uses this — knowlet sees ≥2 distinct
        device_ids in the synced state → switches to Strict.
        """
        existing = self._get_meta("device_id")
        if existing:
            return existing
        new = new_id()
        self._set_meta("device_id", new)
        return new

    def device_label(self) -> str:
        """Human-friendly device name. Defaults to hostname; later
        slices may let users override (so "MacBook" can become "work
        laptop"). For 5.B: hostname only."""
        cached = self._get_meta("device_label")
        if cached:
            return cached
        label = socket.gethostname() or "unknown-device"
        self._set_meta("device_label", label)
        return label

    def start_page_token(self) -> str | None:
        """The Drive ``changes.list`` cursor. None when we've never
        polled — caller must fetch an initial token first."""
        return self._get_meta("start_page_token")

    def set_start_page_token(self, token: str) -> None:
        self._set_meta("start_page_token", token)

    # --------------------------------------------------- sync mode (#107b)

    def sync_mode(self) -> str:
        """One of "auto" / "strict" / "lax". Default "auto" — current
        behavior matches "lax" (inbox only, no blocking modal); the
        cross-device heartbeat slice (#107c) will let auto promote
        itself to strict when a second device shows up."""
        cached = self._get_meta("sync_mode")
        if cached in {"auto", "strict", "lax"}:
            return cached
        return "auto"

    def set_sync_mode(self, mode: str) -> None:
        if mode not in {"auto", "strict", "lax"}:
            raise ValueError(f"invalid sync_mode: {mode!r}")
        self._set_meta("sync_mode", mode)

    # --------------------------------------------------- file_state

    @staticmethod
    def _row_to_file_state(row: tuple[Any, ...]) -> FileState:
        return FileState(
            entity_type=row[0],
            entity_id=row[1],
            drive_file_id=row[2],
            last_known_etag=row[3],
            last_synced_at=row[4],
            dirty=bool(row[5]),
            dismissed_until=row[6],
            delete_intent=row[7],
        )

    _SELECT_BY_ID_SQL = (
        "SELECT entity_type, entity_id, drive_file_id, last_known_etag, "
        "last_synced_at, dirty, dismissed_until, delete_intent "
        "FROM file_state WHERE entity_type=? AND entity_id=?"
    )
    _UPSERT_SQL = """
        INSERT INTO file_state(
            entity_type, entity_id, drive_file_id, last_known_etag,
            last_synced_at, dirty, dismissed_until, delete_intent
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(entity_type, entity_id) DO UPDATE SET
            drive_file_id    = excluded.drive_file_id,
            last_known_etag  = excluded.last_known_etag,
            last_synced_at   = excluded.last_synced_at,
            dirty            = excluded.dirty,
            dismissed_until  = excluded.dismissed_until,
            delete_intent    = excluded.delete_intent
    """
    _LIST_DIRTY_SQL = (
        "SELECT entity_type, entity_id, drive_file_id, last_known_etag, "
        "last_synced_at, dirty, dismissed_until, delete_intent "
        "FROM file_state WHERE dirty=1"
    )
    _LIST_DELETION_PENDING_SQL = (
        "SELECT entity_type, entity_id, drive_file_id, last_known_etag, "
        "last_synced_at, dirty, dismissed_until, delete_intent "
        "FROM file_state WHERE delete_intent IS NOT NULL"
    )
    _LIST_ALL_SQL = (
        "SELECT entity_type, entity_id, drive_file_id, last_known_etag, "
        "last_synced_at, dirty, dismissed_until, delete_intent FROM file_state"
    )

    def get_file_state(self, entity_type: str, entity_id: str) -> FileState | None:
        conn = self._connect()
        with self._lock:
            row = conn.execute(
                self._SELECT_BY_ID_SQL,
                (entity_type, entity_id),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_file_state(row)

    def upsert_file_state(self, state: FileState) -> None:
        """Insert or update the per-entity sync record. Used by 5.C+
        when a write succeeds (etag updates) or a remote-newer is
        detected (dirty=1). Note: ``dismissed_until`` is preserved
        across upserts unless the caller explicitly changes it —
        a successful resolve should clear the snooze (callers can
        pass `dismissed_until=None` to do that). 5.C's resolve_*
        already builds FileState without setting this field, which
        defaults to None, so the snooze is auto-cleared on resolve.
        """
        conn = self._connect()
        with self._lock:
            conn.execute(
                self._UPSERT_SQL,
                (
                    state.entity_type,
                    state.entity_id,
                    state.drive_file_id,
                    state.last_known_etag,
                    state.last_synced_at,
                    1 if state.dirty else 0,
                    state.dismissed_until,
                    state.delete_intent,
                ),
            )
            conn.commit()

    def set_dismissed_until(
        self,
        entity_type: str,
        entity_id: str,
        until: str | None,
    ) -> bool:
        """Set or clear the snooze timestamp without affecting other
        fields. ``until`` is an ISO-UTC string; pass None to unsnooze.
        Returns True if the row exists and was updated."""
        conn = self._connect()
        with self._lock:
            cur = conn.execute(
                "UPDATE file_state SET dismissed_until=? WHERE entity_type=? AND entity_id=?",
                (until, entity_type, entity_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def list_dirty(self) -> list[FileState]:
        conn = self._connect()
        with self._lock:
            rows = conn.execute(self._LIST_DIRTY_SQL).fetchall()
        return [self._row_to_file_state(r) for r in rows]

    def list_deletion_pending(self) -> list[FileState]:
        """#118 — rows the drainer needs to delete on Drive
        (soft = trash; hard = permanent)."""
        conn = self._connect()
        with self._lock:
            rows = conn.execute(self._LIST_DELETION_PENDING_SQL).fetchall()
        return [self._row_to_file_state(r) for r in rows]

    def remove_file_state(self, entity_type: str, entity_id: str) -> bool:
        """Hard-delete a sync_state row. Used after the drainer
        successfully completes a Drive deletion + after orphan
        cleanup. Returns True iff a row was removed."""
        conn = self._connect()
        with self._lock:
            cur = conn.execute(
                "DELETE FROM file_state WHERE entity_type=? AND entity_id=?",
                (entity_type, entity_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def list_all_files(self) -> list[FileState]:
        """Every file_state row. Used by the conflict computation
        path — Slice 5.D.3.A — which walks all tracked files to
        compare last_known_etag against current Drive metadata."""
        conn = self._connect()
        with self._lock:
            rows = conn.execute(self._LIST_ALL_SQL).fetchall()
        return [self._row_to_file_state(r) for r in rows]

    def count_files(self) -> int:
        conn = self._connect()
        with self._lock:
            row = conn.execute("SELECT COUNT(*) FROM file_state").fetchone()
        return int(row[0]) if row else 0

    # --------------------------------------------------- disconnect

    def clear(self) -> None:
        """Wipe sync state. Used by ``knowlet sync disconnect``
        (which also deletes credentials). ``device_id`` is preserved
        in a freshly-recreated meta table so reconnecting from the
        same machine doesn't suddenly look like a "new device" to
        the auto-detection path."""
        existing_device = self._get_meta("device_id")
        existing_label = self._get_meta("device_label")
        conn = self._connect()
        with self._lock:
            conn.execute("DELETE FROM file_state")
            conn.execute("DELETE FROM meta")
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SYNC_STATE_SCHEMA_VERSION),),
            )
            if existing_device:
                conn.execute(
                    "INSERT INTO meta(key, value) VALUES('device_id', ?)",
                    (existing_device,),
                )
            if existing_label:
                conn.execute(
                    "INSERT INTO meta(key, value) VALUES('device_label', ?)",
                    (existing_label,),
                )
            conn.commit()
