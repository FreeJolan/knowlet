"""discard_raw_info — remove the current Raw Info item from review."""

from __future__ import annotations

from typing import Any

from knowlet.core.digest_items import RawInfoStore
from knowlet.core.digest_review import DigestReviewError, discard_raw_info
from knowlet.core.tools._registry import ToolContext, ToolDef


def _handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    info_id = (args.get("info_id") or ctx.current_raw_info_id or "").strip()
    if not info_id:
        return {
            "error": "info_id is required",
            "suggestion": "use the current Raw Info item or pass an explicit info_id",
        }
    try:
        result = discard_raw_info(
            items=RawInfoStore(ctx.vault.digest_items_dir),
            drafts=ctx.drafts,
            info_id=info_id,
        )
    except KeyError:
        return {
            "error": f"raw info not found: {info_id}",
            "suggestion": "choose an item that is still in the digest review queue",
        }
    except DigestReviewError as exc:
        return {
            "error": str(exc),
            "suggestion": "do not discard an item that has already been included",
        }
    return {
        "raw_info_id": result.item.id,
        "status": result.item.status,
        "deleted_draft_id": result.deleted_draft_id,
        "draft_deleted": result.draft_deleted,
    }


TOOL = ToolDef(
    name="discard_raw_info",
    description=(
        "Discard a Raw Info item from the digest review queue. If it already "
        "has a linked note Draft, delete that Draft too. Confirm with the user "
        "before calling; this intentionally chooses not to keep the item."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "info_id": {
                "type": "string",
                "description": "Optional Raw Info id; defaults to the current review item.",
            },
        },
        "additionalProperties": False,
    },
    handler=_handler,
)
