"""Card entity (scenario C — structured spaced-repetition memory).

A Card is structured (front / back / tags + FSRS state) and persists as JSON
at `<vault>/cards/<id>.json`. Per ADR-0006 the JSON shape is the on-disk
format; this module owns the round-trip.

We keep the FSRS state as a nested dict (the fsrs library's `to_dict()`/
`from_dict()` payload) — never reach into its fields by hand. That way
algorithm upgrades (e.g. fsrs 7) only require a wrapper version bump.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ulid import ULID

from knowlet.core.note import now_iso

CARD_TYPES = ("basic", "cloze")


def _new_id() -> str:
    return str(ULID())


@dataclass
class Card:
    id: str = field(default_factory=_new_id)
    type: str = "basic"  # basic | cloze
    front: str = ""
    back: str = ""
    tags: list[str] = field(default_factory=list)
    source_note_id: str | None = None  # optional link back to a Note
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    fsrs_state: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "front": self.front,
            "back": self.back,
            "tags": list(self.tags),
            "source_note_id": self.source_note_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "fsrs_state": dict(self.fsrs_state),
        }
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Card:
        return cls(
            id=str(d.get("id") or _new_id()),
            type=str(d.get("type") or "basic"),
            front=str(d.get("front") or ""),
            back=str(d.get("back") or ""),
            tags=list(d.get("tags") or []),
            source_note_id=d.get("source_note_id"),
            created_at=str(d.get("created_at") or now_iso()),
            updated_at=str(d.get("updated_at") or now_iso()),
            fsrs_state=dict(d.get("fsrs_state") or {}),
        )

    @classmethod
    def from_file(cls, path: Path) -> Card:
        with path.open("r", encoding="utf-8") as f:
            d = json.load(f)
        c = cls.from_dict(d)
        c.path = path
        return c

    @property
    def filename(self) -> str:
        return f"{self.id}.json"


def parse_due(card: Card) -> datetime:
    """Return the card's `due` instant as a tz-aware datetime.

    A brand-new card with empty FSRS state is considered due immediately
    (so it shows up on the first review session).
    """
    iso = card.fsrs_state.get("due") if card.fsrs_state else None
    if not iso:
        return datetime.now(UTC)
    if iso.endswith("Z"):
        iso = iso[:-1] + "+00:00"
    return datetime.fromisoformat(iso)
