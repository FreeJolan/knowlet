"""Chat session: tool-loop driver around the LLM.

Stateless w.r.t. the filesystem — all side effects go through tools or the
sediment flow. This module is also reusable from a UI layer later (the REPL
in cli/main.py is a thin wrapper)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from knowlet.chat.prompts import CHAT_SYSTEM_PROMPT
from knowlet.core.events import (
    ChatEvent,
    ErrorEvent,
    ReplyChunkEvent,
    ReplyDoneEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnDoneEvent,
)
from knowlet.core.llm import (
    AssistantMessage,
    LLMClient,
    ToolCall,
    messages_with_assistant,
    messages_with_tool_results,
)
from knowlet.core.tools._registry import Registry, ToolContext

# Recorded as the output of a tool call that never ran because the turn was
# interrupted (client disconnect, Ctrl+C, error), so the history never holds
# an assistant tool call without a matching tool result.
INTERRUPTED_TOOL_PAYLOAD: dict[str, Any] = {
    "error": "tool call interrupted before it ran",
    "suggestion": "the previous turn was cut off; ask the user whether to retry",
}


@dataclass
class TurnTrace:
    """Observability payload for a single user turn (one or more LLM calls)."""

    tool_calls: list[tuple[ToolCall, dict[str, Any]]] = field(default_factory=list)
    final: AssistantMessage | None = None


@dataclass
class ChatSession:
    llm: LLMClient
    registry: Registry
    ctx: ToolContext
    max_tool_iters: int = 6
    history: list[dict[str, Any]] = field(default_factory=list)
    system_prompt: str | None = None

    def __post_init__(self) -> None:
        if not self.history:
            prompt = self.system_prompt if self.system_prompt is not None else CHAT_SYSTEM_PROMPT
            self.history.append({"role": "system", "content": prompt})

    def user_turn(
        self,
        user_text: str,
        on_tool_call: Callable[[ToolCall, dict[str, Any]], None] | None = None,
    ) -> tuple[str, TurnTrace]:
        self.history.append({"role": "user", "content": user_text})
        # M7.5 / ADR-0017: reset per-turn rate-limit counters so the
        # web_search budget restarts each turn.
        self.ctx.per_turn = {}
        trace = TurnTrace()
        tools = self.registry.openai_schema()

        for _ in range(self.max_tool_iters):
            assistant = self.llm.chat(self.history, tools=tools)

            if not assistant.tool_calls:
                self.history = messages_with_assistant(self.history, assistant)
                trace.final = assistant
                return assistant.content, trace

            results: list[tuple[str, dict[str, Any]]] = []
            try:
                for tc in assistant.tool_calls:
                    payload = self.registry.dispatch(tc.name, tc.arguments, self.ctx)
                    results.append((tc.id, payload))
                    trace.tool_calls.append((tc, payload))
                    if on_tool_call is not None:
                        on_tool_call(tc, payload)
            finally:
                self._commit_tool_round(assistant, results)

        trace.final = AssistantMessage(content="(tool loop iteration limit reached)")
        return trace.final.content, trace

    def _commit_tool_round(
        self,
        assistant: AssistantMessage,
        results: list[tuple[str, dict[str, Any]]],
    ) -> None:
        """Append an assistant tool-call message together with one result
        per call. Calls that never ran get INTERRUPTED_TOOL_PAYLOAD. Runs
        from ``finally`` so a disconnect / Ctrl+C mid-round cannot persist
        a tool call without its output (the API rejects such history)."""
        done = {tc_id for tc_id, _ in results}
        complete = list(results) + [
            (tc.id, INTERRUPTED_TOOL_PAYLOAD) for tc in assistant.tool_calls if tc.id not in done
        ]
        self.history = messages_with_tool_results(
            messages_with_assistant(self.history, assistant), complete
        )

    def user_turn_stream(self, user_text: str) -> Iterator[ChatEvent]:
        """Streaming variant of `user_turn`. Yields structured events that
        any UI (CLI REPL, web SSE, future desktop shell) can consume.

        Per ADR-0008, this generator is the **single** source of streaming
        chat behavior. Tests assert event sequences directly; UIs only render
        events, never reimplement the tool loop.
        """
        self.history.append({"role": "user", "content": user_text})
        self.ctx.per_turn = {}  # ADR-0017 per-turn tool budget reset
        tools = self.registry.openai_schema()

        for _ in range(self.max_tool_iters):
            content_buf: list[str] = []
            tool_calls: list[ToolCall] = []
            try:
                stream = self.llm.chat_stream(self.history, tools=tools)
            except Exception as exc:
                yield ErrorEvent(message=f"LLM stream error: {exc}")
                return

            try:
                for ev in stream:
                    if isinstance(ev, ReplyChunkEvent):
                        content_buf.append(ev.text)
                        yield ev
                    elif isinstance(ev, ToolCallEvent):
                        tool_calls.append(ToolCall(id=ev.id, name=ev.name, arguments=ev.arguments))
                        yield ev
                    elif isinstance(ev, ReplyDoneEvent):
                        final_text = "".join(content_buf)
                        assistant_msg = AssistantMessage(content=final_text, tool_calls=tool_calls)

                        if not tool_calls:
                            self.history = messages_with_assistant(self.history, assistant_msg)
                            yield TurnDoneEvent(final_text=final_text)
                            return

                        results: list[tuple[str, dict[str, Any]]] = []
                        try:
                            for tc in tool_calls:
                                payload = self.registry.dispatch(tc.name, tc.arguments, self.ctx)
                                # Record before yielding: the consumer may
                                # close the generator at this yield.
                                results.append((tc.id, payload))
                                yield ToolResultEvent(id=tc.id, name=tc.name, payload=payload)
                        finally:
                            self._commit_tool_round(assistant_msg, results)
            except Exception as exc:
                yield ErrorEvent(message=f"LLM stream error: {exc}")
                return

        yield ErrorEvent(message="tool loop iteration limit reached")
