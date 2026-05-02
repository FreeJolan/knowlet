"""HTTP-API tests for the M2 web UI.

Stubs the LLM so tests don't need network. Verifies that every public endpoint
delegates to backend functions (single-source-of-truth discipline) and that
error paths produce structured responses.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from knowlet.config import KnowletConfig, save_config
from knowlet.core.events import (
    ReplyChunkEvent,
    ReplyDoneEvent,
    ToolCallEvent,
)
from knowlet.core.llm import AssistantMessage, ToolCall
from knowlet.core.note import Note, new_id
from knowlet.core.user_profile import UserProfile, write_profile
from knowlet.core.vault import Vault
from knowlet.web.server import create_app


class StubLLM:
    """Scripted LLM. The web layer pulls runtime.llm via DI, and we monkeypatch
    runtime.llm.chat to point here."""

    def __init__(self, scripted: list[AssistantMessage]):
        self.scripted = list(scripted)

    def chat(self, messages, tools=None, max_tokens=None, temperature=None):
        return self.scripted.pop(0)


def _ready_vault(tmp_path: Path) -> tuple[Vault, KnowletConfig]:
    v = Vault(tmp_path)
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = "stub"
    save_config(v.root, cfg)
    return v, cfg


def _client_with_stub(tmp_path: Path, stub) -> tuple[TestClient, Vault, KnowletConfig]:
    v, cfg = _ready_vault(tmp_path)
    app = create_app(v, cfg)

    client = TestClient(app)

    # Force runtime init then swap LLM for the stub. ChatSession holds its own
    # `llm` reference, so we have to patch both.
    state = app.state.web_state
    runtime = state.runtime_or_init()
    runtime.llm = stub  # type: ignore[assignment]
    runtime.session.llm = stub  # type: ignore[assignment]
    return client, v, cfg


# ------------------------------------------------------- health


def test_health(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    client = TestClient(create_app(v, cfg))
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["vault"] == str(v.root)
    assert body["model"] == cfg.llm.model


# ------------------------------------------------------- chat turn


def test_chat_turn_simple_reply(tmp_path: Path):
    stub = StubLLM([AssistantMessage(content="hello", tool_calls=[])])
    client, _, _ = _client_with_stub(tmp_path, stub)
    r = client.post("/api/chat/turn", json={"text": "hi"})
    assert r.status_code == 200
    data = r.json()
    assert data["reply"] == "hello"
    assert data["tool_calls"] == []


def test_chat_turn_with_tool_call(tmp_path: Path):
    stub = StubLLM(
        [
            AssistantMessage(
                content="",
                tool_calls=[
                    ToolCall(
                        id="1",
                        name="search_notes",
                        arguments={"query": "x", "limit": 1},
                    )
                ],
            ),
            AssistantMessage(content="answer based on tool result", tool_calls=[]),
        ]
    )
    client, _, _ = _client_with_stub(tmp_path, stub)
    r = client.post("/api/chat/turn", json={"text": "tell me"})
    assert r.status_code == 200
    data = r.json()
    assert "answer" in data["reply"]
    assert len(data["tool_calls"]) == 1
    assert data["tool_calls"][0]["name"] == "search_notes"


def test_chat_turn_propagates_llm_failure(tmp_path: Path):
    class BoomLLM:
        def chat(self, *a, **kw):
            raise RuntimeError("upstream went down")

    boom = BoomLLM()
    client, _, _ = _client_with_stub(tmp_path, boom)
    r = client.post("/api/chat/turn", json={"text": "hi"})
    assert r.status_code == 502
    assert "upstream went down" in r.json()["detail"]


def test_chat_clear_resets_history(tmp_path: Path):
    stub = StubLLM([AssistantMessage(content="ok", tool_calls=[])])
    client, _, _ = _client_with_stub(tmp_path, stub)
    client.post("/api/chat/turn", json={"text": "hi"})
    r = client.post("/api/chat/clear")
    assert r.status_code == 200
    h = client.get("/api/chat/history").json()
    assert h["history"] == []


# ------------------------------------------------------- draft + commit


def test_draft_then_commit(tmp_path: Path):
    stub = StubLLM(
        [
            AssistantMessage(content="some reply", tool_calls=[]),
            AssistantMessage(
                content='{"title": "T", "tags": ["a", "b"], "body": "## body\\nhi"}',
                tool_calls=[],
            ),
        ]
    )
    client, _, _ = _client_with_stub(tmp_path, stub)

    client.post("/api/chat/turn", json={"text": "discuss something"})

    draft_resp = client.post("/api/chat/draft")
    assert draft_resp.status_code == 200
    draft = draft_resp.json()
    assert draft["title"] == "T"
    assert draft["tags"] == ["a", "b"]
    assert "body" in draft

    commit_resp = client.post(
        "/api/notes",
        json={"title": draft["title"], "tags": draft["tags"], "body": draft["body"]},
    )
    assert commit_resp.status_code == 200
    out = commit_resp.json()
    assert out["note_id"]

    rows = client.get("/api/notes?limit=10").json()
    assert any(r["id"] == out["note_id"] for r in rows)


def test_draft_with_no_history_is_400(tmp_path: Path):
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.post("/api/chat/draft")
    assert r.status_code == 400


# ------------------------------------------------------- notes


def test_list_and_get_note(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    n = Note(id=new_id(), title="Existing", body="prior content", tags=["t1"])
    v.write_note(n)

    client = TestClient(create_app(v, cfg))
    rows = client.get("/api/notes").json()
    assert any(r["title"] == "Existing" for r in rows)

    full = client.get(f"/api/notes/{n.id}").json()
    assert full["title"] == "Existing"
    assert full["body"] == "prior content"


def test_get_missing_note_404(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    client = TestClient(create_app(v, cfg))
    r = client.get("/api/notes/no-such-id")
    assert r.status_code == 404


def test_put_note_updates_body_and_indexes(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    n = Note(id=new_id(), title="Old title", body="old body", tags=["a"])
    v.write_note(n)

    client = TestClient(create_app(v, cfg))
    # ensure indexed via initial GET (which triggers reindex via the runtime)
    client.get("/api/notes")

    r = client.put(
        f"/api/notes/{n.id}",
        json={"title": "New title", "tags": ["b"], "body": "new body content"},
    )
    assert r.status_code == 200
    out = r.json()
    assert out["id"] == n.id
    assert out["title"] == "New title"
    assert out["body"] == "new body content"
    assert out["tags"] == ["b"]


def test_put_note_404_for_missing(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    client = TestClient(create_app(v, cfg))
    r = client.put(
        "/api/notes/no-such-id",
        json={"title": "x", "tags": [], "body": "y"},
    )
    assert r.status_code == 404


# ------------------------------------------------------- profile


def test_profile_get_when_missing(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    client = TestClient(create_app(v, cfg))
    r = client.get("/api/profile")
    assert r.status_code == 200
    assert r.json() == {"exists": False}


def test_profile_round_trip(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    client = TestClient(create_app(v, cfg))
    r = client.put(
        "/api/profile", json={"name": "Jolan", "body": "I prefer concise replies."}
    )
    assert r.status_code == 200
    g = client.get("/api/profile").json()
    assert g["exists"] is True
    assert g["name"] == "Jolan"
    assert "concise" in g["body"]


def test_profile_update_refreshes_runtime_system_prompt(tmp_path: Path):
    """PUT /api/profile must update the live runtime so the next chat turn
    sees the new profile (single-source-of-truth: profile change = system
    prompt change everywhere)."""
    stub = StubLLM([AssistantMessage(content="ack", tool_calls=[])])
    client, v, cfg = _client_with_stub(tmp_path, stub)

    state = client.app.state.web_state  # type: ignore[attr-defined]
    runtime = state.runtime
    assert runtime is not None
    before = runtime.session.history[0]["content"]

    client.put("/api/profile", json={"body": "I read AI papers."})
    after = runtime.session.history[0]["content"]
    assert before != after
    assert "I read AI papers." in after
    assert runtime.user_profile is not None
    assert runtime.user_profile.body == "I read AI papers."


# ------------------------------------------------------- index page (static mount)


def test_root_serves_index_html(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    client = TestClient(create_app(v, cfg))
    r = client.get("/")
    assert r.status_code == 200
    assert "knowlet" in r.text.lower()


# ------------------------------------------------------- SSE streaming


class StreamStubLLM:
    def __init__(self, scripts):
        self.scripts = list(scripts)

    def chat_stream(self, messages, tools=None, max_tokens=None, temperature=None):
        events = self.scripts.pop(0)
        for ev in events:
            yield ev


def _parse_sse(raw: str) -> list[dict]:
    events: list[dict] = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        data_lines = [
            line[len("data: "):]
            for line in block.split("\n")
            if line.startswith("data: ")
        ]
        if not data_lines:
            continue
        events.append(json.loads("".join(data_lines)))
    return events


def test_chat_stream_yields_events(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    app = create_app(v, cfg)
    client = TestClient(app)
    state = app.state.web_state
    runtime = state.runtime_or_init()
    runtime.session.llm = StreamStubLLM(  # type: ignore[assignment]
        [
            [
                ReplyChunkEvent(text="hello "),
                ReplyChunkEvent(text="world"),
                ReplyDoneEvent(final_text="hello world"),
            ]
        ]
    )
    with client.stream(
        "POST", "/api/chat/stream", json={"text": "hi"}
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    events = _parse_sse(body)
    types = [e["type"] for e in events]
    assert types == ["reply_chunk", "reply_chunk", "turn_done"]
    assert events[-1]["final_text"] == "hello world"


def test_chat_stream_with_tool_call(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    n = Note(id=new_id(), title="Note A", body="some body")
    v.write_note(n)

    app = create_app(v, cfg)
    client = TestClient(app)
    state = app.state.web_state
    runtime = state.runtime_or_init()
    runtime.session.llm = StreamStubLLM(  # type: ignore[assignment]
        [
            [
                ToolCallEvent(
                    id="c1", name="search_notes", arguments={"query": "x", "limit": 1}
                ),
                ReplyDoneEvent(final_text=""),
            ],
            [
                ReplyChunkEvent(text="answer"),
                ReplyDoneEvent(final_text="answer"),
            ],
        ]
    )
    with client.stream(
        "POST", "/api/chat/stream", json={"text": "search for x"}
    ) as r:
        body = "".join(r.iter_text())
    events = _parse_sse(body)
    types = [e["type"] for e in events]
    assert types == [
        "tool_call",
        "tool_result",
        "reply_chunk",
        "turn_done",
    ]
    assert events[1]["name"] == "search_notes"
    assert "results" in events[1]["payload"]


# ------------------------------------------------------- async lifespan / ready gate


def test_health_exposes_ready_and_bootstrap_status(tmp_path: Path):
    """Tests don't enter lifespan as a context manager, so bootstrap stays
    `idle` until something triggers it. Health should still serve."""
    v, cfg = _ready_vault(tmp_path)
    client = TestClient(create_app(v, cfg))
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert "ready" in body
    assert body["bootstrap_status"] == "idle"
    assert body["ready"] is False


def test_lifespan_kicks_off_async_bootstrap(tmp_path: Path):
    """When TestClient is used as a context manager, lifespan runs and
    `start_bootstrap_async` flips status to running/ready. We wait for the
    daemon thread to finish (DummyBackend is instant; reindex on an empty
    vault is fast) and then assert status='ready'."""
    v, cfg = _ready_vault(tmp_path)
    app = create_app(v, cfg)
    state = app.state.web_state
    with TestClient(app) as client:
        # status started as 'running' or 'ready' depending on thread-scheduler
        # luck; either is fine. Wait deterministically.
        if state._bootstrap_thread is not None:
            state._bootstrap_thread.join(timeout=5.0)
        assert state.bootstrap_status == "ready"
        body = client.get("/api/health").json()
        assert body["ready"] is True
        assert body["bootstrap_status"] == "ready"


def test_chat_endpoint_503s_while_indexing(tmp_path: Path):
    """If a request hits while bootstrap is still running, the chat endpoint
    must return 503 (not crash, not block forever)."""
    v, cfg = _ready_vault(tmp_path)
    app = create_app(v, cfg)
    state = app.state.web_state
    # Force the running state without actually starting a thread.
    state.bootstrap_status = "running"

    client = TestClient(app)
    r = client.post("/api/chat/turn", json={"text": "hi"})
    assert r.status_code == 503
    assert "indexing" in r.json()["detail"].lower()


def test_chat_endpoint_500s_after_bootstrap_error(tmp_path: Path):
    """If bootstrap raised a non-recoverable error, endpoints surface 500
    with the original message."""
    v, cfg = _ready_vault(tmp_path)
    app = create_app(v, cfg)
    state = app.state.web_state
    state.bootstrap_status = "error"
    state.bootstrap_error = RuntimeError("simulated bootstrap failure")

    client = TestClient(app)
    r = client.post("/api/chat/turn", json={"text": "hi"})
    assert r.status_code == 500
    assert "simulated bootstrap failure" in r.json()["detail"]


# ------------------------------------------------------- multi-session (M6.4)


def test_sessions_list_starts_empty(tmp_path: Path):
    """Fresh vault: no conversations yet, but the active session id (the
    one bootstrap created) is reported."""
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    body = client.get("/api/chat/sessions").json()
    assert body["active_id"]
    assert body["sessions"] == []  # no meaningful conversations yet


def test_chat_turn_persists_to_active_session(tmp_path: Path):
    stub = StubLLM([AssistantMessage(content="hello", tool_calls=[])])
    client, _, _ = _client_with_stub(tmp_path, stub)
    r = client.post("/api/chat/turn", json={"text": "hi"})
    assert r.status_code == 200

    # After one turn, the active session shows up in the listing.
    sessions = client.get("/api/chat/sessions").json()["sessions"]
    assert len(sessions) == 1
    assert sessions[0]["message_count"] >= 2  # at least system + user (+ assistant)


def test_clear_starts_a_new_session(tmp_path: Path):
    """`/api/chat/clear` is now `start a fresh session` — the previous
    one stays on disk."""
    stub = StubLLM([AssistantMessage(content="hello", tool_calls=[])])
    client, _, _ = _client_with_stub(tmp_path, stub)
    client.post("/api/chat/turn", json={"text": "hi"})
    first_id = client.get("/api/chat/history").json()["active_id"]

    r = client.post("/api/chat/clear")
    assert r.status_code == 200
    second_id = r.json()["active_id"]
    assert second_id != first_id

    # Old session still listed.
    sessions = client.get("/api/chat/sessions").json()["sessions"]
    assert any(s["id"] == first_id for s in sessions)


def test_sessions_activate_switches_runtime(tmp_path: Path):
    stub = StubLLM(
        [
            AssistantMessage(content="reply-1", tool_calls=[]),
            AssistantMessage(content="reply-2", tool_calls=[]),
        ]
    )
    client, _, _ = _client_with_stub(tmp_path, stub)

    # First session
    client.post("/api/chat/turn", json={"text": "in session A"})
    a_id = client.get("/api/chat/history").json()["active_id"]

    # Start a new one
    new_resp = client.post("/api/chat/sessions").json()
    b_id = new_resp["id"]
    assert b_id != a_id

    # Talk in session B
    client.post("/api/chat/turn", json={"text": "in session B"})

    # Switch back to A
    r = client.post(f"/api/chat/sessions/{a_id}/activate")
    assert r.status_code == 200
    history = client.get("/api/chat/history").json()
    assert history["active_id"] == a_id
    assert any("in session A" in (m.get("content") or "") for m in history["history"])


def test_sessions_rename(tmp_path: Path):
    stub = StubLLM([AssistantMessage(content="reply", tool_calls=[])])
    client, _, _ = _client_with_stub(tmp_path, stub)
    client.post("/api/chat/turn", json={"text": "hi"})
    sid = client.get("/api/chat/history").json()["active_id"]

    r = client.put(f"/api/chat/sessions/{sid}", json={"title": "renamed!"})
    assert r.status_code == 200
    assert r.json()["title"] == "renamed!"
    sessions = client.get("/api/chat/sessions").json()["sessions"]
    assert next(s for s in sessions if s["id"] == sid)["title"] == "renamed!"


def test_sessions_delete_refuses_active(tmp_path: Path):
    stub = StubLLM([AssistantMessage(content="reply", tool_calls=[])])
    client, _, _ = _client_with_stub(tmp_path, stub)
    client.post("/api/chat/turn", json={"text": "hi"})
    sid = client.get("/api/chat/history").json()["active_id"]

    r = client.delete(f"/api/chat/sessions/{sid}")
    assert r.status_code == 409
    assert "active" in r.json()["detail"].lower()


def test_sessions_delete_inactive_succeeds(tmp_path: Path):
    stub = StubLLM(
        [
            AssistantMessage(content="reply-a", tool_calls=[]),
            AssistantMessage(content="reply-b", tool_calls=[]),
        ]
    )
    client, _, _ = _client_with_stub(tmp_path, stub)
    client.post("/api/chat/turn", json={"text": "in session A"})
    a_id = client.get("/api/chat/history").json()["active_id"]
    client.post("/api/chat/sessions")
    client.post("/api/chat/turn", json={"text": "in session B"})

    # A is no longer active — delete it.
    r = client.delete(f"/api/chat/sessions/{a_id}")
    assert r.status_code == 200
    sessions = client.get("/api/chat/sessions").json()["sessions"]
    assert all(s["id"] != a_id for s in sessions)


def test_sessions_404_for_unknown_id(tmp_path: Path):
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.post("/api/chat/sessions/does-not-exist/activate")
    assert r.status_code == 404
    r = client.put("/api/chat/sessions/does-not-exist", json={"title": "x"})
    assert r.status_code == 404
    r = client.delete("/api/chat/sessions/does-not-exist")
    # Still 404 because we never become "active" with this id.
    assert r.status_code == 404


def test_auto_title_summarizes_first_exchange(tmp_path: Path):
    """First-exchange auto-title (M6.4 Phase 2). The summary call uses
    the runtime's regular `LLMClient.chat` — same path the test stub
    intercepts."""
    stub = StubLLM(
        [
            AssistantMessage(content="hybrid retrieval is BM25+vector via RRF.", tool_calls=[]),
            # Second call = the auto-title summary itself.
            AssistantMessage(content="RAG hybrid retrieval primer", tool_calls=[]),
        ]
    )
    client, _, _ = _client_with_stub(tmp_path, stub)
    client.post("/api/chat/turn", json={"text": "what is RAG?"})
    sid = client.get("/api/chat/history").json()["active_id"]

    r = client.post(f"/api/chat/sessions/{sid}/auto-title")
    assert r.status_code == 200
    body = r.json()
    assert body["generated"] is True
    assert body["title"] == "RAG hybrid retrieval primer"

    # Listing reflects the new title.
    sessions = client.get("/api/chat/sessions").json()["sessions"]
    assert next(s for s in sessions if s["id"] == sid)["title"] == "RAG hybrid retrieval primer"


def test_auto_title_idempotent_when_already_titled(tmp_path: Path):
    """If a title already exists, the endpoint returns it without
    burning another LLM call."""
    stub = StubLLM([AssistantMessage(content="hi", tool_calls=[])])
    client, _, _ = _client_with_stub(tmp_path, stub)
    client.post("/api/chat/turn", json={"text": "hi"})
    sid = client.get("/api/chat/history").json()["active_id"]
    client.put(f"/api/chat/sessions/{sid}", json={"title": "manual"})

    r = client.post(f"/api/chat/sessions/{sid}/auto-title")
    assert r.status_code == 200
    body = r.json()
    assert body["generated"] is False
    assert body["title"] == "manual"


def test_system_reindex_endpoint(tmp_path: Path):
    """M6.5: /api/system/reindex hits reindex_vault and returns counts."""
    # Pre-create a Note on disk so reindex sees something.
    v, cfg = _ready_vault(tmp_path)
    from knowlet.core.note import Note, new_id
    n = Note(id=new_id(), title="x", body="hello world hello world")
    v.write_note(n)

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.post("/api/system/reindex")
    assert r.status_code == 200
    body = r.json()
    assert "changed" in body
    assert "deleted" in body
    assert "unchanged" in body


def test_system_doctor_endpoint(tmp_path: Path):
    """M6.5: /api/system/doctor runs the full check pipeline (skipping LLM
    so the test stays hermetic) and returns a structured result list."""
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.post("/api/system/doctor?skip_llm=true&skip_embedding=true")
    assert r.status_code == 200
    body = r.json()
    assert "results" in body
    assert "failures" in body
    assert "warnings" in body
    assert any(item["name"] == "vault" for item in body["results"])


def test_auto_title_unsaved_session_404(tmp_path: Path):
    """A brand-new session without any turn yet hasn't been persisted to
    disk (we only save after a real exchange — see persist_active()), so
    the store-keyed lookup correctly 404s."""
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    sid = client.get("/api/chat/history").json()["active_id"]
    r = client.post(f"/api/chat/sessions/{sid}/auto-title")
    assert r.status_code == 404
