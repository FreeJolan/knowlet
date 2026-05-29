"""Phase 2 E Slice 4.B — vault audit log (ADR-0023 §3 + ADR-0018).

Covers:
- AuditEventStore append + query round-trip + schema versioning.
- Producer hooks on Vault: write_note / trash_note / restore_note
  emit the right events with the right payloads.
- log.md rendering.
- /api/events endpoint round-trip.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from knowlet.core.audit_log import (
    EVENTS_SCHEMA_VERSION,
    AuditEvent,
    AuditEventStore,
    events_db_path,
    log_md_path,
)
from knowlet.core.note import Note, new_id
from knowlet.core.vault import Vault

# ----------------------------------------------------- store unit tests


def test_round_trip_append_and_query(tmp_path: Path) -> None:
    store = AuditEventStore(tmp_path)
    try:
        ev = AuditEvent(
            kind="note.created",
            entity_type="note",
            entity_id="abc",
            payload={"title": "Hello", "folder": "daily"},
        )
        store.append(ev)
        got = store.query()
        assert len(got) == 1
        assert got[0].kind == "note.created"
        assert got[0].entity_id == "abc"
        assert got[0].payload == {"title": "Hello", "folder": "daily"}
        assert got[0].id == ev.id  # ULID preserved on round-trip
    finally:
        store.close()


def test_writes_create_db_file(tmp_path: Path) -> None:
    store = AuditEventStore(tmp_path)
    try:
        assert not events_db_path(tmp_path).exists()
        store.append(
            AuditEvent(kind="note.created", entity_type="note", entity_id="x")
        )
        assert events_db_path(tmp_path).exists()
    finally:
        store.close()


def test_schema_version_persisted(tmp_path: Path) -> None:
    store = AuditEventStore(tmp_path)
    store.append(
        AuditEvent(kind="note.created", entity_type="note", entity_id="x")
    )
    store.close()
    # Re-open — schema_version handshake must NOT crash.
    store2 = AuditEventStore(tmp_path)
    try:
        assert store2.count() == 1
    finally:
        store2.close()
    # Tamper with stored schema_version: simulate "we somehow loaded a
    # newer DB". Re-opening must raise (per ADR-0018 §1: code never
    # silently downgrades data).
    import sqlite3

    conn = sqlite3.connect(events_db_path(tmp_path))
    conn.execute(
        "UPDATE meta SET value = ? WHERE key = 'schema_version'",
        (str(EVENTS_SCHEMA_VERSION + 5),),
    )
    conn.commit()
    conn.close()
    store3 = AuditEventStore(tmp_path)
    with pytest.raises(RuntimeError, match="schema_version"):
        store3.append(
            AuditEvent(kind="note.created", entity_type="note", entity_id="y")
        )
    store3.close()


def test_query_filters(tmp_path: Path) -> None:
    store = AuditEventStore(tmp_path)
    try:
        ids = ["n1", "n2", "n3"]
        for nid in ids:
            store.append(
                AuditEvent(
                    kind="note.created", entity_type="note", entity_id=nid
                )
            )
            store.append(
                AuditEvent(
                    kind="note.updated", entity_type="note", entity_id=nid
                )
            )
        # Filter by kind.
        got = store.query(kinds=["note.created"])
        assert len(got) == 3
        assert all(e.kind == "note.created" for e in got)
        # Filter by entity.
        got = store.query(entity_id="n2")
        assert len(got) == 2
        assert {e.kind for e in got} == {"note.created", "note.updated"}
        # Both filters AND together.
        got = store.query(kinds=["note.updated"], entity_id="n2")
        assert len(got) == 1
        # Limit caps the result.
        got = store.query(limit=4)
        assert len(got) == 4
    finally:
        store.close()


def test_tail_returns_oldest_first_within_slice(tmp_path: Path) -> None:
    store = AuditEventStore(tmp_path)
    try:
        for i in range(5):
            store.append(
                AuditEvent(
                    kind="note.created",
                    entity_type="note",
                    entity_id=f"n{i}",
                )
            )
        last3 = store.tail(3)
        assert [e.entity_id for e in last3] == ["n2", "n3", "n4"]
    finally:
        store.close()


def test_render_log_md(tmp_path: Path) -> None:
    store = AuditEventStore(tmp_path)
    try:
        store.append(
            AuditEvent(
                kind="note.created",
                entity_type="note",
                entity_id="abc",
                payload={"title": "Hello", "folder": "daily"},
            )
        )
        out = store.render_log_md(limit=10)
        assert out == log_md_path(tmp_path)
        text = out.read_text(encoding="utf-8")
        assert "# Vault Activity Log" in text
        assert "note.created" in text
        assert "note/abc" in text
        assert "Hello" in text
    finally:
        store.close()


def test_iter_all_streams_in_insertion_order(tmp_path: Path) -> None:
    store = AuditEventStore(tmp_path)
    try:
        for i in range(3):
            store.append(
                AuditEvent(
                    kind="note.created",
                    entity_type="note",
                    entity_id=f"n{i}",
                )
            )
        ids = [e.entity_id for e in store.iter_all()]
        assert ids == ["n0", "n1", "n2"]
    finally:
        store.close()


def test_no_mutation_api_exposed() -> None:
    """Append-only contract: the store class must NOT expose any
    public mutation method beyond ``append``. Migrations / repair
    tools open SQLite directly — the API is read-only."""
    public_methods = {
        m for m in dir(AuditEventStore) if not m.startswith("_")
    }
    forbidden = {"update", "delete", "remove", "drop", "clear"}
    leaks = public_methods & forbidden
    assert not leaks, f"audit log must stay append-only; got mutation methods: {leaks}"


# ----------------------------------------------------- Vault producer hooks


def _vault_with_audit(tmp_path: Path) -> tuple[Vault, AuditEventStore]:
    vault_root = tmp_path / "v"
    vault_root.mkdir()
    audit = AuditEventStore(vault_root)
    vault = Vault(vault_root, audit_log=audit)
    return vault, audit


def test_write_note_emits_created_then_updated(tmp_path: Path) -> None:
    vault, audit = _vault_with_audit(tmp_path)
    try:
        note = Note(id=new_id(), title="A", body="alpha")
        vault.write_note(note, folder="daily")
        # Update — same id, new body.
        note.body = "alpha v2"
        vault.write_note(note)
        events = audit.query(entity_id=note.id)
        kinds = [e.kind for e in events]
        assert kinds == ["note.created", "note.updated"]
        assert events[0].payload["title"] == "A"
        assert events[0].payload["folder"] == "daily"
    finally:
        audit.close()


def test_trash_note_emits_deleted_then_restore_emits_restored(
    tmp_path: Path,
) -> None:
    vault, audit = _vault_with_audit(tmp_path)
    try:
        note = Note(id=new_id(), title="B", body="b")
        path = vault.write_note(note, folder="weekly")
        trashed = vault.trash_note(path)
        vault.restore_note(trashed)
        events = audit.query(entity_id=note.id)
        kinds = [e.kind for e in events]
        assert kinds == [
            "note.created",
            "note.deleted",
            "note.restored",
        ]
        # `from_folder` carries through delete; `to_folder` carries
        # through restore. Both should be `weekly` for this test.
        del_ev = next(e for e in events if e.kind == "note.deleted")
        assert del_ev.payload.get("from_folder") == "weekly"
        restore_ev = next(e for e in events if e.kind == "note.restored")
        assert restore_ev.payload.get("to_folder") == "weekly"
    finally:
        audit.close()


def test_audit_failure_does_not_break_writes(tmp_path: Path) -> None:
    """If the audit log throws (corrupted DB, disk full…), Vault
    write_note must STILL succeed. The audit trail is best-effort
    around the user's actual work."""
    vault_root = tmp_path / "v"
    vault_root.mkdir()
    # Sabotage: a fake store whose append raises.

    class BrokenAudit:
        def append(self, *_a: object, **_kw: object) -> None:
            raise RuntimeError("audit blew up")

    vault = Vault(vault_root, audit_log=BrokenAudit())  # type: ignore[arg-type]
    note = Note(id=new_id(), title="resilient", body="x")
    path = vault.write_note(note, folder="daily")
    assert path.exists()
    assert path.read_text(encoding="utf-8").startswith("---")


# ----------------------------------------------------- /api/events endpoint


def test_api_events_endpoint_round_trip(tmp_path: Path) -> None:
    from tests.test_web import StubLLM, _client_with_stub

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    runtime = client.app.state.web_state.runtime_or_init()
    # Drive the producer side via the Vault attached to runtime.
    note = Note(id=new_id(), title="API", body="x")
    runtime.vault.write_note(note, folder="daily")
    # Read back via the endpoint.
    resp = client.get("/api/events")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] >= 1
    kinds = [e["kind"] for e in body["events"]]
    assert "note.created" in kinds
    # Filter via the query string.
    resp2 = client.get(
        "/api/events", params={"kind": ["note.created"], "entity_id": note.id}
    )
    assert resp2.status_code == 200
    assert all(e["entity_id"] == note.id for e in resp2.json()["events"])
