"""Review actions for Raw Info items.

Raw Info is source material. Review actions either include it by committing a
linked Draft, or discard it so it leaves the pending digest queue.
"""

from __future__ import annotations

from dataclasses import dataclass

from knowlet.core.digest_items import RawInfo, RawInfoStore
from knowlet.core.drafts import DraftStore


class DigestReviewError(ValueError):
    """A Raw Info review action is invalid for the current item state."""


@dataclass(frozen=True)
class RawInfoDiscardResult:
    item: RawInfo
    deleted_draft_id: str | None = None
    draft_deleted: bool = False


@dataclass(frozen=True)
class RawInfoBulkDiscardResult:
    discarded_count: int
    deleted_draft_ids: list[str]


def discard_raw_info(
    *,
    items: RawInfoStore,
    drafts: DraftStore,
    info_id: str,
) -> RawInfoDiscardResult:
    """Mark a Raw Info item discarded and delete its linked Draft if present."""
    item = items.get(info_id)
    if item is None:
        raise KeyError(f"raw info not found: {info_id}")
    if item.status == "included":
        raise DigestReviewError("raw info has already been included as a note")

    linked_draft_id = item.note_draft_id
    draft_deleted = drafts.delete(linked_draft_id) if linked_draft_id else False
    item.status = "discarded"
    items.save(item)
    return RawInfoDiscardResult(
        item=item,
        deleted_draft_id=linked_draft_id,
        draft_deleted=draft_deleted,
    )


def discard_pending_raw_infos(
    *,
    items: RawInfoStore,
    drafts: DraftStore,
) -> RawInfoBulkDiscardResult:
    """Discard every pending Raw Info item in one review-queue action."""
    deleted_draft_ids: list[str] = []
    discarded_count = 0
    for item in items.list():
        if not item.is_pending:
            continue
        result = discard_raw_info(items=items, drafts=drafts, info_id=item.id)
        discarded_count += 1
        if result.deleted_draft_id and result.draft_deleted:
            deleted_draft_ids.append(result.deleted_draft_id)
    return RawInfoBulkDiscardResult(
        discarded_count=discarded_count,
        deleted_draft_ids=deleted_draft_ids,
    )
