"""Source fetchers: RSS / Atom feeds and plain URL pages.

Returns a normalized iterable of `SourceItem` regardless of the underlying
format. The runner / extractor layers don't need to know whether something
came from a feed or a URL — they only see content + provenance fields.

Per ADR-0009 the source set is RSS + URL only for M4. Webhooks, IMAP,
JS-rendered pages are explicitly out of scope.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

import httpx

from knowlet.core.mining.task import SourceSpec
from knowlet.core.url_capture import fetch_bounded


@dataclass
class SourceItem:
    """Normalized output of a fetch."""

    source_url: str  # the spec URL (feed or page)
    item_id: str  # stable id (entry.id, entry.link, or the URL itself)
    title: str
    url: str  # canonical link to the item itself
    published: str | None  # ISO timestamp if known
    content: str  # plain-text content (already extracted from HTML if needed)


_HTTP_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
_HTTP_HEADERS = {
    "User-Agent": "knowlet/0.0 (+https://github.com/FreeJolan/knowlet)",
    "Accept": "*/*",
}
# Long-running podcast feeds can reach several MB; pages are smaller.
_MAX_FEED_BYTES = 20 * 1024 * 1024
_MAX_PAGE_BYTES = 5 * 1024 * 1024
_MAX_FETCH_SECONDS = 60.0


def _get(url: str, *, max_bytes: int) -> httpx.Response:
    # Sources are configured by the user, so LAN / self-hosted feeds stay
    # reachable (block_private=False) — unlike pasted / model-chosen URLs.
    return fetch_bounded(
        url,
        headers=_HTTP_HEADERS,
        timeout=_HTTP_TIMEOUT,
        max_bytes=max_bytes,
        max_seconds=_MAX_FETCH_SECONDS,
        block_private=False,
    )


def fetch_source(spec: SourceSpec) -> list[SourceItem]:
    if spec.type == "rss":
        return _fetch_rss(spec.url)
    if spec.type == "url":
        return _fetch_url(spec.url)
    raise ValueError(f"unsupported source type: {spec.type}")


def _fetch_rss(url: str) -> list[SourceItem]:
    """Raises FetchError (network / HTTP status) or ValueError when the
    response is not a parseable feed."""
    import feedparser

    response = _get(url, max_bytes=_MAX_FEED_BYTES)
    response_headers = {k.lower(): v for k, v in response.headers.items()}
    # Base for relative entry links (feedparser used the URL itself when it
    # downloaded the feed).
    response_headers.setdefault("content-location", str(response.url))
    # A file object, not bytes: feedparser tries ``open()`` on a bytes
    # argument first, so a body naming a local path would be read from disk.
    parsed = feedparser.parse(io.BytesIO(response.content), response_headers=response_headers)
    if not parsed.entries and (parsed.get("bozo") or not parsed.get("version")):
        reason = parsed.get("bozo_exception") or "unrecognized feed format"
        raise ValueError(f"not a valid RSS/Atom feed: {reason}")
    items: list[SourceItem] = []
    for entry in parsed.entries or []:
        link = entry.get("link") or entry.get("id") or ""
        eid = entry.get("id") or link or entry.get("title", "") or ""
        title = (entry.get("title") or "").strip()
        published = entry.get("published") or entry.get("updated") or None
        content = _entry_text(entry)
        items.append(
            SourceItem(
                source_url=url,
                item_id=str(eid),
                title=title,
                url=link,
                published=str(published) if published else None,
                content=content.strip(),
            )
        )
    return items


def _entry_text(entry: dict[str, Any]) -> str:
    """Best-effort plain-text content for a feed entry."""
    content_blocks = entry.get("content") or []
    if isinstance(content_blocks, list) and content_blocks:
        body = content_blocks[0].get("value") if isinstance(content_blocks[0], dict) else ""
        if body:
            return _strip_html(body)
    summary = entry.get("summary") or entry.get("description") or ""
    if summary:
        return _strip_html(summary)
    return ""


def _strip_html(html: str) -> str:
    """Strip HTML tags via trafilatura's extractor for plain text."""
    try:
        import trafilatura

        out = trafilatura.extract(html, include_links=False, include_tables=False)
        return out or ""
    except Exception:
        # Fallback: naive tag strip
        import re

        return re.sub(r"<[^>]+>", "", html)


def _fetch_url(url: str) -> list[SourceItem]:
    """Fetch a single page, extract main content via trafilatura.

    Raises FetchError on network / HTTP failures; the runner records it in
    the run report."""
    html = _get(url, max_bytes=_MAX_PAGE_BYTES).text

    import trafilatura

    extracted = trafilatura.extract(html, include_links=False, include_tables=False)
    title = _extract_title(html) or url
    return [
        SourceItem(
            source_url=url,
            item_id=url,
            title=title,
            url=url,
            published=None,
            content=(extracted or "").strip(),
        )
    ]


def _extract_title(html: str) -> str | None:
    import re

    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()
    return None
