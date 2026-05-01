"""Tests for the streaming chat path (events module + LLMClient.chat_stream + ChatSession.user_turn_stream).

Streams are tested at the event-sequence level — no display-layer assertions.
This is the discipline ADR-0008 codifies: any UI that renders these events
gets coverage by virtue of the backend tests.
"""

from pathlib import Path
from typing import Any, Iterator

from knowlet.chat.bootstrap import bootstrap_chat
from knowlet.config import KnowletConfig, save_config
from knowlet.core.events import (
    ErrorEvent,
    ReplyChunkEvent,
    ReplyDoneEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnDoneEvent,
    event_to_dict,
)
from knowlet.core.note import Note, new_id
from knowlet.core.vault import Vault


def _ready_vault(tmp_path: Path) -> tuple[Vault, KnowletConfig]:
    v = Vault(tmp_path)
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = "stub"
    save_config(v.root, cfg)
    return v, cfg


class StreamStubLLM:
    """LLM stub that yields scripted event sequences from chat_stream."""

    def __init__(self, scripts: list[list[Any]]):
        self.scripts = list(scripts)
        self.calls = 0

    def chat_stream(
        self, messages, tools=None, max_tokens=None, temperature=None
    ) -> Iterator[Any]:
        self.calls += 1
        events = self.scripts.pop(0)
        for ev in events:
            yield ev


# ----------------------------------------------------- events module


def test_event_to_dict_round_trip():
    ev = ReplyChunkEvent(text="hello")
    d = event_to_dict(ev)
    assert d == {"type": "reply_chunk", "text": "hello"}

    ev = ToolCallEvent(id="x", name="search_notes", arguments={"q": "rag"})
    d = event_to_dict(ev)
    assert d == {
        "type": "tool_call",
        "id": "x",
        "name": "search_notes",
        "arguments": {"q": "rag"},
    }


# ----------------------------------------------------- ChatSession.user_turn_stream


def test_stream_simple_reply_no_tools(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    runtime, _ = bootstrap_chat(v, cfg)
    runtime.session.llm = StreamStubLLM(  # type: ignore[assignment]
        [
            [
                ReplyChunkEvent(text="hello "),
                ReplyChunkEvent(text="world"),
                ReplyDoneEvent(final_text="hello world"),
            ]
        ]
    )
    try:
        events = list(runtime.session.user_turn_stream("hi"))
    finally:
        runtime.close()
    types = [type(e).__name__ for e in events]
    assert types == ["ReplyChunkEvent", "ReplyChunkEvent", "TurnDoneEvent"]
    assert isinstance(events[-1], TurnDoneEvent)
    assert events[-1].final_text == "hello world"


def test_stream_with_tool_call_then_final_reply(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    n = Note(id=new_id(), title="Note A", body="some content")
    v.write_note(n)

    runtime, _ = bootstrap_chat(v, cfg)
    runtime.session.llm = StreamStubLLM(  # type: ignore[assignment]
        [
            # Iteration 1: model calls search_notes (no content tokens)
            [
                ToolCallEvent(
                    id="call_1",
                    name="search_notes",
                    arguments={"query": "Note", "limit": 1},
                ),
                ReplyDoneEvent(final_text=""),
            ],
            # Iteration 2: model produces the final reply
            [
                ReplyChunkEvent(text="Found "),
                ReplyChunkEvent(text="Note A."),
                ReplyDoneEvent(final_text="Found Note A."),
            ],
        ]
    )
    try:
        events = list(runtime.session.user_turn_stream("any notes?"))
    finally:
        runtime.close()
    types = [type(e).__name__ for e in events]
    assert types == [
        "ToolCallEvent",
        "ToolResultEvent",
        "ReplyChunkEvent",
        "ReplyChunkEvent",
        "TurnDoneEvent",
    ]
    tool_result = events[1]
    assert isinstance(tool_result, ToolResultEvent)
    assert tool_result.name == "search_notes"
    assert "results" in tool_result.payload

    final = events[-1]
    assert isinstance(final, TurnDoneEvent)
    assert final.final_text == "Found Note A."


def test_stream_propagates_llm_failure_as_error_event(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    runtime, _ = bootstrap_chat(v, cfg)

    class BoomLLM:
        def chat_stream(self, *a, **kw):
            raise RuntimeError("network gone")

    runtime.session.llm = BoomLLM()  # type: ignore[assignment]
    try:
        events = list(runtime.session.user_turn_stream("hi"))
    finally:
        runtime.close()
    assert len(events) == 1
    err = events[0]
    assert isinstance(err, ErrorEvent)
    assert "network gone" in err.message


def test_stream_iter_limit_yields_error(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    runtime, _ = bootstrap_chat(v, cfg)
    runtime.session.max_tool_iters = 2

    # Both iterations claim a tool call → exceeds the limit.
    looped = [
        [
            ToolCallEvent(id=f"c{i}", name="search_notes", arguments={"query": "x"}),
            ReplyDoneEvent(final_text=""),
        ]
        for i in range(3)
    ]
    runtime.session.llm = StreamStubLLM(looped)  # type: ignore[assignment]

    try:
        events = list(runtime.session.user_turn_stream("loop"))
    finally:
        runtime.close()
    last = events[-1]
    assert isinstance(last, ErrorEvent)
    assert "iteration limit" in last.message
