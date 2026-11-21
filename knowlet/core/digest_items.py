"""Raw Info items for Stage C v2.

RawInfo is the read-only inbox object produced by digest sources. It is
not a Draft and not a Note; later stages settle it into an editable note
draft before the user commits anything into the vault.
"""

from __future__ import annotations

import contextlib
import glob
import json
import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from knowlet.core.note import new_id, now_iso, slugify

RAW_INFO_SCHEMA_VERSION = 1
RawInfoStatus = Literal[
    "unprocessed",
    "viewed",
    "discussed",
    "drafted",
    "discarded",
    "included",
]
FINAL_STATUSES = {"discarded", "included"}
_UNREADABLE_ERRORS = (OSError, ValueError, json.JSONDecodeError)


class AmbiguousIdError(LookupError):
    """An id prefix matched more than one stored file."""

    def __init__(self, kind: str, given: str, candidates: list[str]):
        self.given = given
        self.candidates = candidates
        super().__init__(f"{kind} id {given!r} is ambiguous; matches: {', '.join(candidates)}")


def owns_stem(entity_id: str, stem: str) -> bool:
    """Files are named ``<id>-<slug>``; ULIDs never contain ``-``."""
    return stem == entity_id or stem.startswith(entity_id + "-")


def resolve_id_path(paths: Iterable[Path], given: str, *, kind: str) -> Path | None:
    """Pick the file for a full id or a unique id prefix.

    An exact id wins over prefix hits; several prefix hits raise
    :class:`AmbiguousIdError` since callers go on to mutate the result."""
    if not given:
        return None
    exact: list[Path] = []
    prefixed: list[Path] = []
    for path in sorted(paths):
        if owns_stem(given, path.stem):
            exact.append(path)
        elif path.stem.startswith(given):
            prefixed.append(path)
    if exact:
        return exact[0]
    if len(prefixed) > 1:
        raise AmbiguousIdError(kind, given, [p.stem.split("-", 1)[0] for p in prefixed])
    return prefixed[0] if prefixed else None


def remove_stale_files(root: Path, entity_id: str, keep: Path, *, known: Path | None) -> list[Path]:
    """Delete older ``<id>-<old-slug>`` files of one entity (after a rename).

    When the entity was loaded from ``known`` only that file can be stale,
    so the directory is not rescanned."""
    if known is not None:
        candidates = [known] if known.parent == root else []
    else:
        pattern = os.path.join(glob.escape(str(root)), glob.escape(entity_id) + "*.json")
        candidates = [Path(p) for p in glob.glob(pattern)]
    removed: list[Path] = []
    for path in candidates:
        if path.name != keep.name and owns_stem(entity_id, path.stem) and path.exists():
            with contextlib.suppress(OSError):
                os.unlink(path)
                removed.append(path)
    return removed


@dataclass
class RawInfo:
    source_id: str
    source_name: str
    source_kind: Literal["rss", "prompt"]
    item_key: str
    title: str
    url: str
    summary: str
    id: str = field(default_factory=new_id)
    published_at: str | None = None
    fetched_at: str = field(default_factory=now_iso)
    key_points: list[str] = field(default_factory=list)
    why_it_matters: str = ""
    suggested_tags: list[str] = field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    content_excerpt: str = ""
    status: RawInfoStatus = "unprocessed"
    note_draft_id: str | None = None
    note_id: str | None = None
    schema_version: int = RAW_INFO_SCHEMA_VERSION
    path: Path | None = None

    @property
    def slug(self) -> str:
        return slugify(self.title) if self.title else "raw-info"

    @property
    def filename(self) -> str:
        return f"{self.id}-{self.slug}.json"

    @property
    def is_pending(self) -> bool:
        return self.status not in FINAL_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RAW_INFO_SCHEMA_VERSION,
            "id": self.id,
            "source_id": self.source_id,
            "source_name": self.source_name,
            "source_kind": self.source_kind,
            "item_key": self.item_key,
            "title": self.title,
            "url": self.url,
            "published_at": self.published_at,
            "fetched_at": self.fetched_at,
            "summary": self.summary,
            "key_points": list(self.key_points),
            "why_it_matters": self.why_it_matters,
            "suggested_tags": list(self.suggested_tags),
            "confidence": self.confidence,
            "content_excerpt": self.content_excerpt,
            "status": self.status,
            "note_draft_id": self.note_draft_id,
            "note_id": self.note_id,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any], *, path: Path | None = None) -> RawInfo:
        status = str(raw.get("status") or "unprocessed")
        if status not in (
            "unprocessed",
            "viewed",
            "discussed",
            "drafted",
            "discarded",
            "included",
        ):
            status = "unprocessed"
        confidence = str(raw.get("confidence") or "medium")
        if confidence not in ("high", "medium", "low"):
            confidence = "medium"
        source_kind = str(raw.get("source_kind") or "rss")
        if source_kind not in ("rss", "prompt"):
            source_kind = "rss"
        try:
            schema_version = int(raw.get("schema_version") or 1)
        except (TypeError, ValueError):
            schema_version = 1
        return cls(
            id=str(raw.get("id") or new_id()),
            source_id=str(raw.get("source_id") or ""),
            source_name=str(raw.get("source_name") or ""),
            source_kind=source_kind,  # type: ignore[arg-type]
            item_key=str(raw.get("item_key") or ""),
            title=str(raw.get("title") or ""),
            url=str(raw.get("url") or ""),
            published_at=str(raw["published_at"]) if raw.get("published_at") else None,
            fetched_at=str(raw.get("fetched_at") or now_iso()),
            summary=str(raw.get("summary") or ""),
            key_points=[
                str(item).strip() for item in (raw.get("key_points") or []) if str(item).strip()
            ],
            why_it_matters=str(raw.get("why_it_matters") or ""),
            suggested_tags=[
                str(item).strip() for item in (raw.get("suggested_tags") or []) if str(item).strip()
            ],
            confidence=confidence,  # type: ignore[arg-type]
            content_excerpt=str(raw.get("content_excerpt") or ""),
            status=status,  # type: ignore[arg-type]
            note_draft_id=str(raw["note_draft_id"]) if raw.get("note_draft_id") else None,
            note_id=str(raw["note_id"]) if raw.get("note_id") else None,
            schema_version=schema_version,
            path=path,
        )

    @classmethod
    def from_file(cls, path: Path) -> RawInfo:
        data = json.loads(path.read_text("utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"invalid raw info file: {path}")
        return cls.from_dict(data, path=path)


class RawInfoStore:
    def __init__(self, root: Path):
        self.root = root

    def iter_paths(self) -> Iterator[Path]:
        if not self.root.exists():
            return iter(())
        return (path for path in self.root.glob("*.json") if path.is_file())

    def _iter_items(self) -> Iterator[RawInfo]:
        for path in self.iter_paths():
            try:
                yield RawInfo.from_file(path)
            except _UNREADABLE_ERRORS:
                continue

    def list(self) -> list[RawInfo]:
        out = list(self._iter_items())
        out.sort(key=lambda item: (item.fetched_at, _mtime_ns(item.path), item.id))
        return out

    def get(self, info_id: str) -> RawInfo | None:
        """Full id or unique prefix; raises :class:`AmbiguousIdError`."""
        path = resolve_id_path(self.iter_paths(), info_id, kind="raw info")
        if path is None:
            return None
        try:
            return RawInfo.from_file(path)
        except _UNREADABLE_ERRORS:
            return None

    def save(self, item: RawInfo) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / item.filename
        remove_stale_files(self.root, item.id, target, known=item.path)
        item.path = target
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(
            json.dumps(item.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(target)
        self._queue_sync(item)
        return target

    def pending_count(self) -> int:
        return sum(1 for item in self._iter_items() if item.is_pending)

    def item_keys(self) -> set[str]:
        """All stored item keys in one scan — callers checking many keys
        should use this instead of repeated :meth:`has_item_key`."""
        return {item.item_key for item in self._iter_items() if item.item_key}

    def has_item_key(self, item_key: str) -> bool:
        return any(item.item_key == item_key for item in self._iter_items())

    def _queue_sync(self, item: RawInfo) -> None:
        if item.path is None:
            return
        from knowlet.core.sync.tracked_files import (
            RAW_INFO_ENTITY_TYPE,
            infer_vault_root_from_digest_dir,
            queue_synced_json_if_authenticated,
        )

        vault_root = infer_vault_root_from_digest_dir(self.root)
        if vault_root is None:
            return
        queue_synced_json_if_authenticated(
            vault_root=vault_root,
            entity_type=RAW_INFO_ENTITY_TYPE,
            entity_id=item.path.name,
        )


def _mtime_ns(path: Path | None) -> int:
    if path is None:
        return 0
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0
