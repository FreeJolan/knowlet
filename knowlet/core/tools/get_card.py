"""get_card — fetch a Card by id."""

from __future__ import annotations

from typing import Any

from knowlet.core.card import parse_due
from knowlet.core.tools._registry import ToolContext, ToolDef


def _handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    card_id = (args.get("card_id") or "").strip()
    if not card_id:
        return {
            "error": "card_id is empty",
            "suggestion": "pass a card_id from list_due_cards or create_card",
        }
    card = ctx.cards.get(card_id)
    if card is None:
        return {
            "error": f"card not found: {card_id}",
            "suggestion": "call list_due_cards to find a valid id",
        }
    return {
        "card": {
            "id": card.id,
            "type": card.type,
            "front": card.front,
            "back": card.back,
            "tags": card.tags,
            "source_note_id": card.source_note_id,
            "created_at": card.created_at,
            "updated_at": card.updated_at,
            "due": parse_due(card).isoformat(),
            "fsrs_state": card.fsrs_state,
        }
    }


TOOL = ToolDef(
    name="get_card",
    description=(
        "Fetch a single Card by id. Use this if you need the full content "
        "(front + back + tags + scheduling state) before deciding how to "
        "review it."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "card_id": {
                "type": "string",
                "description": "the Card's ULID",
            },
        },
        "required": ["card_id"],
        "additionalProperties": False,
    },
    handler=_handler,
)
