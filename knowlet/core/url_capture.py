"""URL fetch + summarize for the M7.2 capture flow (ADR-0016).

The user pastes a URL into the chat input; this module:
1. Fetches the page bytes (httpx, 10s timeout, browser-y UA)
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

import re
from dataclasses import dataclass
from typing import Protocol
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
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
        "image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Hard cap on the article content we send to the summarize LLM. Most articles
# fit in 5000 chars; longer pieces still summarize on the leading section,
# which is usually the thesis + lead. Token cost stays predictable.
_MAX_INPUT_CHARS = 5000

# The summary prompt is fixed and neutral per ADR-0016 §3 — we want extraction,
# not voice. If the user wants opinionated takes that's a chat turn, not the
# capture call.
SUMMARY_PROMPT = (
    "对以下网页正文做 300 字左右的中立摘要,提取主旨 + 关键论点 + 结论。"
    "不要带个人评论,不要扩展超出原文的信息。\n\n"
    "—— 网页正文 ——\n{content}"
)


class FetchError(Exception):
    """The URL couldn't be retrieved (network / DNS / 4xx / 5xx)."""


class ExtractionError(Exception):
    """The page came back but trafilatura couldn't pull readable content
    (JS-heavy SPA / paywall / pure binary). Caller should surface this so
    the user can fall back to manual paste."""


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
        messages: list[dict],
        tools: list[dict] | None = None,
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


def fetch_and_extract(url: str) -> tuple[str, str]:
    """Return (title, content). Raises FetchError / ExtractionError."""
    try:
        with httpx.Client(
            timeout=_HTTP_TIMEOUT,
            headers=_HTTP_HEADERS,
            follow_redirects=True,
        ) as client:
            r = client.get(url)
            r.raise_for_status()
            html = r.text
    except httpx.HTTPError as exc:
        raise FetchError(f"无法访问 {url}: {exc}") from exc

    import trafilatura

    extracted = trafilatura.extract(
        html,
        include_links=False,
        include_tables=False,
    )
    if not extracted or len(extracted.strip()) < 80:
        raise ExtractionError(
            f"抓取到页面但没有提取到可读正文(可能是 JS 重度页面 / 付费墙)"
        )
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


def capture_url(url: str, llm: _LLMLike) -> UrlCapsule:
    """End-to-end: fetch → extract → summarize → return UrlCapsule.

    Doesn't catch summarize errors — the web layer translates them into a
    capsule with empty summary + a flag, so the user can still attach the
    URL and ask manually."""
    title, content = fetch_and_extract(url)  # may raise FetchError / ExtractionError
    summary = summarize_content(llm, content)
    return UrlCapsule(
        url=url,
        title=title,
        hostname=_hostname(url),
        summary=summary,
    )


def is_likely_url(text: str) -> bool:
    """Loose heuristic for the frontend's paste detection — single-line
    `http(s)://...` with no whitespace. Keeps false positives down so
    plain text paste still works as expected."""
    s = (text or "").strip()
    if not s or "\n" in s or "\r" in s or " " in s:
        return False
    return bool(re.match(r"^https?://[^\s]+$", s))
