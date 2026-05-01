"""list_drafts — surface pending-review drafts produced by mining tasks."""

from __future__ import annotations

from typing import Any

from knowlet.core.tools._registry import ToolContext, ToolDef


def _handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    drafts = ctx.drafts.list()
    return {
        "results": [
            {
                "draft_id": d.id,
                "title": d.title,
                "tags": d.tags,
                "source": d.source,
                "task_id": d.task_id,
                "created_at": d.created_at,
            }
            for d in drafts
        ],
        "count": len(drafts),
    }


TOOL = ToolDef(
    name="list_drafts",
    description=(
        "List Notes pending user review (produced by mining tasks). Use "
        "when the user asks 'what's in my inbox' / 'anything to review'."
    ),
    input_schema={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    handler=_handler,
)
