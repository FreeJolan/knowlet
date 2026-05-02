"""Atomic-capability registry.

Each tool declares an MCP-style schema (name + description + JSON Schema
input). The registry can:
- export the tool list in OpenAI function-calling format
- dispatch a tool call by name

Tools follow ADR-0004 constraints: input/output explicit, side effects
limited and reversible, return structured payloads (not natural language),
and errors carry a `suggestion` field for the LLM to recover from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from knowlet.config import KnowletConfig
from knowlet.core.card_store import CardStore
from knowlet.core.drafts import DraftStore
from knowlet.core.index import Index
from knowlet.core.mining.task_store import TaskStore
from knowlet.core.vault import Vault


@dataclass
class ToolContext:
    vault: Vault
    index: Index
    config: KnowletConfig
    cards: CardStore
    tasks: TaskStore
    drafts: DraftStore
    # Per-turn rate-limit counters. ChatSession resets this at the start of
    # each `user_turn` / `user_turn_stream`. Tools that need a per-turn cap
    # (web_search, fetch_url) read+increment their own key here. Free-form
    # so future tools can add new keys without changing this dataclass.
    per_turn: dict[str, int] = field(default_factory=dict)


@dataclass
class ToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any], ToolContext], dict[str, Any]]


@dataclass
class Registry:
    tools: dict[str, ToolDef] = field(default_factory=dict)

    def register(self, tool: ToolDef) -> None:
        if tool.name in self.tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self.tools[tool.name] = tool

    def get(self, name: str) -> ToolDef | None:
        return self.tools.get(name)

    def openai_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in self.tools.values()
        ]

    def dispatch(self, name: str, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        tool = self.get(name)
        if tool is None:
            return {
                "error": f"unknown tool: {name}",
                "suggestion": "call `list_tools` or pick a name from the provided tool list",
            }
        try:
            return tool.handler(args, ctx)
        except Exception as exc:  # noqa: BLE001 — boundary
            return {
                "error": f"{type(exc).__name__}: {exc}",
                "suggestion": "check the input shape and retry",
            }


def _build_default_registry() -> Registry:
    from knowlet.core.tools import (
        approve_draft,
        create_card,
        fetch_url,
        get_card,
        get_draft,
        get_note,
        get_user_profile,
        list_drafts,
        list_due_cards,
        list_mining_tasks,
        list_recent_notes,
        reject_draft,
        review_card,
        run_mining_task,
        search_notes,
        web_search,
    )

    reg = Registry()
    reg.register(search_notes.TOOL)
    reg.register(get_note.TOOL)
    reg.register(list_recent_notes.TOOL)
    reg.register(get_user_profile.TOOL)
    reg.register(create_card.TOOL)
    reg.register(get_card.TOOL)
    reg.register(list_due_cards.TOOL)
    reg.register(review_card.TOOL)
    reg.register(list_mining_tasks.TOOL)
    reg.register(run_mining_task.TOOL)
    reg.register(list_drafts.TOOL)
    reg.register(get_draft.TOOL)
    reg.register(approve_draft.TOOL)
    reg.register(reject_draft.TOOL)
    # M7.5 / ADR-0017: backend-agnostic web search. Two-stage pattern —
    # web_search returns snippets, fetch_url pulls full bodies.
    reg.register(web_search.TOOL)
    reg.register(fetch_url.TOOL)
    return reg


default_registry = _build_default_registry
