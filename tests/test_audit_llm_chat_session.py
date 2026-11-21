"""Regression tests: an interrupted tool turn must not leave the session
history with an assistant tool call that has no tool output
(session.py:120, llm-chat audit batch)."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from knowlet.chat.session import ChatSession
from knowlet.core.events import ReplyDoneEvent, ToolCallEvent, ToolResultEvent
from knowlet.core.llm import AssistantMessage, ToolCall
from knowlet.core.tools._registry import Registry, ToolDef


def _registry(calls: list[str]) -> Registry:
    def handler(args: dict[str, Any], ctx: Any) -> dict[str, Any]:
        calls.append(args.get("q", ""))
        return {"ok": True, "q": args.get("q", "")}

    reg = Registry()
    reg.register(
        ToolDef(
            name="slow_tool",
            description="test tool",
            input_schema={"type": "object", "properties": {}},
            handler=handler,
        )
    )
    return reg


class _TwoToolCallsLLM:
    def chat_stream(self, messages, tools=None, max_tokens=None, temperature=None) -> Iterator[Any]:
        yield ToolCallEvent(id="call_a", name="slow_tool", arguments={"q": "a"})
        yield ToolCallEvent(id="call_b", name="slow_tool", arguments={"q": "b"})
        yield ReplyDoneEvent(final_text="")

    def chat(self, messages, tools=None, max_tokens=None, temperature=None):
        return AssistantMessage(
            content="",
            tool_calls=[
                ToolCall(id="call_a", name="slow_tool", arguments={"q": "a"}),
                ToolCall(id="call_b", name="slow_tool", arguments={"q": "b"}),
            ],
        )


def _session(calls: list[str]) -> ChatSession:
    return ChatSession(
        llm=_TwoToolCallsLLM(),  # type: ignore[arg-type]
        registry=_registry(calls),
        ctx=SimpleNamespace(per_turn={}),  # type: ignore[arg-type]
        system_prompt="sys",
    )


def _assert_every_tool_call_has_output(history: list[dict[str, Any]]) -> None:
    call_ids = [
        tc["id"]
        for m in history
        if m.get("role") == "assistant"
        for tc in (m.get("tool_calls") or [])
    ]
    output_ids = [m["tool_call_id"] for m in history if m.get("role") == "tool"]
    assert sorted(call_ids) == sorted(output_ids), (call_ids, output_ids)


def test_stream_closed_at_first_tool_result_keeps_history_consistent() -> None:
    """SSE client disconnects (GeneratorExit) right after the first tool
    result is yielded — the second tool never runs."""
    calls: list[str] = []
    session = _session(calls)
    gen = session.user_turn_stream("search twice")
    for ev in gen:
        if isinstance(ev, ToolResultEvent):
            break
    gen.close()

    assert calls == ["a"]
    _assert_every_tool_call_has_output(session.history)
    tool_msgs = {m["tool_call_id"]: m["content"] for m in session.history if m["role"] == "tool"}
    # The tool that actually ran keeps its real payload…
    assert '"q": "a"' in tool_msgs["call_a"]
    # …the one that never ran is recorded as interrupted, not left dangling.
    assert "interrupted" in tool_msgs["call_b"]


def test_stream_closed_at_tool_call_event_keeps_history_consistent() -> None:
    """Disconnect before ReplyDone: no assistant tool call may be
    committed without its output."""
    calls: list[str] = []
    session = _session(calls)
    gen = session.user_turn_stream("search twice")
    next(gen)  # first ToolCallEvent
    gen.close()
    assert calls == []
    _assert_every_tool_call_has_output(session.history)


def test_sync_turn_interrupted_mid_tools_keeps_history_consistent() -> None:
    """CLI REPL: Ctrl+C (KeyboardInterrupt) inside the tool callback."""
    calls: list[str] = []
    session = _session(calls)

    def on_tool_call(tc: ToolCall, payload: dict[str, Any]) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        session.user_turn("search twice", on_tool_call=on_tool_call)
    _assert_every_tool_call_has_output(session.history)
