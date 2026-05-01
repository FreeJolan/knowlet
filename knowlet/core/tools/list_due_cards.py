"""list_due_cards — surface Cards whose `due` <= now."""

from __future__ import annotations

from typing import Any

from knowlet.core.card import parse_due
from knowlet.core.tools._registry import ToolContext, ToolDef


def _handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    limit = int(args.get("limit") or 20)
    limit = max(1, min(limit, 100))
    due = ctx.cards.list_due(limit=limit)
    return {
        "results": [
            {
                "card_id": c.id,
                "type": c.type,
                "front": c.front,
                "back": c.back,
                "tags": c.tags,
                "due": parse_due(c).isoformat(),
                "state": c.fsrs_state.get("state"),
            }
            for c in due
        ],
        "count": len(due),
    }


TOOL = ToolDef(
    name="list_due_cards",
    description=(
        "List Cards that are due for review now (or earlier). Returns front, "
        "back, tags, and due time. Call this when the user wants to start a "
        "review session or asks how many cards are pending."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "description": "max number of due cards to return (default 20)",
            },
        },
        "additionalProperties": False,
    },
    handler=_handler,
)
