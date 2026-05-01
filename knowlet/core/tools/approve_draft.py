"""approve_draft — promote a draft to a Note and remove it from the queue."""

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
    draft = ctx.drafts.get(draft_id)
    if draft is None:
        return {
            "error": f"draft not found: {draft_id}",
            "suggestion": "call list_drafts to find a valid id",
        }

    note = draft.to_note()
    path = ctx.vault.write_note(note)
    note.path = path
    ctx.index.upsert_note(
        note,
        chunk_size=ctx.config.retrieval.chunk_size,
        chunk_overlap=ctx.config.retrieval.chunk_overlap,
    )
    ctx.drafts.delete(draft.id)

    return {
        "note_id": note.id,
        "path": str(path),
        "title": note.title,
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
