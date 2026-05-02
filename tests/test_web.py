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


def test_list_notes_includes_folder_field(tmp_path: Path):
    """M7.0.2: /api/notes summary now carries `folder` (relative to
    notes/, "" = top-level). The frontend uses this to build the tree."""
    from knowlet.core.note import Note, new_id

    v, cfg = _ready_vault(tmp_path)
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))

    state = client.app.state.web_state
    runtime = state.runtime_or_init()

    # Top-level note
    top = Note(id=new_id(), title="t", body="...")
    v.write_note(top)
    runtime.index.upsert_note(top, chunk_size=64, chunk_overlap=16)

    # Note in a subdir (manually placed)
    sub_dir = v.notes_dir / "AI papers"
    sub_dir.mkdir(parents=True, exist_ok=True)
    sub = Note(id=new_id(), title="s", body="...")
    sub_path = sub_dir / sub.filename
    sub_path.write_text(sub.to_markdown(), encoding="utf-8")
    sub.path = sub_path
    runtime.index.upsert_note(sub, chunk_size=64, chunk_overlap=16)

    rows = client.get("/api/notes?limit=10").json()
    by_id = {r["id"]: r for r in rows}
    assert by_id[top.id]["folder"] == ""
    assert by_id[sub.id]["folder"] == "AI papers"


def test_delete_note_endpoint_soft_deletes_to_trash(tmp_path: Path):
    """M7.0.1: DELETE /api/notes/{id} moves to notes/.trash/, removes
    the index entry, returns 200 with the trashed path."""
    from knowlet.core.note import Note, new_id

    v, cfg = _ready_vault(tmp_path)
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))

    # Seed a note via the runtime so it lands in the index too.
    state = client.app.state.web_state
    runtime = state.runtime_or_init()
    n = Note(id=new_id(), title="to be trashed", body="...")
    path = v.write_note(n)
    runtime.index.upsert_note(n, chunk_size=64, chunk_overlap=16)

    r = client.delete(f"/api/notes/{n.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["id"] == n.id
    assert ".trash" in body["trashed_to"]
    # File moved off notes/ root
    assert not path.exists()
    assert (v.notes_dir / ".trash" / path.name).exists()
    # Index forgot it
    assert runtime.index.get_note_meta(n.id) is None


def test_delete_note_endpoint_404_for_unknown_id(tmp_path: Path):
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.delete("/api/notes/does-not-exist")
    assert r.status_code == 404


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


# ------------------------------------------------------------- M7.0.3 attachments


def _png_bytes() -> bytes:
    """Smallest possible valid PNG — 1x1 transparent pixel. Saves us from
    needing Pillow as a test dep."""
    import base64
    return base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
    )


def test_upload_attachment_returns_relative_path(tmp_path: Path):
    """M7.0.3: image POST → saved to notes/_attachments/<ulid>.png and the
    response carries a portable `_attachments/<id>.png` path (no absolute
    paths, no `/files/` prefix — the markdown link should round-trip across
    Obsidian / Finder)."""
    client, v, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.post(
        "/api/attachments",
        files={"file": ("pasted.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["path"].startswith("_attachments/")
    assert body["path"].endswith(".png")
    assert body["bytes"] == len(_png_bytes())
    saved = v.notes_dir / body["path"]
    assert saved.exists()
    assert saved.read_bytes() == _png_bytes()


def test_upload_attachment_rejects_unsupported_type(tmp_path: Path):
    """SVG is intentionally blocked — it's a script-execution vector in any
    pane that renders it via <img> or <object>. PDFs / .docx are also out
    of scope for the paste flow."""
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.post(
        "/api/attachments",
        files={"file": ("evil.svg", b"<svg/>", "image/svg+xml")},
    )
    assert r.status_code == 415


def test_get_attachment_serves_bytes(tmp_path: Path):
    """Round-trip: upload, then GET back the bytes via /files/."""
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    up = client.post(
        "/api/attachments",
        files={"file": ("p.png", _png_bytes(), "image/png")},
    ).json()
    name = up["path"].split("/")[-1]
    got = client.get(f"/files/_attachments/{name}")
    assert got.status_code == 200
    assert got.content == _png_bytes()


def test_get_attachment_rejects_traversal(tmp_path: Path):
    """`..` in the basename must 400 — defense in depth on top of the
    single-segment route shape."""
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.get("/files/_attachments/.hidden.png")
    assert r.status_code == 400
    r = client.get("/files/_attachments/x.svg")
    assert r.status_code == 400


def test_get_attachment_404_for_missing(tmp_path: Path):
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.get("/files/_attachments/01HX0000000000000000000099.png")
    assert r.status_code == 404


# ------------------------------------------------------------- M7.0.4 backlinks


def test_backlinks_endpoint_returns_inbound_references(tmp_path: Path):
    """M7.0.4: GET /api/notes/<id>/backlinks scans the vault for `[[Title]]`
    references and returns source + sentence preview."""
    client, v, _ = _client_with_stub(tmp_path, StubLLM([]))
    runtime = client.app.state.web_state.runtime_or_init()

    target = Note(id=new_id(), title="Attention", body="core idea")
    v.write_note(target)
    runtime.index.upsert_note(target, chunk_size=64, chunk_overlap=16)

    src = Note(
        id=new_id(),
        title="Survey",
        body="see [[Attention]] for the seminal paper",
    )
    v.write_note(src)
    runtime.index.upsert_note(src, chunk_size=64, chunk_overlap=16)

    rows = client.get(f"/api/notes/{target.id}/backlinks").json()
    assert len(rows) == 1
    assert rows[0]["source_id"] == src.id
    assert rows[0]["source_title"] == "Survey"
    assert "[[Attention]]" in rows[0]["sentence"]


def test_backlinks_endpoint_404_for_unknown_note(tmp_path: Path):
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.get("/api/notes/01HXMISSING0000000000000/backlinks")
    assert r.status_code == 404


def test_backlinks_endpoint_empty_when_no_inbound(tmp_path: Path):
    client, v, _ = _client_with_stub(tmp_path, StubLLM([]))
    runtime = client.app.state.web_state.runtime_or_init()
    n = Note(id=new_id(), title="Lonely", body="no inbound links")
    v.write_note(n)
    runtime.index.upsert_note(n, chunk_size=64, chunk_overlap=16)

    rows = client.get(f"/api/notes/{n.id}/backlinks").json()
    assert rows == []


# ------------------------------------------------------------- M7.1 references


def test_chat_turn_with_reference_prepends_quote_block(tmp_path: Path):
    """M7.1: when ChatTurnRequest carries a `references` capsule, the
    backend composes a "quote + enclosing section" prefix and feeds the
    enriched text to Session.user_turn — the LLM sees it, the response
    schema is unchanged."""
    from knowlet.core.llm import AssistantMessage

    captured: list[str] = []

    class CapturingLLM:
        """Stand-in that captures the last user content the session sent
        to the LLM. Returns an empty assistant reply so the turn closes
        cleanly without further tool-call cycles."""

        def chat(self, messages, tools=None, max_tokens=None, temperature=None):
            for m in messages:
                if m.get("role") == "user":
                    captured.append(m["content"])
            return AssistantMessage(content="ok", tool_calls=[])

    client, v, _ = _client_with_stub(tmp_path, CapturingLLM())
    runtime = client.app.state.web_state.runtime_or_init()

    n = Note(
        id=new_id(),
        title="Transformers",
        body="## Attention\n\nself-attention weights tokens by relevance.\n",
    )
    v.write_note(n)
    runtime.index.upsert_note(n, chunk_size=64, chunk_overlap=16)

    payload = {
        "text": "explain why this matters",
        "references": [
            {
                "note_id": n.id,
                "note_title": n.title,
                "quote_text": "self-attention weights tokens by relevance.",
                "paragraph_anchor": "self-attention weights tokens",
            }
        ],
    }
    r = client.post("/api/chat/turn", json=payload)
    assert r.status_code == 200, r.text

    last = captured[-1]
    assert "我想就这段问你" in last
    assert "《Transformers》" in last
    assert "> self-attention weights tokens by relevance." in last
    assert "## Attention" in last  # enclosing section
    assert "explain why this matters" in last  # user text preserved


def test_chat_turn_drops_capsule_for_deleted_note(tmp_path: Path):
    """If a capsule's source Note has been deleted between attach and
    send, that capsule is silently dropped — the rest of the turn proceeds."""
    from knowlet.core.llm import AssistantMessage

    captured: list[str] = []

    class CapturingLLM:
        def chat(self, messages, tools=None, max_tokens=None, temperature=None):
            for m in messages:
                if m.get("role") == "user":
                    captured.append(m["content"])
            return AssistantMessage(content="ok", tool_calls=[])

    client, _, _ = _client_with_stub(tmp_path, CapturingLLM())

    payload = {
        "text": "still asking",
        "references": [
            {
                "note_id": "01HXMISSING0000000000000",
                "note_title": "ghost",
                "quote_text": "won't be found",
                "paragraph_anchor": "won't be found",
            }
        ],
    }
    r = client.post("/api/chat/turn", json=payload)
    assert r.status_code == 200
    # No prefix — capsule dropped, only the bare user text reached the LLM.
    last = captured[-1]
    assert last == "still asking"


# ------------------------------------------------------------- M7.2 url capture


def test_url_capture_endpoint_happy_path(tmp_path: Path, monkeypatch):
    """M7.2: POST /api/url/capture fetches via httpx (mocked) + summarizes
    via the runtime LLM stub, returns {url, title, hostname, summary}."""
    import httpx
    from knowlet.core.llm import AssistantMessage

    html = (
        "<html><head><title>Article Title</title></head><body><article><p>"
        + "Main body content here. " * 50
        + "</p></article></body></html>"
    )

    def fake_get(self, url, **kwargs):
        return httpx.Response(200, text=html, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    class FixedLLM:
        def chat(self, messages, tools=None, max_tokens=None, temperature=None):
            return AssistantMessage(content="一段中性摘要", tool_calls=[])

    client, _, _ = _client_with_stub(tmp_path, FixedLLM())
    r = client.post(
        "/api/url/capture",
        json={"url": "https://www.example.com/article"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["url"] == "https://www.example.com/article"
    assert body["title"] == "Article Title"
    assert body["hostname"] == "example.com"
    assert body["summary"] == "一段中性摘要"
    assert body["summary_failed"] is False


def test_url_capture_rejects_non_http(tmp_path: Path):
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.post("/api/url/capture", json={"url": "ftp://example.com/file"})
    assert r.status_code == 400
    r2 = client.post("/api/url/capture", json={"url": ""})
    assert r2.status_code == 400


def test_url_capture_502_when_fetch_fails(tmp_path: Path, monkeypatch):
    import httpx

    def fake_get(self, url, **kwargs):
        return httpx.Response(404, text="not found", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.post("/api/url/capture", json={"url": "https://example.com/missing"})
    assert r.status_code == 502


def test_url_capture_422_when_extraction_empty(tmp_path: Path, monkeypatch):
    """Page returns 200 but trafilatura can't pull readable content."""
    import httpx

    empty = "<html><head><title>x</title></head><body></body></html>"

    def fake_get(self, url, **kwargs):
        return httpx.Response(200, text=empty, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.post("/api/url/capture", json={"url": "https://example.com/empty"})
    assert r.status_code == 422


# ------------------------------------------------------------- M7.2 similar notes


def test_similar_notes_returns_top_k(tmp_path: Path):
    """ADR-0013 §3 Layer A: /api/notes/similar returns top-K hits, no scores."""
    client, v, _ = _client_with_stub(tmp_path, StubLLM([]))
    runtime = client.app.state.web_state.runtime_or_init()

    n1 = Note(id=new_id(), title="RAG retrieval", body="hybrid retrieval combines FTS and vector search")
    n2 = Note(id=new_id(), title="Embeddings", body="embeddings power semantic search")
    n3 = Note(id=new_id(), title="Cards", body="spaced repetition with FSRS")
    for n in (n1, n2, n3):
        v.write_note(n)
        runtime.index.upsert_note(n, chunk_size=64, chunk_overlap=16)

    rows = client.get("/api/notes/similar?q=hybrid retrieval search&top_k=2").json()
    assert isinstance(rows, list)
    assert len(rows) <= 2
    if rows:
        # Each row has the M7.2 payload shape.
        r0 = rows[0]
        assert set(r0.keys()) == {"id", "title", "path", "preview"}


def test_similar_notes_empty_query_returns_empty(tmp_path: Path):
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    rows = client.get("/api/notes/similar?q=").json()
    assert rows == []


# ------------------------------------------------------------- M7.2 url capsule chat


def test_chat_turn_with_url_capsule_uses_summary_directly(tmp_path: Path):
    """source='url' capsules go through `format_references_block` without
    a vault lookup — the summary IS the context, so no enclosing-section
    machinery runs."""
    from knowlet.core.llm import AssistantMessage

    captured: list[str] = []

    class CapturingLLM:
        def chat(self, messages, tools=None, max_tokens=None, temperature=None):
            for m in messages:
                if m.get("role") == "user":
                    captured.append(m["content"])
            return AssistantMessage(content="ok", tool_calls=[])

    client, _, _ = _client_with_stub(tmp_path, CapturingLLM())

    payload = {
        "text": "what's the takeaway?",
        "references": [
            {
                "note_id": "url://https://example.com/x",
                "note_title": "An Article About RAG",
                "quote_text": "RAG fuses retrieval + generation; key tradeoff is latency.",
                "paragraph_anchor": "",
                "source": "url",
                "source_url": "https://example.com/x",
            }
        ],
    }
    r = client.post("/api/chat/turn", json=payload)
    assert r.status_code == 200
    last = captured[-1]
    assert "我想就这篇文章问你" in last
    assert "《An Article About RAG》" in last
    assert "https://example.com/x" in last
    assert "RAG fuses retrieval + generation" in last
    assert "what's the takeaway?" in last
    # url-source capsules don't carry the enclosing-section hint.
    assert "标题节是" not in last


# ------------------------------------------------------------- M7.4 quiz endpoints


def test_quiz_start_generates_persists_returns_session(tmp_path: Path):
    """M7.4.1: POST /api/quiz/start scopes to the given Notes, calls the
    LLM (stubbed), and persists the QuizSession to .knowlet/quizzes/."""
    from knowlet.core.llm import AssistantMessage

    quiz_json = (
        '{"questions": ['
        '{"type": "recall", "question": "What is RAG?", '
        ' "reference_answer": "Retrieval-augmented generation.", '
        ' "source_note_ids": ["__NID__"]},'
        '{"type": "concept-explanation", "question": "Why fuse?", '
        ' "reference_answer": "Robust to single-retriever failure.", '
        ' "source_note_ids": ["__NID__"]}'
        ']}'
    )

    class GenerateLLM:
        def __init__(self, payload):
            self.payload = payload

        def chat(self, messages, tools=None, max_tokens=None, temperature=None):
            return AssistantMessage(content=self.payload, tool_calls=[])

    client, v, _ = _client_with_stub(tmp_path, GenerateLLM(quiz_json))
    runtime = client.app.state.web_state.runtime_or_init()

    n = Note(id=new_id(), title="RAG", body="hybrid retrieval combines FTS + vec")
    v.write_note(n)
    runtime.index.upsert_note(n, chunk_size=64, chunk_overlap=16)

    # The stub doesn't substitute __NID__, but generate_quiz tolerates the
    # source_note_ids string verbatim. We just need the questions to land.
    r = client.post("/api/quiz/start", json={"note_ids": [n.id], "n": 2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["questions"]) == 2
    assert body["scope_note_ids"] == [n.id]
    assert body["session_score"] == 0  # not aggregated yet
    # On disk?
    assert (v.state_dir / "quizzes" / f"{body['id']}.json").exists()


def test_quiz_start_404_for_unknown_note(tmp_path: Path):
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.post("/api/quiz/start", json={"note_ids": ["nonexistent"], "n": 5})
    assert r.status_code == 404


def test_quiz_start_400_for_empty_note_list(tmp_path: Path):
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.post("/api/quiz/start", json={"note_ids": [], "n": 5})
    assert r.status_code == 400


def test_quiz_answer_grades_and_persists(tmp_path: Path):
    from knowlet.core.llm import AssistantMessage

    quiz_json = (
        '{"questions": [{"type": "recall", "question": "Q1?", '
        '"reference_answer": "A1", "source_note_ids": []}]}'
    )
    grade_json = '{"score": 4, "reason": "Solid.", "missing": []}'

    class TwoCallLLM:
        """First call returns generation; subsequent calls return grading."""

        def __init__(self):
            self.calls = 0

        def chat(self, messages, tools=None, max_tokens=None, temperature=None):
            self.calls += 1
            return AssistantMessage(
                content=quiz_json if self.calls == 1 else grade_json,
                tool_calls=[],
            )

    client, v, _ = _client_with_stub(tmp_path, TwoCallLLM())
    runtime = client.app.state.web_state.runtime_or_init()

    n = Note(id=new_id(), title="t", body="body")
    v.write_note(n)
    runtime.index.upsert_note(n, chunk_size=64, chunk_overlap=16)

    start = client.post("/api/quiz/start", json={"note_ids": [n.id], "n": 1}).json()
    qid = start["id"]

    r = client.post(
        f"/api/quiz/{qid}/answer",
        json={"question_index": 0, "user_answer": "RAG fuses retrieval + generation."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["questions"][0]["ai_score"] == 4
    assert body["questions"][0]["user_answer"].startswith("RAG fuses")
    assert "Solid" in body["questions"][0]["ai_reason"]


def test_quiz_complete_aggregates_score(tmp_path: Path):
    """After answering, complete should run aggregate_score (n_correct,
    session_score, finished_at)."""
    from knowlet.core.llm import AssistantMessage

    quiz_json = (
        '{"questions": ['
        '{"type": "recall", "question": "Q1?", "reference_answer": "A", "source_note_ids": []},'
        '{"type": "recall", "question": "Q2?", "reference_answer": "A", "source_note_ids": []}'
        ']}'
    )

    class ScriptedLLM:
        def __init__(self):
            self.replies = [
                quiz_json,
                '{"score": 5, "reason": "perfect", "missing": []}',
                '{"score": 3, "reason": "ok", "missing": []}',
            ]

        def chat(self, messages, tools=None, max_tokens=None, temperature=None):
            return AssistantMessage(content=self.replies.pop(0), tool_calls=[])

    client, v, _ = _client_with_stub(tmp_path, ScriptedLLM())
    runtime = client.app.state.web_state.runtime_or_init()

    n = Note(id=new_id(), title="t", body="body")
    v.write_note(n)
    runtime.index.upsert_note(n, chunk_size=64, chunk_overlap=16)

    start = client.post("/api/quiz/start", json={"note_ids": [n.id], "n": 2}).json()
    qid = start["id"]
    client.post(f"/api/quiz/{qid}/answer", json={"question_index": 0, "user_answer": "ok"})
    client.post(f"/api/quiz/{qid}/answer", json={"question_index": 1, "user_answer": "ok"})

    final = client.post(f"/api/quiz/{qid}/complete").json()
    assert final["n_questions"] == 2
    assert final["n_correct"] == 2  # 5 + 3 both ≥ PASS_QUESTION_SCORE
    # 5+3 = 8 / (2*5) * 100 = 80
    assert final["session_score"] == 80
    assert final["finished_at"]  # populated


def test_quiz_disagree_marks_question(tmp_path: Path):
    from knowlet.core.llm import AssistantMessage

    quiz_json = (
        '{"questions": [{"type": "recall", "question": "Q?", '
        '"reference_answer": "A", "source_note_ids": []}]}'
    )

    class ScriptedLLM:
        def __init__(self):
            self.replies = [
                quiz_json,
                '{"score": 2, "reason": "weak", "missing": ["x"]}',
            ]

        def chat(self, messages, tools=None, max_tokens=None, temperature=None):
            return AssistantMessage(content=self.replies.pop(0), tool_calls=[])

    client, v, _ = _client_with_stub(tmp_path, ScriptedLLM())
    runtime = client.app.state.web_state.runtime_or_init()
    n = Note(id=new_id(), title="t", body="body")
    v.write_note(n)
    runtime.index.upsert_note(n, chunk_size=64, chunk_overlap=16)

    start = client.post("/api/quiz/start", json={"note_ids": [n.id], "n": 1}).json()
    qid = start["id"]
    client.post(f"/api/quiz/{qid}/answer", json={"question_index": 0, "user_answer": "ans"})
    r = client.post(
        f"/api/quiz/{qid}/disagree",
        json={"question_index": 0, "disagree": True, "reason": "AI was too strict"},
    )
    assert r.status_code == 200
    q = r.json()["questions"][0]
    assert q["user_disagrees"] is True
    assert "too strict" in q["user_disagree_reason"]


def test_quiz_reflux_creates_card(tmp_path: Path):
    """M7.4.2 Cards reflux: convert one quiz question into a Card."""
    from knowlet.core.llm import AssistantMessage

    quiz_json = (
        '{"questions": [{"type": "recall", "question": "Why X?", '
        '"reference_answer": "Because X.", "source_note_ids": ["__NID__"]}]}'
    )

    class ScriptedLLM:
        def __init__(self):
            self.replies = [
                quiz_json,
                '{"score": 2, "reason": "missed", "missing": ["X"]}',
            ]

        def chat(self, messages, tools=None, max_tokens=None, temperature=None):
            return AssistantMessage(content=self.replies.pop(0), tool_calls=[])

    client, v, _ = _client_with_stub(tmp_path, ScriptedLLM())
    runtime = client.app.state.web_state.runtime_or_init()
    n = Note(id=new_id(), title="t", body="body", tags=["topic-a"])
    v.write_note(n)
    runtime.index.upsert_note(n, chunk_size=64, chunk_overlap=16)

    start = client.post("/api/quiz/start", json={"note_ids": [n.id], "n": 1}).json()
    qid = start["id"]
    client.post(f"/api/quiz/{qid}/answer", json={"question_index": 0, "user_answer": "shrug"})

    r = client.post(f"/api/quiz/{qid}/reflux", json={"question_index": 0})
    assert r.status_code == 200, r.text
    body = r.json()
    card_id = body["questions"][0]["card_id_after_reflux"]
    assert card_id  # populated
    assert body["cards_created"] == 1

    # And the Card actually lives in the cards dir.
    card_resp = client.get(f"/api/cards/{card_id}")
    assert card_resp.status_code == 200
    cd = card_resp.json()
    assert cd["front"] == "Why X?"
    assert cd["back"] == "Because X."
    # tags = source-note tags ∪ {"quiz"}
    assert "quiz" in cd["tags"]


def test_quiz_reflux_idempotent(tmp_path: Path):
    """Calling reflux twice on the same question doesn't double-create."""
    from knowlet.core.llm import AssistantMessage

    quiz_json = (
        '{"questions": [{"type": "recall", "question": "Q?", '
        '"reference_answer": "A", "source_note_ids": []}]}'
    )

    class ScriptedLLM:
        def __init__(self):
            self.replies = [
                quiz_json,
                '{"score": 2, "reason": "...", "missing": []}',
            ]

        def chat(self, messages, tools=None, max_tokens=None, temperature=None):
            return AssistantMessage(content=self.replies.pop(0), tool_calls=[])

    client, v, _ = _client_with_stub(tmp_path, ScriptedLLM())
    runtime = client.app.state.web_state.runtime_or_init()
    n = Note(id=new_id(), title="t", body="body")
    v.write_note(n)
    runtime.index.upsert_note(n, chunk_size=64, chunk_overlap=16)

    start = client.post("/api/quiz/start", json={"note_ids": [n.id], "n": 1}).json()
    qid = start["id"]
    client.post(f"/api/quiz/{qid}/answer", json={"question_index": 0, "user_answer": "ans"})

    first = client.post(f"/api/quiz/{qid}/reflux", json={"question_index": 0}).json()
    second = client.post(f"/api/quiz/{qid}/reflux", json={"question_index": 0}).json()
    assert first["questions"][0]["card_id_after_reflux"] == second["questions"][0]["card_id_after_reflux"]
    assert second["cards_created"] == 1


def test_quiz_get_404_for_unknown(tmp_path: Path):
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.get("/api/quiz/01HXNONEXISTENT00000000000")
    assert r.status_code == 404


# ------------------------------------------------------------- M7.4.3 tag scope + list


def test_quiz_start_with_tag_scope_resolves_notes(tmp_path: Path):
    """M7.4.3: scope_type='tag' resolves all notes carrying the tag.
    No need to send note_ids explicitly."""
    from knowlet.core.llm import AssistantMessage

    quiz_json = (
        '{"questions": [{"type": "recall", "question": "Q?", '
        '"reference_answer": "A", "source_note_ids": []}]}'
    )

    class GenerateLLM:
        def chat(self, messages, tools=None, max_tokens=None, temperature=None):
            return AssistantMessage(content=quiz_json, tool_calls=[])

    client, v, _ = _client_with_stub(tmp_path, GenerateLLM())
    runtime = client.app.state.web_state.runtime_or_init()

    n1 = Note(id=new_id(), title="A", body="body a", tags=["topic-x"])
    n2 = Note(id=new_id(), title="B", body="body b", tags=["topic-x", "extra"])
    n3 = Note(id=new_id(), title="C", body="body c", tags=["other"])
    for n in (n1, n2, n3):
        v.write_note(n)
        runtime.index.upsert_note(n, chunk_size=64, chunk_overlap=16)

    r = client.post(
        "/api/quiz/start",
        json={"scope_type": "tag", "tag": "topic-x", "n": 1},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scope_type"] == "tag"
    assert body["scope_tag"] == "topic-x"
    # Both n1 and n2 carry the tag.
    assert set(body["scope_note_ids"]) == {n1.id, n2.id}


def test_quiz_start_tag_scope_404_when_no_match(tmp_path: Path):
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.post("/api/quiz/start", json={"scope_type": "tag", "tag": "no-match", "n": 5})
    assert r.status_code == 404


def test_quiz_start_tag_scope_400_when_tag_empty(tmp_path: Path):
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.post("/api/quiz/start", json={"scope_type": "tag", "tag": "", "n": 5})
    assert r.status_code == 400


def test_quiz_start_cluster_scope_blocked_until_layer_b(tmp_path: Path):
    """M7.4.3: cluster scope is wire-compatible but the route returns
    501 until M8 Layer B lands. Catches any frontend that ships the
    cluster picker too early."""
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.post(
        "/api/quiz/start",
        json={"scope_type": "cluster", "cluster_id": "c1", "n": 5},
    )
    assert r.status_code == 501


def test_quiz_list_returns_recent_sessions(tmp_path: Path):
    """M7.4.3: GET /api/quiz lists past sessions (light row, no question text)."""
    from knowlet.core.quiz import QuizSession
    from knowlet.core.quiz_store import QuizStore
    from datetime import UTC, datetime, timedelta

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    runtime = client.app.state.web_state.runtime_or_init()
    store = QuizStore(runtime.vault.state_dir)
    now = datetime.now(UTC)
    store.save(
        QuizSession(
            id="01HXNEW",
            started_at=(now).strftime("%Y-%m-%dT%H:%M:%SZ"),
            session_score=80,
            n_questions=5,
            n_correct=4,
        )
    )
    store.save(
        QuizSession(
            id="01HXOLD",
            started_at=(now - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            session_score=60,
            n_questions=5,
            n_correct=3,
        )
    )
    rows = client.get("/api/quiz?limit=10").json()
    assert len(rows) == 2
    # Newest first.
    assert rows[0]["id"] == "01HXNEW"
    assert rows[0]["session_score"] == 80
    # Light shape — no `questions` key.
    assert "questions" not in rows[0]
