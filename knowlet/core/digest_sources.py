"""Stage C v2 digest source configuration.

DigestSource is the user-facing configuration layer for information
intake. It deliberately supports only RSS/Atom feeds and model-driven
Prompt Sources; website subscriptions stay out of this surface.
"""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from knowlet.core.note import new_id, now_iso, slugify

DigestSourceKind = Literal["rss", "prompt"]
DigestPullStatus = Literal["idle", "ok", "error", "paused"]
DIGEST_SOURCE_SCHEMA_VERSION = 1


@dataclass
class DigestSource:
    name: str
    kind: DigestSourceKind
    id: str = field(default_factory=new_id)
    enabled: bool = True
    url: str | None = None
    prompt: str | None = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    last_pull_at: str | None = None
    last_success_at: str | None = None
    last_error: str | None = None
    pull_status: DigestPullStatus = "idle"
    schema_version: int = DIGEST_SOURCE_SCHEMA_VERSION
    path: Path | None = None

    @property
    def slug(self) -> str:
        return slugify(self.name) if self.name else "digest-source"

    @property
    def filename(self) -> str:
        return f"{self.id}-{self.slug}.json"

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not self.name.strip():
            problems.append("name is required")
        if self.kind not in ("rss", "prompt"):
            problems.append("kind must be rss or prompt")
        if self.kind == "rss":
            if not (self.url or "").strip():
                problems.append("RSS URL is required")
            elif not _is_http_url(str(self.url)):
                problems.append("RSS URL must be an http(s) URL")
        if self.kind == "prompt" and not (self.prompt or "").strip():
            problems.append("prompt is required")
        return problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": DIGEST_SOURCE_SCHEMA_VERSION,
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "enabled": self.enabled,
            "url": self.url if self.kind == "rss" else None,
            "prompt": self.prompt if self.kind == "prompt" else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_pull_at": self.last_pull_at,
            "last_success_at": self.last_success_at,
            "last_error": self.last_error,
            "pull_status": self.pull_status,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any], *, path: Path | None = None) -> DigestSource:
        try:
            schema_version = int(raw.get("schema_version") or 1)
        except (TypeError, ValueError):
            schema_version = 1
        kind = str(raw.get("kind") or "rss")
        if kind not in ("rss", "prompt"):
            kind = "rss"
        pull_status = str(raw.get("pull_status") or "idle")
        if pull_status not in ("idle", "ok", "error", "paused"):
            pull_status = "idle"
        return cls(
            id=str(raw.get("id") or new_id()),
            name=str(raw.get("name") or ""),
            kind=kind,  # type: ignore[arg-type]
            enabled=bool(raw.get("enabled", True)),
            url=str(raw["url"]) if raw.get("url") else None,
            prompt=str(raw["prompt"]) if raw.get("prompt") else None,
            created_at=str(raw.get("created_at") or now_iso()),
            updated_at=str(raw.get("updated_at") or now_iso()),
            last_pull_at=str(raw["last_pull_at"]) if raw.get("last_pull_at") else None,
            last_success_at=(str(raw["last_success_at"]) if raw.get("last_success_at") else None),
            last_error=str(raw["last_error"]) if raw.get("last_error") else None,
            pull_status=pull_status,  # type: ignore[arg-type]
            schema_version=schema_version,
            path=path,
        )

    @classmethod
    def from_file(cls, path: Path) -> DigestSource:
        data = json.loads(path.read_text("utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"invalid digest source file: {path}")
        return cls.from_dict(data, path=path)


class DigestSourceStore:
    def __init__(self, root: Path):
        self.root = root

    def iter_paths(self) -> Iterator[Path]:
        if not self.root.exists():
            return iter(())
        return (p for p in self.root.glob("*.json") if p.is_file())

    def list(self) -> list[DigestSource]:
        out: list[DigestSource] = []
        for path in self.iter_paths():
            try:
                out.append(DigestSource.from_file(path))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        out.sort(key=lambda s: (s.created_at, _mtime_ns(s.path), s.id))
        return out

    def get(self, source_id: str) -> DigestSource | None:
        for path in self.iter_paths():
            if path.stem.startswith(source_id):
                try:
                    return DigestSource.from_file(path)
                except (OSError, ValueError, json.JSONDecodeError):
                    return None
        return None

    def save(self, source: DigestSource) -> Path:
        problems = source.validate()
        if problems:
            raise ValueError("; ".join(problems))
        self.root.mkdir(parents=True, exist_ok=True)
        source.updated_at = now_iso()
        target = self.root / source.filename
        for path in self.iter_paths():
            if path.stem.startswith(source.id) and path.name != target.name:
                with contextlib.suppress(OSError):
                    os.unlink(path)
        source.path = target
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(
            json.dumps(source.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp.replace(target)
        return target

    def delete(self, source_id: str) -> bool:
        source = self.get(source_id)
        if source is None or source.path is None:
            return False
        os.unlink(source.path)
        return True


def _is_http_url(raw: str) -> bool:
    parsed = urlparse(raw.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _mtime_ns(path: Path | None) -> int:
    if path is None:
        return 0
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0
