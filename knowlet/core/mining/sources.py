"""Source fetchers: RSS / Atom feeds and plain URL pages.

Returns a normalized iterable of `SourceItem` regardless of the underlying
format. The runner / extractor layers don't need to know whether something
came from a feed or a URL — they only see content + provenance fields.

Per ADR-0009 the source set is RSS + URL only for M4. Webhooks, IMAP,
JS-rendered pages are explicitly out of scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import httpx

from knowlet.core.mining.task import SourceSpec


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


def fetch_source(spec: SourceSpec) -> list[SourceItem]:
    if spec.type == "rss":
        return _fetch_rss(spec.url)
    if spec.type == "url":
        return _fetch_url(spec.url)
    raise ValueError(f"unsupported source type: {spec.type}")


def _fetch_rss(url: str) -> list[SourceItem]:
    import feedparser

    parsed = feedparser.parse(url, request_headers=_HTTP_HEADERS, agent=_HTTP_HEADERS["User-Agent"])
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


def _entry_text(entry: dict) -> str:
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
    except Exception:  # noqa: BLE001 — defensive
        # Fallback: naive tag strip
        import re

        return re.sub(r"<[^>]+>", "", html)


def _fetch_url(url: str) -> list[SourceItem]:
    """Fetch a single page, extract main content via trafilatura."""
    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT, headers=_HTTP_HEADERS, follow_redirects=True) as client:
            r = client.get(url)
            r.raise_for_status()
            html = r.text
    except httpx.HTTPError as exc:
        return []  # caller's run report counts errors; empty here is fine

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
