"""approve_draft — promote a draft to a Note and remove it from the queue."""

from __future__ import annotations

from typing import Any

from knowlet.core.digest_items import RawInfoStore
from knowlet.core.draft_flow import DraftFlowError, commit_note_draft
from knowlet.core.tools._registry import ToolContext, ToolDef


def _handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    draft_id = (args.get("draft_id") or "").strip()
    if not draft_id:
        return {
            "error": "draft_id is required",
            "suggestion": "call list_drafts to find a valid id",
        }
    try:
        result = commit_note_draft(
            vault=ctx.vault,
            index=ctx.index,
            config=ctx.config,
            drafts=ctx.drafts,
            draft_id=draft_id,
            raw_infos=RawInfoStore(ctx.vault.digest_items_dir),
        )
    except KeyError:
        return {
            "error": f"draft not found: {draft_id}",
            "suggestion": "call list_drafts to find a valid id",
        }
    except DraftFlowError as exc:
        return {
            "error": str(exc),
            "suggestion": "fix or review the draft before approving",
        }

    return {
        "note_id": result.note_id,
        "path": str(result.path),
        "title": result.title,
    }


TOOL = ToolDef(
    name="approve_draft",
    description=(
        "Approve a pending draft: write it as a Note under <vault>/notes/, "
        "index it, and remove it from the drafts queue. Reversible only by "
        "deleting the note and re-running the mining task. Confirm with the "
        "user before calling, since the title/body are AI-generated."
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
