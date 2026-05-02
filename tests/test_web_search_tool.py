"""Tests for the LLM-callable `web_search` and `fetch_url` tools."""

from pathlib import Path

import httpx
import pytest

from knowlet.config import KnowletConfig, WebSearchConfig
from knowlet.core.card_store import CardStore
from knowlet.core.drafts import DraftStore
from knowlet.core.embedding import make_backend
from knowlet.core.index import Index
from knowlet.core.mining.task_store import TaskStore
from knowlet.core.tools._registry import ToolContext
from knowlet.core.tools import fetch_url as fetch_url_tool
from knowlet.core.tools import web_search as web_search_tool
from knowlet.core.vault import Vault


def _ctx(tmp_path: Path, web_search_cfg: WebSearchConfig) -> ToolContext:
    """Build a minimal ToolContext for tool tests. No LLM, no real
    embedding backend (DummyBackend), just enough for the tool handler
    to read config + per_turn."""
    v = Vault(tmp_path)
    v.init_layout()
    cfg = KnowletConfig(web_search=web_search_cfg)
    cfg.embedding.backend = "dummy"
    backend = make_backend("dummy", "x", 16)
    cfg.embedding.dim = backend.dim
    idx = Index(v.db_path, backend)
    idx.connect()
    return ToolContext(
        vault=v,
        index=idx,
        config=cfg,
        cards=CardStore(v.cards_dir),
        tasks=TaskStore(v.tasks_dir),
        drafts=DraftStore(v.drafts_dir),
    )


# -------------------------------------------------- web_search tool


def test_web_search_returns_results_via_provider(tmp_path: Path, monkeypatch):
    """Happy path — DDG provider, faked response, tool returns the
    structured payload + decrements budget."""
    monkeypatch.setattr(
        httpx.Client, "get",
        lambda self, url, **kw: httpx.Response(
            200,
            json={
                "Heading": "Knowlet",
                "AbstractURL": "https://example.com/knowlet",
                "Abstract": "personal kb",
                "RelatedTopics": [],
            },
            request=httpx.Request("GET", url),
        ),
    )
    ctx = _ctx(tmp_path, WebSearchConfig())  # auto → DDG
    out = web_search_tool.TOOL.handler({"query": "knowlet"}, ctx)
    assert out["provider"] == "ddg"
    assert out["count"] == 1
    assert out["results"][0]["url"] == "https://example.com/knowlet"
    assert out["budget_remaining"] == 2  # max_per_turn=3, used 1
    # And the per_turn counter is updated.
    assert ctx.per_turn["web_search"] == 1


def test_web_search_empty_query_returns_error(tmp_path: Path):
    ctx = _ctx(tmp_path, WebSearchConfig())
    out = web_search_tool.TOOL.handler({"query": "  "}, ctx)
    assert "error" in out
    assert "empty" in out["error"]
    # Empty-query failure shouldn't burn a budget unit.
    assert ctx.per_turn.get("web_search", 0) == 0


def test_web_search_budget_exhausted_returns_error(tmp_path: Path):
    """At cap, the tool errors instead of calling the provider."""
    ctx = _ctx(tmp_path, WebSearchConfig(max_per_turn=2))
    ctx.per_turn["web_search"] = 2  # already at cap
    out = web_search_tool.TOOL.handler({"query": "ok"}, ctx)
    assert "budget" in out["error"]
    assert "2/2" in out["error"]


def test_web_search_unconfigured_provider_returns_error(tmp_path: Path):
    """Explicit provider="brave" without a key — tool returns a clear
    error so the LLM can ask the user to set the config."""
    cfg = WebSearchConfig(provider="brave")
    ctx = _ctx(tmp_path, cfg)
    out = web_search_tool.TOOL.handler({"query": "x"}, ctx)
    assert "not configured" in out["error"]
    assert "brave_api_key" in out["suggestion"] or "brave_api_key" in out["error"]


def test_web_search_unknown_provider_returns_error(tmp_path: Path):
    cfg = WebSearchConfig(provider="unknown")
    ctx = _ctx(tmp_path, cfg)
    out = web_search_tool.TOOL.handler({"query": "x"}, ctx)
    assert "error" in out


def test_web_search_provider_network_error_returns_error(tmp_path: Path, monkeypatch):
    def boom(self, url, **kw):
        raise httpx.ConnectError("dns failure")

    monkeypatch.setattr(httpx.Client, "get", boom)
    ctx = _ctx(tmp_path, WebSearchConfig())  # auto → DDG
    out = web_search_tool.TOOL.handler({"query": "x"}, ctx)
    assert "search failed" in out["error"]


# -------------------------------------------------- fetch_url tool


def test_fetch_url_extracts_body(tmp_path: Path, monkeypatch):
    html = (
        "<html><head><title>Test Article</title></head>"
        "<body><article><p>" + "main body content. " * 30 + "</p></article></body></html>"
    )

    def fake_get(self, url, **kw):
        return httpx.Response(200, text=html, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    ctx = _ctx(tmp_path, WebSearchConfig())
    out = fetch_url_tool.TOOL.handler({"url": "https://example.com/x"}, ctx)
    assert out["title"] == "Test Article"
    assert "main body content" in out["body"]
    assert out["truncated"] is False
    assert out["budget_remaining"] == 2
    assert ctx.per_turn["fetch_url"] == 1


def test_fetch_url_rejects_non_http(tmp_path: Path):
    ctx = _ctx(tmp_path, WebSearchConfig())
    out = fetch_url_tool.TOOL.handler({"url": "ftp://example.com"}, ctx)
    assert "error" in out
    assert ctx.per_turn.get("fetch_url", 0) == 0


def test_fetch_url_rejects_empty(tmp_path: Path):
    ctx = _ctx(tmp_path, WebSearchConfig())
    out = fetch_url_tool.TOOL.handler({"url": ""}, ctx)
    assert "empty" in out["error"]


def test_fetch_url_extraction_failure_returns_error(tmp_path: Path, monkeypatch):
    """JS-heavy / paywall page → trafilatura extracts < 80 chars → tool
    surfaces a clear error so the LLM tries another result."""
    monkeypatch.setattr(
        httpx.Client, "get",
        lambda self, url, **kw: httpx.Response(
            200,
            text="<html><body></body></html>",
            request=httpx.Request("GET", url),
        ),
    )
    ctx = _ctx(tmp_path, WebSearchConfig())
    out = fetch_url_tool.TOOL.handler({"url": "https://empty.example.com/"}, ctx)
    assert "extraction" in out["error"].lower()


def test_fetch_url_budget_exhausted(tmp_path: Path):
    ctx = _ctx(tmp_path, WebSearchConfig(max_per_turn=1))
    ctx.per_turn["fetch_url"] = 1
    out = fetch_url_tool.TOOL.handler({"url": "https://x"}, ctx)
    assert "budget" in out["error"]


def test_fetch_url_truncates_long_body(tmp_path: Path, monkeypatch):
    long_body = "abcde " * 2000  # ~12000 chars
    html = (
        f"<html><head><title>Long</title></head>"
        f"<body><article><p>{long_body}</p></article></body></html>"
    )
    monkeypatch.setattr(
        httpx.Client, "get",
        lambda self, url, **kw: httpx.Response(200, text=html, request=httpx.Request("GET", url)),
    )
    ctx = _ctx(tmp_path, WebSearchConfig())
    out = fetch_url_tool.TOOL.handler({"url": "https://long.example.com"}, ctx)
    assert out["truncated"] is True
    assert len(out["body"]) <= 6000


# -------------------------------------------------- per-turn isolation


def test_web_search_and_fetch_url_have_independent_budgets(tmp_path: Path, monkeypatch):
    """ADR-0017 §5: separate budgets so an answer that legitimately needs
    web_search + fetch_url + fetch_url isn't penalized by sharing a pool."""
    monkeypatch.setattr(
        httpx.Client, "get",
        lambda self, url, **kw: httpx.Response(
            200,
            json={"Heading": "X", "AbstractURL": "https://x", "Abstract": "x"},
            request=httpx.Request("GET", url),
        ),
    )
    ctx = _ctx(tmp_path, WebSearchConfig(max_per_turn=2))
    web_search_tool.TOOL.handler({"query": "x"}, ctx)
    web_search_tool.TOOL.handler({"query": "y"}, ctx)
    # web_search is at cap (2/2) but fetch_url has its own budget.
    assert ctx.per_turn["web_search"] == 2
    assert ctx.per_turn.get("fetch_url", 0) == 0
