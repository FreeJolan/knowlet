"""Conversation log persistence (ADR-0006: 30-day raw payload retention).

One file per session at `<vault>/.knowlet/conversations/<ulid>.json`. Pruning
runs on chat startup so the history doesn't grow unboundedly.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ulid import ULID


@dataclass
class ConversationLog:
    dir: Path
    model: str
    id: str = field(default_factory=lambda: str(ULID()))
    started_at: str = field(default_factory=lambda: datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def write(self, history: list[dict[str, Any]]) -> Path | None:
        if not history or len(history) <= 1:
            return None  # nothing meaningful to keep
        self.dir.mkdir(parents=True, exist_ok=True)
        target = self.dir / f"{self.id}.json"
        payload = {
            "id": self.id,
            "model": self.model,
            "started_at": self.started_at,
            "ended_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "messages": history,
        }
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(target)
        return target


def prune_old(dir: Path, days: int = 30) -> int:
    """Delete conversation files older than `days`. Returns count deleted."""
    if not dir.exists():
        return 0
    cutoff = time.time() - days * 86400
    deleted = 0
    for p in dir.glob("*.json"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                deleted += 1
        except OSError:
            continue
    return deleted
