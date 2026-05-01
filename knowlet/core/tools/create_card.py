"""create_card — make a new spaced-repetition Card.

Used during scenario C (foreign-language vocab, concept disambiguation,
writing critique). The LLM can call this when the user says things like
"add this to my flashcards" or "remember this term".
"""

from __future__ import annotations

from typing import Any

from knowlet.core.card import CARD_TYPES, Card
from knowlet.core.fsrs_wrap import initial_state
from knowlet.core.tools._registry import ToolContext, ToolDef


def _handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    front = (args.get("front") or "").strip()
    back = (args.get("back") or "").strip()
    if not front or not back:
        return {
            "error": "front and back are both required",
            "suggestion": "front is the question / cue; back is the answer / explanation",
        }
    card_type = (args.get("type") or "basic").lower()
    if card_type not in CARD_TYPES:
        return {
            "error": f"unsupported card type: {card_type}",
            "suggestion": f"use one of {list(CARD_TYPES)}",
        }
    tags = [str(t).strip() for t in (args.get("tags") or []) if str(t).strip()]
    source_note_id = args.get("source_note_id") or None
    if source_note_id is not None and not isinstance(source_note_id, str):
        return {
            "error": "source_note_id must be a string note id or null",
            "suggestion": "pass the id from a previous search_notes / get_note result",
        }

    card = Card(
        type=card_type,
        front=front,
        back=back,
        tags=tags,
        source_note_id=source_note_id,
        fsrs_state=initial_state(),
    )
    ctx.cards.save(card)
    return {
        "card_id": card.id,
        "filename": card.filename,
        "due": card.fsrs_state.get("due"),
    }


TOOL = ToolDef(
    name="create_card",
    description=(
        "Create a new spaced-repetition Card. Use when the user wants to "
        "remember something via active recall (vocabulary, concept "
        "definitions, formula triggers, writing-critique notes). The new "
        "card becomes due immediately so it shows up in the next review."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "front": {
                "type": "string",
                "description": "the question / cue side",
            },
            "back": {
                "type": "string",
                "description": "the answer / explanation side",
            },
            "type": {
                "type": "string",
                "enum": ["basic", "cloze"],
                "description": "card style; default 'basic'",
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "1-5 short topic tags",
            },
            "source_note_id": {
                "type": ["string", "null"],
                "description": "optional Note id this card was derived from",
            },
        },
        "required": ["front", "back"],
        "additionalProperties": False,
    },
    handler=_handler,
)
