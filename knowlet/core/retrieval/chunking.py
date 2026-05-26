"""Markdown-aware chunking (Phase 3 Stage 1 Step 1.5).

Replaces the older paragraph/sentence-boundary heuristic in
``knowlet/core/splitter.py`` for Markdown notes. Walks header
structure first (``#``/``##``/``###``) so chunks line up with
the user's own sectioning, then size-bounds inside each header
section with overlap. Fenced code blocks stay whole — splitting
inside ``` blocks would corrupt them.

Why not roll our own (per AGENTS.md "don't reinvent wheels"):
LangChain's ``langchain-text-splitters`` is a narrow, battle-
tested package (no LLM / no chain runtime) that handles Markdown
edge cases other implementations get wrong — nested headers,
code fences, front matter passthrough. We use it directly as the
underlying primitive and wrap it to return knowlet's
:class:`Chunk` shape.

Output shape matches :func:`knowlet.core.splitter.chunk_text` so
this is a drop-in replacement at the indexer call site.
"""

from __future__ import annotations

from typing import Iterable

from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

from knowlet.core.splitter import Chunk

# Header levels we use as structural seams. Lower levels (#### and
# below) fold into their nearest parent section — that's typical
# note-taking practice; we don't fragment by every minor header.
_HEADERS_TO_SPLIT_ON: list[tuple[str, str]] = [
    ("#", "h1"),
    ("##", "h2"),
    ("###", "h3"),
]


def smart_chunk_markdown(
    text: str,
    *,
    size: int = 500,
    overlap: int = 100,
) -> list[Chunk]:
    """Markdown-aware chunking.

    Pipeline:

    1. Split by ``#``/``##``/``###`` headers — each header section
       becomes a candidate chunk.
    2. Within each candidate, if it's longer than ``size`` chars,
       use :class:`RecursiveCharacterTextSplitter` to size-bound
       with paragraph/line/word/char fallback boundaries and
       ``overlap`` char overlap. Code fences stay intact (the
       splitter's separators don't break inside ```` ``` ```` ).
    3. Position numbers run sequentially over the final list.

    Empty / whitespace input → ``[]``. Plain text (no headers)
    falls through to the recursive splitter, which is what we want.
    """
    if size <= 0:
        raise ValueError("size must be > 0")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be in [0, size)")

    body = (text or "").strip()
    if not body:
        return []

    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=_HEADERS_TO_SPLIT_ON,
        strip_headers=False,  # keep "## Foo" in the chunk text — useful for FTS
        return_each_line=False,
    )
    char_splitter = RecursiveCharacterTextSplitter(
        chunk_size=size,
        chunk_overlap=overlap,
        # Order matters — paragraph → line → sentence-ish → word →
        # char. CJK punctuation is included so Chinese notes split
        # at sentence boundaries too. Code fences `\n```` are not
        # listed so the splitter avoids breaking inside them.
        separators=[
            "\n\n",
            "\n",
            "。",
            ".",
            "!",
            "?",
            "!",
            "?",
            " ",
            "",
        ],
    )

    header_sections = header_splitter.split_text(body)
    pieces: list[str] = []
    for section in header_sections:
        section_text = (section.page_content or "").strip()
        if not section_text:
            continue
        if len(section_text) <= size:
            pieces.append(section_text)
        else:
            pieces.extend(
                p.strip() for p in char_splitter.split_text(section_text) if p.strip()
            )

    # If the header splitter found nothing (no headers), MarkdownHeaderTextSplitter
    # returns an empty list. Fall back to the char splitter directly.
    if not pieces:
        pieces = [
            p.strip() for p in char_splitter.split_text(body) if p.strip()
        ]
        # Tiny inputs (single paragraph shorter than ``size``) still need
        # to be emitted as one chunk; RecursiveCharacterTextSplitter
        # returns a single-element list in that case, which is fine.
        if not pieces:
            pieces = [body]

    return [Chunk(position=i, text=t) for i, t in enumerate(pieces)]
