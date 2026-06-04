"""Phase 2 E Slice 4.B — Vault audit log (ADR-0023 §3 + ADR-0018).

A vault-scoped, append-only record of structural changes:

- ``note.created`` / ``note.updated`` / ``note.deleted`` / ``note.restored``
- ``draft.proposed`` / ``draft.approved`` / ``draft.rejected``  (Phase 3+)
- ``chat.sediment_committed``                                    (Phase 3+)
- ``source.ingested``                                            (Phase 3+)
- ``lint.run``                                                   (Phase 3+)
- ``quiz.session.completed``                                     (Phase 3+)

Events live in ``vault/.knowlet/events.sqlite`` (separate from
``index.sqlite`` so a "rebuild index" command can never wipe history).
A markdown view is rendered on demand to ``vault/.knowlet/log.md``.

This module is the **substrate**. The concrete event-emission hooks
live in the producer modules (Vault, Drafts, Quiz, etc.) — they each
take an ``AuditEventStore | None`` and emit through it. ``None`` is
the no-op store, used in tests / CLI scripts that don't care.

Why a separate file from ``knowlet.core.events``: that module carries
**transient chat streaming events** (tool_call / reply_chunk) that
flow over SSE and never persist. The two concerns share the word
"event" but nothing else.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from knowlet.core.note import new_id, now_iso

# ----------------------------------------------------------- schema

# Bump on any breaking change to the events table — column type, new
# required column, or rename. Old code reading a higher schema_version
# will fail loudly rather than silently dropping data (per ADR-0018
# §1: 1 major backward compat is enforced via the schema_version
# migration code path, not by tolerating unknown shapes).
EVENTS_SCHEMA_VERSION = 1

# Event-kind names are namespaced ``<entity>.<verb>``. The full list
# is open-ended; producers register strings as they need. We don't
# constrain it here so this module can ship before all producers are
# instrumented (Slice 4.B covers Note; later slices add the rest).
ActorKind = Literal["user", "llm", "system"]


@dataclass
class AuditEvent:
    """One row of the audit log.

    ``id`` is a ULID assigned at construction time. ``ts`` is the
    UTC ISO-8601 timestamp captured on construction; we don't trust
    callers to backdate (no provenance for that until we have a
    multi-actor model).
    """

    kind: str
    entity_type: str
    entity_id: str
    actor: ActorKind = "user"
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=new_id)
    ts: str = field(default_factory=now_iso)


def events_db_path(vault_root: Path) -> Path:
    """Where the audit log lives. Separate from the search index so a
    `knowlet doctor reindex` can never wipe history."""
    return vault_root / ".knowlet" / "events.sqlite"


def log_md_path(vault_root: Path) -> Path:
    """Markdown rendering of the audit log (rendered on demand). The
    rendered file is regenerated wholesale on each call — never edited
    in place. ADR-0023 §3 says the user sees this view; the SQLite
    table is the source of truth."""
    return vault_root / ".knowlet" / "log.md"


# ----------------------------------------------------------- store


class AuditEventStore:
    """Append-only audit log backed by SQLite.

    Concurrency: SQLite handles serialization for single-file writes,
    but we wrap the connection in a per-store lock so the Python
    layer doesn't reorder appends from concurrent threads (the web
    server's request workers + an inline write from the CLI both hit
    the same store).

    Connection lifetime: opened lazily on first append/query, closed
    by ``close()``. Tests should call ``close()`` in teardown so
    pytest doesn't trip the "DB still open" warning.
    """

    def __init__(self, vault_root: Path) -> None:
        self.vault_root = vault_root
        self._path = events_db_path(vault_root)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------- lifecycle

    def _connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        # Schema. Note: id is the PK so we get unique-id enforcement
        # for free; ts is indexed because tail/range queries are the
        # common access pattern. payload is JSON-as-TEXT (sqlite has
        # JSON1 but we don't need anything beyond round-trip).
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
            CREATE TABLE IF NOT EXISTS events (
                id          TEXT PRIMARY KEY,
                ts          TEXT NOT NULL,
                kind        TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id   TEXT NOT NULL,
                actor       TEXT NOT NULL,
                payload     TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS events_ts_idx ON events(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS events_kind_idx ON events(kind)")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS events_entity_idx ON events(entity_type, entity_id)"
        )
        # Schema version handshake.
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?)",
                (str(EVENTS_SCHEMA_VERSION),),
            )
        else:
            stored = int(row[0])
            if stored > EVENTS_SCHEMA_VERSION:
                raise RuntimeError(
                    f"events.sqlite schema_version {stored} is newer than "
                    f"this knowlet build supports ({EVENTS_SCHEMA_VERSION}). "
                    "Upgrade knowlet."
                )
            # stored == EVENTS_SCHEMA_VERSION → fine.
            # stored < EVENTS_SCHEMA_VERSION → migration would run here
            # when v2 lands. For now there's no v2.
        conn.commit()
        self._conn = conn
        return conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # ------------------------------------------------------- mutations

    def append(self, event: AuditEvent) -> AuditEvent:
        """Insert a row. Returns the same event so callers can chain."""
        conn = self._connect()
        with self._lock:
            conn.execute(
                """
                INSERT INTO events(id, ts, kind, entity_type, entity_id,
                                   actor, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.ts,
                    event.kind,
                    event.entity_type,
                    event.entity_id,
                    event.actor,
                    json.dumps(event.payload, ensure_ascii=False),
                ),
            )
            conn.commit()
        return event

    # ------------------------------------------------------- queries

    def count(self) -> int:
        conn = self._connect()
        with self._lock:
            row = conn.execute("SELECT COUNT(*) FROM events").fetchone()
        return int(row[0]) if row else 0

    def query(
        self,
        *,
        kinds: list[str] | None = None,
        entity_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int | None = None,
    ) -> list[AuditEvent]:
        """Filter by kind list / entity / time window. Results are
        sorted by ts ASCENDING (oldest first) so callers can easily
        replay. Apply ``reversed()`` for "most recent first"
        rendering."""
        conn = self._connect()
        clauses: list[str] = []
        args: list[Any] = []
        if kinds:
            placeholders = ",".join("?" * len(kinds))
            clauses.append(f"kind IN ({placeholders})")
            args.extend(kinds)
        if entity_id:
            clauses.append("entity_id = ?")
            args.append(entity_id)
        if since:
            clauses.append("ts >= ?")
            args.append(since)
        if until:
            clauses.append("ts <= ?")
            args.append(until)
        sql = "SELECT id, ts, kind, entity_type, entity_id, actor, payload FROM events"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY ts ASC, rowid ASC"
        if limit is not None:
            sql += " LIMIT ?"
            args.append(int(limit))
        with self._lock:
            rows = conn.execute(sql, args).fetchall()
        return [_row_to_event(r) for r in rows]

    def tail(self, n: int) -> list[AuditEvent]:
        """Last ``n`` events, oldest-first."""
        conn = self._connect()
        with self._lock:
            rows = conn.execute(
                "SELECT id, ts, kind, entity_type, entity_id, actor, payload "
                "FROM events ORDER BY rowid DESC LIMIT ?",
                (int(n),),
            ).fetchall()
        # Reverse so the caller renders in chronological order.
        return [_row_to_event(r) for r in reversed(rows)]

    def iter_all(self) -> Iterator[AuditEvent]:
        """Stream every event in insertion order. For backups / migrations."""
        conn = self._connect()
        with self._lock:
            cur = conn.execute(
                "SELECT id, ts, kind, entity_type, entity_id, actor, payload "
                "FROM events ORDER BY rowid ASC"
            )
            for row in cur:
                yield _row_to_event(row)

    # ------------------------------------------------------- rendering

    def render_log_md(self, *, limit: int = 200) -> Path:
        """Regenerate ``vault/.knowlet/log.md`` with the most recent
        ``limit`` events, newest-first. Returns the path written.

        The file is rewritten in full each call (atomic via .tmp +
        rename). It's a *view*, not the source of truth — the SQLite
        table is. ADR-0023 §3 calls out the rendered view as what
        the user actually opens in their editor.
        """
        events = self.tail(limit)
        out = log_md_path(self.vault_root)
        out.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = [
            "# Vault Activity Log",
            "",
            f"_Last {min(limit, len(events))} events; full history in `events.sqlite`._",
            "",
        ]
        # Newest first.
        for ev in reversed(events):
            payload_summary = _summarize_payload(ev)
            lines.append(
                f"- `{ev.ts}` **{ev.kind}** · {ev.entity_type}/{ev.entity_id}"
                + (f" — {payload_summary}" if payload_summary else "")
            )
        tmp = out.with_suffix(out.suffix + ".tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.replace(out)
        return out


# ----------------------------------------------------------- helpers


def _row_to_event(row: tuple[Any, ...]) -> AuditEvent:
    id_, ts, kind, entity_type, entity_id, actor, payload_json = row
    payload = json.loads(payload_json) if payload_json else {}
    return AuditEvent(
        id=id_,
        ts=ts,
        kind=kind,
        entity_type=entity_type,
        entity_id=entity_id,
        actor=actor,
        payload=payload,
    )


def _summarize_payload(ev: AuditEvent) -> str:
    """One-line human-friendly summary for the markdown rendering.
    Keys we know about get pretty rendering; unknown keys fall back
    to a compact JSON-ish string.
    """
    if not ev.payload:
        return ""
    if "title" in ev.payload:
        title = ev.payload["title"]
        rest = {k: v for k, v in ev.payload.items() if k != "title"}
        if not rest:
            return f'"{title}"'
        return f'"{title}" ({_compact(rest)})'
    return _compact(ev.payload)


def _compact(d: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in d.items())
