"""Review-flow operations for Draft diffing and final Note commit."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from knowlet.config import KnowletConfig
from knowlet.core.digest_items import RawInfo, RawInfoStore
from knowlet.core.drafts import Draft, DraftStore
from knowlet.core.index import Index
from knowlet.core.vault import Vault


class DraftFlowError(ValueError):
    """Raised when a draft review operation cannot be safely applied."""


@dataclass(frozen=True)
class DraftCommitResult:
    draft_id: str
    note_id: str
    title: str
    path: Path
    raw_info: RawInfo | None = None


def set_draft_pending_diff(
    drafts: DraftStore,
    draft: Draft,
    *,
    new_body: str,
) -> Draft:
    draft.pending_diff_base = draft.body
    draft.pending_diff_body = new_body
    drafts.save(draft)
    return draft


def accept_draft_diff(
    drafts: DraftStore,
    draft_id: str,
    *,
    final_body: str | None = None,
) -> Draft:
    draft = _get_draft_or_raise(drafts, draft_id)
    if draft.pending_diff_body is None and final_body is None:
        raise DraftFlowError("no pending draft diff to accept")
    if (
        draft.pending_diff_base is not None
        and draft.body != draft.pending_diff_base
        and final_body is None
    ):
        raise DraftFlowError("draft body changed after the diff was proposed")
    draft.body = final_body if final_body is not None else (draft.pending_diff_body or draft.body)
    draft.pending_diff_base = None
    draft.pending_diff_body = None
    drafts.save(draft)
    return draft


def reject_draft_diff(drafts: DraftStore, draft_id: str) -> Draft:
    draft = _get_draft_or_raise(drafts, draft_id)
    draft.pending_diff_base = None
    draft.pending_diff_body = None
    drafts.save(draft)
    return draft


def commit_note_draft(
    *,
    vault: Vault,
    index: Index,
    config: KnowletConfig,
    drafts: DraftStore,
    draft_id: str,
    raw_infos: RawInfoStore | None = None,
) -> DraftCommitResult:
    draft = _get_draft_or_raise(drafts, draft_id)
    if not draft.title.strip():
        raise DraftFlowError("draft title is required before commit")
    if not draft.body.strip():
        raise DraftFlowError("draft body is required before commit")
    if draft.pending_diff_body is not None:
        raise DraftFlowError("accept or reject the pending diff before commit")

    note = draft.to_note()
    path = vault.write_note(note, folder=draft.folder)
    note.path = path
    index.upsert_note(
        note,
        chunk_size=config.retrieval.chunk_size,
        chunk_overlap=config.retrieval.chunk_overlap,
    )
    drafts.delete(draft.id)

    raw_info = None
    if raw_infos is not None:
        raw_info = _find_raw_info_for_draft(raw_infos, draft.id)
        if raw_info is not None:
            raw_info.status = "included"
            raw_info.note_id = note.id
            raw_info.note_draft_id = draft.id
            raw_infos.save(raw_info)

    return DraftCommitResult(
        draft_id=draft.id,
        note_id=note.id,
        title=note.title,
        path=path,
        raw_info=raw_info,
    )


def _get_draft_or_raise(drafts: DraftStore, draft_id: str) -> Draft:
    draft = drafts.get(draft_id)
    if draft is None:
        raise KeyError(f"draft not found: {draft_id}")
    return draft


def _find_raw_info_for_draft(store: RawInfoStore, draft_id: str) -> RawInfo | None:
    for item in store.list():
        if item.note_draft_id == draft_id:
            return item
    return None
