"""Regression tests for the web server's Drive-sync wiring.

Covers the drainer callbacks' "runtime not ready" signal, Drive-side
deletion of non-note files going to the trash, the auto-pull vs. stale
editor buffer guard, index refresh after every pull / merge write path,
push-failure snapshotting, and the preflight listing-failure path.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from knowlet.config import KnowletConfig, save_config
from knowlet.core.audit_log import AuditEventStore
from knowlet.core.backups import BackupStore
from knowlet.core.note import Note, new_id
from knowlet.core.sync.drainer import RuntimeNotReadyError
from knowlet.core.sync.state import FileState, SyncStateStore
from knowlet.core.sync.status import DEV_FAKE_DRIVE_FILE_ID, NoteSyncStatus
from knowlet.core.sync.tracked_files import resolve_syncable_vault_file_path
from knowlet.core.vault import Vault
from knowlet.web.server import create_app


def _vault(tmp_path: Path) -> tuple[Vault, KnowletConfig]:
    v = Vault(tmp_path, audit_log=AuditEventStore(tmp_path), backups=BackupStore(tmp_path))
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = "stub"
    save_config(v.root, cfg)
    return v, cfg


def _app(tmp_path: Path, *, init: bool = True):
    v, cfg = _vault(tmp_path)
    app = create_app(v, cfg)
    if init:
        app.state.web_state.runtime_or_init()
    return app, TestClient(app), v


def _seed_note(app, title: str = "Original", body: str = "old body") -> Note:
    runtime = app.state.web_state.runtime
    note = Note(id=new_id(), title=title, body=body)
    runtime.vault.write_note(note)
    runtime.index.upsert_note(note, chunk_size=400, chunk_overlap=40)
    return note


def _track(v: Vault, entity_type: str, entity_id: str, **kw: Any) -> None:
    store = SyncStateStore(v.root)
    try:
        store.upsert_file_state(
            FileState(
                entity_type=entity_type,
                entity_id=entity_id,
                drive_file_id=kw.get("drive_file_id", f"drive-{entity_id}"),
                last_known_etag=kw.get("etag", "rev-1"),
                last_synced_at=kw.get("last_synced_at", "2020-01-01T00:00:00Z"),
                dirty=kw.get("dirty", False),
            )
        )
    finally:
        store.close()


class _FakeDriveClient:
    def __init__(self, _creds: Any) -> None:
        pass

    def service(self) -> object:
        return object()


def _fake_drive(monkeypatch: pytest.MonkeyPatch) -> None:
    import knowlet.core.sync.credentials as creds_mod
    import knowlet.core.sync.drive_client as dc_mod

    monkeypatch.setattr(creds_mod, "load_credentials", lambda _p: object())
    monkeypatch.setattr(dc_mod, "DriveClient", _FakeDriveClient)


def _fake_pull(monkeypatch: pytest.MonkeyPatch, remote_text_for) -> list[str]:
    import knowlet.core.sync.pull as pull_mod

    pulled: list[str] = []

    def _pull(*, service, state, note_id, local_path):
        local_path.write_text(remote_text_for(note_id), encoding="utf-8")
        pulled.append(note_id)

        class _R:
            drive_file_id = f"drive-{note_id}"
            new_revision = "rev-2"
            new_bytes = b"x"

        return _R()

    monkeypatch.setattr(pull_mod, "pull_note_to_local", _pull)
    return pulled


def _remote_version(note: Note, *, title: str, body: str) -> str:
    remote = Note(
        id=note.id,
        title=title,
        body=body,
        created_at=note.created_at,
        updated_at="2030-01-01T00:00:00Z",
    )
    return remote.to_markdown()


def _status(state: str) -> NoteSyncStatus:
    return NoteSyncStatus(
        state=state,  # type: ignore[arg-type]
        last_synced_at=None,
        drive_file_id="drive-x",
        last_known_revision="rev-1",
        current_drive_revision="rev-2",
        detail=None,
    )


# ----------------------------------------------- drainer: runtime not ready


def test_drainer_callbacks_signal_runtime_not_ready(tmp_path: Path) -> None:
    app, _client, _v = _app(tmp_path, init=False)
    drainer = app.state.web_state.push_drainer
    assert app.state.web_state.runtime is None
    with pytest.raises(RuntimeNotReadyError):
        drainer.note_lookup("01ANYTHING")
    with pytest.raises(RuntimeNotReadyError):
        drainer.attachment_lookup("01ANY.png")
    with pytest.raises(RuntimeNotReadyError):
        drainer.synced_file_lookup("card", "abc.json")
    with pytest.raises(RuntimeNotReadyError):
        drainer.untracked_sweep()


def test_drainer_callbacks_return_none_for_missing_files_once_ready(tmp_path: Path) -> None:
    app, _client, _v = _app(tmp_path)
    drainer = app.state.web_state.push_drainer
    assert drainer.note_lookup("01MISSING") is None
    assert drainer.attachment_lookup("01MISSING.png") is None
    assert drainer.synced_file_lookup("card", "missing.json") is None
    assert not [item for item in drainer.untracked_sweep() if item[0] == "note"]


# ----------------------------------------------- preflight callbacks


def _capture_preflight(monkeypatch: pytest.MonkeyPatch, report_factory=None) -> dict:
    import knowlet.core.sync.preflight as pf_mod

    captured: dict = {}
    real = pf_mod.preflight_scan

    def _scan(**kw):
        captured.update(kw)
        if report_factory is not None:
            return report_factory(**kw)
        return real(**{**kw, "materialize_drive_file": None})

    monkeypatch.setattr(pf_mod, "preflight_scan", _scan)
    return captured


def _empty_report(auto_pulled_ids: list[str] | None = None):
    from knowlet.core.sync.preflight import PreflightReport

    return PreflightReport(
        conflicts=[],
        offline=[],
        auto_pulled_ids=list(auto_pulled_ids or []),
        synced_count=0,
        dirty_count=0,
        scanned=0,
        unauthenticated=True,
        alive_devices=[],
    )


def test_drive_deleted_card_is_moved_to_trash_not_unlinked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, client, v = _app(tmp_path)
    card = resolve_syncable_vault_file_path(v.root, "card", "c1.json")
    assert card is not None
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text('{"front": "q", "back": "a"}', encoding="utf-8")
    _track(v, "card", "c1.json")
    captured = _capture_preflight(monkeypatch, lambda **_kw: _empty_report())
    assert client.post("/api/sync/preflight").status_code == 200

    captured["delete_local_vault_file_for_drive_deleted"]("card", "c1.json")

    assert not card.exists()
    trashed = list(v.trash_dir.rglob("c1*.json"))
    assert len(trashed) == 1
    assert trashed[0].read_text(encoding="utf-8") == '{"front": "q", "back": "a"}'
    store = SyncStateStore(v.root)
    try:
        assert store.get_file_state("card", "c1.json") is None
    finally:
        store.close()


def test_preflight_without_runtime_passes_no_destructive_callbacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, client, _v = _app(tmp_path, init=False)
    # Keep the endpoint from bootstrapping on its own.
    app.state.web_state.bootstrap_status = "running"
    captured = _capture_preflight(monkeypatch, lambda **_kw: _empty_report())
    assert client.post("/api/sync/preflight").status_code == 200
    assert captured["trash_local_for_drive_deleted"] is None
    assert captured["delete_local_vault_file_for_drive_deleted"] is None
    assert captured["materialize_drive_file"] is None


def test_preflight_drive_listing_failure_deletes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """server.py:2318 — the endpoint wires destructive callbacks; a failed
    Drive listing must not turn into "everything was deleted remotely"."""
    import knowlet.core.sync.files as files_mod
    import knowlet.core.sync.preflight as pf_mod
    import knowlet.core.sync.status as status_mod

    app, client, v = _app(tmp_path)
    note = _seed_note(app)
    _track(v, "note", note.id)
    card = resolve_syncable_vault_file_path(v.root, "card", "c1.json")
    assert card is not None
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text("{}", encoding="utf-8")
    _track(v, "card", "c1.json")

    monkeypatch.setattr(pf_mod, "_maybe_heartbeat_pass", lambda **_kw: object())

    def _boom(_service):
        raise RuntimeError("429 rate limited")

    monkeypatch.setattr(files_mod, "list_appdata_revisions", _boom)
    monkeypatch.setattr(status_mod, "compute_note_sync_status", lambda **_kw: _status("synced"))
    monkeypatch.setattr(pf_mod, "compute_note_sync_status", lambda **_kw: _status("synced"))

    r = client.post("/api/sync/preflight")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["trashed_for_drive_delete_ids"] == []
    assert body["deleted_for_drive_delete_ids"] == []
    assert note.path is not None and note.path.exists()
    assert card.exists()


# ----------------------------------------------- push-errors snapshot


def test_push_errors_survives_concurrent_failure_updates(tmp_path: Path) -> None:
    app, client, _v = _app(tmp_path)
    state = app.state.web_state
    drainer = state.push_drainer
    drainer.failures.update(
        {
            "a": {"count": 1, "last_error": "e", "last_attempt_at": "t"},
            "b": {"count": 1, "last_error": "e", "last_attempt_at": "t"},
        }
    )
    runtime = state.runtime
    real_meta = runtime.index.get_note_meta
    calls = {"n": 0}

    def _meta_while_drainer_ticks(note_id: str):
        # The drainer thread records a new failure while the request
        # thread is mid-iteration (index I/O releases the GIL).
        calls["n"] += 1
        drainer.failures[f"new-{calls['n']}"] = {"count": 1}
        return real_meta(note_id)

    runtime.index.get_note_meta = _meta_while_drainer_ticks  # type: ignore[method-assign]
    r = client.get("/api/sync/push-errors")
    assert r.status_code == 200
    assert {e["note_id"] for e in r.json()["errors"]} >= {"a", "b"}


# ----------------------------------------------- auto-pull vs. editor buffer


def test_note_status_reports_auto_pull_and_refreshes_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import knowlet.core.sync.status as status_mod

    app, client, v = _app(tmp_path)
    note = _seed_note(app)
    _track(v, "note", note.id)
    _fake_drive(monkeypatch)
    pulled = _fake_pull(
        monkeypatch, lambda _id: _remote_version(note, title="Remote Title", body="remote body")
    )
    states = iter([_status("stale"), _status("synced")])
    monkeypatch.setattr(status_mod, "compute_note_sync_status", lambda **_kw: next(states))

    r = client.get(f"/api/sync/note-status/{note.id}")
    assert r.status_code == 200
    body = r.json()
    assert pulled == [note.id]
    assert body["state"] == "synced"
    assert body["auto_pulled"] is True
    meta = app.state.web_state.runtime.index.get_note_meta(note.id)
    assert meta["title"] == "Remote Title"


def test_note_status_without_pull_reports_auto_pulled_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import knowlet.core.sync.status as status_mod

    app, client, _v = _app(tmp_path)
    note = _seed_note(app)
    monkeypatch.setattr(status_mod, "compute_note_sync_status", lambda **_kw: _status("synced"))
    body = client.get(f"/api/sync/note-status/{note.id}").json()
    assert body["auto_pulled"] is False


def test_put_with_stale_base_updated_at_is_rejected(tmp_path: Path) -> None:
    app, client, _v = _app(tmp_path)
    note = _seed_note(app)
    loaded = client.get(f"/api/notes/{note.id}").json()
    # Another device's edit lands on disk (what auto-pull does).
    assert note.path is not None
    note.path.write_text(
        _remote_version(note, title="Remote Title", body="remote edit"), encoding="utf-8"
    )

    r = client.put(
        f"/api/notes/{note.id}",
        json={
            "title": loaded["title"],
            "tags": [],
            "body": loaded["body"] + " typed",
            "base_updated_at": loaded["updated_at"],
        },
    )
    assert r.status_code == 409
    assert "remote edit" in note.path.read_text(encoding="utf-8")


def test_put_with_current_base_updated_at_succeeds(tmp_path: Path) -> None:
    app, client, _v = _app(tmp_path)
    note = _seed_note(app)
    loaded = client.get(f"/api/notes/{note.id}").json()
    r = client.put(
        f"/api/notes/{note.id}",
        json={
            "title": "T",
            "tags": [],
            "body": "new",
            "base_updated_at": loaded["updated_at"],
        },
    )
    assert r.status_code == 200, r.text
    # Legacy clients without a base keep working.
    r2 = client.put(f"/api/notes/{note.id}", json={"title": "T", "tags": [], "body": "newer"})
    assert r2.status_code == 200


# ----------------------------------------------- index refresh after pulls


def test_explicit_note_pull_refreshes_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, client, v = _app(tmp_path)
    note = _seed_note(app)
    _track(v, "note", note.id)
    _fake_drive(monkeypatch)
    _fake_pull(monkeypatch, lambda _id: _remote_version(note, title="Pulled", body="b"))
    r = client.post(f"/api/sync/note-pull/{note.id}")
    assert r.status_code == 200, r.text
    assert app.state.web_state.runtime.index.get_note_meta(note.id)["title"] == "Pulled"


def test_note_pull_local_changed_maps_to_409(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import knowlet.core.sync.pull as pull_mod

    app, client, v = _app(tmp_path)
    note = _seed_note(app)
    _track(v, "note", note.id)
    _fake_drive(monkeypatch)

    def _raise(**_kw):
        raise pull_mod.PullLocalChangedError("changed while pulling")

    monkeypatch.setattr(pull_mod, "pull_note_to_local", _raise)
    r = client.post(f"/api/sync/note-pull/{note.id}")
    assert r.status_code == 409


def test_preflight_auto_pulled_notes_are_reindexed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, client, _v = _app(tmp_path)
    note = _seed_note(app)

    def _report(**_kw):
        assert note.path is not None
        note.path.write_text(
            _remote_version(note, title="Preflight Pulled", body="b"), encoding="utf-8"
        )
        return _empty_report(auto_pulled_ids=[note.id, "cards/not-a-note.json"])

    _capture_preflight(monkeypatch, _report)
    assert client.post("/api/sync/preflight").status_code == 200
    meta = app.state.web_state.runtime.index.get_note_meta(note.id)
    assert meta["title"] == "Preflight Pulled"


def test_resolve_merge_refreshes_index(tmp_path: Path) -> None:
    app, client, v = _app(tmp_path)
    note = _seed_note(app, title="Mine", body="mine body")
    fake = v.root / ".knowlet" / "dev_conflicts" / f"{note.id}.md"
    fake.parent.mkdir(parents=True, exist_ok=True)
    fake.write_text(_remote_version(note, title="Mine", body="theirs body"), encoding="utf-8")
    _track(v, "note", note.id, drive_file_id=DEV_FAKE_DRIVE_FILE_ID)

    r = client.post(
        f"/api/sync/resolve-merge/{note.id}",
        json={"merged_text": "merged zebracorn body"},
    )
    assert r.status_code == 200, r.text
    hits = app.state.web_state.runtime.index.search("zebracorn", top_k=5)
    assert any(h.note_id == note.id for h in hits)


def test_drainer_lookup_errors_are_not_swallowed_as_missing(tmp_path: Path) -> None:
    """A note that exists must be returned; only a truly absent file is None."""
    app, _client, _v = _app(tmp_path)
    note = _seed_note(app)
    found = app.state.web_state.push_drainer.note_lookup(note.id)
    assert found is not None and found.id == note.id
    assert os.path.exists(found.path)
