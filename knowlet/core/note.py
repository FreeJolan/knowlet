"""Note entity: Markdown body + frontmatter.

A Note is the only entity type in the MVP. It's stored at
`<vault>/notes/<id>-<slug>.md` with YAML frontmatter and Markdown body.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import frontmatter
from ulid import ULID


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id() -> str:
    return str(ULID())


_SLUG_BAD = re.compile(r"[^a-z0-9一-鿿]+")


def slugify(title: str, max_len: int = 40) -> str:
    """Slug for the filename. Keeps ASCII letters/digits and CJK; replaces the rest with `-`."""
    norm = unicodedata.normalize("NFKC", title).strip().lower()
    slug = _SLUG_BAD.sub("-", norm).strip("-")
    if not slug:
        slug = "note"
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-") or "note"
    return slug


@dataclass
class Note:
    id: str
    title: str
    body: str
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    source: str | None = None
    path: Path | None = None

    @property
    def slug(self) -> str:
        return slugify(self.title)

    @property
    def filename(self) -> str:
        return f"{self.id}-{self.slug}.md"

    @property
    def content_hash(self) -> str:
        h = hashlib.sha256()
        h.update(self.title.encode("utf-8"))
        h.update(b"\x00")
        h.update(self.body.encode("utf-8"))
        return h.hexdigest()

    def to_markdown(self) -> str:
        meta = {
            "id": self.id,
            "title": self.title,
            "tags": list(self.tags),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.source:
            meta["source"] = self.source
        post = frontmatter.Post(self.body, **meta)
        return frontmatter.dumps(post)

    @classmethod
    def from_file(cls, path: Path) -> Note:
        with path.open("r", encoding="utf-8") as f:
            post = frontmatter.load(f)
        meta = post.metadata
        return cls(
            id=str(meta.get("id") or new_id()),
            title=str(meta.get("title") or path.stem),
            body=post.content,
            tags=list(meta.get("tags") or []),
            created_at=str(meta.get("created_at") or now_iso()),
            updated_at=str(meta.get("updated_at") or now_iso()),
            source=meta.get("source"),
            path=path,
        )
