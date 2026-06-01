"""Chat-layer tools that need note-anchored LLM behavior."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from knowlet.chat.note_chat import propose_note_edit
from knowlet.chat.note_check import check_note
from knowlet.core.note import Note
from knowlet.core.tools._registry import ToolContext, ToolDef


def _read_current_note(ctx: ToolContext) -> tuple[Note | None, dict[str, Any] | None]:
    note_id = (ctx.current_note_id or "").strip()
    if not note_id:
        return None, {
            "error": "no current note is active",
            "suggestion": "use this tool only inside a note discussion",
        }
    meta = ctx.index.get_note_meta(note_id)
    if meta is None:
        return None, {
            "error": f"current note not found: {note_id}",
            "suggestion": "reopen the note or run `knowlet reindex`",
        }
    try:
        path = ctx.vault.resolve_note_path_from_index(meta["path"])
        note = ctx.vault.read_note(path)
    except (FileNotFoundError, ValueError) as exc:
        return None, {
            "error": f"note file missing on disk: {exc}",
            "suggestion": "run `knowlet reindex` to sync the index",
        }
    return note, None


def _missing_llm() -> dict[str, str]:
    return {
        "error": "LLM client is unavailable",
        "suggestion": "retry after the LLM runtime is initialized",
    }


def _check_current_note(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    note, error = _read_current_note(ctx)
    if error is not None:
        return error
    if note is None:
        return {"error": "current note unavailable", "suggestion": "reopen the note"}
    if ctx.llm is None:
        return _missing_llm()
    report = check_note(
        llm=ctx.llm,
        note=note,
        standard_answer=str(args.get("standard_answer") or ""),
        instruction=str(args.get("instruction") or ""),
    )
    return {
        "note_id": note.id,
        "title": note.title,
        "summary": report.summary,
        "findings": [asdict(finding) for finding in report.findings],
        "count": len(report.findings),
    }


def _propose_current_note_edit(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    note, error = _read_current_note(ctx)
    if error is not None:
        return error
    if note is None:
        return {"error": "current note unavailable", "suggestion": "reopen the note"}
    if ctx.llm is None:
        return _missing_llm()
    instruction = str(args.get("instruction") or "").strip()
    if not instruction:
        instruction = "根据用户当前请求,对这篇笔记做最小、局部、可审阅的修改。"
    proposal = propose_note_edit(llm=ctx.llm, note=note, instruction=instruction)
    summary = (
        "已生成可审阅的修改提案。"
        if proposal.changed
        else proposal.reason or "未发现需要应用到正文的改动。"
    )
    return {
        "kind": "note_edit_proposal",
        "note_id": note.id,
        "title": note.title,
        "changed": proposal.changed,
        "old_body": proposal.old_body,
        "new_body": proposal.new_body,
        "reason": proposal.reason,
        "summary": summary,
    }


_EXPLICIT_APPLY_MARKERS = (
    "应用",
    "接受",
    "确认",
    "同意",
    "落盘",
    "写入",
    "保存",
    "应用当前",
    "接受当前",
    "apply",
    "accept",
    "confirm",
    "commit",
    "save",
)


def _reject_apply(error: str, suggestion: str) -> dict[str, Any]:
    return {
        "kind": "note_edit_apply_rejected",
        "changed": False,
        "error": error,
        "suggestion": suggestion,
    }


def _proposed_bodies_match(current_body: str, old_body: str) -> bool:
    return current_body.strip() == old_body.strip()


def _apply_current_note_edit(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Apply the pending human-reviewed diff carried by the web session.

    The guard is intentionally duplicated here even though the prompt says
    "only call after explicit user request": tool-call safety lives in code,
    not only in model instructions.
    """
    explicit_request = str(args.get("explicit_user_request") or "").strip()
    lowered_request = explicit_request.lower()
    if not explicit_request or not any(m in lowered_request for m in _EXPLICIT_APPLY_MARKERS):
        return _reject_apply(
            "explicit apply request required",
            "Only call this tool after the user clearly says to apply, accept, confirm, save, or commit the current diff.",
        )
    pending = ctx.pending_note_edit or {}
    old_body = pending.get("old_body") if isinstance(pending, dict) else None
    new_body = pending.get("new_body") if isinstance(pending, dict) else None
    if not isinstance(old_body, str) or not isinstance(new_body, str):
        return _reject_apply(
            "no pending note edit",
            "Ask the user to generate a diff proposal first, then apply it after they explicitly confirm.",
        )
    note, error = _read_current_note(ctx)
    if error is not None:
        return {
            "kind": "note_edit_apply_rejected",
            "changed": False,
            **error,
        }
    if note is None:
        return _reject_apply("current note unavailable", "reopen the note and retry")
    if not _proposed_bodies_match(note.body, old_body):
        return _reject_apply(
            "pending edit is stale",
            "The note body changed after this diff was generated. Generate a fresh diff before applying.",
        )
    if note.body.strip() == new_body.strip():
        return {
            "kind": "note_edit_applied",
            "note_id": note.id,
            "title": note.title,
            "changed": False,
            "summary": "当前修改已经应用。无需再次写入。",
        }

    note.body = new_body
    ctx.vault.write_note(note)
    ctx.index.upsert_note(
        note,
        chunk_size=ctx.config.retrieval.chunk_size,
        chunk_overlap=ctx.config.retrieval.chunk_overlap,
    )
    if ctx.mark_note_dirty is not None:
        ctx.mark_note_dirty(note.id)
    return {
        "kind": "note_edit_applied",
        "note_id": note.id,
        "title": note.title,
        "changed": True,
        "summary": "已应用当前修改。",
    }


CHECK_CURRENT_NOTE_TOOL = ToolDef(
    name="check_current_note",
    description=(
        "Check the Note currently open in the note discussion for factual "
        "mistakes, reasoning gaps, or important omissions. Use this when the "
        "user asks to inspect, calibrate, verify, fact-check, or find problems "
        "in 'this note'. Read-only: it never edits the note."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "standard_answer": {
                "type": "string",
                "description": (
                    "Optional reference answer or rubric supplied by the user. "
                    "Leave empty when the user only asks for self-consistency "
                    "or obvious factual checks."
                ),
            },
            "instruction": {
                "type": "string",
                "description": (
                    "Optional extra checking instruction, such as the area to "
                    "focus on or the user's concern."
                ),
            },
        },
        "additionalProperties": False,
    },
    handler=_check_current_note,
)


APPLY_CURRENT_NOTE_EDIT_TOOL = ToolDef(
    name="apply_current_note_edit",
    description=(
        "Apply the current pending diff for the Note currently open in the "
        "note discussion. ONLY call this when the user explicitly asks to "
        "apply, accept, confirm, save, or commit the current pending "
        "change/diff. Do not call it for checking, suggesting, editing, "
        "rewriting, previewing, or ambiguous requests. This writes to the "
        "vault, updates the index, and queues sync when sync is configured."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "explicit_user_request": {
                "type": "string",
                "description": (
                    "The exact user message that explicitly asked to apply, "
                    "accept, confirm, save, or commit the current diff."
                ),
            },
        },
        "required": ["explicit_user_request"],
        "additionalProperties": False,
    },
    handler=_apply_current_note_edit,
)


PROPOSE_CURRENT_NOTE_EDIT_TOOL = ToolDef(
    name="propose_current_note_edit",
    description=(
        "Generate a minimal, localized edit proposal for the Note currently "
        "open in the note discussion. Use this when the user asks to edit, "
        "rewrite, fix, refine, clarify, produce a diff/reviewable proposal, "
        "or apply corrections to 'this note'. If the user asks for a diff "
        "or says the change must be reviewed before applying, call this tool "
        "instead of pasting a rewritten full note in chat. "
        "Proposal-only: it returns old_body and new_body for a human-reviewed "
        "diff and never writes the note."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "instruction": {
                "type": "string",
                "description": (
                    "The user's edit goal. Be specific about what should change "
                    "and keep the proposal minimal and local."
                ),
            },
        },
        "required": ["instruction"],
        "additionalProperties": False,
    },
    handler=_propose_current_note_edit,
)
