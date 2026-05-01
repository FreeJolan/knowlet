"""reject_draft — discard a draft without saving as a Note."""

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
    deleted = ctx.drafts.delete(draft_id)
    if not deleted:
        return {
            "error": f"draft not found: {draft_id}",
            "suggestion": "the draft may have already been approved or rejected",
        }
    return {"draft_id": draft_id, "deleted": True}


TOOL = ToolDef(
    name="reject_draft",
    description=(
        "Reject a pending draft (delete the file). Confirm with the user "
        "before calling — rejection is irreversible (the source item will "
        "stay in the seen-set, so the same item won't re-extract)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "draft_id": {"type": "string"},
        },
        "required": ["draft_id"],
        "additionalProperties": False,
    },
    handler=_handler,
)
