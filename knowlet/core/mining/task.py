"""MiningTask — a "knowledge mining" recipe stored at `<vault>/tasks/<id>-<slug>.md`.

Frontmatter shape (canonical):

    ---
    id: 01HX...
    name: "AI papers daily"
    enabled: true
    schedule:
      every: "1h"            # interval mode; or omit and use `cron:` instead
      # cron: "0 9 * * *"    # standard 5-field cron expression
    sources:
      - rss: "https://arxiv.org/rss/cs.AI"
      - url: "https://example.com/somewhere"
    prompt: |
      Summarize each item in 2-3 sentences ...
    created_at: 2026-05-01T00:00:00Z
    updated_at: 2026-05-01T00:00:00Z
    ---
    Optional free-form notes about why this task exists (Markdown body).

Per ADR-0009 the file is user-editable. Schedule + sources + prompt are the
contract; everything else is decoration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import frontmatter

from knowlet.core.note import new_id, now_iso, slugify


@dataclass
class SourceSpec:
    """A single source line in a mining task."""

    type: str  # "rss" | "url"
    url: str

    @classmethod
    def parse(cls, raw: dict[str, Any] | str) -> SourceSpec:
        if isinstance(raw, str):
            return cls(type="url", url=raw)
        if not isinstance(raw, dict):
            raise ValueError(f"invalid source spec: {raw!r}")
        if "rss" in raw:
            return cls(type="rss", url=str(raw["rss"]))
        if "url" in raw:
            return cls(type="url", url=str(raw["url"]))
        raise ValueError(f"source must have rss: or url:; got {raw!r}")

    def to_payload(self) -> dict[str, str]:
        return {self.type: self.url}


@dataclass
class Schedule:
    """When the scheduler should fire this task."""

    every: str | None = None  # "1h", "30m", "2d", "45s"
    cron: str | None = None  # "0 9 * * *"

    def to_payload(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if self.every:
            out["every"] = self.every
        if self.cron:
            out["cron"] = self.cron
        return out

    @classmethod
    def parse(cls, raw: dict[str, Any] | None) -> Schedule:
        if not raw:
            return cls()
        return cls(every=raw.get("every"), cron=raw.get("cron"))

    def interval_seconds(self) -> int | None:
        """Return the interval in seconds if `every` is set, else None."""
        if not self.every:
            return None
        return parse_interval_seconds(self.every)


_INTERVAL_RE = re.compile(r"^\s*(\d+)\s*([smhd])\s*$", re.IGNORECASE)
_INTERVAL_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_interval_seconds(spec: str) -> int:
    m = _INTERVAL_RE.match(spec)
    if not m:
        raise ValueError(
            f"invalid interval {spec!r}; expected like '30s' / '15m' / '2h' / '1d'"
        )
    return int(m.group(1)) * _INTERVAL_UNITS[m.group(2).lower()]


@dataclass
class MiningTask:
    id: str = field(default_factory=new_id)
    name: str = ""
    enabled: bool = True
    schedule: Schedule = field(default_factory=Schedule)
    sources: list[SourceSpec] = field(default_factory=list)
    prompt: str = ""
    output_language: str | None = None  # "en" | "zh" | None → fall back to cfg.general.language
    # Hard ceiling on new items processed per run. Without this, a daemon
    # offline for N days then waking up hits the entire backlog at once and
    # generates an unbounded number of LLM calls (a real risk for active RSS
    # feeds). 50 is a default that fits "I'm catching up after a weekend"
    # without blowing through a token budget. None disables the cap (caller
    # opts in to unlimited explicitly).
    max_items_per_run: int | None = 50
    body: str = ""  # free-form Markdown description
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    path: Path | None = None

    @property
    def slug(self) -> str:
        return slugify(self.name) if self.name else "task"

    @property
    def filename(self) -> str:
        return f"{self.id}-{self.slug}.md"

    def to_markdown(self) -> str:
        meta: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "schedule": self.schedule.to_payload(),
            "sources": [s.to_payload() for s in self.sources],
            "prompt": self.prompt,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.output_language:
            meta["output_language"] = self.output_language
        if self.max_items_per_run is not None:
            meta["max_items_per_run"] = self.max_items_per_run
        post = frontmatter.Post(self.body, **meta)
        return frontmatter.dumps(post)

    @classmethod
    def from_file(cls, path: Path) -> MiningTask:
        with path.open("r", encoding="utf-8") as f:
            post = frontmatter.load(f)
        meta = post.metadata
        sources_raw = meta.get("sources") or []
        sources = [SourceSpec.parse(s) for s in sources_raw]
        ol_raw = meta.get("output_language")
        cap_raw = meta.get("max_items_per_run")
        if cap_raw is None:
            cap = 50  # match dataclass default for tasks written before the field existed
        else:
            try:
                cap = int(cap_raw)
            except (TypeError, ValueError):
                cap = 50
        return cls(
            id=str(meta.get("id") or new_id()),
            name=str(meta.get("name") or path.stem),
            enabled=bool(meta.get("enabled", True)),
            schedule=Schedule.parse(meta.get("schedule")),
            sources=sources,
            prompt=str(meta.get("prompt") or ""),
            output_language=str(ol_raw) if ol_raw else None,
            max_items_per_run=cap,
            body=post.content,
            created_at=str(meta.get("created_at") or now_iso()),
            updated_at=str(meta.get("updated_at") or now_iso()),
            path=path,
        )

    def validate(self) -> list[str]:
        """Return a list of human-readable problems; empty list = ok."""
        problems: list[str] = []
        if not self.name:
            problems.append("name is empty")
        if not self.sources:
            problems.append("at least one source is required")
        if not self.prompt.strip():
            problems.append("prompt is empty")
        if self.schedule.every and self.schedule.cron:
            problems.append("schedule cannot have both `every` and `cron`")
        if self.schedule.every:
            try:
                parse_interval_seconds(self.schedule.every)
            except ValueError as exc:
                problems.append(str(exc))
        return problems
