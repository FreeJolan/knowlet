"""Phase 1 C polish — inline `#tag` syntax extraction.

Per dogfood feedback (2026-05-08), editing YAML frontmatter to add a
tag is too geeky for the target user. The chip-strip UI in NoteView
solves part of that, but power users prefer Bear-style inline `#tag`.

This module gives both `vault.write_note` callers and the
`PUT /api/notes/{id}` endpoint a one-liner: scan the body for `#tag`
patterns and merge them additively into the note's frontmatter `tags`
list. Frontmatter remains the canonical source — body `#tag` is just
a low-friction way to add to it.
"""

from __future__ import annotations

import re

# `(?<!\w)#([\w\-/]+)(?!\w)` —
#   - negative lookbehind: # cannot follow a word char (so `foo#bar`
#     doesn't match)
#   - capture: word chars (Unicode-aware in Python 3, matches CJK), `-`,
#     `_`, `/`
#   - negative lookahead: stop at non-word boundary
# Markdown headings are `^# Title` — note the SPACE between `#` and the
# content. This regex requires no whitespace, so heading syntax is
# naturally excluded.
_INLINE_TAG_RE = re.compile(r"(?<!\w)#([\w\-/]+)(?!\w)", re.UNICODE)

# Strip fenced code blocks (``` ... ```) and inline code (`...`) before
# scanning — `#tag` inside code is verbatim text, not a tag mention.
_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")

# `#…` literals in technical prose that are not tags:
#   - pure numbers: issue / PR references ("fix #108", "(#1)"). Obsidian
#     likewise requires a tag to contain a non-digit character.
#   - hex colors: 3/6/8-digit CSS values ("#fff", "#ffffff", "#ffffff00").
#     4-digit (#RGBA) is deliberately NOT excluded — too many real words
#     (#cafe, #face, #dead …) would stop being tags.
_PURE_NUMBER_RE = re.compile(r"^\d+$")
_HEX_COLOR_RE = re.compile(r"^(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def _looks_like_tag(candidate: str) -> bool:
    """False for `#…` literals that are clearly not tags (issue
    numbers, hex color values)."""
    if _PURE_NUMBER_RE.match(candidate):
        return False
    return not _HEX_COLOR_RE.match(candidate)


def extract_inline_tags(body: str) -> list[str]:
    """Return unique `#tag` names found in body, in document order.

    Skips matches inside fenced code blocks (``` … ```) and inline
    code (`…`). Tags are returned without the leading `#` and case is
    preserved (tags are user-typed identity strings)."""
    if not body:
        return []
    cleaned = _FENCED_CODE_RE.sub("", body)
    cleaned = _INLINE_CODE_RE.sub("", cleaned)
    seen: set[str] = set()
    out: list[str] = []
    for m in _INLINE_TAG_RE.finditer(cleaned):
        tag = m.group(1).strip()
        if tag and _looks_like_tag(tag) and tag.lower() not in seen:
            seen.add(tag.lower())
            out.append(tag)
    return out


def merge_with_inline_tags(
    explicit: list[str],
    body: str,
    *,
    previous_body: str | None = None,
) -> list[str]:
    """Return `explicit + (body_inline_tags - explicit)`, preserving the
    order of `explicit` (user's chip-strip order) followed by new
    body-derived tags. Case-insensitive dedup; original casing wins.

    Used at PUT /api/notes/{id} to make `#tag` typed in the body act
    like an additive tag-add. Frontmatter is the canonical source —
    this just lowers the friction for adding tags inline.

    ``previous_body``: the body as it was before this edit. When given,
    only inline tags that are NEW relative to it are merged in, so a
    tag the user removed from the chip strip is not re-added just
    because its ``#tag`` literal is still in the (unchanged) body.
    ``None`` keeps the purely additive behavior for callers that have
    no previous text.
    """
    out: list[str] = []
    seen: set[str] = set()
    for t in explicit:
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    inline = extract_inline_tags(body)
    if previous_body is not None:
        already_present = {t.lower() for t in extract_inline_tags(previous_body)}
        inline = [t for t in inline if t.lower() not in already_present]
    for t in inline:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out
