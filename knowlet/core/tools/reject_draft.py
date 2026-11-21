"""reject_draft — discard a draft without saving as a Note."""

from __future__ import annotations

from typing import Any

from knowlet.core.drafts import AmbiguousDraftIdError
from knowlet.core.tools._registry import ToolContext, ToolDef


def _handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    draft_id = (args.get("draft_id") or "").strip()
    if not draft_id:
        return {
            "error": "draft_id is required",
            "suggestion": "call list_drafts to find a valid id",
        }
    try:
        ctx.drafts.archive_draft(draft_id)
    except AmbiguousDraftIdError as exc:
        return {
            "error": str(exc),
            "suggestion": "pass the full draft id from list_drafts",
        }
    except KeyError:
        return {
            "error": f"draft not found: {draft_id}",
            "suggestion": "the draft may have already been approved or rejected",
        }
    return {"draft_id": draft_id, "archived": True}


TOOL = ToolDef(
    name="reject_draft",
    description=(
        "Reject a pending draft: it leaves the review queue and is moved to "
        "the drafts archive (recoverable by hand, not deleted). Confirm with "
        "the user before calling — the source item stays in the seen-set, so "
        "the same item won't be mined again."
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
