"""Chat session: tool-loop driver around the LLM.

Stateless w.r.t. the filesystem — all side effects go through tools or the
sediment flow. This module is also reusable from a UI layer later (the REPL
in cli/main.py is a thin wrapper)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from knowlet.chat.prompts import CHAT_SYSTEM_PROMPT
from knowlet.core.llm import (
    AssistantMessage,
    LLMClient,
    ToolCall,
    messages_with_assistant,
    messages_with_tool_results,
)
from knowlet.core.tools._registry import Registry, ToolContext


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
        trace = TurnTrace()
        tools = self.registry.openai_schema()

        for _ in range(self.max_tool_iters):
            assistant = self.llm.chat(self.history, tools=tools)
            self.history = messages_with_assistant(self.history, assistant)

            if not assistant.tool_calls:
                trace.final = assistant
                return assistant.content, trace

            results: list[tuple[str, dict[str, Any]]] = []
            for tc in assistant.tool_calls:
                payload = self.registry.dispatch(tc.name, tc.arguments, self.ctx)
                trace.tool_calls.append((tc, payload))
                if on_tool_call is not None:
                    on_tool_call(tc, payload)
                results.append((tc.id, payload))

            self.history = messages_with_tool_results(self.history, results)

        trace.final = AssistantMessage(content="(tool loop iteration limit reached)")
        return trace.final.content, trace
