"""Regression tests for the digest-mining fetch layer (2026-11 audit).

Covers mining/sources.py (RSS timeout + bozo surfacing, URL source
errors) and url_capture.py (bounded download, SSRF guard, content-type).
Network is faked at ``httpx.HTTPTransport.handle_request`` so the real
httpx client machinery (event hooks, redirects, body reads) still runs.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator

import httpx
import pytest

from knowlet.core import url_capture
from knowlet.core.mining import sources
from knowlet.core.mining.task import SourceSpec
from knowlet.core.url_capture import ExtractionError, FetchError, fetch_and_extract

_PUBLIC_IP = "93.184.216.34"

_ARTICLE_HTML = (
    "<html><head><title>Audit Page</title></head><body><article><p>"
    + "This is the main article body for the audit test. " * 30
    + "</p></article></body></html>"
)

_RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>t</title><link>https://feeds.example/</link>
<item><title>Entry A</title><link>/a</link><guid>g1</guid><description>first</description></item>
</channel></rss>"""

_EMPTY_RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>t</title><link>https://feeds.example/</link></channel></rss>"""


class _ChunkStream(httpx.SyncByteStream):
    """A response body that records how much of it was consumed."""

    def __init__(self, chunks: Iterator[bytes]):
        self._chunks = chunks
        self.yielded = 0
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self._chunks:
            self.yielded += len(chunk)
            yield chunk

    def close(self) -> None:
        self.closed = True


def _route(monkeypatch, handler) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def fake_handle_request(self, request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_handle_request)
    return seen


def _resolve_to(monkeypatch, mapping: dict[str, str]) -> None:
    real = socket.getaddrinfo

    def fake_getaddrinfo(host, port, *args, **kwargs):
        if host in mapping:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (mapping[host], port or 0))]
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


# ------------------------------------------------------------ RSS: timeout


def test_rss_fetch_times_out_on_a_server_that_never_answers(monkeypatch):
    """A feed server that accepts the connection but never sends bytes must
    not hang the caller forever (it holds digest_pull_lock in the web app)."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    accepted: list[socket.socket] = []

    def accept_and_stall() -> None:
        try:
            conn, _ = listener.accept()
            accepted.append(conn)
        except OSError:
            pass

    threading.Thread(target=accept_and_stall, daemon=True).start()
    monkeypatch.setattr(sources, "_HTTP_TIMEOUT", httpx.Timeout(0.5, connect=0.5))

    outcome: dict[str, object] = {}

    def run() -> None:
        try:
            outcome["result"] = sources.fetch_source(
                SourceSpec(type="rss", url=f"http://127.0.0.1:{port}/feed.xml")
            )
        except Exception as exc:
            outcome["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout=8)
    try:
        assert not worker.is_alive(), "RSS fetch hung past its network timeout"
        assert isinstance(outcome.get("error"), FetchError)
    finally:
        for conn in accepted:
            conn.close()
        listener.close()


def test_rss_fetch_hands_feedparser_bytes_not_a_url(monkeypatch):
    """feedparser must parse downloaded bytes (fetched with our timeout),
    never download by itself."""
    seen = _route(
        monkeypatch,
        lambda req: httpx.Response(
            200, content=_RSS, headers={"content-type": "application/rss+xml"}
        ),
    )
    items = sources.fetch_source(SourceSpec(type="rss", url="https://feeds.example/feed.xml"))
    assert [item.title for item in items] == ["Entry A"]
    # Relative entry links still resolve against the feed URL.
    assert items[0].url == "https://feeds.example/a"
    assert len(seen) == 1
    timeout = seen[0].extensions["timeout"]
    assert timeout["read"] is not None and timeout["connect"] is not None


# ------------------------------------------------------------ RSS: bozo


def test_rss_fetch_raises_when_url_returns_html_instead_of_a_feed(monkeypatch):
    _route(
        monkeypatch,
        lambda req: httpx.Response(
            200,
            content=b"<html><body><p>not a feed</p></body></html>",
            headers={"content-type": "text/html; charset=utf-8"},
        ),
    )
    with pytest.raises(ValueError, match="feed"):
        sources.fetch_source(SourceSpec(type="rss", url="https://feeds.example/typo"))


def test_rss_fetch_raises_on_http_error_status(monkeypatch):
    _route(monkeypatch, lambda req: httpx.Response(404, content=b"missing"))
    with pytest.raises(FetchError):
        sources.fetch_source(SourceSpec(type="rss", url="https://feeds.example/404"))


def test_rss_fetch_accepts_a_valid_feed_with_no_entries(monkeypatch):
    _route(
        monkeypatch,
        lambda req: httpx.Response(
            200, content=_EMPTY_RSS, headers={"content-type": "application/rss+xml"}
        ),
    )
    assert sources.fetch_source(SourceSpec(type="rss", url="https://feeds.example/empty")) == []


def test_rss_body_that_looks_like_a_local_path_is_not_opened(monkeypatch, tmp_path):
    """feedparser treats a bytes argument that names an existing file as a
    filename; the fetched body must never be interpreted as a local path."""
    secret = tmp_path / "secret.xml"
    secret.write_bytes(_RSS)
    _route(monkeypatch, lambda req: httpx.Response(200, content=str(secret).encode()))
    with pytest.raises(ValueError):
        sources.fetch_source(SourceSpec(type="rss", url="https://feeds.example/path"))


def test_url_source_fetch_error_is_raised_not_swallowed(monkeypatch):
    _route(monkeypatch, lambda req: httpx.Response(500, content=b"boom"))
    with pytest.raises(FetchError):
        sources.fetch_source(SourceSpec(type="url", url="https://pages.example/x"))


# ------------------------------------------------------------ url_capture: size


def test_fetch_and_extract_rejects_declared_oversize_body(monkeypatch):
    _resolve_to(monkeypatch, {"big.example": _PUBLIC_IP})
    stream = _ChunkStream(iter([b"x" * 1024]))
    _route(
        monkeypatch,
        lambda req: httpx.Response(
            200,
            headers={
                "content-type": "text/html",
                "content-length": str(url_capture.MAX_RESPONSE_BYTES + 1),
            },
            stream=stream,
        ),
    )
    with pytest.raises(FetchError, match="MB"):
        fetch_and_extract("https://big.example/huge.html")
    assert stream.yielded == 0


def test_fetch_and_extract_stops_reading_undeclared_oversize_body(monkeypatch):
    _resolve_to(monkeypatch, {"big.example": _PUBLIC_IP})
    chunk = b"a" * 65536

    def endless() -> Iterator[bytes]:
        while True:
            yield chunk

    stream = _ChunkStream(endless())
    _route(
        monkeypatch,
        lambda req: httpx.Response(200, headers={"content-type": "text/html"}, stream=stream),
    )
    with pytest.raises(FetchError, match="MB"):
        fetch_and_extract("https://big.example/stream.html")
    assert stream.yielded <= url_capture.MAX_RESPONSE_BYTES + len(chunk)
    assert stream.closed


def test_fetch_and_extract_enforces_total_deadline_on_slow_drip(monkeypatch):
    _resolve_to(monkeypatch, {"slow.example": _PUBLIC_IP})
    monkeypatch.setattr(url_capture, "_MAX_FETCH_SECONDS", 0.3)

    def drip() -> Iterator[bytes]:
        while True:
            time.sleep(0.1)
            yield b"<p>still going</p>"

    _route(
        monkeypatch,
        lambda req: httpx.Response(
            200, headers={"content-type": "text/html"}, stream=_ChunkStream(drip())
        ),
    )
    started = time.monotonic()
    with pytest.raises(FetchError):
        fetch_and_extract("https://slow.example/drip.html")
    assert time.monotonic() - started < 5


def test_fetch_and_extract_rejects_binary_content_type_before_download(monkeypatch):
    _resolve_to(monkeypatch, {"files.example": _PUBLIC_IP})
    stream = _ChunkStream(iter([b"%PDF-1.7 ..."]))
    _route(
        monkeypatch,
        lambda req: httpx.Response(200, headers={"content-type": "application/pdf"}, stream=stream),
    )
    with pytest.raises(ExtractionError):
        fetch_and_extract("https://files.example/paper.pdf")
    assert stream.yielded == 0


# ------------------------------------------------------------ url_capture: SSRF


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8765/api/notes",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.8/admin",
        "http://192.168.1.1/",
        "http://[::1]:8765/",
        "http://0.0.0.0/",
    ],
)
def test_fetch_and_extract_blocks_internal_ip_literals(monkeypatch, url):
    seen = _route(monkeypatch, lambda req: httpx.Response(200, text=_ARTICLE_HTML))
    with pytest.raises(FetchError, match=r"内网|private|blocked"):
        fetch_and_extract(url)
    assert seen == []


def test_fetch_and_extract_blocks_hostname_resolving_to_private_ip(monkeypatch):
    _resolve_to(monkeypatch, {"intranet.example": "10.1.2.3"})
    seen = _route(monkeypatch, lambda req: httpx.Response(200, text=_ARTICLE_HTML))
    with pytest.raises(FetchError):
        fetch_and_extract("https://intranet.example/wiki")
    assert seen == []


def test_fetch_and_extract_blocks_redirect_into_link_local(monkeypatch):
    _resolve_to(monkeypatch, {"public.example": _PUBLIC_IP})

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "public.example":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})
        return httpx.Response(200, text=_ARTICLE_HTML)

    seen = _route(monkeypatch, handler)
    with pytest.raises(FetchError):
        fetch_and_extract("https://public.example/redirect")
    assert [r.url.host for r in seen] == ["public.example"]


def test_fetch_and_extract_allows_public_and_fake_ip_proxy_ranges(monkeypatch):
    """Clash / Surge fake-ip DNS answers with 198.18.0.0/15 for every
    domain; that range must keep working."""
    _resolve_to(monkeypatch, {"public.example": _PUBLIC_IP, "proxied.example": "198.18.0.7"})
    _route(
        monkeypatch,
        lambda req: httpx.Response(
            200, content=_ARTICLE_HTML.encode(), headers={"content-type": "text/html"}
        ),
    )
    title, body = fetch_and_extract("https://public.example/a")
    assert title == "Audit Page"
    assert "main article body" in body
    title, _ = fetch_and_extract("https://proxied.example/a")
    assert title == "Audit Page"


# ------------------------------------------------------------ summarize fallback


class _FailingLLM:
    def chat(self, messages, tools=None, max_tokens=None, temperature=None):
        raise RuntimeError("llm down")


def test_capture_url_detailed_keeps_content_when_summary_fails(monkeypatch):
    """Lets the web layer build the "(摘要失败)" capsule without fetching
    the same URL a second time."""
    _resolve_to(monkeypatch, {"public.example": _PUBLIC_IP})
    seen = _route(
        monkeypatch,
        lambda req: httpx.Response(
            200, content=_ARTICLE_HTML.encode(), headers={"content-type": "text/html"}
        ),
    )
    result = url_capture.capture_url_detailed("https://public.example/a", _FailingLLM())
    assert isinstance(result.summary_error, RuntimeError)
    assert result.capsule.title == "Audit Page"
    assert result.capsule.summary == ""
    assert "main article body" in result.content
    assert len(seen) == 1
    with pytest.raises(RuntimeError, match="llm down"):
        url_capture.capture_url("https://public.example/a", _FailingLLM())


def test_fetch_and_extract_reports_http_errors_before_content_type(monkeypatch):
    _resolve_to(monkeypatch, {"api.example": _PUBLIC_IP})
    _route(
        monkeypatch,
        lambda req: httpx.Response(
            404, content=b'{"error": "nope"}', headers={"content-type": "application/json"}
        ),
    )
    with pytest.raises(FetchError):
        fetch_and_extract("https://api.example/missing")
