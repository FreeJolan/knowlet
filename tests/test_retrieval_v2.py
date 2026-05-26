"""Tests for Retrieval v2 (Phase 3 Stage 1 — AI 底盘).

- expansion.expand_query_hyde + fuse_rrf
- rerank.llm_rerank + _parse_scores
- chunking.smart_chunk_markdown
"""

from __future__ import annotations

from typing import Any

import pytest

from knowlet.config import LLMConfig
from knowlet.core.index import SearchHit
from knowlet.core.llm import AssistantMessage
from knowlet.core.retrieval.chunking import smart_chunk_markdown
from knowlet.core.retrieval.expansion import (
    DEFAULT_RRF_K,
    expand_query_hyde,
    fuse_rrf,
)
from knowlet.core.retrieval.rerank import _parse_scores, llm_rerank

# ----------------------------------------------- fake LLMClient


class _FakeLLM:
    """LLMClient stand-in: returns canned text, records the last call."""

    def __init__(self, content: str = "fake response") -> None:
        self.content = content
        self.calls: list[dict[str, Any]] = []
        # Match LLMClient attrs the rerank module reads.
        self.audit_store = None

    def chat(self, *, messages, role=None, max_tokens=None, **_kw):
        self.calls.append({
            "messages": messages,
            "role": role,
            "max_tokens": max_tokens,
        })
        return AssistantMessage(content=self.content)


def _hit(note_id: str, score: float = 1.0) -> SearchHit:
    return SearchHit(
        note_id=note_id,
        title=f"Title {note_id}",
        path=f"{note_id}.md",
        snippet=f"snippet for {note_id}",
        chunk_position=0,
        score=score,
    )


# ----------------------------------------------- expansion.expand_query_hyde


def test_hyde_returns_llm_text() -> None:
    llm = _FakeLLM(content="Hypothetical answer paragraph here.")
    out = expand_query_hyde("what is RAG?", llm)  # type: ignore[arg-type]
    assert out == "Hypothetical answer paragraph here."
    assert len(llm.calls) == 1
    assert llm.calls[0]["role"] == "search_booster"


def test_hyde_empty_query_short_circuits() -> None:
    llm = _FakeLLM()
    assert expand_query_hyde("", llm) == ""  # type: ignore[arg-type]
    assert len(llm.calls) == 0


def test_hyde_falls_back_on_llm_error() -> None:
    class _BoomLLM:
        audit_store = None

        def chat(self, **_kw):
            raise RuntimeError("upstream down")

    out = expand_query_hyde("real query", _BoomLLM())  # type: ignore[arg-type]
    assert out == "real query"  # graceful fallback


# ----------------------------------------------- expansion.fuse_rrf


def test_fuse_rrf_combines_two_rankings() -> None:
    a = [_hit("n1"), _hit("n2"), _hit("n3")]
    b = [_hit("n3"), _hit("n1"), _hit("n4")]
    fused = fuse_rrf([a, b], top_k=4)
    # n1 (1, 2) and n3 (3, 1) should top the list — each appears in
    # both rankings at high positions.
    ids = [h.note_id for h in fused]
    assert ids[:2] == ["n1", "n3"] or ids[:2] == ["n3", "n1"]
    assert set(ids) == {"n1", "n2", "n3", "n4"}


def test_fuse_rrf_preserves_metadata() -> None:
    hit_with_title = SearchHit("n1", "Special Title", "n1.md", "x", 0, 0.5)
    fused = fuse_rrf([[hit_with_title]], top_k=1)
    assert fused[0].title == "Special Title"


def test_fuse_rrf_default_k_matches_index() -> None:
    """The fuse default rrf_k must match the value Index.search uses."""
    assert DEFAULT_RRF_K == 60


def test_fuse_rrf_top_k_limits_output() -> None:
    a = [_hit(f"n{i}") for i in range(10)]
    fused = fuse_rrf([a], top_k=3)
    assert len(fused) == 3


# ----------------------------------------------- rerank.llm_rerank


def _cfg(rerank_model: str = "") -> LLMConfig:
    return LLMConfig(
        base_url="http://fake",
        api_key="fake",
        model="main-model",
        rerank_model=rerank_model,
    )


def test_rerank_reorders_by_llm_scores() -> None:
    hits = [_hit("a", 0.1), _hit("b", 0.2), _hit("c", 0.3)]
    # LLM thinks "b" is most relevant.
    llm = _FakeLLM(
        content='[{"id":0,"score":0.1},{"id":1,"score":0.95},{"id":2,"score":0.4}]'
    )
    reranked = llm_rerank(
        "query", hits, llm=llm, cfg=_cfg()  # type: ignore[arg-type]
    )
    assert reranked[0].note_id == "b"
    assert reranked[0].score == pytest.approx(0.95)


def test_rerank_falls_back_on_bad_json() -> None:
    hits = [_hit("a"), _hit("b")]
    llm = _FakeLLM(content="not JSON at all")
    reranked = llm_rerank(
        "q", hits, llm=llm, cfg=_cfg()  # type: ignore[arg-type]
    )
    # Returns original order unchanged.
    assert [h.note_id for h in reranked] == ["a", "b"]


def test_rerank_handles_missing_ids() -> None:
    """LLM forgets to score some candidates → they keep original score and
    don't get dropped from results. Realistic original scores are RRF-fused
    values around 0.01-0.05, well below LLM's 0..1 judgments."""
    hits = [
        _hit("a", score=0.03),
        _hit("b", score=0.02),
        _hit("c", score=0.01),
    ]
    llm = _FakeLLM(content='[{"id":1,"score":0.9}]')  # only b scored
    reranked = llm_rerank(
        "q", hits, llm=llm, cfg=_cfg()  # type: ignore[arg-type]
    )
    ids = [h.note_id for h in reranked]
    # b's new score (0.9) wins; a and c keep their original (small) scores
    # but are still present in the result.
    assert set(ids) == {"a", "b", "c"}
    assert ids[0] == "b"


def test_rerank_with_one_or_zero_hits_is_noop() -> None:
    llm = _FakeLLM()
    assert llm_rerank("q", [], llm=llm, cfg=_cfg()) == []  # type: ignore[arg-type]
    one = [_hit("a")]
    assert llm_rerank(  # type: ignore[arg-type]
        "q", one, llm=llm, cfg=_cfg()
    ) == one
    assert len(llm.calls) == 0  # no LLM call made


def test_rerank_uses_separate_rerank_model_when_configured() -> None:
    """When rerank_model is set, a fresh LLMClient is constructed for
    the rerank call. The original ``llm`` should not see the call."""
    hits = [_hit("a"), _hit("b")]
    llm = _FakeLLM(content='[{"id":0,"score":0.9},{"id":1,"score":0.1}]')
    cfg = _cfg(rerank_model="gpt-5.4-mini")
    # Patch the rerank module's LLMClient constructor so we observe
    # the model it would use without actually building a real client.
    from knowlet.core.retrieval import rerank as rerank_mod

    captured: dict[str, Any] = {}

    class _CapturedClient:
        audit_store = None

        def __init__(self, cfg, audit_store=None):
            captured["model"] = cfg.model
            captured["base_url"] = cfg.base_url

        def chat(self, **_kw):
            return AssistantMessage(content=llm.content)

    orig = rerank_mod.LLMClient
    rerank_mod.LLMClient = _CapturedClient  # type: ignore[misc]
    try:
        llm_rerank(
            "q", hits, llm=llm, cfg=cfg  # type: ignore[arg-type]
        )
    finally:
        rerank_mod.LLMClient = orig  # type: ignore[misc]
    assert captured["model"] == "gpt-5.4-mini"


def test_parse_scores_handles_code_fence() -> None:
    payload = "```json\n[{\"id\":0,\"score\":0.5}]\n```"
    assert _parse_scores(payload) == [(0, 0.5)]


def test_parse_scores_bare_array() -> None:
    assert _parse_scores('[{"id":2,"score":1.0}]') == [(2, 1.0)]


def test_parse_scores_invalid_returns_empty() -> None:
    assert _parse_scores("hello") == []
    assert _parse_scores('{"not": "array"}') == []


# ----------------------------------------------- chunking.smart_chunk_markdown


def test_smart_chunk_empty() -> None:
    assert smart_chunk_markdown("") == []
    assert smart_chunk_markdown("   \n  \n") == []


def test_smart_chunk_small_text_one_chunk() -> None:
    chunks = smart_chunk_markdown("Just a short paragraph.", size=500)
    assert len(chunks) == 1
    assert "Just a short paragraph" in chunks[0].text


def test_smart_chunk_splits_on_headers() -> None:
    body = (
        "# Title\n\nIntro paragraph.\n\n"
        "## Section A\n\nDetails about A.\n\n"
        "## Section B\n\nDetails about B.\n"
    )
    chunks = smart_chunk_markdown(body, size=500)
    # Each header section becomes its own chunk (they're all <500 chars).
    texts = [c.text for c in chunks]
    assert any("Section A" in t for t in texts)
    assert any("Section B" in t for t in texts)
    # Title content is in a chunk too (header preserved per strip_headers=False).
    assert any("Title" in t for t in texts) or any("Intro" in t for t in texts)


def test_smart_chunk_oversized_section_split_further() -> None:
    long = "Sentence. " * 200  # ~2000 chars
    body = f"## Big section\n\n{long}"
    chunks = smart_chunk_markdown(body, size=500, overlap=50)
    assert len(chunks) >= 2
    # All chunk positions sequential.
    assert [c.position for c in chunks] == list(range(len(chunks)))


def test_smart_chunk_plain_text_no_headers() -> None:
    """Body with no Markdown headers should still chunk cleanly."""
    body = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
    chunks = smart_chunk_markdown(body, size=500)
    assert len(chunks) >= 1
    # All content present.
    joined = " ".join(c.text for c in chunks)
    assert "Paragraph one" in joined
    assert "Paragraph three" in joined


def test_smart_chunk_validates_args() -> None:
    with pytest.raises(ValueError):
        smart_chunk_markdown("x", size=0)
    with pytest.raises(ValueError):
        smart_chunk_markdown("x", size=10, overlap=20)
