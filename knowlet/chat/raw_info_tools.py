"""Chat-layer tools for Raw Info review mode."""

from __future__ import annotations

from typing import Any

from knowlet.chat.digest_draft import (
    RawInfoDraftError,
    create_note_draft_from_info,
)
from knowlet.core.digest_items import RawInfoStore
from knowlet.core.tools._registry import ToolContext, ToolDef


def _create_note_draft_from_info(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    info_id = str(args.get("info_id") or ctx.current_raw_info_id or "").strip()
    if not info_id:
        return {
            "error": "info_id is required",
            "suggestion": "use this tool inside a Raw Info review or pass a raw info id",
        }
    if ctx.llm is None:
        return {
            "error": "LLM client is unavailable",
            "suggestion": "retry after the LLM runtime is initialized",
        }
    store = RawInfoStore(ctx.vault.digest_items_dir)
    try:
        result = create_note_draft_from_info(
            llm=ctx.llm,
            vault=ctx.vault,
            index=ctx.index,
            drafts=ctx.drafts,
            item_store=store,
            info_id=info_id,
            discussion_summary=str(args.get("discussion_summary") or ""),
        )
    except KeyError:
        return {
            "error": f"raw info not found: {info_id}",
            "suggestion": "pick an id from the current Digest review item",
        }
    except RawInfoDraftError as exc:
        return {
            "error": str(exc),
            "suggestion": "retry with a shorter discussion summary or ask the user to create manually",
        }
    draft = result.draft
    return {
        "kind": "raw_info_note_draft",
        "info_id": result.item.id,
        "draft_id": draft.id,
        "title": draft.title,
        "note_kind": draft.kind,
        "folder": draft.folder or "",
        "tags": list(draft.tags),
        "source": draft.source,
        "existed": result.existed,
        "rationale": result.rationale,
    }


CREATE_NOTE_DRAFT_FROM_INFO_TOOL = ToolDef(
    name="create_note_draft_from_info",
    description=(
        "Create a reviewable note Draft from the Raw Info item currently being "
        "reviewed. Use this when the user says to settle, save as a draft, "
        "turn this information into a note draft, or prepare it for later "
        "commit. Proposal-only: it writes under drafts/ and never commits a "
        "formal Note."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "info_id": {
                "type": "string",
                "description": "Optional Raw Info id. Omit inside the current review item.",
            },
            "discussion_summary": {
                "type": "string",
                "description": (
                    "Short summary of the user's discussion and judgement so far. "
                    "Use this to help classify knowledge vs reference."
                ),
            },
        },
        "additionalProperties": False,
    },
    handler=_create_note_draft_from_info,
)
