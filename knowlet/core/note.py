"""Note entity: Markdown body + frontmatter.

A Note is the only entity type in the MVP. It's stored at
`<vault>/notes/<id>.md` with YAML frontmatter and Markdown body. The
filename is the ULID alone — no title-derived slug — so renaming a
note's title is a pure in-place rewrite. With a slug-suffixed filename,
a rename was a `write new + unlink old` pair, which on iCloud /
Syncthing fans out as a delete + create event and races into
`(conflict)` copies on peers that hadn't pulled yet (2026-05-02
critique #5). The title still lives in frontmatter, so Finder / Obsidian
users can read it, and the chat / web UI display it directly.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, get_args

import frontmatter
from ulid import ULID

# Phase 2 E Slice 4.C — Note frontmatter v2 status (ADR-0023 §7).
# `active`        — default; the note is live and current.
# `stub`          — auto-detectable as undercooked (e.g. body < 100
#                   chars + zero wikilinks); flagged in lint.
# `needs-update`  — linter saw a newer source contradict this page.
#                   ADR-0024 §5 B forbids the linter from rewriting
#                   body — it can only flip the status.
# `deprecated`    — user-marked superseded; stays around for
#                   backlinks but de-prioritized in search.
NoteStatus = Literal["active", "stub", "needs-update", "deprecated"]
NOTE_STATUSES: tuple[str, ...] = get_args(NoteStatus)
DEFAULT_NOTE_STATUS: NoteStatus = "active"


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


# Frontmatter schema version. Bump this whenever a Note field is added,
# removed, or has its serialization changed in a way old code can't read.
#
# v1 (pre-2026-05-10) — no `status` field.
# v2 (2026-05-10, ADR-0023 §7) — adds `status` (NoteStatus enum). v1
#   notes default to `active` on read; on the next write they're
#   re-stamped as v2 (lazy migration per ADR-0018 §1).
#
# Migration policy: code at schema_version = N must be able to read
# notes written by N-1 without manual intervention. Newer-than-known
# raises (we never silently truncate user data).
NOTE_SCHEMA_VERSION = 2


@dataclass
class Note:
    id: str
    title: str
    body: str
    tags: list[str] = field(default_factory=list)
    # Alternate names this note can be referenced by (Phase 1 D / D3
    # Properties UI). Stored in frontmatter as `aliases: [list]`. Future
    # wiki schema (ADR-0023 §2) will let `[[Alias]]` resolve to the
    # canonical note via this field; today they're metadata-only and
    # the resolver still matches on title.
    aliases: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    source: str | None = None
    path: Path | None = None
    schema_version: int = NOTE_SCHEMA_VERSION
    # Phase 2 E Slice 4.C — Note lifecycle status. v1 notes default
    # to "active" on read; the field is always emitted on write so
    # the frontmatter stays self-describing.
    status: NoteStatus = DEFAULT_NOTE_STATUS
    # When the note is in `notes/.trash/`, this captures the folder
    # (relative to `notes/`) it was sitting in before deletion. `None`
    # when the note is live or when the trash entry pre-dates this
    # field (legacy notes restore to root). Keeps the file portable —
    # if the user opens it from Finder, they can still tell where it
    # came from. Stripped from the frontmatter on restore.
    trashed_from: str | None = None

    @property
    def slug(self) -> str:
        # Kept for callers / tests / scripts that still want a title-derived
        # slug for a non-filesystem purpose (display, URL hint, etc.). The
        # filename intentionally does *not* use it.
        return slugify(self.title)

    @property
    def filename(self) -> str:
        return f"{self.id}.md"

    @property
    def content_hash(self) -> str:
        h = hashlib.sha256()
        h.update(self.title.encode("utf-8"))
        h.update(b"\x00")
        h.update(self.body.encode("utf-8"))
        return h.hexdigest()

    def to_markdown(self) -> str:
        # Always stamp with the current schema_version on write — that
        # gives lazy migration of v1 files (next edit upgrades them
        # to v2) per ADR-0018 §1.
        meta: dict[str, object] = {
            "schema_version": NOTE_SCHEMA_VERSION,
            "id": self.id,
            "title": self.title,
            "tags": list(self.tags),
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.aliases:
            meta["aliases"] = list(self.aliases)
        if self.source:
            meta["source"] = self.source
        if self.trashed_from is not None:
            meta["trashed_from"] = self.trashed_from
        post = frontmatter.Post(self.body, **meta)
        return str(frontmatter.dumps(post))

    @classmethod
    def from_file(cls, path: Path) -> Note:
        with path.open("r", encoding="utf-8") as f:
            post = frontmatter.load(f)
        meta = post.metadata
        # Pre-versioned notes default to v1 — same shape, just unmarked.
        try:
            schema_version = int(meta.get("schema_version") or 1)
        except (TypeError, ValueError):
            schema_version = 1
        # Status: present on v2+; default "active" on v1 / missing /
        # invalid value (forward-compat per ADR-0018 §1). We don't
        # silently coerce a typo into a valid enum — invalid values
        # log + degrade to default; the next write re-stamps a clean
        # value.
        status_raw = meta.get("status")
        if status_raw in NOTE_STATUSES:
            status: NoteStatus = status_raw
        else:
            if status_raw is not None and schema_version >= 2:
                # Schema claims v2 but status is bogus — surface for
                # the doctor command without raising.
                import logging

                logging.getLogger(__name__).warning(
                    "note %s has invalid status %r; defaulting to %s",
                    path.name,
                    status_raw,
                    DEFAULT_NOTE_STATUS,
                )
            status = DEFAULT_NOTE_STATUS
        trashed_from_raw = meta.get("trashed_from")
        trashed_from = str(trashed_from_raw) if trashed_from_raw is not None else None
        return cls(
            id=str(meta.get("id") or new_id()),
            title=str(meta.get("title") or path.stem),
            body=post.content,
            tags=list(meta.get("tags") or []),
            aliases=[str(a) for a in (meta.get("aliases") or [])],
            created_at=str(meta.get("created_at") or now_iso()),
            updated_at=str(meta.get("updated_at") or now_iso()),
            source=meta.get("source"),
            path=path,
            schema_version=schema_version,
            status=status,
            trashed_from=trashed_from,
        )
