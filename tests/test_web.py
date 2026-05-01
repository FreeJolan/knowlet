"""HTTP-API tests for the M2 web UI.

Stubs the LLM so tests don't need network. Verifies that every public endpoint
delegates to backend functions (single-source-of-truth discipline) and that
error paths produce structured responses.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from knowlet.config import KnowletConfig, save_config
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
