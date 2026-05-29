"""HTTP-API tests for the note-anchored discussion endpoint.

Phase 3 Stage 4 redesign, P1 — grounded discussion pane. The pane is
Cursor-style "chat about this note": a conversation anchored to a
specific note, with the note's content grounded into the user turn
so the user never re-explains context (closes pain (a)).

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

from knowlet.chat.note_chat import build_grounded_turn, wants_current_note_edit_proposal
from knowlet.config import KnowletConfig, save_config
from knowlet.core.drafts import Draft, DraftStore
from knowlet.core.events import ReplyChunkEvent, ReplyDoneEvent, ToolCallEvent
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


class CheckCurrentNoteStubLLM:
    """Streams a tool call, then answers after the tool result is added.

    The same object also serves the nested `check_note` LLM call through
    `.chat`, mirroring the real runtime where the note-chat tool loop and
    the Stage D checker share the configured model client.
    """

    def __init__(self) -> None:
        self.stream_calls = 0
        self.check_messages: list[dict[str, Any]] | None = None

    def chat_stream(
        self, messages, tools=None, max_tokens=None, temperature=None
    ) -> Iterator[Any]:
        self.stream_calls += 1
        if self.stream_calls == 1:
            yield ToolCallEvent(
                id="check_1",
                name="check_current_note",
                arguments={"instruction": "重点检查 RAG 事实错误"},
            )
            yield ReplyDoneEvent(final_text="")
            return
        yield ReplyChunkEvent(text="校准完成。")
        yield ReplyDoneEvent(final_text="校准完成。")

    def chat(self, messages, tools=None, max_tokens=None, temperature=None):
        self.check_messages = messages
        return AssistantMessage(
            content=json.dumps(
                {
                    "summary": "发现一处高风险事实错误。",
                    "findings": [
                        {
                            "severity": "high",
                            "paragraph": 1,
                            "quote": "RAG means putting every note into the prompt.",
                            "finding": "RAG 不是把全部笔记塞进 prompt。",
                            "why": "RAG 是先检索相关材料,再把相关上下文交给生成模型。",
                            "suggestion": "改为先检索、再生成的描述。",
                            "fix_instruction": "把第 1 段改成检索相关笔记再生成。",
                            "confidence": 0.92,
                        }
                    ],
                }
            ),
            tool_calls=[],
        )


class ProposeCurrentNoteEditStubLLM:
    """Streams a current-note edit proposal tool call, then answers after
    the proposal has been returned to the tool loop."""

    def __init__(self, new_body: str) -> None:
        self.new_body = new_body
        self.stream_calls = 0
        self.propose_messages: list[dict[str, Any]] | None = None

    def chat_stream(
        self, messages, tools=None, max_tokens=None, temperature=None
    ) -> Iterator[Any]:
        self.stream_calls += 1
        if self.stream_calls == 1:
            yield ToolCallEvent(
                id="edit_1",
                name="propose_current_note_edit",
                arguments={"instruction": "把 RAG 描述改得更准确,保持最小改动"},
            )
            yield ReplyDoneEvent(final_text="")
            return
        yield ReplyChunkEvent(text="我已经准备好一版可审阅的 diff。")
        yield ReplyDoneEvent(final_text="我已经准备好一版可审阅的 diff。")

    def chat(self, messages, tools=None, max_tokens=None, temperature=None):
        self.propose_messages = messages
        return AssistantMessage(
            content=json.dumps({"new_body": self.new_body}),
            tool_calls=[],
        )


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


def _client_with_draft(
    tmp_path: Path, body: str, stub: Any
) -> tuple[TestClient, Draft]:
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

    draft = Draft(id=new_id(), title="Digest item", body=body, tags=["digest"])
    DraftStore(v.drafts_dir).save(draft)

    app = create_app(v, cfg)
    client = TestClient(app)
    runtime = app.state.web_state.runtime_or_init()
    runtime.llm = stub  # type: ignore[assignment]
    runtime.session.llm = stub  # type: ignore[assignment]
    return client, draft


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


def test_note_chat_can_trigger_current_note_check_tool(tmp_path: Path):
    """Stage D through normal conversation: the model can call a
    note-scoped checker tool from the Discuss stream, the UI receives a
    structured tool trace, and the note remains read-only."""
    stub = CheckCurrentNoteStubLLM()
    client, note = _client_with_note(
        tmp_path,
        body="RAG means putting every note into the prompt.",
        stub=stub,
    )

    r = client.post(
        f"/api/chat/note/{note.id}/stream",
        json={"text": "帮我检查这篇笔记有没有错漏"},
    )

    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert [e["type"] for e in events] == [
        "tool_call",
        "tool_result",
        "reply_chunk",
        "turn_done",
    ]
    assert events[0]["name"] == "check_current_note"
    assert events[1]["name"] == "check_current_note"
    payload = events[1]["payload"]
    assert payload["note_id"] == note.id
    assert payload["summary"] == "发现一处高风险事实错误。"
    assert payload["findings"][0]["finding"] == "RAG 不是把全部笔记塞进 prompt。"
    assert stub.check_messages is not None
    checker_prompt = "\n".join(
        m["content"] for m in stub.check_messages if m["role"] == "user"
    )
    assert "RAG means putting every note into the prompt." in checker_prompt

    after = client.get(f"/api/notes/{note.id}").json()
    assert after["body"] == "RAG means putting every note into the prompt."


def test_note_chat_can_trigger_current_note_edit_proposal_tool(tmp_path: Path):
    """Normal discussion can ask for an applyable note change: the model
    calls a note-scoped proposal tool, the SSE payload carries old/new
    bodies for the diff UI, and the note remains untouched until the user
    accepts the diff."""
    new_body = "RAG retrieves relevant chunks, then generates an answer."
    stub = ProposeCurrentNoteEditStubLLM(new_body)
    client, note = _client_with_note(
        tmp_path,
        body="RAG puts every note into the prompt.",
        stub=stub,
    )

    r = client.post(
        f"/api/chat/note/{note.id}/stream",
        json={"text": "请帮我把这篇笔记改得更准确,但先给我 diff 审。"},
    )

    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert [e["type"] for e in events] == [
        "tool_call",
        "tool_result",
        "reply_chunk",
        "turn_done",
    ]
    assert events[0]["name"] == "propose_current_note_edit"
    payload = events[1]["payload"]
    assert payload["note_id"] == note.id
    assert payload["changed"] is True
    assert payload["old_body"] == "RAG puts every note into the prompt."
    assert payload["new_body"] == new_body
    assert payload["summary"] == "已生成可审阅的修改提案。"
    assert stub.propose_messages is not None
    propose_prompt = "\n".join(
        m["content"] for m in stub.propose_messages if m["role"] == "user"
    )
    assert "RAG puts every note into the prompt." in propose_prompt

    after = client.get(f"/api/notes/{note.id}").json()
    assert after["body"] == "RAG puts every note into the prompt."


def test_note_chat_routes_explicit_diff_prompt_to_proposal_tool(tmp_path: Path):
    """When the user's own message explicitly asks for a reviewable diff,
    the app should not rely on the model choosing the tool. It should emit
    the same tool trace deterministically and open the normal DiffReview path."""

    class DirectProposalLLM:
        def __init__(self) -> None:
            self.stream_called = False
            self.propose_messages: list[dict[str, Any]] | None = None

        def chat_stream(self, *args: Any, **kwargs: Any) -> Iterator[Any]:
            self.stream_called = True
            yield ReplyDoneEvent(final_text="")

        def chat(self, messages, tools=None, max_tokens=None, temperature=None):
            self.propose_messages = messages
            return AssistantMessage(
                content=json.dumps({"new_body": "RAG retrieves, then generates."}),
                tool_calls=[],
            )

    stub = DirectProposalLLM()
    client, note = _client_with_note(
        tmp_path,
        body="RAG puts everything into the prompt.",
        stub=stub,
    )

    r = client.post(
        f"/api/chat/note/{note.id}/stream",
        json={
            "text": (
                "请为这篇笔记生成一个可在 diff 中审阅的最小改写提案,"
                "不要直接把整篇改写正文贴在聊天里。"
            )
        },
    )

    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert [e["type"] for e in events] == [
        "tool_call",
        "tool_result",
        "reply_chunk",
        "turn_done",
    ]
    assert events[0]["name"] == "propose_current_note_edit"
    assert events[1]["payload"]["changed"] is True
    assert events[1]["payload"]["old_body"] == "RAG puts everything into the prompt."
    assert events[1]["payload"]["new_body"] == "RAG retrieves, then generates."
    assert "diff 中审阅" in events[0]["arguments"]["instruction"]
    assert "diff 中审阅" in events[2]["text"]
    assert stub.stream_called is False

    after = client.get(f"/api/notes/{note.id}").json()
    assert after["body"] == "RAG puts everything into the prompt."


def test_draft_chat_streams_grounded_reply(tmp_path: Path):
    """C3: digest drafts can be discussed before the user decides to
    skip/save/internalize. The draft body must reach the same grounded
    note-chat machinery without first promoting it to a Note."""
    stub = StreamStubLLM([ReplyDoneEvent(final_text="draft answer")])
    client, draft = _client_with_draft(
        tmp_path, body="The feed item argues that notes need context.", stub=stub
    )
    r = client.post(
        f"/api/chat/draft/{draft.id}/stream", json={"text": "what matters here?"}
    )
    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert "turn_done" in [e["type"] for e in events]
    assert stub.seen_messages is not None
    user_blob = "\n".join(
        m["content"] for m in stub.seen_messages if m["role"] == "user"
    )
    assert "The feed item argues that notes need context." in user_blob


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
    assert "内部判断这篇笔记是什么性质" in user_blob  # tone guidance in the user turn
    assert "不要把分类判断过程写给用户" in user_blob
    assert "Markdown" in user_blob
    assert "UNIQUE_GROUND_MARKER_42" not in system_blob  # not only in system


def test_emotional_tone_guidance_is_non_fixing_and_non_cliche() -> None:
    note = Note(
        id="n1",
        title="今日反思",
        body="今天被很多事情压着,很疲惫,也有点委屈。",
        tags=["daily"],
    )
    turn = build_grounded_turn(note, "陪我聊聊")
    assert "先接住和映照具体感受" in turn
    assert "不急着给建议" in turn
    assert "不要诊断" in turn
    assert "不灌鸡汤" in turn
    assert "最多只问一个轻问题" in turn


def test_edit_intent_router_is_limited_to_applyable_note_changes() -> None:
    assert wants_current_note_edit_proposal(
        "请为这篇笔记生成一个可在 diff 中审阅的最小改写提案"
    )
    assert wants_current_note_edit_proposal("帮我把这篇笔记改写得更清楚")
    assert not wants_current_note_edit_proposal("帮我检查这篇笔记有没有错漏")


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


def test_draft_internalize_proposes_diff_without_writing(tmp_path: Path):
    """C3: internalizing a digest item asks AI for a knowledge-note body,
    but still writes nothing until the UI diff is accepted."""
    new_body = "# My take\n\nContext beats recall."
    stub = ChatStubLLM(json.dumps({"new_body": new_body}))
    client, draft = _client_with_draft(
        tmp_path, body="Source says context helps recall.", stub=stub
    )
    r = client.post(
        f"/api/chat/draft/{draft.id}/propose-internalize",
        json={"instruction": "turn this into my own durable note"},
    )
    assert r.status_code == 200
    d = r.json()
    assert d["changed"] is True
    assert d["old_body"] == "Source says context helps recall."
    assert "Context beats recall" in d["new_body"]

    # Proposal only: the draft and notes collection are untouched.
    draft_after = client.get(f"/api/drafts/{draft.id}").json()
    assert draft_after["body"] == "Source says context helps recall."
    assert client.get("/api/notes").json() == []
