"""Wikilink extraction + backlink resolution (M7.0.4).

`[[Title]]` is the wikilink syntax — chosen over `[[<ULID>]]` because
users type titles, not ULIDs, and titles are also what they see in the
editor. Title collisions are real but rare; when two Notes share a
title the backlink panel surfaces both as candidates and the user
disambiguates by clicking.

Sentence preview: a line containing a wikilink, trimmed to a window
around the match. We split paragraphs on `\\n` rather than running a
real sentence segmenter — Markdown is line-based, and a single line
is usually a single sentence or a list item, both of which read well
without further chopping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from knowlet.core.note import Note

# `[[anything but a closing bracket]]` — non-greedy, single-line. Pipe-style
# aliases (`[[Title|alias]]`) take the part before `|` as the target.
_WIKILINK_RE = re.compile(r"\[\[([^\[\]\n|]+?)(?:\|[^\[\]\n]+?)?\]\]")

# Trim the surrounding sentence so the panel doesn't render essays.
_PREVIEW_MAX = 240


@dataclass(frozen=True)
class Wikilink:
    """One `[[...]]` occurrence inside a body."""

    target: str  # raw target text — already stripped of the alias suffix
    line: int  # 1-based line number
    line_text: str  # the full line (untrimmed) the link appeared on


@dataclass(frozen=True)
class Backlink:
    """A reference *to* a target Note found in some other source Note."""

    source_id: str
    source_title: str
    target: str  # the wikilink target as written (case may differ from title)
    line: int
    sentence: str  # trimmed line, suitable for the panel


def extract_wikilinks(body: str) -> list[Wikilink]:
    """Return every `[[...]]` occurrence in `body`, in document order."""
    out: list[Wikilink] = []
    if not body:
        return out
    for line_no, line in enumerate(body.splitlines(), start=1):
        for m in _WIKILINK_RE.finditer(line):
            target = m.group(1).strip()
            if target:
                out.append(Wikilink(target=target, line=line_no, line_text=line))
    return out


def _normalize(s: str) -> str:
    """Backlink matching is case-insensitive and whitespace-collapsed.
    `[[ Attention is All You Need ]]` should still resolve to the Note
    titled `Attention is All You Need`."""
    return " ".join(s.split()).lower()


def _sentence_preview(line_text: str, target: str) -> str:
    """Trim `line_text` around the wikilink so the panel shows a focused
    snippet. If the line is short, return it as-is; otherwise window it."""
    line_text = line_text.strip()
    if len(line_text) <= _PREVIEW_MAX:
        return line_text
    needle = f"[[{target}"
    idx = line_text.lower().find(needle.lower())
    if idx < 0:
        return line_text[: _PREVIEW_MAX] + "…"
    half = _PREVIEW_MAX // 2
    start = max(0, idx - half)
    end = min(len(line_text), idx + half)
    snippet = line_text[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(line_text):
        snippet = snippet + "…"
    return snippet


def find_backlinks(
    target_title: str,
    sources: Iterable[Path],
    *,
    exclude_id: str | None = None,
) -> list[Backlink]:
    """Scan every source path, return backlinks pointing at `target_title`
    (case-insensitive, whitespace-collapsed match). `exclude_id` skips a
    source whose Note id equals it — typically the target itself, since a
    Note rarely benefits from "you reference yourself" hits."""
    target_norm = _normalize(target_title)
    if not target_norm:
        return []
    out: list[Backlink] = []
    for path in sources:
        try:
            note = Note.from_file(path)
        except Exception:
            # A malformed note shouldn't break the whole panel. Caller
            # already filtered to valid `.md` files via iter_note_paths.
            continue
        if exclude_id is not None and note.id == exclude_id:
            continue
        for w in extract_wikilinks(note.body):
            if _normalize(w.target) == target_norm:
                out.append(
                    Backlink(
                        source_id=note.id,
                        source_title=note.title,
                        target=w.target,
                        line=w.line,
                        sentence=_sentence_preview(w.line_text, w.target),
                    )
                )
    # Stable sort: source title, then line — easy to scan in the panel.
    out.sort(key=lambda b: (b.source_title.lower(), b.line))
    return out
