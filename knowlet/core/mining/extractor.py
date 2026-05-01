"""LLM-based extraction: turn a SourceItem + task prompt into a Draft.

Same Claude-Code-via-proxy lesson as `chat/sediment.py`: role:'system'
instructions are unreliable in some backends, so the task prompt is folded
into the user message.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from knowlet.core.drafts import Draft
from knowlet.core.llm import LLMClient
from knowlet.core.mining.sources import SourceItem
from knowlet.core.mining.task import MiningTask
from knowlet.core.note import new_id


@dataclass
class ExtractionResult:
    item: SourceItem
    draft: Draft | None
    error: str | None = None


_EXTRACT_INSTRUCTIONS_TPL = """\
You are extracting one Note draft from a single source item for the user's knowledge vault.

Output **strict JSON** with these fields:
- title: short and descriptive, {language_hint}
- tags: 1-5 lowercase, hyphen-separated tags
- body: Markdown body. Structure:
    - one-paragraph plain-language summary at the top
    - "## Key points" with 3-6 bullets — facts, claims, definitions, numbers
    - "## Why it matters" — one or two sentences, only if a clear answer
    - "## Source" — exactly one bullet: `[<title>](<url>)`

{output_language_directive}Be honest: if the source content is too thin to extract, output:
{{"title": "", "tags": [], "body": ""}}
and we will skip it.

Do not include any text outside the JSON object.
"""


_LANG_NAMES = {
    "en": "English",
    "zh": "Chinese (中文)",
}


def _instructions_for(output_language: str | None) -> str:
    if not output_language:
        return _EXTRACT_INSTRUCTIONS_TPL.format(
            language_hint="in the source's main language",
            output_language_directive="",
        )
    name = _LANG_NAMES.get(output_language, output_language)
    return _EXTRACT_INSTRUCTIONS_TPL.format(
        language_hint=f"in {name}",
        output_language_directive=(
            f"**Translate the entire output (title, tags, body) into {name}**, "
            f"regardless of the source's language. Keep proper nouns, code, "
            f"and inline URLs in their original form.\n\n"
        ),
    )


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_BLOCK.search(text)
        if m is None:
            raise
        return json.loads(m.group(0))


def extract_one(
    task: MiningTask,
    item: SourceItem,
    llm: LLMClient,
    max_input_chars: int = 8000,
    output_language: str | None = None,
) -> ExtractionResult:
    """Run the LLM on a single item; return a Draft (or an error).

    `output_language` (when provided) instructs the LLM to translate the
    output into that language regardless of source language. Caller usually
    passes `task.output_language or cfg.general.language`.
    """
    if not item.content.strip() and not item.title.strip():
        return ExtractionResult(item=item, draft=None, error="empty source content")

    body_excerpt = item.content[:max_input_chars]
    instructions = _instructions_for(output_language or task.output_language)
    user_msg = (
        f"{instructions}\n\n"
        f"Task-specific guidance:\n{task.prompt.strip()}\n\n"
        f"---\n"
        f"Source title: {item.title}\n"
        f"Source URL: {item.url}\n"
        f"Source content:\n{body_excerpt}\n"
        f"---\n\n"
        f"Now output the JSON object. Output **only** the JSON, nothing else."
    )
    try:
        resp = llm.chat(
            messages=[{"role": "user", "content": user_msg}],
            tools=None,
            temperature=0.2,
        )
    except Exception as exc:  # noqa: BLE001 — boundary
        return ExtractionResult(item=item, draft=None, error=f"LLM error: {exc}")

    raw = (resp.content or "").strip()
    if not raw:
        return ExtractionResult(item=item, draft=None, error="LLM returned empty content")
    try:
        payload = _parse_json(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        return ExtractionResult(
            item=item,
            draft=None,
            error=f"could not parse JSON ({exc}); raw={raw[:200]!r}",
        )

    title = str(payload.get("title") or "").strip()
    body = str(payload.get("body") or "").strip()
    if not title or not body:
        return ExtractionResult(item=item, draft=None, error="LLM declined (empty title/body)")

    draft = Draft(
        id=new_id(),
        title=title,
        body=body,
        tags=[str(t).strip() for t in (payload.get("tags") or []) if str(t).strip()],
        source=item.url or item.source_url,
        task_id=task.id,
    )
    return ExtractionResult(item=item, draft=draft, error=None)
