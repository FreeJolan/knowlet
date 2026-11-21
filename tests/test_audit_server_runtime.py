"""Regression tests for the web server's runtime lifecycle.

Covers: bootstrap failure being logged and recoverable from the UI,
background services (mining scheduler + digest auto-pull) starting once an
API key is configured at runtime, /api/system/reindex closing the old
Index before deleting the DB, and vault import while the runtime is not
ready / reusing the loaded embedding backend.
"""

from __future__ import annotations

import io
import logging
import time
import zipfile
from pathlib import Path
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

from knowlet.config import KnowletConfig, save_config
from knowlet.core.index import IndexDimensionMismatchError
from knowlet.core.note import Note, new_id
from knowlet.core.vault import Vault
from knowlet.web import server as server_mod
from knowlet.web.server import create_app


def _vault(tmp_path: Path, *, api_key: str = "stub") -> tuple[Vault, KnowletConfig]:
    v = Vault(tmp_path)
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = api_key
    save_config(v.root, cfg)
    return v, cfg


def _wait_for(predicate, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met in time")


class _FakeScheduler:
    instances: ClassVar[list[_FakeScheduler]] = []

    def __init__(self, *_a, **_kw) -> None:
        self.started = False
        self.stopped = False
        _FakeScheduler.instances.append(self)

    def start(self) -> int:
        self.started = True
        return 0

    def shutdown(self) -> None:
        self.stopped = True

    def reload(self) -> int:
        return 0


@pytest.fixture()
def fake_background(monkeypatch: pytest.MonkeyPatch) -> list[_FakeScheduler]:
    import knowlet.core.digest_pull as digest_pull_mod

    _FakeScheduler.instances = []
    monkeypatch.setattr(server_mod, "MiningScheduler", _FakeScheduler)
    monkeypatch.setattr(digest_pull_mod, "maybe_auto_pull_digest_sources", lambda **_kw: None)
    return _FakeScheduler.instances


# ------------------------------------------------ bootstrap failure recovery


def _failing_once(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> dict:
    real = server_mod.bootstrap_chat
    calls = {"n": 0}

    def _bootstrap(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise exc
        return real(*a, **kw)

    monkeypatch.setattr(server_mod, "bootstrap_chat", _bootstrap)
    return calls


def test_bootstrap_failure_is_logged_with_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    fake_background: list,
) -> None:
    v, cfg = _vault(tmp_path)
    _failing_once(monkeypatch, RuntimeError("database is locked"))
    app = create_app(v, cfg)
    state = app.state.web_state
    with caplog.at_level(logging.ERROR, logger="knowlet.web.server"), TestClient(app):
        _wait_for(lambda: state.bootstrap_status == "error")
    records = [r for r in caplog.records if "bootstrap" in r.getMessage().lower()]
    assert records and records[0].exc_info is not None


def test_rebuild_reindex_recovers_from_bootstrap_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_background: list
) -> None:
    import knowlet.core.index as index_mod

    v, cfg = _vault(tmp_path)
    _failing_once(monkeypatch, IndexDimensionMismatchError("dim mismatch: rebuild"))
    deleted: list[Path] = []
    real_delete = index_mod.delete_index_db

    def _spy_delete(db_path: Path) -> None:
        deleted.append(db_path)
        real_delete(db_path)

    monkeypatch.setattr(index_mod, "delete_index_db", _spy_delete)
    app = create_app(v, cfg)
    state = app.state.web_state
    with TestClient(app) as client:
        _wait_for(lambda: state.bootstrap_status == "error")
        assert client.get("/api/tree").status_code == 500
        # Diagnostics stay reachable in the error state.
        r = client.post("/api/system/doctor?skip_llm=true&skip_embedding=true")
        assert r.status_code == 200, r.text

        r = client.post("/api/system/reindex?rebuild=true")
        assert r.status_code == 200, r.text
        assert deleted == [v.db_path]
        assert state.bootstrap_status == "ready"
        assert client.get("/api/tree").status_code == 200
        # The recovered runtime also gets its background services.
        assert fake_background and fake_background[-1].started


def test_plain_reindex_retries_bootstrap_after_transient_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_background: list
) -> None:
    v, cfg = _vault(tmp_path)
    _failing_once(monkeypatch, RuntimeError("database is locked"))
    app = create_app(v, cfg)
    state = app.state.web_state
    with TestClient(app) as client:
        _wait_for(lambda: state.bootstrap_status == "error")
        r = client.post("/api/system/reindex")
        assert r.status_code == 200, r.text
        assert client.get("/api/tree").status_code == 200


# ------------------------------------------------ background services


def test_api_key_set_at_runtime_starts_background_services(
    tmp_path: Path, fake_background: list
) -> None:
    v, cfg = _vault(tmp_path, api_key="")
    app = create_app(v, cfg)
    state = app.state.web_state
    with TestClient(app) as client:
        _wait_for(lambda: state.bootstrap_status == "ready")
        assert state.scheduler is None
        assert state.digest_auto_pull_thread is None

        r = client.put("/api/llm/config", json={"api_key": "sk-new"})
        assert r.status_code == 200
        assert state.scheduler is not None and state.scheduler.started
        assert state.digest_auto_pull_thread is not None
        assert state.digest_auto_pull_thread.is_alive()

        # Idempotent: a second save does not start a second scheduler.
        client.put("/api/llm/config", json={"model": "other"})
        assert len(fake_background) == 1
    assert fake_background[0].stopped


def test_background_services_never_start_outside_lifespan(
    tmp_path: Path, fake_background: list
) -> None:
    """Tests (and other non-lifespan callers) must not spawn threads."""
    v, cfg = _vault(tmp_path, api_key="")
    app = create_app(v, cfg)
    app.state.web_state.runtime_or_init()
    client = TestClient(app)
    assert client.put("/api/llm/config", json={"api_key": "sk-new"}).status_code == 200
    assert app.state.web_state.scheduler is None
    assert fake_background == []


# ------------------------------------------------ system reindex


def test_rebuild_closes_old_index_before_deleting_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import knowlet.core.index as index_mod

    v, cfg = _vault(tmp_path)
    app = create_app(v, cfg)
    runtime = app.state.web_state.runtime_or_init()
    client = TestClient(app)
    note = Note(id=new_id(), title="Before", body="alpha")
    v.write_note(note)
    runtime.index.upsert_note(note, chunk_size=400, chunk_overlap=40)

    order: list[str] = []
    old_index = runtime.index
    real_close = old_index.close

    def _close() -> None:
        order.append("close")
        real_close()

    monkeypatch.setattr(old_index, "close", _close)
    real_delete = index_mod.delete_index_db

    def _delete(db_path: Path) -> None:
        order.append("delete")
        real_delete(db_path)

    monkeypatch.setattr(index_mod, "delete_index_db", _delete)

    r = client.post("/api/system/reindex?rebuild=true")
    assert r.status_code == 200, r.text
    assert order[:2] == ["close", "delete"]
    assert runtime.index is not old_index
    assert runtime.ctx.index is runtime.index
    assert runtime.session.ctx.index is runtime.index
    assert runtime.index.get_note_meta(note.id) is not None

    # Saves after the rebuild land in the live DB.
    r = client.put(f"/api/notes/{note.id}", json={"title": "After", "tags": [], "body": "zeta"})
    assert r.status_code == 200
    assert runtime.index.get_note_meta(note.id)["title"] == "After"


# ------------------------------------------------ vault import


def _archive(title: str) -> bytes:
    buf = io.BytesIO()
    note = Note(id=new_id(), title=title, body="imported body")
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"notes/{note.filename}", note.to_markdown())
    return buf.getvalue()


def test_import_while_bootstrapping_is_503_and_writes_nothing(tmp_path: Path) -> None:
    v, cfg = _vault(tmp_path)
    app = create_app(v, cfg)
    app.state.web_state.bootstrap_status = "running"
    client = TestClient(app)
    r = client.post(
        "/api/vault/import", files={"file": ("v.zip", _archive("Imported"), "application/zip")}
    )
    assert r.status_code == 503
    assert not list(v.notes_dir.rglob("*.md"))


def test_import_indexes_new_notes_without_reloading_embedding_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import knowlet.core.embedding as embedding_mod

    v, cfg = _vault(tmp_path)
    app = create_app(v, cfg)
    runtime = app.state.web_state.runtime_or_init()
    client = TestClient(app)

    def _no_reload(*_a, **_kw):
        raise AssertionError("import must reuse runtime.backend")

    monkeypatch.setattr(embedding_mod, "make_backend", _no_reload)
    r = client.post(
        "/api/vault/import", files={"file": ("v.zip", _archive("Imported"), "application/zip")}
    )
    assert r.status_code == 200, r.text
    titles = [n["title"] for n in runtime.index.list_notes()]
    assert "Imported" in titles
    assert runtime.ctx.index is runtime.index
