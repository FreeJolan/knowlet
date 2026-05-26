"""HTTP-API tests for the note-anchored discussion endpoint.

Phase 3 Stage 4 redesign, P1 — grounded discussion pane. The pane is
Cursor-style "chat about this note": a conversation anchored to a
specific note, with the note's content grounded into the system
prompt so the user never re-explains context (closes pain (a)).

Per ADR-0008, the endpoint is a thin shell over a core helper that
assembles a note-grounded ``ChatSession``; this file tests the HTTP
seam — SSE streaming, grounding, 404, and the LLM-failure event.
Real tool-loop behavior is covered by the shared streaming-generator
tests (test_streaming.py); the e2e suite covers the pane UI + the
failure UX. Mirrors the StubLLM + _client_with_stub pattern in
test_web.py, but seeds a note first and scripts ``chat_stream``.
"""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from knowlet.config import KnowletConfig, save_config
from knowlet.core.events import ReplyChunkEvent, ReplyDoneEvent
from knowlet.core.llm import AssistantMessage
from knowlet.core.note import Note, new_id
from knowlet.core.vault import Vault


class StreamStubLLM:
    """Captures the messages it was handed, then yields a scripted event
    stream from ``chat_stream`` (the path ``user_turn_stream`` drives)."""

    def __init__(self, events: list[Any]):
        self._events = list(events)
        self.seen_messages: list[dict[str, Any]] | None = None

    def chat_stream(
        self, messages, tools=None, max_tokens=None, temperature=None
    ) -> Iterator[Any]:
        self.seen_messages = messages
        yield from self._events


def _client_with_note(
    tmp_path: Path, body: str, stub: Any
) -> tuple[TestClient, Note]:
    from knowlet.core.audit_log import AuditEventStore
    from knowlet.core.backups import BackupStore
    from knowlet.web.server import create_app

    v = Vault(
        tmp_path,
        audit_log=AuditEventStore(tmp_path),
        backups=BackupStore(tmp_path),
    )
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = "stub"
    save_config(v.root, cfg)

    # Seed the anchored note BEFORE the client so bootstrap indexes it.
    note = Note(id=new_id(), title="RAG 综述", body=body, tags=["rag"])
    v.write_note(note)

    app = create_app(v, cfg)
    client = TestClient(app)
    runtime = app.state.web_state.runtime_or_init()
    # The note-chat session reuses runtime.session.llm (like ask-once),
    # so patching that reference routes the call to our stub.
    runtime.llm = stub  # type: ignore[assignment]
    runtime.session.llm = stub  # type: ignore[assignment]
    return client, note


def _parse_sse(text: str) -> list[dict[str, Any]]:
    """Split a buffered ``text/event-stream`` body into event dicts."""
    events: list[dict[str, Any]] = []
    for block in text.strip().split("\n\n"):
        block = block.strip()
        if block.startswith("data:"):
            events.append(json.loads(block[len("data:") :].strip()))
    return events


def test_note_chat_streams_grounded_reply(tmp_path: Path):
    stub = StreamStubLLM(
        [
            ReplyChunkEvent(text="grounded "),
            ReplyChunkEvent(text="answer"),
            ReplyDoneEvent(final_text="grounded answer"),
        ]
    )
    client, note = _client_with_note(
        tmp_path, body="RAG retrieves then generates.", stub=stub
    )
    r = client.post(
        f"/api/chat/note/{note.id}/stream", json={"text": "explain this note"}
    )
    assert r.status_code == 200
    events = _parse_sse(r.text)
    types = [e["type"] for e in events]
    assert "reply_chunk" in types
    assert "turn_done" in types

    # Grounding (pain (a)): the note body reached the LLM without the
    # user re-explaining it. It must ride in a USER message (not only
    # system) — some proxies drop system; see the dropped-system test.
    assert stub.seen_messages is not None
    user_blob = "\n".join(
        m["content"] for m in stub.seen_messages if m["role"] == "user"
    )
    assert "RAG retrieves then generates." in user_blob


def test_note_chat_missing_note_is_404(tmp_path: Path):
    stub = StreamStubLLM([ReplyDoneEvent(final_text="")])
    client, _ = _client_with_note(tmp_path, body="x", stub=stub)
    r = client.post("/api/chat/note/no-such-id/stream", json={"text": "hi"})
    assert r.status_code == 404


def test_note_chat_llm_failure_yields_error_event(tmp_path: Path):
    """Branch (ii): LLM unreachable → the stream surfaces an error event
    so the pane can show an informed failure (per failure-path memory),
    not a silent stall."""

    class BoomLLM:
        def chat_stream(self, *a: Any, **kw: Any) -> Iterator[Any]:
            raise RuntimeError("upstream went down")
            yield  # pragma: no cover  (make this a generator)

    client, note = _client_with_note(tmp_path, body="x", stub=BoomLLM())
    r = client.post(f"/api/chat/note/{note.id}/stream", json={"text": "hi"})
    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert "error" in [e["type"] for e in events]
    msg = next(e["message"] for e in events if e["type"] == "error")
    assert "upstream went down" in msg


# ------------------------------ tone (AI infers from the note's nature)


def test_note_grounding_and_tone_guidance_in_user_turn(tmp_path: Path):
    """There is no user-selected stance: the AI infers tone from the
    note's nature. So the grounded turn carries (a) the note body and
    (b) the tone-guidance instruction — and both must ride in a USER
    message, never only in system (cliproxyapi-style proxies drop the
    caller's system message; dogfood 2026-05-25)."""
    stub = StreamStubLLM([ReplyDoneEvent(final_text="")])
    client, note = _client_with_note(
        tmp_path, body="UNIQUE_GROUND_MARKER_42", stub=stub
    )
    client.post(f"/api/chat/note/{note.id}/stream", json={"text": "hi"})
    assert stub.seen_messages is not None
    user_blob = "\n".join(
        m["content"] for m in stub.seen_messages if m["role"] == "user"
    )
    system_blob = "\n".join(
        m["content"] for m in stub.seen_messages if m["role"] == "system"
    )
    assert "UNIQUE_GROUND_MARKER_42" in user_blob  # note in the user turn
    assert "先判断这篇笔记是什么性质" in user_blob  # tone guidance in the user turn
    assert "UNIQUE_GROUND_MARKER_42" not in system_blob  # not only in system


# ------------------------------------- A6: multi-turn (conversation memory)


def test_note_chat_sends_prior_history_for_memory(tmp_path: Path):
    """A6: prior turns are forwarded so the model actually remembers the
    conversation (otherwise a restored chat the AI can't continue is
    half-baked). The current grounded turn stays last; the note grounding
    rides in it (prior turns are the clean exchange)."""
    stub = StreamStubLLM([ReplyDoneEvent(final_text="")])
    client, note = _client_with_note(tmp_path, body="NOTE_BODY", stub=stub)
    client.post(
        f"/api/chat/note/{note.id}/stream",
        json={
            "text": "第二个问题",
            "history": [
                {"role": "user", "content": "第一个问题"},
                {"role": "assistant", "content": "第一个回答"},
            ],
        },
    )
    assert stub.seen_messages is not None
    blob = "\n".join(m["content"] for m in stub.seen_messages)
    assert "第一个问题" in blob  # prior user turn forwarded
    assert "第一个回答" in blob  # prior assistant turn forwarded
    assert "第二个问题" in blob  # current turn present
    assert "NOTE_BODY" in blob  # grounding still present
    user_turns = [
        m["content"] for m in stub.seen_messages if m["role"] == "user"
    ]
    assert "第一个问题" in user_turns[0]  # prior exchange comes first
    assert "第二个问题" in user_turns[-1]  # current grounded turn is last


# ----------------------------------------- P3: AI proposes an edit (diff)


class ChatStubLLM:
    """Non-streaming stub for the propose-edit path (one ``.chat`` call)."""

    def __init__(self, content: str):
        self._content = content
        self.seen: list[Any] | None = None

    def chat(self, messages, tools=None, max_tokens=None, temperature=None):
        self.seen = messages
        return AssistantMessage(content=self._content, tool_calls=[])


def test_propose_edit_returns_a_diff_without_writing(tmp_path: Path):
    """P3: AI proposes a revised body; the endpoint returns old + new
    for the diff UI but does NOT touch the file on disk (per ADR-0029
    原则 1 — nothing lands without the user's diff-accept in P4)."""
    new_body = "RAG retrieves then generates. It also reranks the chunks."
    stub = ChatStubLLM(json.dumps({"new_body": new_body}))
    client, note = _client_with_note(
        tmp_path, body="RAG retrieves then generates.", stub=stub
    )
    r = client.post(
        f"/api/chat/note/{note.id}/propose-edit",
        json={"instruction": "note that it reranks"},
    )
    assert r.status_code == 200
    d = r.json()
    assert d["changed"] is True
    assert d["old_body"] == "RAG retrieves then generates."
    assert "reranks" in d["new_body"]
    # The note file is untouched — proposal only.
    after = client.get(f"/api/notes/{note.id}").json()
    assert "reranks" not in after["body"]


def test_propose_edit_noop_when_body_unchanged(tmp_path: Path):
    body = "this body does not change."
    stub = ChatStubLLM(json.dumps({"new_body": body}))
    client, note = _client_with_note(tmp_path, body=body, stub=stub)
    r = client.post(
        f"/api/chat/note/{note.id}/propose-edit",
        json={"instruction": "leave it alone"},
    )
    assert r.status_code == 200
    assert r.json()["changed"] is False


def test_propose_edit_invalid_output_is_noop_not_corruption(tmp_path: Path):
    """Branch (ii): a malformed / non-JSON AI reply must not corrupt the
    note — the endpoint reports changed=false so the pane can say
    '无可应用改动'."""
    stub = ChatStubLLM("sorry, I can't produce that")
    client, note = _client_with_note(tmp_path, body="intact body", stub=stub)
    r = client.post(
        f"/api/chat/note/{note.id}/propose-edit",
        json={"instruction": "x"},
    )
    assert r.status_code == 200
    assert r.json()["changed"] is False
    after = client.get(f"/api/notes/{note.id}").json()
    assert after["body"] == "intact body"
