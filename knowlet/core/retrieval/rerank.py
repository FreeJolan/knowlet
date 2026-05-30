"""LLM-based re-ranking of retrieval candidates.

Re-ranking with an LLM dramatically improves top-K precision when
the base retrieval gives reasonable recall but mixed precision —
which is the typical FTS+vector RRF outcome. We ask the LLM to
score each candidate snippet for relevance to the query, then sort.

knowlet stays vendor-neutral (OpenAI-compatible), so this module
does **not** call cohere/voyage rerank APIs. It uses the same
``LLMClient`` as everything else. To keep latency / cost
manageable, the user can configure a separate ``rerank_model``
(typically cheaper / faster — e.g. Haiku for rerank while Opus
answers chat). When unset, the main chat model is used.

This is a **pure function over ``list[SearchHit]``** — easy to
test without a real LLM by injecting a fake :class:`LLMClient`.
Always falls back to the original ranking on LLM error.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace

from knowlet.config import LLMConfig
from knowlet.core.index import SearchHit
from knowlet.core.llm import LLMClient

# Hard cap on candidates we ship to the LLM. Reranking 50 snippets
# burns tokens with diminishing returns; 20 is a sweet spot per the
# usual published RAG benchmarks.
_MAX_CANDIDATES = 20

# Each candidate's snippet is truncated before being sent to the LLM
# so a few oversized hits don't blow the context window.
_SNIPPET_TRUNC = 400

_RERANK_PROMPT = (
    "You are scoring search-result snippets for relevance to a query.\n"
    'Return a JSON array of objects: [{{"id": <int>, "score": <0..1>}}, ...]\n'
    "Score 1.0 = the snippet directly answers the query.\n"
    "Score 0.0 = unrelated. Score every candidate; do not skip any.\n"
    "Return ONLY the JSON array, no preamble.\n\n"
    "Query: {query}\n\n"
    "Candidates:\n{candidates}"
)


def _rerank_client(base: LLMClient, cfg: LLMConfig) -> LLMClient:
    """Return the LLMClient to use for the rerank call.

    If ``cfg.rerank_model`` is set, build a new LLMClient with the
    same base_url + api_key but the alternate model. Otherwise reuse
    the caller's client (audit store is preserved either way only
    when we reuse — the alternate-model client gets a fresh, audit-
    disabled wrapper to avoid double-counting).
    """
    if not cfg.rerank_model.strip() or cfg.rerank_model == cfg.model:
        return base
    alt_cfg = LLMConfig(
        base_url=cfg.base_url,
        api_key=cfg.api_key,
        model=cfg.rerank_model,
        max_tokens=cfg.max_tokens,
        temperature=cfg.temperature,
    )
    return LLMClient(alt_cfg, audit_store=base.audit_store)


def llm_rerank(
    query: str,
    hits: Sequence[SearchHit],
    *,
    llm: LLMClient,
    cfg: LLMConfig,
    top_k: int | None = None,
) -> list[SearchHit]:
    """Re-rank ``hits`` by LLM-judged relevance to ``query``.

    Returns a fresh list with the same SearchHit objects in new
    order (scores updated to the LLM's 0..1 judgment, rounded).
    Returns the original ``hits`` unchanged on any error — rerank
    is a best-effort enhancement, not a hard requirement.
    """
    candidates = list(hits[:_MAX_CANDIDATES])
    if len(candidates) < 2:
        return list(hits)  # nothing to reorder
    if not query.strip():
        return list(hits)

    block = "\n".join(
        f"[{i}] {h.title}\n     {h.snippet[:_SNIPPET_TRUNC]}" for i, h in enumerate(candidates)
    )
    prompt = _RERANK_PROMPT.format(query=query.strip(), candidates=block)

    try:
        client = _rerank_client(llm, cfg)
        result = client.chat(
            messages=[{"role": "user", "content": prompt}],
            role="search_booster",
            max_tokens=512,
        )
        scores = _parse_scores(result.content or "")
    except Exception:
        return list(hits)
    if not scores:
        return list(hits)

    rescored: list[SearchHit] = []
    seen: set[int] = set()
    for idx, sc in scores:
        if not 0 <= idx < len(candidates):
            continue
        if idx in seen:
            continue
        seen.add(idx)
        rescored.append(replace(candidates[idx], score=round(float(sc), 6)))
    # Any candidate the LLM forgot to score keeps its original spot at
    # the tail (with original score) so we never drop notes silently.
    for idx, hit in enumerate(candidates):
        if idx not in seen:
            rescored.append(hit)

    rescored.sort(key=lambda h: h.score, reverse=True)
    if top_k is not None:
        return rescored[:top_k]
    return rescored


def _parse_scores(content: str) -> list[tuple[int, float]]:
    """Pull a list of ``(id, score)`` pairs out of the LLM's response.

    Accepts the canonical ``[{"id": 0, "score": 0.9}, ...]`` shape.
    Tolerates a leading/trailing ``json`` code fence so we don't
    bounce when the model adds stylized formatting against
    instructions."""
    s = content.strip()
    if s.startswith("```"):
        # Strip fenced blocks: ```json\n[...]\n``` or ```\n[...]\n```
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[: -len("```")]
        s = s.strip()
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[tuple[int, float]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item["id"])
            score = float(item["score"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append((idx, score))
    return out
