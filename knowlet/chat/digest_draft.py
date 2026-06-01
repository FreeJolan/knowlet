"""Settle read-only Raw Info into a reviewable note Draft."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from pydantic import BaseModel, Field, ValidationError, field_validator

from knowlet.core.digest_items import RawInfo, RawInfoStore
from knowlet.core.drafts import Draft, DraftStore
from knowlet.core.index import Index
from knowlet.core.note import NOTE_KINDS, NoteKind
from knowlet.core.vault import Vault


class RawInfoDraftError(RuntimeError):
    """Raised when the LLM cannot produce a valid review draft."""


class DraftLLMOutput(BaseModel):
    title: str = Field(min_length=1)
    body: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    kind: Literal["knowledge", "reference"]
    folder: str = ""
    rationale: str = ""

    @field_validator("title", "body", "folder", "rationale", mode="before")
    @classmethod
    def _strip_string(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("tags", mode="before")
    @classmethod
    def _clean_tags(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        seen: set[str] = set()
        out: list[str] = []
        for raw in value:
            tag = str(raw).strip().lstrip("#")
            if tag and tag not in seen:
                seen.add(tag)
                out.append(tag)
        return out


@dataclass(frozen=True)
class LibraryContext:
    tags: list[tuple[str, int]]
    folders: list[str]
    recent_notes: list[dict[str, Any]]


@dataclass(frozen=True)
class RawInfoDraftResult:
    item: RawInfo
    draft: Draft
    rationale: str
    existed: bool = False


DRAFT_SYSTEM_PROMPT = """\
You are Knowlet's Raw Info settlement assistant.

Your job is to turn one read-only Raw Info item into an editable note draft.
The draft is only a proposal; the user will review it before it enters the
knowledge base.

Inputs you may receive:
- One Raw Info item with original URL, summary, key points, tags, and excerpt.
- The user's discussion history about this item.
- Hidden library context: existing tags, folder tree, and recent notes.

Classification rule:
- Use kind="reference" (资料) when the user has not deeply discussed the item,
  or mostly wants to keep it for lookup/reference.
- Use kind="knowledge" (知识) when the discussion adds user judgement,
  synthesis, follow-up thinking, design decisions, or reusable conclusions.

Output only strict JSON with exactly this shape:
{
  "title": "concise note title",
  "body": "complete Markdown draft body",
  "tags": ["existing-or-new-tag"],
  "kind": "knowledge" | "reference",
  "folder": "existing/folder/or-empty-root",
  "rationale": "one short sentence explaining the choice"
}

Rules:
- Preserve provenance: include the original URL in the body when useful.
- Do not invent facts that are not in the Raw Info or discussion.
- Prefer existing tags and folders when they fit.
- Pick folder="" for vault root if no existing folder fits.
- Markdown body should be useful as a note draft, not a chat answer.
"""


def build_library_context(vault: Vault, index: Index) -> LibraryContext:
    folders = [""]
    for folder_path in vault.iter_folders():
        try:
            rel_path = folder_path.relative_to(vault.notes_dir)
        except ValueError:
            continue
        rel = "/".join(rel_path.parts)
        if rel and rel not in folders:
            folders.append(rel)
    tags = index.aggregate_tags()[:30]
    recent_notes: list[dict[str, Any]] = []
    for row in index.list_notes(limit=12):
        path_raw = str(row.get("path") or "")
        recent_folder = ""
        if path_raw:
            try:
                recent_folder = vault.folder_of(vault.resolve_note_path_from_index(path_raw))
            except ValueError:
                recent_folder = ""
        recent_notes.append(
            {
                "title": row.get("title") or "",
                "folder": recent_folder,
                "tags": row.get("tags") or [],
            }
        )
    return LibraryContext(tags=tags, folders=folders, recent_notes=recent_notes)


def create_note_draft_from_info(
    *,
    llm: Any,
    vault: Vault,
    index: Index,
    drafts: DraftStore,
    item_store: RawInfoStore,
    info_id: str,
    history: Sequence[Mapping[str, str]] | None = None,
    discussion_summary: str = "",
) -> RawInfoDraftResult:
    item = item_store.get(info_id)
    if item is None:
        raise KeyError(f"raw info not found: {info_id}")
    if item.note_draft_id:
        existing = drafts.get(item.note_draft_id)
        if existing is not None:
            return RawInfoDraftResult(
                item=item,
                draft=existing,
                rationale="Existing draft reused.",
                existed=True,
            )

    context = build_library_context(vault, index)
    messages = [
        {"role": "system", "content": "You turn Raw Info into reviewable Knowlet note drafts."},
        {
            "role": "user",
            "content": _build_prompt(
                item=item,
                context=context,
                history=history or [],
                discussion_summary=discussion_summary,
            ),
        },
    ]
    resp = llm.chat(messages, temperature=None)
    output = _parse_llm_output(getattr(resp, "content", "") or "")
    folder = _normalize_folder(output.folder, context.folders)
    draft = Draft(
        title=output.title,
        body=output.body,
        tags=output.tags or list(item.suggested_tags),
        source=item.url,
        kind=output.kind,
        folder=folder,
    )
    drafts.save(draft)
    item.status = "drafted"
    item.note_draft_id = draft.id
    item_store.save(item)
    return RawInfoDraftResult(item=item, draft=draft, rationale=output.rationale)


def _parse_llm_output(content: str) -> DraftLLMOutput:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        data = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise RawInfoDraftError("AI did not return valid JSON") from exc
    try:
        return DraftLLMOutput.model_validate(data)
    except ValidationError as exc:
        raise RawInfoDraftError(f"AI draft schema validation failed: {exc}") from exc


def _build_prompt(
    *,
    item: RawInfo,
    context: LibraryContext,
    history: Sequence[Mapping[str, str]],
    discussion_summary: str,
) -> str:
    key_points = "\n".join(f"- {point}" for point in item.key_points) or "- (none)"
    suggested_tags = ", ".join(item.suggested_tags) or "(none)"
    tags = "\n".join(f"- {name} ({count})" for name, count in context.tags) or "- (none)"
    folders = "\n".join(f"- {folder or '(root)'}" for folder in context.folders) or "- (root)"
    notes = (
        "\n".join(
            "- {title} [{folder}] tags: {tags}".format(
                title=note["title"],
                folder=note["folder"] or "(root)",
                tags=", ".join(note["tags"]) or "(none)",
            )
            for note in context.recent_notes
        )
        or "- (none)"
    )
    discussion = _render_history(history)
    if discussion_summary.strip():
        discussion = (discussion + "\n\n" if discussion else "") + (
            f"AI-provided discussion summary:\n{discussion_summary.strip()}"
        )
    return f"""\
{DRAFT_SYSTEM_PROMPT}

Raw Info:
- ID: {item.id}
- Title: {item.title}
- Source: {item.source_name} ({item.source_kind})
- Original URL: {item.url}
- Published: {item.published_at or "unknown"}
- Summary: {item.summary}
- Key points:
{key_points}
- Why it matters: {item.why_it_matters or "(none)"}
- Suggested tags: {suggested_tags}
- Excerpt:
{item.content_excerpt or "(none)"}

Discussion history:
{discussion or "(no discussion yet)"}

Hidden library context:

Existing tags:
{tags}

Folder tree:
{folders}

Recent notes:
{notes}
"""


def _render_history(history: Sequence[Mapping[str, str]]) -> str:
    out: list[str] = []
    for msg in history:
        role = str(msg.get("role") or "").strip()
        if role not in ("user", "assistant"):
            continue
        content = str(msg.get("content") or "").strip()
        if content:
            out.append(f"{role}: {content}")
    return "\n\n".join(out)


def _normalize_folder(folder: str, allowed_folders: Sequence[str]) -> str:
    cleaned = folder.strip().strip("/")
    if not cleaned:
        return ""
    if "\\" in cleaned or ".." in cleaned.split("/") or cleaned.startswith("."):
        return ""
    allowed = set(allowed_folders)
    if allowed and cleaned not in allowed:
        return ""
    return cleaned


def coerce_note_kind(value: str) -> NoteKind:
    if value in NOTE_KINDS:
        return cast(NoteKind, value)
    return "reference"
