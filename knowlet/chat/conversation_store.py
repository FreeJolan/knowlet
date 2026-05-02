"""Persistent multi-session chat conversations (M6.4 Phase 1).

Each conversation is a JSON file under `<vault>/.knowlet/conversations/<id>.json`
with the schema below. The store is the single read/write entry point;
`ChatRuntime` holds an active conversation id and saves after every turn.

File schema:

    {
      "id":        "<ulid>",
      "title":     "free-form, ~5 words; auto-summarized after first turn",
      "model":     "claude-opus-4-7",
      "started_at":"2026-05-02T10:00:00Z",
      "updated_at":"2026-05-02T10:42:00Z",
      "messages":  [{"role": "system"|"user"|"assistant"|"tool", ...}, ...]
    }

Backwards-compatible with the M0 single-log format (no `title` field, no
`updated_at`): missing fields are filled with sensible defaults on load,
and saved back in the new shape on next write.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ulid import ULID


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Conversation:
    id: str = field(default_factory=lambda: str(ULID()))
    title: str = ""
    model: str = ""
    started_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    messages: list[dict[str, Any]] = field(default_factory=list)

    @property
    def filename(self) -> str:
        return f"{self.id}.json"

    @property
    def is_meaningful(self) -> bool:
        """A conversation is worth listing if it has at least one user turn.

        The first message is the system prompt; anything past index 1 means
        the user has actually said something.
        """
        return len(self.messages) > 1

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "model": self.model,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "messages": self.messages,
        }


@dataclass
class ConversationSummary:
    """Light-weight listing entry. UI lists these — full body loads on click."""

    id: str
    title: str
    model: str
    started_at: str
    updated_at: str
    message_count: int


class ConversationStore:
    """File-backed CRUD for `Conversation`s.

    One file per conversation under `<vault>/.knowlet/conversations/`. The
    store reads / writes JSON; everything else is in-memory. Tests target
    this class directly with a tmp_path.
    """

    def __init__(self, root: Path):
        self.root = root

    # ---------------------------------------------------------------- read

    def list(self, limit: int = 50, only_meaningful: bool = True) -> list[ConversationSummary]:
        """Return summaries sorted by `updated_at` descending (most recent first).

        `only_meaningful=True` filters out conversations that never got past
        the system prompt — e.g. someone opened the chat dock and refreshed
        without saying anything. M6.4 sidebar uses this default.
        """
        if not self.root.exists():
            return []
        out: list[ConversationSummary] = []
        for p in self.root.glob("*.json"):
            if not p.is_file():
                continue
            try:
                conv = self._load_path(p)
            except (OSError, json.JSONDecodeError):
                continue
            if only_meaningful and not conv.is_meaningful:
                continue
            out.append(
                ConversationSummary(
                    id=conv.id,
                    title=conv.title,
                    model=conv.model,
                    started_at=conv.started_at,
                    updated_at=conv.updated_at,
                    message_count=len(conv.messages),
                )
            )
        out.sort(key=lambda s: s.updated_at, reverse=True)
        return out[:limit]

    def get(self, conv_id: str) -> Conversation | None:
        p = self.root / f"{conv_id}.json"
        if not p.exists():
            return None
        try:
            return self._load_path(p)
        except (OSError, json.JSONDecodeError):
            return None

    def most_recent(self, only_meaningful: bool = True) -> Conversation | None:
        """Convenience for "resume last session on bootstrap"."""
        summaries = self.list(limit=1, only_meaningful=only_meaningful)
        if not summaries:
            return None
        return self.get(summaries[0].id)

    def _load_path(self, p: Path) -> Conversation:
        with p.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        # Tolerant load: M0 logs lacked `title` / `updated_at`. Fill defaults.
        return Conversation(
            id=str(payload.get("id") or p.stem),
            title=str(payload.get("title") or ""),
            model=str(payload.get("model") or ""),
            started_at=str(
                payload.get("started_at") or payload.get("ended_at") or _now_iso()
            ),
            updated_at=str(
                payload.get("updated_at") or payload.get("ended_at") or _now_iso()
            ),
            messages=list(payload.get("messages") or []),
        )

    # ---------------------------------------------------------------- write

    def save(self, conv: Conversation) -> Path:
        """Atomic write. Updates `updated_at` to now."""
        self.root.mkdir(parents=True, exist_ok=True)
        conv.updated_at = _now_iso()
        target = self.root / conv.filename
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(
            json.dumps(conv.to_payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.chmod(tmp, 0o600)
        tmp.replace(target)
        return target

    def rename(self, conv_id: str, new_title: str) -> Conversation | None:
        conv = self.get(conv_id)
        if conv is None:
            return None
        conv.title = new_title.strip()
        self.save(conv)
        return conv

    def delete(self, conv_id: str) -> bool:
        p = self.root / f"{conv_id}.json"
        if not p.exists():
            return False
        try:
            p.unlink()
            return True
        except OSError:
            return False

    def new(self, model: str = "", system_prompt: str = "") -> Conversation:
        """Start a fresh conversation with the given system prompt as the
        first message. Caller should `save()` after appending real turns.
        """
        conv = Conversation(model=model)
        if system_prompt:
            conv.messages.append({"role": "system", "content": system_prompt})
        return conv
