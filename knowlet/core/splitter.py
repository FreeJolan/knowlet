"""Sliding-window text splitter.

Operates on character count rather than tokens — sufficient for MVP and
language-agnostic (works for CN+EN mixed). Tries to break on paragraph
boundaries when possible.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Chunk:
    position: int
    text: str


def chunk_text(text: str, size: int = 500, overlap: int = 100) -> list[Chunk]:
    if size <= 0:
        raise ValueError("size must be > 0")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be in [0, size)")

    text = text.strip()
    if not text:
        return []

    if len(text) <= size:
        return [Chunk(position=0, text=text)]

    chunks: list[Chunk] = []
    step = size - overlap
    pos = 0
    idx = 0
    while pos < len(text):
        end = min(pos + size, len(text))
        # Prefer to end at a paragraph or sentence boundary inside the last 30% of the window.
        if end < len(text):
            window_start = pos + int(size * 0.7)
            best = -1
            for marker in ("\n\n", "\n", "。", ".", "!", "?", "!", "?"):
                found = text.rfind(marker, window_start, end)
                if found > best:
                    best = found + len(marker)
            if best > pos:
                end = best
        chunk = text[pos:end].strip()
        if chunk:
            chunks.append(Chunk(position=idx, text=chunk))
            idx += 1
        if end >= len(text):
            break
        pos = max(end - overlap, pos + 1)
    return chunks
