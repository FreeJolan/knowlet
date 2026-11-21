"""URL fetch + summarize for the M7.2 capture flow (ADR-0016).

The user pastes a URL into the chat input; this module:
1. Fetches the page bytes (httpx, 10s timeout, browser-y UA, bounded size /
   total time, internal addresses refused)
2. Extracts the main content (trafilatura — already used by mining/sources.py)
3. Calls the LLM once for a neutral 300-char summary
4. Returns a UrlCapsule the frontend renders + sends as a chat reference

Pure module — no FastAPI, no Vault. The web layer composes this with the
LLMClient and surfaces it via /api/url/capture.

Failure modes are explicit:
- network / 4xx / 5xx → FetchError
- trafilatura extracts nothing useful → ExtractionError
- LLM summarize fails → caller catches and surfaces a "(摘要失败)" capsule
  variant per ADR-0016 §3, so the user can still attach + send.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

# Mirror the headers mining/sources.py uses, since some sites 403 a bare UA.
_HTTP_TIMEOUT = 10.0
_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36 knowlet/0"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Download bounds. httpx's read timeout is per read, so a server dripping
# bytes forever never trips it — the total deadline does.
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
_MAX_FETCH_SECONDS = 30.0

# Hard cap on the article content we send to the summarize LLM. Most articles
# fit in 5000 chars; longer pieces still summarize on the leading section,
# which is usually the thesis + lead. Token cost stays predictable.
_MAX_INPUT_CHARS = 5000

# The summary prompt is fixed and neutral per ADR-0016 §3 — extraction, not
# voice. Bilingual instructions so the LLM matches the article's language
# (and falls back gracefully when content is multilingual). Hardcoding either
# language alone would produce English-summary-of-Chinese-article (or vice
# versa) for users whose UI language doesn't match the page.
SUMMARY_PROMPT = (
    "Produce a ~300-character neutral summary of the webpage body below, "
    "extracting the thesis, key arguments, and conclusion. Match the language "
    "of the source article. No personal commentary; do not add facts beyond "
    "what's in the source.\n"
    "对以下网页正文做 300 字左右的中立摘要,提取主旨 + 关键论点 + 结论。"
    "用与原文相同的语言输出。不要带个人评论,不要扩展超出原文的信息。\n\n"
    "—— Article body / 网页正文 ——\n{content}"
)


class FetchError(Exception):
    """The URL couldn't be retrieved (network / DNS / 4xx / 5xx)."""


class ExtractionError(Exception):
    """The page came back but trafilatura couldn't pull readable content
    (JS-heavy SPA / paywall / pure binary). Caller should surface this so
    the user can fall back to manual paste."""


class BlockedAddressError(FetchError):
    """The URL (or a redirect hop) points at loopback / private / link-local
    address space, which a pasted or model-chosen URL must not reach."""


class ResponseTooLargeError(FetchError):
    """The response body exceeds the download cap."""


@dataclass(frozen=True)
class UrlCapsule:
    """One captured URL, ready to be wrapped in a chat reference capsule."""

    url: str
    title: str
    hostname: str
    summary: str  # may be empty if summarize failed; caller decides how to surface


class _LLMLike(Protocol):
    """Minimal shape of LLMClient.chat we need — kept narrow so unit tests
    can pass a stub without depending on the full class."""

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> object:  # AssistantMessage; .content is what we read
        ...


def _hostname(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        host = ""
    return host[4:] if host.startswith("www.") else host


def _extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    raw = m.group(1)
    # Common HTML entities that show up in titles. Light-touch decode — full
    # entity decoding isn't worth a html.parser dependency for this path.
    return (
        raw.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .strip()
    )


# Explicit list rather than ``not ip.is_global``: proxy tools in fake-ip DNS
# mode (Clash / Surge) answer every domain from 198.18.0.0/15, which
# ``is_global`` also rejects — that would break every capture for those users.
_BLOCKED_NETWORKS = tuple(
    ipaddress.ip_network(net)
    for net in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "::/128",
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
)


def _is_blocked_ip(raw: str) -> bool:
    try:
        ip = ipaddress.ip_address(raw.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_multicast or any(ip in net for net in _BLOCKED_NETWORKS)


def _ensure_public_host(request: httpx.Request) -> None:
    """Request hook: runs for the first request and every redirect hop.

    Resolution happens again inside httpx when it connects, so a DNS
    rebinding attacker can still race this check; it stops the plain
    "paste http://127.0.0.1 / 169.254.169.254 / intranet name" cases.
    An unresolvable name is let through: with a remote-DNS proxy the proxy
    resolves it, and without one httpx fails to connect anyway."""
    host = request.url.host
    if not host:
        return
    if _is_blocked_ip(host):
        raise BlockedAddressError(f"拒绝访问内网/本机地址 (blocked private address): {host}")
    try:
        infos = socket.getaddrinfo(host, request.url.port or 443, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        return
    for info in infos:
        addr = str(info[4][0])
        if _is_blocked_ip(addr):
            raise BlockedAddressError(
                f"拒绝访问内网/本机地址 (blocked private address): {host} -> {addr}"
            )


class _CappedStream(httpx.SyncByteStream):
    """Wraps a response body so reading stops at ``max_bytes`` / ``deadline``.

    Counts bytes on the wire: a compressed body can still expand past the
    cap when decoded (httpx decodes after this layer)."""

    def __init__(self, inner: httpx.SyncByteStream, *, max_bytes: int, deadline: float):
        self._inner = inner
        self._max_bytes = max_bytes
        self._deadline = deadline

    def __iter__(self) -> Iterator[bytes]:
        total = 0
        for chunk in self._inner:
            total += len(chunk)
            if total > self._max_bytes:
                raise ResponseTooLargeError(_too_large_message(self._max_bytes))
            if time.monotonic() > self._deadline:
                raise FetchError("下载超时 (download exceeded the total time limit)")
            yield chunk

    def close(self) -> None:
        self._inner.close()


def _too_large_message(max_bytes: int) -> str:
    return f"响应体超过 {max_bytes / (1024 * 1024):.0f} MB 上限 (response too large)"


def fetch_bounded(
    url: str,
    *,
    headers: dict[str, str],
    timeout: httpx.Timeout | float,
    max_bytes: int,
    max_seconds: float,
    block_private: bool,
    accept_content_type: Callable[[str], bool] | None = None,
) -> httpx.Response:
    """GET ``url`` with a byte cap, a total deadline and (optionally) the
    internal-address guard applied to every redirect hop.

    Returns the fully-read response after ``raise_for_status``. Raises
    :class:`FetchError` (network / HTTP status / guard failures) or
    :class:`ExtractionError` when ``accept_content_type`` rejects the
    declared Content-Type — checked before the body is downloaded.
    Env proxy settings keep working (no custom transport)."""
    deadline = time.monotonic() + max_seconds

    def guard_response(response: httpx.Response) -> None:
        declared = response.headers.get("content-length")
        if declared is not None and declared.strip().isdigit() and int(declared) > max_bytes:
            raise ResponseTooLargeError(_too_large_message(max_bytes))
        if accept_content_type is not None and response.is_success:
            content_type = response.headers.get("content-type", "")
            if content_type and not accept_content_type(content_type):
                raise ExtractionError(
                    f"不支持的内容类型 (unsupported content type): {content_type}"
                )
        if isinstance(response.stream, httpx.SyncByteStream):
            response.stream = _CappedStream(response.stream, max_bytes=max_bytes, deadline=deadline)

    request_hooks: list[Callable[[httpx.Request], None]] = []
    if block_private:
        request_hooks.append(_ensure_public_host)
    try:
        with httpx.Client(
            timeout=timeout,
            headers=headers,
            follow_redirects=True,
            event_hooks={"request": request_hooks, "response": [guard_response]},
        ) as client:
            r = client.get(url)
            r.raise_for_status()
            return r
    except httpx.HTTPError as exc:
        raise FetchError(f"无法访问 {url}: {exc}") from exc


def _is_readable_content_type(content_type: str) -> bool:
    mime = content_type.split(";", 1)[0].strip().lower()
    return not mime or mime.startswith("text/") or "html" in mime or "xml" in mime


def fetch_and_extract(url: str) -> tuple[str, str]:
    """Return (title, content). Raises FetchError / ExtractionError."""
    r = fetch_bounded(
        url,
        headers=_HTTP_HEADERS,
        timeout=_HTTP_TIMEOUT,
        max_bytes=MAX_RESPONSE_BYTES,
        max_seconds=_MAX_FETCH_SECONDS,
        block_private=True,
        accept_content_type=_is_readable_content_type,
    )
    html = r.text

    import trafilatura

    extracted = trafilatura.extract(
        html,
        include_links=False,
        include_tables=False,
    )
    if not extracted or len(extracted.strip()) < 80:
        raise ExtractionError("抓取到页面但没有提取到可读正文(可能是 JS 重度页面 / 付费墙)")
    title = _extract_title(html) or url
    return title, extracted.strip()


def summarize_content(llm: _LLMLike, content: str) -> str:
    """Run a single LLM call to produce a 300-char-ish neutral summary.
    Raises whatever the LLM client raises — caller decides whether to
    fall back to "(摘要失败)" or surface to the user."""
    truncated = content[:_MAX_INPUT_CHARS]
    messages = [
        {"role": "user", "content": SUMMARY_PROMPT.format(content=truncated)},
    ]
    msg = llm.chat(messages=messages, tools=None, max_tokens=600, temperature=0.2)
    summary = (getattr(msg, "content", "") or "").strip()
    return summary


@dataclass(frozen=True)
class UrlCaptureResult:
    """Outcome of one fetch + summarize. ``summary_error`` is set (and
    ``capsule.summary`` empty) when only the LLM step failed, so callers can
    still build a capsule from ``capsule.title`` / ``content`` without
    fetching the page again."""

    capsule: UrlCapsule
    content: str
    summary_error: Exception | None = None


def capture_url_detailed(url: str, llm: _LLMLike) -> UrlCaptureResult:
    """Fetch → extract → summarize. Raises FetchError / ExtractionError;
    summarize failures are returned in ``summary_error`` instead."""
    title, content = fetch_and_extract(url)
    summary = ""
    summary_error: Exception | None = None
    try:
        summary = summarize_content(llm, content)
    except Exception as exc:
        summary_error = exc
    return UrlCaptureResult(
        capsule=UrlCapsule(url=url, title=title, hostname=_hostname(url), summary=summary),
        content=content,
        summary_error=summary_error,
    )


def capture_url(url: str, llm: _LLMLike) -> UrlCapsule:
    """End-to-end: fetch → extract → summarize → return UrlCapsule.

    Doesn't catch summarize errors — the web layer translates them into a
    capsule with empty summary + a flag, so the user can still attach the
    URL and ask manually."""
    result = capture_url_detailed(url, llm)  # may raise FetchError / ExtractionError
    if result.summary_error is not None:
        raise result.summary_error
    return result.capsule


def is_likely_url(text: str) -> bool:
    """Loose heuristic for the frontend's paste detection — single-line
    `http(s)://...` with no whitespace. Keeps false positives down so
    plain text paste still works as expected."""
    s = (text or "").strip()
    if not s or "\n" in s or "\r" in s or " " in s:
        return False
    return bool(re.match(r"^https?://[^\s]+$", s))
