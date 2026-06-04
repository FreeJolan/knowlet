"""TaskStore — CRUD over `<vault>/tasks/*.md`."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path

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
                with contextlib.suppress(OSError):
                    os.unlink(p)
                self._queue_delete_sync(p)
        task.path = target
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(task.to_markdown(), encoding="utf-8")
        tmp.replace(target)
        self._queue_sync(target)
        return target

    def delete(self, task_id: str) -> bool:
        t = self.get(task_id)
        if t is None or t.path is None:
            return False
        deleted_path = t.path
        os.unlink(t.path)
        self._queue_delete_sync(deleted_path)
        return True

    def _vault_root(self) -> Path | None:
        if self.root.name != "tasks":
            return None
        return self.root.parent

    def _queue_sync(self, path: Path) -> None:
        vault_root = self._vault_root()
        if vault_root is None:
            return
        from knowlet.core.sync.tracked_files import queue_syncable_vault_file_if_authenticated

        queue_syncable_vault_file_if_authenticated(vault_root=vault_root, path=path)

    def _queue_delete_sync(self, path: Path) -> None:
        vault_root = self._vault_root()
        if vault_root is None:
            return
        from knowlet.core.sync.tracked_files import (
            queue_syncable_vault_file_delete_if_authenticated,
        )

        queue_syncable_vault_file_delete_if_authenticated(vault_root=vault_root, path=path)
