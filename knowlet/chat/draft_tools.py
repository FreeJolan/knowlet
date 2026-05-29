"""Chat-layer tools for editing and committing the current Draft."""

from __future__ import annotations

from typing import Any

from knowlet.chat.note_chat import propose_note_edit
from knowlet.core.digest_items import RawInfoStore
from knowlet.core.draft_flow import (
    DraftFlowError,
    accept_draft_diff,
    commit_note_draft,
    reject_draft_diff,
    set_draft_pending_diff,
)
from knowlet.core.tools._registry import ToolContext, ToolDef


def _draft_id(args: dict[str, Any], ctx: ToolContext) -> str:
    return str(args.get("draft_id") or ctx.current_draft_id or "").strip()


def _missing_draft(draft_id: str) -> dict[str, str]:
    return {
        "error": f"draft not found: {draft_id}",
        "suggestion": "settle the Raw Info into a draft first, or pass a valid draft_id",
    }


def _propose_current_draft_edit(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    draft_id = _draft_id(args, ctx)
    if not draft_id:
        return {
            "error": "draft_id is required",
            "suggestion": "use this tool inside a Raw Info review after a draft exists",
        }
    if ctx.llm is None:
        return {
            "error": "LLM client is unavailable",
            "suggestion": "retry after the LLM runtime is initialized",
        }
    draft = ctx.drafts.get(draft_id)
    if draft is None:
        return _missing_draft(draft_id)
    instruction = str(args.get("instruction") or "").strip()
    if not instruction:
        instruction = "根据用户当前请求,对这份笔记草稿做最小、局部、可审阅的修改。"
    proposal = propose_note_edit(llm=ctx.llm, note=draft.to_note(), instruction=instruction)
    if proposal.changed:
        draft = set_draft_pending_diff(
            ctx.drafts,
            draft,
            new_body=proposal.new_body,
        )
    summary = (
        "已生成可审阅的草稿 diff。"
        if proposal.changed
        else proposal.reason or "未发现需要应用到草稿正文的改动。"
    )
    return {
        "kind": "draft_edit_proposal",
        "draft_id": draft.id,
        "title": draft.title,
        "changed": proposal.changed,
        "old_body": proposal.old_body,
        "new_body": proposal.new_body,
        "reason": proposal.reason,
        "summary": summary,
    }


def _accept_all_draft_diff(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    draft_id = _draft_id(args, ctx)
    if not draft_id:
        return {
            "error": "draft_id is required",
            "suggestion": "use this tool inside a Raw Info review after a draft diff exists",
        }
    try:
        draft = accept_draft_diff(ctx.drafts, draft_id)
    except KeyError:
        return _missing_draft(draft_id)
    except DraftFlowError as exc:
        return {"error": str(exc), "suggestion": "propose a draft diff first"}
    return {
        "kind": "draft_diff_accepted",
        "draft_id": draft.id,
        "title": draft.title,
        "accepted": True,
        "body": draft.body,
    }


def _reject_all_draft_diff(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    draft_id = _draft_id(args, ctx)
    if not draft_id:
        return {
            "error": "draft_id is required",
            "suggestion": "use this tool inside a Raw Info review after a draft diff exists",
        }
    try:
        draft = reject_draft_diff(ctx.drafts, draft_id)
    except KeyError:
        return _missing_draft(draft_id)
    return {
        "kind": "draft_diff_rejected",
        "draft_id": draft.id,
        "title": draft.title,
        "rejected": True,
        "body": draft.body,
    }


def _commit_note_draft(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    draft_id = _draft_id(args, ctx)
    if not draft_id:
        return {
            "error": "draft_id is required",
            "suggestion": "use this tool inside a Raw Info review after a draft exists",
        }
    try:
        result = commit_note_draft(
            vault=ctx.vault,
            index=ctx.index,
            config=ctx.config,
            drafts=ctx.drafts,
            draft_id=draft_id,
            raw_infos=RawInfoStore(ctx.vault.digest_items_dir),
            folder=str(args.get("folder") or "").strip() or None,
        )
    except KeyError:
        return _missing_draft(draft_id)
    except DraftFlowError as exc:
        return {"error": str(exc), "suggestion": "fix the draft before committing"}
    if ctx.mark_note_dirty is not None:
        ctx.mark_note_dirty(result.note_id)
    return {
        "kind": "note_draft_committed",
        "draft_id": result.draft_id,
        "note_id": result.note_id,
        "title": result.title,
        "path": str(result.path),
        "raw_info_id": result.raw_info.id if result.raw_info is not None else None,
    }


PROPOSE_CURRENT_DRAFT_EDIT_TOOL = ToolDef(
    name="propose_current_draft_edit",
    description=(
        "Generate a minimal, localized edit proposal for the Draft currently "
        "being reviewed. Use this when the user asks to revise, fix, clarify, "
        "polish, or produce a diff for the draft. Proposal-only: it stores a "
        "pending diff and returns old_body/new_body; the draft body is not "
        "changed until accept_all_draft_diff is called."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "draft_id": {
                "type": "string",
                "description": "Optional Draft id. Omit inside the current review item.",
            },
            "instruction": {
                "type": "string",
                "description": "The user's requested draft revision.",
            },
        },
        "additionalProperties": False,
    },
    handler=_propose_current_draft_edit,
)


ACCEPT_ALL_DRAFT_DIFF_TOOL = ToolDef(
    name="accept_all_draft_diff",
    description=(
        "Accept the current pending diff for the Draft being reviewed. Use only "
        "after the user explicitly says to accept/apply all changes. This "
        "mutates the Draft body but does not commit a formal Note."
    ),
    input_schema={
        "type": "object",
        "properties": {"draft_id": {"type": "string"}},
        "additionalProperties": False,
    },
    handler=_accept_all_draft_diff,
)


REJECT_ALL_DRAFT_DIFF_TOOL = ToolDef(
    name="reject_all_draft_diff",
    description=(
        "Reject/clear the current pending diff for the Draft being reviewed. "
        "Use when the user says to reject, discard, revert, or withdraw all "
        "draft changes."
    ),
    input_schema={
        "type": "object",
        "properties": {"draft_id": {"type": "string"}},
        "additionalProperties": False,
    },
    handler=_reject_all_draft_diff,
)


COMMIT_NOTE_DRAFT_TOOL = ToolDef(
    name="commit_note_draft",
    description=(
        "Commit the reviewed Draft as a formal Note in the vault, update the "
        "index, remove the draft, and mark the source Raw Info included. Use "
        "only when the user explicitly asks to commit/save it into the "
        "knowledge base."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "draft_id": {"type": "string"},
            "folder": {
                "type": "string",
                "description": "Optional target folder under notes/. Omit to use the Draft's recommended folder.",
            },
        },
        "additionalProperties": False,
    },
    handler=_commit_note_draft,
)
