"""Draft entity — a half-finished item pending user review.

Drafts live at `<vault>/drafts/<id>-<slug>.md`. They share the Markdown +
frontmatter shape with Notes so the user's editor sees a familiar file. On
approval, a Draft is converted to a Note (id, title, body, tags, source,
kind preserved), written into `<vault>/notes/`, indexed, then the draft file
is removed.

Per ADR-0009 (+ amendment 2026-05-16) the drafts directory is the
**explicit-defer** staging area — content only enters by the user
saying "save for later". AI-extracted material that the user decides
on at capture time goes straight to `<vault>/notes/` instead.

ADR-0029 §4 原则 7 ties anti-drift safety nets to Draft:
- age tickling: 7 day muted, 30 day banner, 90 day auto-archive
- soft limit warning at >20 active
- mining throttle: `max_pending_drafts` per task

ADR-0002 (data sovereignty) requires the files be plain Markdown the
user can edit/inspect at any time.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import frontmatter

from knowlet.core.note import (
    DEFAULT_NOTE_KIND,
    NOTE_KINDS,
    Note,
    NoteKind,
    new_id,
    now_iso,
    slugify,
)

DRAFTS_DIR = "drafts"

# Phase 2 E Slice 4.D — Draft schema version (ADR-0018 §2). Same lazy-
# migration policy as Note: legacy frontmatter without `schema_version`
# defaults to v1 on read; current value is stamped on every write.
DRAFT_SCHEMA_VERSION = 1

# Phase 3 Stage 3 — ADR-0029 §4 原则 7 + ADR-0009 amendment 2026-05-16.
# Age thresholds for anti-drift safety nets on the drafts queue. Tuned
# to the doc's specification, not arbitrary.
STALE_AGE_DAYS = 7        # row visually muted after this
WARN_AGE_DAYS = 30        # one-time banner on open after this
ARCHIVE_AGE_DAYS = 90     # auto-archive after this
SOFT_LIMIT_DRAFTS = 20    # >this active = inline soft warning


def _age_days_from_iso(iso_ts: str | None) -> int:
    """Days elapsed since ``iso_ts`` (timezone-aware UTC). 0 on parse error.

    Lenient parser: accepts both ``...Z`` and ``...+00:00`` shapes; falls
    back to 0 so a malformed timestamp never breaks age computation."""
    if not iso_ts:
        return 0
    try:
        s = iso_ts.replace("Z", "+00:00") if iso_ts.endswith("Z") else iso_ts
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return 0
    delta = datetime.now(UTC) - dt
    return max(0, int(delta.total_seconds() // 86400))


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
    schema_version: int = DRAFT_SCHEMA_VERSION
    path: Path | None = None
    # Phase 3 Stage 3 — ADR-0029 §4.5 knowledge / reference distinction
    # also applies to drafts: a deferred URL is typically 资料, a
    # deferred chat sediment is typically 知识. Default knowledge to
    # mirror Note's default; callers (capture flow / mining task) set
    # the right value at create time per ADR-0029 §4.5 default-by-
    # source table.
    kind: NoteKind = DEFAULT_NOTE_KIND

    @property
    def slug(self) -> str:
        return slugify(self.title) if self.title else "draft"

    @property
    def filename(self) -> str:
        return f"{self.id}-{self.slug}.md"

    # ---------- age helpers (Phase 3 Stage 3, ADR-0029 §4 原则 7) ----------

    @property
    def age_days(self) -> int:
        return _age_days_from_iso(self.created_at)

    @property
    def is_stale(self) -> bool:
        """Draft is past the 7-day visual-mute threshold."""
        return self.age_days >= STALE_AGE_DAYS

    @property
    def is_warn_age(self) -> bool:
        """Draft has crossed the 30-day banner threshold."""
        return self.age_days >= WARN_AGE_DAYS

    @property
    def should_auto_archive(self) -> bool:
        """Draft is old enough to be auto-archived (90 days)."""
        return self.age_days >= ARCHIVE_AGE_DAYS

    def to_markdown(self) -> str:
        meta: dict[str, object] = {
            "schema_version": DRAFT_SCHEMA_VERSION,
            "id": self.id,
            "title": self.title,
            "tags": list(self.tags),
            "kind": self.kind,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": "draft",
        }
        if self.source:
            meta["source"] = self.source
        if self.task_id:
            meta["task_id"] = self.task_id
        post = frontmatter.Post(self.body, **meta)
        return str(frontmatter.dumps(post))

    @classmethod
    def from_file(cls, path: Path) -> Draft:
        with path.open("r", encoding="utf-8") as f:
            post = frontmatter.load(f)
        meta = post.metadata
        try:
            schema_version = int(meta.get("schema_version") or 1)
        except (TypeError, ValueError):
            schema_version = 1
        # Forward-compat for the kind field: legacy drafts (pre-Stage-3)
        # have no `kind` → default knowledge; bogus values fall back the
        # same way Note does.
        kind_raw = meta.get("kind")
        kind: NoteKind = (
            kind_raw if kind_raw in NOTE_KINDS else DEFAULT_NOTE_KIND
        )
        return cls(
            id=str(meta.get("id") or new_id()),
            title=str(meta.get("title") or path.stem),
            body=post.content,
            tags=list(meta.get("tags") or []),
            source=meta.get("source"),
            task_id=meta.get("task_id"),
            created_at=str(meta.get("created_at") or now_iso()),
            updated_at=str(meta.get("updated_at") or now_iso()),
            schema_version=schema_version,
            kind=kind,
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
            kind=self.kind,
        )


class DraftStore:
    """Filesystem operations for drafts. Mirrors `Vault` for Notes."""

    def __init__(self, root: Path):
        self.root = root  # = vault.drafts_dir

    def iter_paths(self) -> Iterator[Path]:
        if not self.root.exists():
            return iter(())
        return (p for p in self.root.glob("*.md") if p.is_file())

    def all_drafts(self) -> list[Draft]:
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
        # Capture the on-disk path BEFORE we reassign — the title may
        # have changed, which would re-derive the slug and hence the
        # filename. If we ignore the old file, it'd linger as a
        # duplicate of the same draft id.
        previous_path = draft.path
        target = self.root / draft.filename
        draft.path = target
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(draft.to_markdown(), encoding="utf-8")
        tmp.replace(target)
        # If the slug changed, delete the old file so the draft has
        # exactly one home on disk.
        if (
            previous_path is not None
            and previous_path != target
            and previous_path.exists()
        ):
            with suppress(OSError):
                os.unlink(previous_path)
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

    def archive(self, draft: Draft, *, month_subdir: bool = False) -> Path | None:
        """Soft-delete: move the draft into `.archive/`. Recoverable; the
        sidebar count + main `list()` ignore archived drafts so they
        don't pollute the queue.

        When ``month_subdir=True`` the file lands under
        ``.archive/<YYYY-MM>/`` instead of flat under ``.archive/``.
        Stage 3's age-based auto-archive uses this so 90 days of old
        drafts don't pile into one giant directory; Stage 1's
        mining-quota archive stays flat for back-compat.
        """
        if draft.path is None or not draft.path.exists():
            return None
        if month_subdir:
            from datetime import datetime as _dt

            yyyy_mm = _dt.now(UTC).strftime("%Y-%m")
            base = self.archive_dir / yyyy_mm
        else:
            base = self.archive_dir
        base.mkdir(parents=True, exist_ok=True)
        target = base / draft.path.name
        # If a same-named file exists in archive, suffix with timestamp.
        if target.exists():
            target = base / f"{draft.path.stem}-{now_iso().replace(':', '-')}.md"
        draft.path.rename(target)
        return target

    def list_for_task(self, task_id: str) -> list[Draft]:
        return [d for d in self.all_drafts() if d.task_id == task_id]

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

    # --------------- age-based archive (Phase 3 Stage 3) ---------------

    def enforce_age_archive(self) -> int:
        """Move every draft older than ``ARCHIVE_AGE_DAYS`` into
        ``.archive/<YYYY-MM>/``. Returns the number archived.

        Per ADR-0029 §4 原则 7 + ADR-0009 amendment A2.3: 90-day drafts
        auto-archive — not deleted, recoverable, but moved out of the
        active queue so the user is never staring at 200+ stale items.

        Idempotent: re-running does nothing if no drafts crossed the
        threshold since last call. Safe to invoke on every drafts list
        fetch (cheap — only walks live `iter_paths`)."""
        archived = 0
        for path in list(self.iter_paths()):  # snapshot — we mutate
            try:
                draft = Draft.from_file(path)
            except OSError:
                continue
            if draft.should_auto_archive and self.archive(draft, month_subdir=True) is not None:
                archived += 1
        return archived

    def active_count(self) -> int:
        """How many drafts are in the live queue right now (excludes
        ``.archive/`` and its month subdirs). Used for the soft-limit
        UI warning (>20 = inline 'consider reviewing first' prompt)."""
        return sum(1 for _ in self.iter_paths())
