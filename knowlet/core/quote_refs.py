"""Quote-reference helpers for M7.1 (selection → chat capsule).

Per ADR-0015, the user selects a passage in a Note and attaches it as a
"capsule" to the chat input. When the message is sent, each capsule is
expanded into a structured block fed to the LLM:

    我想就这段问你:
    > {quote_text}

    (为给你上下文,这段所在的标题节是:)
    > {enclosing_section}

The enclosing section is computed at *send time* (not stored on the
capsule) so it stays in sync with the latest Note body. Capsule itself
holds {note_id, note_title, quote_text, paragraph_anchor}.

Module is pure-string in/out — no I/O. The web layer fetches Note bodies
and injects them; tests can run without filesystem.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Per-capsule cap on the enclosing-section block fed to the LLM. 1500
# chars ≈ 400 tokens; 5 capsules max → ≈ 2000 tokens of ambient context,
# well below any reasonable LLM window. Adjustable via a future config
# knob if dogfooding shows it bites.
MAX_SECTION_CHARS = 1500

# How many capsules a single message can carry (ADR-0015 §2). The web
# layer truncates silently past this — frontend should also enforce it
# with a friendlier toast.
MAX_REFERENCES = 5

# Heading detector — markdown ATX headings only (the only kind knowlet
# Notes use, per ADR-0011 §3 prose-note styling).
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class QuoteRef:
    """One capsule. Two flavors per ADR-0016 §2:

    - `source = "note"` (M7.1 default): a quote pulled from a Note, with
      paragraph_anchor for fuzzy re-locate after edits. The web layer
      fetches the Note body and runs `extract_enclosing_section` at send
      time so the LLM sees the structural backdrop.
    - `source = "url"` (M7.2): the user pasted a URL, the backend
      fetched + summarized it. quote_text holds the summary; source_url
      is the original page. No vault lookup, no enclosing section —
      summary is already the context.
    """

    note_id: str
    note_title: str
    quote_text: str
    paragraph_anchor: str  # first ~64 normalized chars of the quote's paragraph
    source: str = "note"  # "note" | "url"
    source_url: str = ""  # populated when source == "url"


def normalize_anchor(text: str) -> str:
    """Anchor = first 64 chars of the paragraph, lowercased + whitespace
    collapsed. Used for fuzzy re-locate when an edit displaces the exact
    quote string."""
    collapsed = " ".join((text or "").split())
    return collapsed[:64].lower()


def _locate_quote(body: str, ref: QuoteRef) -> int | None:
    """Return the character offset of `ref.quote_text` in `body`, or None
    if both exact and anchor-based fuzzy match fail.

    Strategy:
    1. Exact `find()` on the literal quote_text — wins in the common case.
    2. Whitespace-collapsed search (handles the user editing intra-quote
       whitespace without changing words).
    3. Anchor-based fuzzy: find a paragraph whose first 64 normalized
       chars match ref.paragraph_anchor, return that paragraph's offset.
    """
    if not body or not ref.quote_text:
        return None

    # 1. Exact
    idx = body.find(ref.quote_text)
    if idx >= 0:
        return idx

    # 2. Collapsed whitespace — always try, even if the input was already
    # single-line. The body may have line-wrapped text that the user's
    # selection collapsed (PDF / browser copy often does this).
    collapsed_quote = " ".join(ref.quote_text.split())
    if collapsed_quote:
        parts = [re.escape(p) for p in collapsed_quote.split(" ") if p]
        if parts:
            rx = re.compile(r"\s+".join(parts))
            m = rx.search(body)
            if m:
                return m.start()

    # 3. Anchor-based fuzzy
    anchor = ref.paragraph_anchor
    if anchor:
        # Walk paragraphs (\n\n-separated chunks) and look for one whose
        # leading normalized text matches the anchor.
        offset = 0
        for para in re.split(r"\n\s*\n", body):
            head = normalize_anchor(para)
            if head and head.startswith(anchor[:32]):  # 32 chars is enough signal
                return offset
            offset += len(para) + 2  # rough: paragraphs separated by "\n\n"
    return None


def extract_enclosing_section(body: str, ref: QuoteRef) -> str:
    """Return the markdown section enclosing the quote, capped at
    MAX_SECTION_CHARS. If the quote can't be located at all, return a
    degraded "(原文已变更)" marker so the LLM knows the context is stale.

    Algorithm:
    1. Locate the quote offset in `body`.
    2. From that offset, walk backwards to the nearest ATX heading
       (`#…######`). The "section" runs from that heading up to the
       next heading of the same or higher level.
    3. If no heading exists at all → fall back to the whole Note,
       windowed at MAX_SECTION_CHARS around the quote.
    4. If section length > MAX_SECTION_CHARS → window around the quote
       (half before, half after) with ellipses on the boundaries.
    """
    if not body:
        return ""

    quote_offset = _locate_quote(body, ref)
    if quote_offset is None:
        return f"(原文已变更,无法定位:{ref.quote_text[:60]}…)"

    # Find the nearest heading whose START offset <= quote_offset.
    headings = list(_HEADING_RE.finditer(body))
    above = [m for m in headings if m.start() <= quote_offset]

    if not above:
        # No heading above → take the whole Note, windowed at the quote.
        return _window_around(body, quote_offset, len(ref.quote_text))

    cur = above[-1]
    cur_level = len(cur.group(1))
    section_start = cur.start()

    # Find next heading of same-or-higher level after `cur`.
    section_end = len(body)
    for m in headings:
        if m.start() <= cur.start():
            continue
        if len(m.group(1)) <= cur_level:
            section_end = m.start()
            break

    section = body[section_start:section_end].rstrip()
    if len(section) <= MAX_SECTION_CHARS:
        return section

    # Section too long → window around the quote with ellipses.
    return _window_around(body, quote_offset, len(ref.quote_text))


def _window_around(body: str, quote_offset: int, quote_len: int) -> str:
    """Return a quote-centered window of the body, capped at
    MAX_SECTION_CHARS. The split is half before / quote / half after, so
    the LLM sees the immediate ambient context on both sides."""
    if len(body) <= MAX_SECTION_CHARS:
        return body
    half = (MAX_SECTION_CHARS - quote_len) // 2
    start = max(0, quote_offset - max(half, 0))
    end = min(len(body), quote_offset + quote_len + max(half, 0))
    snippet = body[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(body):
        snippet = snippet + "…"
    return snippet


def format_references_block(refs_with_bodies: list[tuple[QuoteRef, str]]) -> str:
    """Compose the LLM-facing prompt prefix for one or more capsules.

    `refs_with_bodies` is a list of (capsule, current Note body) pairs
    — the web layer is responsible for fetching the body via vault, so
    this function stays pure-string and trivially testable.

    Empty input → empty string (caller passes user text through as-is).
    """
    if not refs_with_bodies:
        return ""

    blocks: list[str] = []
    for ref, body in refs_with_bodies:
        # Both branches build the same blockquote-rendered quote.
        quote_md = "\n".join(f"> {ln}" for ln in (ref.quote_text or "").splitlines())

        if ref.source == "url":
            # M7.2: URL capsule. quote_text is already the LLM-produced
            # summary; we don't run extract_enclosing_section. The URL is
            # surfaced so the chat-side LLM can mention / cite it.
            url_disp = ref.source_url or ""
            blocks.append(
                f"我想就这篇文章问你(来自《{ref.note_title}》· {url_disp}):\n"
                f"{quote_md}"
            )
        else:
            # M7.1: Note-source capsule. Pull the heading-bounded section
            # around the quote so the chat-side LLM sees structural context.
            section = extract_enclosing_section(body, ref)
            section_md = "\n".join(f"> {ln}" for ln in (section or "").splitlines())
            blocks.append(
                f"我想就这段问你(来自笔记《{ref.note_title}》):\n"
                f"{quote_md}\n\n"
                f"(为给你上下文,这段所在的标题节是:)\n"
                f"{section_md}"
            )
    return "\n\n———————————————\n\n".join(blocks) + "\n\n———————————————\n\n"
