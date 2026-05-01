"""Vault: filesystem layout, Note read/write, vault initialization."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterator

from knowlet.config import VAULT_MARKER_DIR
from knowlet.core.note import Note, now_iso

NOTES_DIR = "notes"
USERS_DIR = "users"
PROFILE_FILENAME = "me.md"
CARDS_DIR = "cards"
TASKS_DIR = "tasks"
DRAFTS_DIR = "drafts"
INDEX_DB = "index.sqlite"
CONVERSATIONS_DIR = "conversations"
BACKUPS_DIR = "backups"


class Vault:
    """Filesystem operations on a knowlet vault."""

    def __init__(self, root: Path):
        self.root = root.resolve()

    @property
    def notes_dir(self) -> Path:
        return self.root / NOTES_DIR

    @property
    def users_dir(self) -> Path:
        return self.root / USERS_DIR

    @property
    def profile_path(self) -> Path:
        return self.users_dir / PROFILE_FILENAME

    @property
    def cards_dir(self) -> Path:
        return self.root / CARDS_DIR

    @property
    def tasks_dir(self) -> Path:
        return self.root / TASKS_DIR

    @property
    def drafts_dir(self) -> Path:
        return self.root / DRAFTS_DIR

    @property
    def state_dir(self) -> Path:
        return self.root / VAULT_MARKER_DIR

    @property
    def db_path(self) -> Path:
        return self.state_dir / INDEX_DB

    @property
    def conversations_dir(self) -> Path:
        return self.state_dir / CONVERSATIONS_DIR

    @property
    def backups_dir(self) -> Path:
        return self.state_dir / BACKUPS_DIR

    def init_layout(self) -> None:
        """Create the directory structure. Idempotent."""
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.users_dir.mkdir(parents=True, exist_ok=True)
        self.cards_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.conversations_dir.mkdir(parents=True, exist_ok=True)
        self.backups_dir.mkdir(parents=True, exist_ok=True)

    def iter_note_paths(self) -> Iterator[Path]:
        if not self.notes_dir.exists():
            return iter(())
        return (p for p in self.notes_dir.glob("*.md") if p.is_file())

    def read_note(self, path: Path) -> Note:
        return Note.from_file(path)

    def write_note(self, note: Note) -> Path:
        """Atomically write a Note. Returns the final path."""
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        target = self.notes_dir / note.filename
        note.path = target
        note.updated_at = now_iso()
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(note.to_markdown(), encoding="utf-8")
        tmp.replace(target)
        return target

    def backup_note(self, path: Path) -> Path:
        """Copy a Note into backups/ before overwriting/deleting it."""
        if not path.exists():
            return path
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        target = self.backups_dir / f"{now_iso().replace(':', '-')}-{path.name}"
        shutil.copy2(path, target)
        return target
