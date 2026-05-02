"""Unit tests for `knowlet/core/web_search.py` (M7.5, ADR-0017)."""

import httpx
import pytest

from knowlet.config import WebSearchConfig
from knowlet.core.web_search import (
    BraveSearch,
    DDGInstantAnswer,
    SearxSearch,
    SearchResult,
    TavilySearch,
    WebSearchError,
    WebSearchUnconfigured,
    pick_provider,
)


# -------------------------------------------------- pick_provider


def test_pick_provider_auto_brave_when_key_set():
    cfg = WebSearchConfig(brave_api_key="bsa-xxx")
    p = pick_provider(cfg)
    assert p.name == "brave"


def test_pick_provider_auto_tavily_when_only_tavily_set():
    cfg = WebSearchConfig(tavily_api_key="tvly-xxx")
    assert pick_provider(cfg).name == "tavily"


def test_pick_provider_auto_searx_when_only_searx_url_set():
    cfg = WebSearchConfig(searx_url="https://searx.example.com/")
    assert pick_provider(cfg).name == "searx"


def test_pick_provider_auto_falls_back_to_ddg():
    cfg = WebSearchConfig()  # no keys, no urls
    assert pick_provider(cfg).name == "ddg"


def test_pick_provider_explicit_overrides_auto():
    """Even with brave_api_key set, explicit provider="ddg" wins."""
    cfg = WebSearchConfig(provider="ddg", brave_api_key="bsa-xxx")
    assert pick_provider(cfg).name == "ddg"


def test_pick_provider_explicit_brave_without_key_raises():
    cfg = WebSearchConfig(provider="brave")  # no key
    with pytest.raises(WebSearchUnconfigured):
        pick_provider(cfg)


def test_pick_provider_explicit_tavily_without_key_raises():
    cfg = WebSearchConfig(provider="tavily")
    with pytest.raises(WebSearchUnconfigured):
        pick_provider(cfg)


def test_pick_provider_explicit_searx_without_url_raises():
    cfg = WebSearchConfig(provider="searx")
    with pytest.raises(WebSearchUnconfigured):
        pick_provider(cfg)


def test_pick_provider_unknown_name_raises():
    cfg = WebSearchConfig(provider="bogus")
    with pytest.raises(WebSearchError):
        pick_provider(cfg)


# -------------------------------------------------- BraveSearch


def test_brave_parses_results(monkeypatch):
    payload = {
        "web": {
            "results": [
                {"title": "T1", "url": "https://a.example/", "description": "snippet 1"},
                {"title": "T2", "url": "https://b.example/", "description": "snippet 2"},
            ]
        }
    }

    def fake_get(self, url, params=None, headers=None, **kwargs):
        assert headers["X-Subscription-Token"] == "bsa-test"
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    out = BraveSearch("bsa-test").search("hello", top_k=2)
    assert len(out) == 2
    assert out[0] == SearchResult(title="T1", url="https://a.example/", snippet="snippet 1", rank=0)
    assert out[1].rank == 1


def test_brave_401_raises_unconfigured(monkeypatch):
    def fake_get(self, url, params=None, headers=None, **kwargs):
        return httpx.Response(401, text="unauthorized", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    with pytest.raises(WebSearchUnconfigured):
        BraveSearch("bsa-bad").search("x")


def test_brave_500_raises_generic(monkeypatch):
    def fake_get(self, url, params=None, headers=None, **kwargs):
        return httpx.Response(500, text="server error", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    with pytest.raises(WebSearchError):
        BraveSearch("bsa-x").search("x")


def test_brave_skips_results_without_url(monkeypatch):
    payload = {
        "web": {
            "results": [
                {"title": "no url", "description": "skip"},
                {"title": "ok", "url": "https://x", "description": "kept"},
            ]
        }
    }
    monkeypatch.setattr(
        httpx.Client, "get",
        lambda self, url, **kw: httpx.Response(200, json=payload, request=httpx.Request("GET", url)),
    )
    out = BraveSearch("k").search("q")
    assert len(out) == 1
    assert out[0].title == "ok"


# -------------------------------------------------- TavilySearch


def test_tavily_parses_results(monkeypatch):
    payload = {
        "results": [
            {"title": "T1", "url": "https://a", "content": "c1"},
            {"title": "T2", "url": "https://b", "content": "c2"},
        ]
    }
    monkeypatch.setattr(
        httpx.Client, "post",
        lambda self, url, **kw: httpx.Response(200, json=payload, request=httpx.Request("POST", url)),
    )
    out = TavilySearch("tvly-k").search("q", top_k=2)
    assert [r.title for r in out] == ["T1", "T2"]


def test_tavily_401_raises_unconfigured(monkeypatch):
    monkeypatch.setattr(
        httpx.Client, "post",
        lambda self, url, **kw: httpx.Response(401, text="bad key", request=httpx.Request("POST", url)),
    )
    with pytest.raises(WebSearchUnconfigured):
        TavilySearch("bad").search("q")


# -------------------------------------------------- SearxSearch


def test_searx_strips_trailing_slash():
    s = SearxSearch("https://searx.example.com/")
    assert s.url == "https://searx.example.com"


def test_searx_parses_results(monkeypatch):
    payload = {
        "results": [
            {"title": "T1", "url": "https://a", "content": "snip1"},
            {"title": "T2", "url": "https://b", "content": "snip2"},
        ]
    }
    monkeypatch.setattr(
        httpx.Client, "get",
        lambda self, url, **kw: httpx.Response(200, json=payload, request=httpx.Request("GET", url)),
    )
    out = SearxSearch("https://searx.x").search("q", top_k=5)
    assert len(out) == 2
    assert out[0].snippet == "snip1"


# -------------------------------------------------- DDGInstantAnswer


def test_ddg_uses_abstract_when_present(monkeypatch):
    payload = {
        "Heading": "Knowlet",
        "AbstractURL": "https://example.com/knowlet",
        "Abstract": "Personal knowledge base.",
        "RelatedTopics": [
            {"FirstURL": "https://example.com/kb1", "Text": "KB1 - desc"},
        ],
    }
    monkeypatch.setattr(
        httpx.Client, "get",
        lambda self, url, **kw: httpx.Response(200, json=payload, request=httpx.Request("GET", url)),
    )
    out = DDGInstantAnswer().search("knowlet", top_k=5)
    assert out[0].url == "https://example.com/knowlet"
    assert out[0].title == "Knowlet"
    assert out[1].url == "https://example.com/kb1"


def test_ddg_empty_when_no_abstract_or_related(monkeypatch):
    monkeypatch.setattr(
        httpx.Client, "get",
        lambda self, url, **kw: httpx.Response(200, json={}, request=httpx.Request("GET", url)),
    )
    out = DDGInstantAnswer().search("rare query", top_k=5)
    assert out == []


def test_ddg_flattens_nested_topics(monkeypatch):
    """DDG sometimes nests RelatedTopics under {Topics: [...]} subgroups."""
    payload = {
        "RelatedTopics": [
            {"Topics": [
                {"FirstURL": "https://a", "Text": "A - x"},
                {"FirstURL": "https://b", "Text": "B - y"},
            ]},
            {"FirstURL": "https://c", "Text": "C"},
        ],
    }
    monkeypatch.setattr(
        httpx.Client, "get",
        lambda self, url, **kw: httpx.Response(200, json=payload, request=httpx.Request("GET", url)),
    )
    out = DDGInstantAnswer().search("q", top_k=5)
    assert [r.url for r in out] == ["https://a", "https://b", "https://c"]


def test_ddg_caps_to_top_k(monkeypatch):
    payload = {
        "RelatedTopics": [
            {"FirstURL": f"https://example.com/{i}", "Text": f"T{i}"} for i in range(10)
        ],
    }
    monkeypatch.setattr(
        httpx.Client, "get",
        lambda self, url, **kw: httpx.Response(200, json=payload, request=httpx.Request("GET", url)),
    )
    out = DDGInstantAnswer().search("q", top_k=3)
    assert len(out) == 3
