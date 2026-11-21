"""Regression tests for the misc-core audit batch — AuditEventStore.

- ``query(limit=N)`` must return the N *most recent* matching events
  (still in oldest-first order), not the N oldest. Consumers: the
  Settings ai.call trace viewer, the ``recent-activity`` LLM layer and
  ``knowlet events list --limit``.
- Lazy connection setup must be race-free: concurrent first writes on a
  shared store used to each open a connection and race the
  schema_version insert (IntegrityError → lost event + leaked conn).
"""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from pathlib import Path

import pytest

from knowlet.core import audit_log as audit_mod
from knowlet.core.audit_log import AuditEvent, AuditEventStore


def _ev(ts: str, entity_id: str, kind: str = "note.created") -> AuditEvent:
    return AuditEvent(ts=ts, kind=kind, entity_type="note", entity_id=entity_id)


def test_query_limit_returns_most_recent_events_oldest_first(tmp_path: Path) -> None:
    store = AuditEventStore(tmp_path)
    try:
        for i in range(10):
            store.append(_ev(f"2026-11-{i + 1:02d}T00:00:00Z", f"n{i}"))

        got = store.query(limit=3)

        assert [e.entity_id for e in got] == ["n7", "n8", "n9"]
    finally:
        store.close()


def test_query_limit_with_filters_and_since(tmp_path: Path) -> None:
    store = AuditEventStore(tmp_path)
    try:
        for i in range(10):
            store.append(_ev(f"2026-11-{i + 1:02d}T00:00:00Z", f"c{i}", kind="ai.call"))
            store.append(_ev(f"2026-11-{i + 1:02d}T00:00:01Z", f"u{i}", kind="note.updated"))

        calls = store.query(kinds=["ai.call"], limit=2)
        assert [e.entity_id for e in calls] == ["c8", "c9"]

        window = store.query(since="2026-11-05T00:00:00Z", limit=3)
        assert [e.entity_id for e in window] == ["u8", "c9", "u9"]
    finally:
        store.close()


def test_query_same_timestamp_tie_breaks_by_insertion(tmp_path: Path) -> None:
    store = AuditEventStore(tmp_path)
    try:
        for i in range(5):
            store.append(_ev("2026-11-01T00:00:00Z", f"n{i}"))
        assert [e.entity_id for e in store.query(limit=2)] == ["n3", "n4"]
    finally:
        store.close()


def test_query_without_limit_unchanged(tmp_path: Path) -> None:
    store = AuditEventStore(tmp_path)
    try:
        for i in range(4):
            store.append(_ev(f"2026-11-{i + 1:02d}T00:00:00Z", f"n{i}"))
        assert [e.entity_id for e in store.query()] == ["n0", "n1", "n2", "n3"]
    finally:
        store.close()


def test_concurrent_first_appends_share_one_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Force two threads to be inside connection setup at the same time
    (if the implementation lets them). Both events must land and only
    one connection may be opened."""
    real_connect = sqlite3.connect
    barrier = threading.Barrier(2, timeout=0.5)
    opened: list[sqlite3.Connection] = []
    opened_lock = threading.Lock()

    def slow_connect(*args, **kwargs):  # type: ignore[no-untyped-def]
        conn = real_connect(*args, **kwargs)
        with opened_lock:
            opened.append(conn)
        with contextlib.suppress(threading.BrokenBarrierError):
            barrier.wait()
        return conn

    monkeypatch.setattr(audit_mod.sqlite3, "connect", slow_connect)

    store = AuditEventStore(tmp_path)
    errors: list[BaseException] = []

    def worker(i: int) -> None:
        try:
            store.append(_ev("2026-11-21T00:00:00Z", f"n{i}"))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert errors == []
        assert len(opened) == 1
        assert store.count() == 2
    finally:
        store.close()
        for conn in opened:
            conn.close()


class _RacingConnection:
    """Proxy that lets a competing initializer write the schema_version
    row right after our SELECT saw it missing (two processes opening a
    fresh events.sqlite at the same moment)."""

    def __init__(self, real: sqlite3.Connection, db_path: Path) -> None:
        self._real = real
        self._db_path = db_path

    def execute(self, sql: str, *args):  # type: ignore[no-untyped-def]
        cur = self._real.execute(sql, *args)
        if "FROM meta WHERE key = 'schema_version'" in sql:
            rows = cur.fetchall()
            other = sqlite3.connect(self._db_path)
            other.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?)",
                (str(audit_mod.EVENTS_SCHEMA_VERSION),),
            )
            other.commit()
            other.close()
            return _FixedCursor(rows)
        return cur

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        return getattr(self._real, name)


class _FixedCursor:
    def __init__(self, rows: list[tuple]) -> None:  # type: ignore[type-arg]
        self._rows = rows

    def fetchone(self):  # type: ignore[no-untyped-def]
        return self._rows[0] if self._rows else None


def test_schema_version_insert_tolerates_concurrent_initializer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_connect = sqlite3.connect
    db_path = audit_mod.events_db_path(tmp_path)

    def racing_connect(*args, **kwargs):  # type: ignore[no-untyped-def]
        return _RacingConnection(real_connect(*args, **kwargs), db_path)

    monkeypatch.setattr(audit_mod.sqlite3, "connect", racing_connect)
    store = AuditEventStore(tmp_path)
    try:
        store.append(_ev("2026-11-21T00:00:00Z", "a"))
        assert store.count() == 1
    finally:
        store.close()
