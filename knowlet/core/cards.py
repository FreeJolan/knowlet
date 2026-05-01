"""CardStore — filesystem operations for Cards.

Mirror of `knowlet/core/vault.py` (which handles Notes), but for the JSON
Card layer at `<vault>/cards/`. Kept separate because Cards have a different
shape (structured fields + FSRS state) and a different lifecycle (review-
driven, not edit-driven).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator

from knowlet.core.card import Card, parse_due
from knowlet.core.note import now_iso

CARDS_DIR = "cards"


class CardStore:
    """All Card I/O lives here. The Vault hands out the directory; this class
    owns the per-file atomic write, the listing, and the due-filter logic."""

    def __init__(self, root: Path):
        self.root = root  # = vault.cards_dir

    @property
    def dir(self) -> Path:
        return self.root

    # ---------------------------------------------------------- discovery

    def iter_card_paths(self) -> Iterator[Path]:
        if not self.root.exists():
            return iter(())
        return (p for p in self.root.glob("*.json") if p.is_file())

    def list_cards(self) -> list[Card]:
        cards: list[Card] = []
        for p in self.iter_card_paths():
            try:
                cards.append(Card.from_file(p))
            except (OSError, json.JSONDecodeError):
                continue
        return cards

    def list_due(self, now: datetime | None = None, limit: int | None = None) -> list[Card]:
        """Cards whose `due` <= now. New cards (empty FSRS state) count as due."""
        if now is None:
            now = datetime.now(UTC)
        out: list[Card] = []
        for c in self.list_cards():
            if parse_due(c) <= now:
                out.append(c)
        out.sort(key=parse_due)  # earliest due first
        if limit is not None:
            out = out[: int(limit)]
        return out

    def get(self, card_id: str) -> Card | None:
        path = self.root / f"{card_id}.json"
        if not path.exists():
            return None
        return Card.from_file(path)

    # ---------------------------------------------------------- write

    def save(self, card: Card) -> Path:
        """Atomically write `<root>/<id>.json`."""
        self.root.mkdir(parents=True, exist_ok=True)
        card.updated_at = now_iso()
        target = self.root / card.filename
        card.path = target
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(
            json.dumps(card.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(target)
        return target

    def delete(self, card_id: str) -> bool:
        path = self.root / f"{card_id}.json"
        if not path.exists():
            return False
        os.unlink(path)
        return True
