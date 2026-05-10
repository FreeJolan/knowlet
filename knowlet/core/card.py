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


# Phase 2 E Slice 4.D — Card schema version (ADR-0018 §2). v1 ships
# alongside the current shape; future bumps follow the same lazy-
# migration policy as Note: read N-1 transparently, stamp current
# version on next write.
CARD_SCHEMA_VERSION = 1


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
    schema_version: int = CARD_SCHEMA_VERSION
    path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        # Always stamp current version on write — that's how lazy
        # migration upgrades pre-versioned cards on the next save.
        d: dict[str, Any] = {
            "schema_version": CARD_SCHEMA_VERSION,
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
        # Pre-versioned cards default to v1 (same shape, just unmarked).
        try:
            schema_version = int(d.get("schema_version") or 1)
        except (TypeError, ValueError):
            schema_version = 1
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
            schema_version=schema_version,
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
