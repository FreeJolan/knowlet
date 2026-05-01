"""review_card — apply a user rating to a Card and update its schedule."""

from __future__ import annotations

from typing import Any

from knowlet.core.card import parse_due
from knowlet.core.fsrs_wrap import schedule_next
from knowlet.core.tools._registry import ToolContext, ToolDef


def _handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    card_id = (args.get("card_id") or "").strip()
    rating = args.get("rating")
    if not card_id:
        return {
            "error": "card_id is required",
            "suggestion": "pass a card_id from list_due_cards or create_card",
        }
    if rating is None:
        return {
            "error": "rating is required",
            "suggestion": "pass an integer 1 (again) / 2 (hard) / 3 (good) / 4 (easy), or the equivalent name",
        }

    card = ctx.cards.get(card_id)
    if card is None:
        return {
            "error": f"card not found: {card_id}",
            "suggestion": "call list_due_cards to find a valid id",
        }

    try:
        updated = schedule_next(card, rating)
    except ValueError as exc:
        return {"error": str(exc), "suggestion": "use an integer 1-4"}

    ctx.cards.save(updated)
    return {
        "card_id": updated.id,
        "next_due": parse_due(updated).isoformat(),
        "state": updated.fsrs_state.get("state"),
        "stability": updated.fsrs_state.get("stability"),
        "difficulty": updated.fsrs_state.get("difficulty"),
    }


TOOL = ToolDef(
    name="review_card",
    description=(
        "Record a review rating for a Card and reschedule its next due time. "
        "Ratings: 1=again (forgot), 2=hard (recalled with effort), 3=good "
        "(recalled comfortably), 4=easy (trivially recalled). Call this once "
        "per card per review session, after the user evaluated themselves."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "card_id": {
                "type": "string",
                "description": "the Card's ULID",
            },
            "rating": {
                "type": ["integer", "string"],
                "description": "1-4 or one of: 'again' | 'hard' | 'good' | 'easy'",
            },
        },
        "required": ["card_id", "rating"],
        "additionalProperties": False,
    },
    handler=_handler,
)
