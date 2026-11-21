"""Review actions for Raw Info items.

Raw Info is source material. Review actions either include it by committing a
linked Draft, or discard it so it leaves the pending digest queue.
"""

from __future__ import annotations

from dataclasses import dataclass

from knowlet.core.digest_items import AmbiguousIdError, RawInfo, RawInfoStore
from knowlet.core.drafts import DraftStore


class DigestReviewError(ValueError):
    """A Raw Info review action is invalid for the current item state."""


@dataclass(frozen=True)
class RawInfoDiscardResult:
    """``draft_deleted`` keeps its API name but means the linked draft left
    the review queue by being archived to ``drafts/.archive/``."""

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
    """Mark a Raw Info item discarded and archive its linked Draft if present."""
    try:
        item = items.get(info_id)
    except AmbiguousIdError as exc:
        raise DigestReviewError(str(exc)) from exc
    if item is None:
        raise KeyError(f"raw info not found: {info_id}")
    return _discard_loaded(item, items=items, drafts=drafts)


def _discard_loaded(
    item: RawInfo, *, items: RawInfoStore, drafts: DraftStore
) -> RawInfoDiscardResult:
    if item.status == "included":
        raise DigestReviewError("raw info has already been included as a note")

    linked_draft_id = item.note_draft_id
    draft_deleted = _archive_linked_draft(drafts, linked_draft_id) if linked_draft_id else False
    item.status = "discarded"
    items.save(item)
    return RawInfoDiscardResult(
        item=item,
        deleted_draft_id=linked_draft_id,
        draft_deleted=draft_deleted,
    )


def _archive_linked_draft(drafts: DraftStore, draft_id: str) -> bool:
    # The draft may hold the user's edits; discarding the source item must
    # stay recoverable.
    try:
        drafts.archive_draft(draft_id)
    except LookupError:  # already gone, or an id that is not exact
        return False
    return True


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
        result = _discard_loaded(item, items=items, drafts=drafts)
        discarded_count += 1
        if result.deleted_draft_id and result.draft_deleted:
            deleted_draft_ids.append(result.deleted_draft_id)
    return RawInfoBulkDiscardResult(
        discarded_count=discarded_count,
        deleted_draft_ids=deleted_draft_ids,
    )
