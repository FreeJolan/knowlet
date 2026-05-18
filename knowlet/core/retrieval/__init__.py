"""Retrieval v2 — Phase 3 Stage 1 "AI 底盘".

Layers on top of :class:`knowlet.core.index.Index` (which already
does FTS5 + dense-vector RRF fusion). v2 adds:

- :mod:`expansion`  — HyDE-style query expansion (off by default)
- :mod:`rerank`     — LLM re-ranking of the top-N candidates
- :mod:`chunking`   — Markdown-aware chunk splitting (used at index time)

Each module is small and import-safe (no LLM call at import time).
Callers decide when to invoke; default knowlet search path stays
on the existing :meth:`Index.search` pipeline.
"""

from __future__ import annotations
