"""Phase 2 D B1 — starred / favorited notes.

Local-only, single-user list of note ids the user wants always one
click away. Stored in ``<vault>/.knowlet/favorites.json``. By design:

- **By id, not path** — survives renames + folder moves.
- **Append-order = display-order** — V1 has no drag-drop reorder; if
  the user wants to change the order, they remove and re-add.
- **Local, not synced** — favorites are per-device UI preference, same
  category as tab pinning state (localStorage) and the sync_state DB.
- **Self-pruning on read** — entries pointing at notes the caller
  reports as "no longer exists" get silently removed and written back.
  That keeps the file from accumulating dangling rows after deletes /
  trashes without forcing the caller to track delete events.

Atomic writes via tmp + ``Path.replace`` so a partial write can't
corrupt the file. The store doesn't need an in-memory cache — favorites
read/write traffic is tiny (handful of entries, ~1 op per user gesture).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

FavoriteIds: TypeAlias = list[str]


@dataclass(frozen=True)
class FavoritesStore:
    """Thin file-backed list of starred note ids.

    Methods don't return errors for "missing file" — an absent
    favorites.json means "no favorites yet", which is the correct
    initial state. Callers can treat empty == fresh install.
    """

    vault_root: Path

    @property
    def path(self) -> Path:
        return self.vault_root / ".knowlet" / "favorites.json"

    def _read_raw(self) -> list[str]:
        """Read the on-disk ids without any pruning. Returns [] when
        the file doesn't exist or is malformed (forgiving — a corrupt
        favorites.json shouldn't block app startup)."""
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(payload, dict):
            return []
        ids = payload.get("ids")
        if not isinstance(ids, list):
            return []
        # Defensive: drop non-strings; the file should never have
        # them but a hand-edit might.
        return [str(x) for x in ids if isinstance(x, str)]

    def _write(self, ids: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps({"ids": ids}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    # --------------------------------------------------- public API

    def list(self, *, existing_ids: Iterable[str] | None = None) -> list[str]:
        """Return current favorites in display order.

        ``existing_ids`` is the set of note ids the caller considers
        "alive" (typically ``runtime.index.list_notes()`` ids).
        Entries not in that set are pruned + the file is rewritten.
        Pass ``None`` to skip pruning (useful when the index isn't
        available, e.g. during a doctor run or test).
        """
        raw = self._read_raw()
        if existing_ids is None:
            return raw
        alive = set(existing_ids)
        pruned = [i for i in raw if i in alive]
        if len(pruned) != len(raw):
            self._write(pruned)
        return pruned

    def add(self, note_id: str) -> FavoriteIds:
        """Add note_id to the end of the list if not already present.
        Returns the updated list. Idempotent."""
        ids = self._read_raw()
        if note_id in ids:
            return ids
        ids.append(note_id)
        self._write(ids)
        return ids

    def remove(self, note_id: str) -> FavoriteIds:
        """Remove note_id if present. Returns the updated list.
        Idempotent — removing an absent id is a no-op."""
        ids = self._read_raw()
        if note_id not in ids:
            return ids
        ids = [i for i in ids if i != note_id]
        self._write(ids)
        return ids

    def contains(self, note_id: str) -> bool:
        return note_id in self._read_raw()
