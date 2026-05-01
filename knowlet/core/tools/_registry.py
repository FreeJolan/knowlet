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
from knowlet.core.index import Index
from knowlet.core.vault import Vault


@dataclass
class ToolContext:
    vault: Vault
    index: Index
    config: KnowletConfig


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
        get_note,
        get_user_profile,
        list_recent_notes,
        search_notes,
    )

    reg = Registry()
    reg.register(search_notes.TOOL)
    reg.register(get_note.TOOL)
    reg.register(list_recent_notes.TOOL)
    reg.register(get_user_profile.TOOL)
    return reg


default_registry = _build_default_registry
