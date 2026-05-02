"""Unit tests for `knowlet/core/url_capture.py` (M7.2)."""

from unittest.mock import patch

import httpx
import pytest

from knowlet.core.url_capture import (
    ExtractionError,
    FetchError,
    UrlCapsule,
    _extract_title,
    _hostname,
    capture_url,
    fetch_and_extract,
    is_likely_url,
    summarize_content,
)


# -------------------------------------------------- is_likely_url


def test_is_likely_url_accepts_http_and_https():
    assert is_likely_url("https://example.com/foo")
    assert is_likely_url("http://example.com")
    assert is_likely_url("https://example.com/path?q=1#frag")


def test_is_likely_url_rejects_plain_text():
    assert not is_likely_url("hello world")
    assert not is_likely_url("look at https://example.com")  # has space
    assert not is_likely_url("https://example.com\nnext line")
    assert not is_likely_url("")
    assert not is_likely_url(None)  # type: ignore[arg-type]
    assert not is_likely_url("ftp://example.com")  # not http(s)
    assert not is_likely_url("example.com")  # no scheme


# -------------------------------------------------- _hostname


def test_hostname_strips_www_prefix():
    assert _hostname("https://www.nytimes.com/article") == "nytimes.com"
    assert _hostname("https://nytimes.com") == "nytimes.com"


def test_hostname_for_invalid_url_is_empty_string():
    assert _hostname("") == ""
    assert _hostname("not a url") == ""


# -------------------------------------------------- _extract_title


def test_extract_title_basic():
    assert _extract_title("<html><title>Hello World</title>") == "Hello World"


def test_extract_title_decodes_common_entities():
    assert _extract_title("<title>Tom &amp; Jerry &quot;quoted&quot;</title>") == 'Tom & Jerry "quoted"'


def test_extract_title_returns_empty_when_missing():
    assert _extract_title("<html><body>no title here</body>") == ""


# -------------------------------------------------- fetch_and_extract


_MIN_HTML = """<html><head><title>The Test Page</title></head>
<body><article><p>""" + "This is the main article body. " * 30 + "</p></article></body></html>"""


def test_fetch_and_extract_happy_path(monkeypatch):
    """Network is mocked at the httpx layer; trafilatura is called real."""

    def fake_get(self, url, **kwargs):
        return httpx.Response(200, text=_MIN_HTML, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    title, content = fetch_and_extract("https://example.com/article")
    assert title == "The Test Page"
    assert "main article body" in content


def test_fetch_and_extract_404_raises_FetchError(monkeypatch):
    def fake_get(self, url, **kwargs):
        return httpx.Response(404, text="not found", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    with pytest.raises(FetchError):
        fetch_and_extract("https://example.com/missing")


def test_fetch_and_extract_network_error_raises_FetchError(monkeypatch):
    def fake_get(self, url, **kwargs):
        raise httpx.ConnectError("dns failure")

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    with pytest.raises(FetchError):
        fetch_and_extract("https://example.com/x")


def test_fetch_and_extract_empty_extraction_raises(monkeypatch):
    """trafilatura returns nothing useful for a basically empty page."""
    empty_html = "<html><head><title>x</title></head><body></body></html>"

    def fake_get(self, url, **kwargs):
        return httpx.Response(200, text=empty_html, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    with pytest.raises(ExtractionError):
        fetch_and_extract("https://example.com/empty")


# -------------------------------------------------- summarize_content


class _StubLLM:
    """Captures messages and returns a fixed reply via .chat()."""

    def __init__(self, reply: str = "短摘要"):
        self.reply = reply
        self.last_messages: list = []

    def chat(self, messages, tools=None, max_tokens=None, temperature=None):
        self.last_messages = messages

        class _M:
            content = self.reply

        return _M()


def test_summarize_content_passes_truncated_input():
    """5000-char cap on the input the LLM sees."""
    huge = "x" * 20_000
    llm = _StubLLM(reply="ok")
    summarize_content(llm, huge)
    sent = llm.last_messages[0]["content"]
    # Truncated to 5000 inside the prompt template (template adds prefix text,
    # so the rendered length > 5000 — what we assert is the source content
    # itself was capped at 5000 chars).
    assert "x" * 5000 in sent
    assert "x" * 5001 not in sent


def test_summarize_content_returns_stripped_summary():
    llm = _StubLLM(reply="  the summary text  \n\n")
    out = summarize_content(llm, "irrelevant content body")
    assert out == "the summary text"


# -------------------------------------------------- capture_url


def test_capture_url_orchestrates_fetch_extract_summarize(monkeypatch):
    def fake_get(self, url, **kwargs):
        return httpx.Response(200, text=_MIN_HTML, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    llm = _StubLLM(reply="文章主旨摘要")
    cap = capture_url("https://www.example.com/x", llm)
    assert isinstance(cap, UrlCapsule)
    assert cap.url == "https://www.example.com/x"
    assert cap.title == "The Test Page"
    assert cap.hostname == "example.com"
    assert cap.summary == "文章主旨摘要"
