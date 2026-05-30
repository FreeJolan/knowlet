"""HyDE-style query expansion.

HyDE (Hypothetical Document Embeddings) lifts retrieval recall on
sparse queries by asking the LLM to **write a plausible answer
paragraph first**, then searching with that text (which embeds much
closer to real notes than the original 5-word question).

Cost: one extra LLM call per search → latency + token spend. So
this is **off by default** — turn on per-call from a UI / settings
toggle, or when chat latency is acceptable.

Pipeline (caller side):
1. ``hypothetical = expand_query_hyde(query, llm)``
2. ``hits_a = index.search(query)``        # FTS-strong on keywords
3. ``hits_b = index.search(hypothetical)`` # vector-strong on intent
4. ``fused = fuse_rrf([hits_a, hits_b])``  # combine via RRF

Why split it this way (instead of one-shot inside ``Index.search``):
keeping :class:`Index` LLM-free preserves "search must work offline"
as a property. Expansion is an *optional* AI booster.
"""

from __future__ import annotations

from collections.abc import Iterable

from knowlet.core.index import SearchHit
from knowlet.core.llm import LLMClient

# Match the rrf_k used inside ``Index.search`` so fused ranks live on
# the same scale as raw search hits.
DEFAULT_RRF_K = 60

_HYDE_PROMPT = (
    "Write a single paragraph (max 150 words) that would directly "
    "answer the question below, written in the same language as the "
    "question, as if you were a knowledgeable person with first-hand "
    "experience. Do not refuse, do not hedge — make a plausible "
    "attempt even if details have to be inferred. Output ONLY the "
    "paragraph, no preamble.\n\n"
    "Question: {query}"
)


def expand_query_hyde(
    query: str,
    llm: LLMClient,
    *,
    max_tokens: int = 400,
) -> str:
    """Generate one hypothetical-answer paragraph for ``query``.

    Returns plain text (not an embedding). The caller passes it as
    the new "query" argument to :meth:`Index.search`, which embeds
    + FTS-tokenizes it itself.

    On any LLM failure, falls back to the original query string —
    HyDE is an *optional* booster; never let it break search.
    """
    q = (query or "").strip()
    if not q:
        return q
    try:
        result = llm.chat(
            messages=[{"role": "user", "content": _HYDE_PROMPT.format(query=q)}],
            role="search_booster",
            max_tokens=max_tokens,
        )
        text = (result.content or "").strip()
        return text if text else q
    except Exception:
        # Network / auth / quota — degrade gracefully to baseline search.
        return q


def fuse_rrf(
    rankings: Iterable[list[SearchHit]],
    *,
    rrf_k: int = DEFAULT_RRF_K,
    top_k: int = 5,
) -> list[SearchHit]:
    """Reciprocal Rank Fusion across multiple :class:`SearchHit` lists.

    Each input list is a ranking (already in descending-score order).
    Fuses across lists by note_id, keeps the first-seen SearchHit's
    metadata (title / snippet / etc.) for each note, and returns the
    top ``top_k`` by fused score.

    This is the same RRF formula that lives inside ``Index.search``,
    pulled out so callers can fuse across **independent** searches
    (e.g., original query + HyDE expansion + per-section variants)
    without re-implementing it. Same default ``rrf_k=60`` as the
    Cormack-et-al-2009 paper recommendation.
    """
    fused_score: dict[str, float] = {}
    first_seen: dict[str, SearchHit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            fused_score[hit.note_id] = fused_score.get(hit.note_id, 0.0) + 1.0 / (rrf_k + rank)
            first_seen.setdefault(hit.note_id, hit)
    ordered = sorted(fused_score.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    out: list[SearchHit] = []
    for note_id, score in ordered:
        base = first_seen[note_id]
        # Re-stamp the fused score so callers see the combined number,
        # not the per-ranking sub-score.
        out.append(
            SearchHit(
                note_id=base.note_id,
                title=base.title,
                path=base.path,
                snippet=base.snippet,
                chunk_position=base.chunk_position,
                score=round(score, 6),
            )
        )
    return out
