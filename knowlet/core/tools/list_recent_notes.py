"""list_recent_notes — surface recently-saved Notes."""

from __future__ import annotations

from typing import Any

from knowlet.core.tools._registry import ToolContext, ToolDef


def _handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    limit = int(args.get("limit") or 10)
    limit = max(1, min(limit, 50))
    rows = ctx.index.list_notes(limit=limit, order="updated_at")
    return {
        "results": [
            {
                "note_id": r["id"],
                "title": r["title"],
                "tags": r["tags"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ],
        "count": len(rows),
    }


TOOL = ToolDef(
    name="list_recent_notes",
    description=(
        "List the user's most recently updated Notes. Use this when the user "
        "asks what they've been saving, or wants a quick overview before diving "
        "into a topic."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50,
                "description": "max number of Notes to return (default 10)",
            },
        },
        "additionalProperties": False,
    },
    handler=_handler,
)
