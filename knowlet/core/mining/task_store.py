"""TaskStore — CRUD over `<vault>/tasks/*.md`."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator

from knowlet.core.mining.task import MiningTask
from knowlet.core.note import now_iso


class TaskStore:
    def __init__(self, root: Path):
        self.root = root

    def iter_paths(self) -> Iterator[Path]:
        if not self.root.exists():
            return iter(())
        return (p for p in self.root.glob("*.md") if p.is_file())

    def list(self) -> list[MiningTask]:
        out: list[MiningTask] = []
        for p in self.iter_paths():
            try:
                out.append(MiningTask.from_file(p))
            except (OSError, ValueError):
                continue
        out.sort(key=lambda t: t.created_at)
        return out

    def get(self, task_id: str) -> MiningTask | None:
        for p in self.iter_paths():
            if p.stem.startswith(task_id):
                try:
                    return MiningTask.from_file(p)
                except (OSError, ValueError):
                    return None
        return None

    def save(self, task: MiningTask) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        task.updated_at = now_iso()
        target = self.root / task.filename
        # If the slug changed, remove the old file (id-prefix matches but slug differs).
        for p in self.iter_paths():
            if p.stem.startswith(task.id) and p.name != target.name:
                try:
                    os.unlink(p)
                except OSError:
                    pass
        task.path = target
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(task.to_markdown(), encoding="utf-8")
        tmp.replace(target)
        return target

    def delete(self, task_id: str) -> bool:
        t = self.get(task_id)
        if t is None or t.path is None:
            return False
        os.unlink(t.path)
        return True
