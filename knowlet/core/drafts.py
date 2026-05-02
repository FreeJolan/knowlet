"""Draft entity — a Note pending user review.

Drafts live at `<vault>/drafts/<id>-<slug>.md`. They share the Markdown +
frontmatter shape with Notes so the user's editor sees a familiar file. On
approval, a Draft is converted to a Note (id, title, body, tags, source
preserved), written into `<vault>/notes/`, indexed, then the draft file is
removed.

Per ADR-0009 the drafts directory is the staging area between AI extraction
and user-approved sedimentation. ADR-0002 (data sovereignty) requires the
files be plain Markdown the user can edit/inspect at any time.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import frontmatter

from knowlet.core.note import Note, new_id, now_iso, slugify

DRAFTS_DIR = "drafts"


@dataclass
class Draft:
    id: str = field(default_factory=new_id)
    title: str = ""
    body: str = ""
    tags: list[str] = field(default_factory=list)
    source: str | None = None
    task_id: str | None = None  # mining-task id that produced this draft, if any
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    path: Path | None = None

    @property
    def slug(self) -> str:
        return slugify(self.title) if self.title else "draft"

    @property
    def filename(self) -> str:
        return f"{self.id}-{self.slug}.md"

    def to_markdown(self) -> str:
        meta: dict[str, object] = {
            "id": self.id,
            "title": self.title,
            "tags": list(self.tags),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": "draft",
        }
        if self.source:
            meta["source"] = self.source
        if self.task_id:
            meta["task_id"] = self.task_id
        post = frontmatter.Post(self.body, **meta)
        return frontmatter.dumps(post)

    @classmethod
    def from_file(cls, path: Path) -> Draft:
        with path.open("r", encoding="utf-8") as f:
            post = frontmatter.load(f)
        meta = post.metadata
        return cls(
            id=str(meta.get("id") or new_id()),
            title=str(meta.get("title") or path.stem),
            body=post.content,
            tags=list(meta.get("tags") or []),
            source=meta.get("source"),
            task_id=meta.get("task_id"),
            created_at=str(meta.get("created_at") or now_iso()),
            updated_at=str(meta.get("updated_at") or now_iso()),
            path=path,
        )

    def to_note(self) -> Note:
        """Project a Draft to a Note (drops the draft-only metadata)."""
        return Note(
            id=self.id,
            title=self.title,
            body=self.body,
            tags=list(self.tags),
            source=self.source,
            created_at=self.created_at,
            updated_at=now_iso(),
        )


class DraftStore:
    """Filesystem operations for drafts. Mirrors `Vault` for Notes."""

    def __init__(self, root: Path):
        self.root = root  # = vault.drafts_dir

    def iter_paths(self) -> Iterator[Path]:
        if not self.root.exists():
            return iter(())
        return (p for p in self.root.glob("*.md") if p.is_file())

    def list(self) -> list[Draft]:
        out: list[Draft] = []
        for p in self.iter_paths():
            try:
                out.append(Draft.from_file(p))
            except OSError:
                continue
        out.sort(key=lambda d: d.created_at, reverse=True)
        return out

    def get(self, draft_id: str) -> Draft | None:
        for p in self.iter_paths():
            if p.stem.startswith(draft_id):
                return Draft.from_file(p)
        return None

    def save(self, draft: Draft) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        draft.updated_at = now_iso()
        target = self.root / draft.filename
        draft.path = target
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(draft.to_markdown(), encoding="utf-8")
        tmp.replace(target)
        return target

    def delete(self, draft_id: str) -> bool:
        d = self.get(draft_id)
        if d is None or d.path is None:
            return False
        os.unlink(d.path)
        return True

    # ---------------------------------------------------- archive (M6.5)

    @property
    def archive_dir(self) -> Path:
        return self.root / ".archive"

    def archive(self, draft: Draft) -> Path | None:
        """Soft-delete: move the draft into `.archive/`. Recoverable; the
        sidebar count + main `list()` ignore archived drafts so they
        don't pollute the inbox.
        """
        if draft.path is None or not draft.path.exists():
            return None
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        target = self.archive_dir / draft.path.name
        # If a same-named file exists in archive, suffix with timestamp.
        if target.exists():
            target = self.archive_dir / f"{draft.path.stem}-{now_iso().replace(':', '-')}.md"
        draft.path.rename(target)
        return target

    def list_for_task(self, task_id: str) -> list[Draft]:
        return [d for d in self.list() if d.task_id == task_id]

    def enforce_max_keep(self, task_id: str, max_keep: int) -> int:
        """Archive oldest drafts produced by `task_id` until the live
        queue size drops to `max_keep`. Returns the number archived.

        ADR-0011 §6: prevents the "247 unread" inbox-hell pattern. New
        drafts kick the oldest out instead of accumulating forever.
        """
        if max_keep <= 0:
            return 0
        live = self.list_for_task(task_id)
        if len(live) <= max_keep:
            return 0
        # `list()` returns newest first; archive the oldest tail.
        to_archive = live[max_keep:]
        archived = 0
        for d in to_archive:
            if self.archive(d) is not None:
                archived += 1
        return archived
