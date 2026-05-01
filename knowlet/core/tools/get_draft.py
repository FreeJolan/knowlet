"""get_draft — read a single draft's content."""

from __future__ import annotations

from typing import Any

from knowlet.core.tools._registry import ToolContext, ToolDef


def _handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    draft_id = (args.get("draft_id") or "").strip()
    if not draft_id:
        return {
            "error": "draft_id is required",
            "suggestion": "call list_drafts to find a valid id",
        }
    d = ctx.drafts.get(draft_id)
    if d is None:
        return {
            "error": f"draft not found: {draft_id}",
            "suggestion": "call list_drafts to find a valid id",
        }
    return {
        "draft": {
            "id": d.id,
            "title": d.title,
            "tags": d.tags,
            "source": d.source,
            "task_id": d.task_id,
            "body": d.body,
            "created_at": d.created_at,
            "updated_at": d.updated_at,
        }
    }


TOOL = ToolDef(
    name="get_draft",
    description=(
        "Fetch the full body of a draft by id. Use this before approving or "
        "rejecting it so you can summarize the content for the user."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "draft_id": {
                "type": "string",
                "description": "the draft ULID (8-char prefix also accepted)",
            },
        },
        "required": ["draft_id"],
        "additionalProperties": False,
    },
    handler=_handler,
)
