"""`:save` flow — turn a chat conversation into a reviewed Note.

LLM drafts → user reviews (y/n/e) → on accept, write to vault and index.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from knowlet.chat.prompts import SEDIMENT_PROMPT
from knowlet.config import KnowletConfig
from knowlet.core.index import Index
from knowlet.core.llm import LLMClient
from knowlet.core.note import Note, new_id
from knowlet.core.vault import Vault


@dataclass
class Draft:
    title: str
    tags: list[str]
    body: str

    def to_note(self) -> Note:
        return Note(id=new_id(), title=self.title, body=self.body, tags=self.tags)


def draft_from_conversation(
    llm: LLMClient,
    history: list[dict[str, Any]],
) -> Draft:
    """Ask the LLM to summarize the chat into a Note draft. Returns a Draft.

    Some OpenAI-compat proxies (notably ones routing through Claude Code) do
    not respect role:'system' task assignment — they stay in the proxy's
    default persona. So the sediment instructions live in a single user
    message instead.
    """
    convo_text = _render_history(history)
    user_msg = (
        f"{SEDIMENT_PROMPT}\n\n"
        f"---\nConversation to sediment:\n\n{convo_text}\n---\n\n"
        "Now output the JSON object. Output **only** the JSON, nothing else."
    )
    messages = [{"role": "user", "content": user_msg}]
    resp = llm.chat(messages, tools=None, temperature=0.2)
    raw = (resp.content or "").strip()
    if not raw:
        raise RuntimeError("LLM returned empty content for sediment")
    try:
        payload = _parse_json_object(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"could not parse JSON from sediment response. raw={raw[:300]!r}"
        ) from exc
    return Draft(
        title=str(payload.get("title") or "Untitled").strip(),
        tags=[str(t).strip() for t in (payload.get("tags") or []) if str(t).strip()],
        body=str(payload.get("body") or "").strip(),
    )


def open_in_editor(draft: Draft) -> Draft:
    """Open the draft in $EDITOR for manual edits. Returns the edited draft."""
    note = draft.to_note()  # gives us a temporary id; thrown away after edit
    initial = note.to_markdown()
    editor = os.environ.get("EDITOR") or "vi"
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", encoding="utf-8", delete=False
    ) as f:
        f.write(initial)
        tmp_path = Path(f.name)
    try:
        subprocess.run([editor, str(tmp_path)], check=True)
        edited = Note.from_file(tmp_path)
        return Draft(title=edited.title, tags=edited.tags, body=edited.body)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


def commit_draft(
    draft: Draft,
    vault: Vault,
    index: Index,
    config: KnowletConfig,
) -> Note:
    """Write the draft to the vault and update the index."""
    note = draft.to_note()
    path = vault.write_note(note)
    note.path = path
    index.upsert_note(
        note,
        chunk_size=config.retrieval.chunk_size,
        chunk_overlap=config.retrieval.chunk_overlap,
    )
    return note


# --------------------------------------------------------------------- helpers


def _render_history(history: list[dict[str, Any]]) -> str:
    """Render conversation skipping system + tool noise; keeps user/assistant turns."""
    lines: list[str] = []
    for m in history:
        role = m.get("role")
        if role == "user":
            content = m.get("content") or ""
            lines.append(f"USER: {content}")
        elif role == "assistant":
            content = m.get("content") or ""
            if content:
                lines.append(f"ASSISTANT: {content}")
    return "\n\n".join(lines).strip()


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        # Strip ```json ... ``` fencing if the model added it.
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_BLOCK.search(text)
        if m is None:
            raise
        return json.loads(m.group(0))
