"""Structured stream events for chat turns.

Per ADR-0008 (CLI parity discipline), streaming responses live as a single
event-generator at the backend layer. Both the CLI REPL (rendering with
rich.Live) and the web SSE endpoint subscribe to the **same** generator.
Tests assert event sequences directly — no display-layer assertions needed.

Event schema is intentionally narrow and JSON-friendly so the web layer can
serialize each event to an SSE `data:` line without adapter logic.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass
class ToolCallEvent:
    """The model decided to call a tool. Args may be empty during early chunks."""

    type: Literal["tool_call"] = "tool_call"
    id: str = ""
    name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResultEvent:
    """The atomic-tool handler produced a structured payload."""

    type: Literal["tool_result"] = "tool_result"
    id: str = ""
    name: str = ""
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReplyChunkEvent:
    """A token (or short string) of the assistant's natural-language reply."""

    type: Literal["reply_chunk"] = "reply_chunk"
    text: str = ""


@dataclass
class ReplyDoneEvent:
    """The current LLM call finished. May be followed by more tool_call events
    in the next iteration of the tool-loop."""

    type: Literal["reply_done"] = "reply_done"
    final_text: str = ""


@dataclass
class TurnDoneEvent:
    """The full user-turn completed (tool-loop exhausted; final assistant reply assembled)."""

    type: Literal["turn_done"] = "turn_done"
    final_text: str = ""


@dataclass
class ErrorEvent:
    type: Literal["error"] = "error"
    message: str = ""


ChatEvent = (
    ToolCallEvent
    | ToolResultEvent
    | ReplyChunkEvent
    | ReplyDoneEvent
    | TurnDoneEvent
    | ErrorEvent
)


def event_to_dict(event: ChatEvent) -> dict[str, Any]:
    """Serialize an event for transport (SSE / CLI line / test assertion)."""
    return asdict(event)
