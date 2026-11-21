"""Regression tests for chat / capture / quiz / drafts / health wiring in
the web server.

Covers: note chat passing the user's own message to the apply tool, the
draft chat session carrying its draft anchor, ask-once not sharing the
persistent session's per-turn budget, the shared chat session refusing
overlapping turns / switches, URL capture not fetching twice when only
the summary failed, quiz LLM transport errors mapping to 502, draft
reject archiving instead of deleting, and /api/health echoing the desktop
launch token.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from knowlet.config import KnowletConfig, save_config
from knowlet.core.drafts import Draft, DraftStore
from knowlet.core.events import ReplyChunkEvent, ReplyDoneEvent, ToolCallEvent
from knowlet.core.note import Note, new_id
from knowlet.core.vault import Vault
from knowlet.web import server as server_mod
from knowlet.web.server import create_app
from tests.test_web_note_chat import (
    StreamStubLLM,
    _client_with_draft,
    _client_with_note,
    _parse_sse,
)


def _app(tmp_path: Path):
    v = Vault(tmp_path)
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = "stub"
    save_config(v.root, cfg)
    app = create_app(v, cfg)
    runtime = app.state.web_state.runtime_or_init()
    return app, TestClient(app), v, runtime


# ------------------------------------------------ note chat: user_request_text


class _ModelAppliesOnItsOwn:
    """Model emits an apply call with a made-up 'explicit request' even
    though the user only asked a question."""

    def __init__(self) -> None:
        self.calls = 0

    def chat_stream(self, messages, tools=None, max_tokens=None, temperature=None) -> Iterator[Any]:
        self.calls += 1
        if self.calls == 1:
            yield ToolCallEvent(
                id="apply_1",
                name="apply_current_note_edit",
                arguments={"explicit_user_request": "请应用当前改动"},
            )
            yield ReplyDoneEvent(final_text="")
            return
        yield ReplyChunkEvent(text="ok")
        yield ReplyDoneEvent(final_text="ok")


def test_note_chat_apply_tool_checks_the_users_own_message(tmp_path: Path) -> None:
    old = "RAG puts everything into the prompt."
    client, note = _client_with_note(tmp_path, body=old, stub=_ModelAppliesOnItsOwn())
    r = client.post(
        f"/api/chat/note/{note.id}/stream",
        json={
            "text": "这个改动可以直接用吗",
            "pending_edit": {"old_body": old, "new_body": "RAG retrieves, then generates."},
        },
    )
    assert r.status_code == 200
    results = [e for e in _parse_sse(r.text) if e["type"] == "tool_result"]
    assert results and results[0]["payload"]["kind"] == "note_edit_apply_rejected"
    assert client.get(f"/api/notes/{note.id}").json()["body"] == old


# ------------------------------------------------ draft chat anchor


def test_draft_chat_session_is_anchored_to_the_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import knowlet.chat.note_chat as note_chat_mod

    captured: dict[str, Any] = {}
    real = note_chat_mod.build_note_chat_session

    def _spy(**kw):
        session = real(**kw)
        captured["ctx"] = session.ctx
        return session

    monkeypatch.setattr(note_chat_mod, "build_note_chat_session", _spy)
    stub = StreamStubLLM([ReplyDoneEvent(final_text="draft answer")])
    client, draft = _client_with_draft(tmp_path, body="draft body", stub=stub)
    r = client.post(f"/api/chat/draft/{draft.id}/stream", json={"text": "润色一下"})
    assert r.status_code == 200
    ctx = captured["ctx"]
    assert ctx.current_draft_id == draft.id
    assert ctx.user_request_text == "润色一下"
    assert ctx.mark_note_dirty is not None


# ------------------------------------------------ ask-once budget isolation


def test_ask_once_does_not_reset_the_persistent_sessions_tool_budget(tmp_path: Path) -> None:
    _, client, _v, runtime = _app(tmp_path)
    stub = StreamStubLLM([ReplyDoneEvent(final_text="answer")])
    runtime.llm = stub
    runtime.session.llm = stub
    runtime.session.ctx.per_turn = {"web_search": 2}
    r = client.post("/api/chat/ask-once", json={"text": "quick question"})
    assert r.status_code == 200
    assert runtime.session.ctx.per_turn == {"web_search": 2}


# ------------------------------------------------ shared chat session guard


def test_shared_chat_session_refuses_overlapping_turns_and_switches(tmp_path: Path) -> None:
    app, client, _v, runtime = _app(tmp_path)
    stub = StreamStubLLM([ReplyDoneEvent(final_text="answer")])
    runtime.llm = stub
    runtime.session.llm = stub
    other = runtime.conversations.new()
    runtime.conversations.save(other)
    lock = app.state.web_state.chat_turn_lock

    assert lock.acquire(blocking=False)
    try:
        assert client.post("/api/chat/stream", json={"text": "hi"}).status_code == 409
        assert client.post("/api/chat/turn", json={"text": "hi"}).status_code == 409
        assert client.post(f"/api/chat/sessions/{other.id}/activate").status_code == 409
        assert client.post("/api/chat/sessions").status_code == 409
        assert client.post("/api/chat/clear").status_code == 409
    finally:
        lock.release()

    r = client.post("/api/chat/stream", json={"text": "hi"})
    assert r.status_code == 200
    assert "turn_done" in [e["type"] for e in _parse_sse(r.text)]
    # The stream released the guard when it finished.
    assert not lock.locked()
    assert client.post(f"/api/chat/sessions/{other.id}/activate").status_code == 200


def test_stream_releases_guard_when_llm_fails(tmp_path: Path) -> None:
    app, client, _v, runtime = _app(tmp_path)

    class _Boom:
        def chat_stream(self, *a, **kw):
            raise RuntimeError("proxy down")

    runtime.llm = _Boom()
    runtime.session.llm = _Boom()
    r = client.post("/api/chat/stream", json={"text": "hi"})
    assert r.status_code == 200
    assert not app.state.web_state.chat_turn_lock.locked()


# ------------------------------------------------ URL capture: no second fetch


@pytest.mark.parametrize("endpoint", ["/api/url/capture", "/api/capture/url"])
def test_url_capture_summary_failure_does_not_fetch_twice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, endpoint: str
) -> None:
    import knowlet.core.url_capture as uc

    fetches: list[str] = []

    def _fetch(url: str) -> tuple[str, str]:
        fetches.append(url)
        return "Page Title", "page body text"

    def _summarize(_llm, _content):
        raise RuntimeError("llm down")

    monkeypatch.setattr(uc, "fetch_and_extract", _fetch)
    monkeypatch.setattr(uc, "summarize_content", _summarize)
    _, client, _v, _runtime = _app(tmp_path)
    r = client.post(endpoint, json={"url": "https://example.com/a"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary_failed"] is True
    assert body["title"] == "Page Title"
    assert fetches == ["https://example.com/a"]
    if endpoint == "/api/capture/url":
        assert body["body"] == "page body text"
        assert "llm down" in body["summary_error"]
    else:
        assert "llm down" in body["summary"]


# ------------------------------------------------ quiz LLM errors


def test_quiz_start_maps_llm_transport_errors_to_502(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, client, v, runtime = _app(tmp_path)
    note = Note(id=new_id(), title="Q", body="quiz me")
    v.write_note(note)
    runtime.index.upsert_note(note, chunk_size=400, chunk_overlap=40)

    def _boom(*_a, **_kw):
        raise ConnectionError("proxy unreachable")

    monkeypatch.setattr(server_mod, "generate_quiz", _boom)
    r = client.post("/api/quiz/start", json={"note_ids": [note.id]})
    assert r.status_code == 502
    assert "proxy unreachable" in r.json()["detail"]


# ------------------------------------------------ draft reject archives


def test_reject_draft_archives_instead_of_deleting(tmp_path: Path) -> None:
    _, client, v, _runtime = _app(tmp_path)
    store = DraftStore(v.drafts_dir)
    draft = Draft(id=new_id(), title="Maybe", body="keep me recoverable")
    store.save(draft)
    r = client.post(f"/api/drafts/{draft.id}/reject")
    assert r.status_code == 200
    assert store.get(draft.id) is None
    archived = [p for p in (v.drafts_dir / ".archive").rglob("*.md")]
    assert len(archived) == 1
    assert "keep me recoverable" in archived[0].read_text(encoding="utf-8")
    assert client.post(f"/api/drafts/{draft.id}/reject").status_code == 404


def test_reject_draft_ambiguous_prefix_is_409(tmp_path: Path) -> None:
    _, client, v, _runtime = _app(tmp_path)
    store = DraftStore(v.drafts_dir)
    store.save(Draft(id="01AAAAAAAAAAAAAAAAAAAAAAA1", title="a", body="a"))
    store.save(Draft(id="01AAAAAAAAAAAAAAAAAAAAAAA2", title="b", body="b"))
    r = client.post("/api/drafts/01AAAA/reject")
    assert r.status_code == 409
    assert store.get("01AAAAAAAAAAAAAAAAAAAAAAA1") is not None


# ------------------------------------------------ health launch token


def test_health_echoes_desktop_launch_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, client, _v, _runtime = _app(tmp_path)
    monkeypatch.delenv("KNOWLET_DESKTOP_LAUNCH_TOKEN", raising=False)
    body = client.get("/api/health").json()
    assert body.get("launch_token") is None
    assert body["status"] == "ok"
    monkeypatch.setenv("KNOWLET_DESKTOP_LAUNCH_TOKEN", "tok-123")
    assert client.get("/api/health").json()["launch_token"] == "tok-123"
