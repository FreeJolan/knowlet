"""Web search providers for the LLM `web_search` tool (M7.5, ADR-0017).

Pure module — no FastAPI, no LLM client. Caller (the tool wrapper in
`core/tools/web_search_tool.py`) selects a provider via `pick_provider`
and calls `search(query, top_k)` to get a flat list of SearchResult.

Providers don't fetch full page content; that's a separate concern
covered by `core/url_capture.fetch_and_extract` (M7.2). The LLM picks
which titles look worth deep-reading and calls `fetch_url` itself —
two-stage tool design per ADR-0017 §5.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote_plus, urlparse

import httpx

# Mirror the UA used in url_capture.py — some sites reject bare requests/0.x
# user agents.
_HTTP_TIMEOUT = 10.0
_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36 knowlet/0"
    ),
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

DEFAULT_TOP_K = 5
MAX_TOP_K = 10  # over this, providers cap silently — anti-abuse


class WebSearchError(Exception):
    """Raised when the search provider fails (network, auth, rate limit).
    Caller (the tool wrapper) translates this into a tool error the LLM
    can read and react to."""


class WebSearchUnconfigured(WebSearchError):
    """The chosen provider needs an API key / URL that isn't set. Distinct
    from generic WebSearchError so the tool wrapper can surface a clear
    "set <field> in config" message instead of a network-style failure."""


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    rank: int  # 0-based index in the provider's response


class SearchProvider(Protocol):
    """Narrow shape every provider implements. Stays Protocol-style so
    tests can pass a stub without inheriting any base."""

    name: str

    def search(self, query: str, top_k: int = DEFAULT_TOP_K) -> list[SearchResult]:
        ...


# ---------------------------------------------------------------- providers


class BraveSearch:
    """Brave Search API. Free tier "AI for Free" = 2000 queries/month;
    paid bumps to 10k/month at $3. Quality close to Google, privacy-
    friendly default. Docs: https://brave.com/search/api/."""

    name = "brave"

    def __init__(self, api_key: str):
        if not api_key:
            raise WebSearchUnconfigured(
                "Brave Search requires `web_search.brave_api_key`. "
                "Get one at https://brave.com/search/api/ (free tier, no card)."
            )
        self.api_key = api_key

    def search(self, query: str, top_k: int = DEFAULT_TOP_K) -> list[SearchResult]:
        k = max(1, min(MAX_TOP_K, int(top_k)))
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
                r = client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": k},
                    headers={
                        **_HTTP_HEADERS,
                        "Accept": "application/json",
                        "X-Subscription-Token": self.api_key,
                    },
                )
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise WebSearchUnconfigured(f"Brave rejected the API key: {exc}") from exc
            raise WebSearchError(f"Brave HTTP {exc.response.status_code}: {exc}") from exc
        except httpx.HTTPError as exc:
            raise WebSearchError(f"Brave network error: {exc}") from exc
        web_results = (data.get("web") or {}).get("results") or []
        return [
            SearchResult(
                title=str(r.get("title") or "").strip(),
                url=str(r.get("url") or "").strip(),
                snippet=str(r.get("description") or "").strip()[:400],
                rank=i,
            )
            for i, r in enumerate(web_results[:k])
            if r.get("url")
        ]


class TavilySearch:
    """Tavily Search API — built for LLM agents, returns scored results.
    Free tier 1000/month. Docs: https://tavily.com/."""

    name = "tavily"

    def __init__(self, api_key: str):
        if not api_key:
            raise WebSearchUnconfigured(
                "Tavily Search requires `web_search.tavily_api_key`. "
                "Get one at https://tavily.com/ (free tier)."
            )
        self.api_key = api_key

    def search(self, query: str, top_k: int = DEFAULT_TOP_K) -> list[SearchResult]:
        k = max(1, min(MAX_TOP_K, int(top_k)))
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
                r = client.post(
                    "https://api.tavily.com/search",
                    json={
                        "api_key": self.api_key,
                        "query": query,
                        "max_results": k,
                        "search_depth": "basic",  # "advanced" is ~2x cost
                    },
                    headers=_HTTP_HEADERS,
                )
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise WebSearchUnconfigured(f"Tavily rejected the API key: {exc}") from exc
            raise WebSearchError(f"Tavily HTTP {exc.response.status_code}: {exc}") from exc
        except httpx.HTTPError as exc:
            raise WebSearchError(f"Tavily network error: {exc}") from exc
        results = data.get("results") or []
        return [
            SearchResult(
                title=str(r.get("title") or "").strip(),
                url=str(r.get("url") or "").strip(),
                snippet=str(r.get("content") or "").strip()[:400],
                rank=i,
            )
            for i, r in enumerate(results[:k])
            if r.get("url")
        ]


class SearxSearch:
    """User's self-hosted Searx (https://searx.github.io/searx/) instance.
    Hits the JSON-format endpoint at `<url>/search?format=json&q=...`.

    Why we list this as 1st-class: it's the only provider that gives the
    user full data sovereignty (query never leaves their infra). The
    setup cost is non-trivial (host a Searx) but a real audience exists.
    """

    name = "searx"

    def __init__(self, url: str):
        if not url:
            raise WebSearchUnconfigured(
                "Searx provider requires `web_search.searx_url` "
                "(e.g. https://searx.example.com)."
            )
        self.url = url.rstrip("/")

    def search(self, query: str, top_k: int = DEFAULT_TOP_K) -> list[SearchResult]:
        k = max(1, min(MAX_TOP_K, int(top_k)))
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
                r = client.get(
                    f"{self.url}/search",
                    params={"q": query, "format": "json"},
                    headers=_HTTP_HEADERS,
                )
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as exc:
            raise WebSearchError(f"Searx error: {exc}") from exc
        results = data.get("results") or []
        return [
            SearchResult(
                title=str(r.get("title") or "").strip(),
                url=str(r.get("url") or "").strip(),
                snippet=str(r.get("content") or "").strip()[:400],
                rank=i,
            )
            for i, r in enumerate(results[:k])
            if r.get("url")
        ]


class DDGInstantAnswer:
    """DuckDuckGo Instant Answer API — free, no key, but coverage is
    sparse (only ~30% of queries get an Instant Answer). Used as the
    default fallback for users who haven't configured anything else.

    The "RelatedTopics" array is the closest thing the IA endpoint has
    to a search result list; we map those to SearchResult. Empty result
    is a real outcome, not a bug — the LLM should see "no results" and
    handle it.
    """

    name = "ddg"

    def __init__(self):
        pass

    def search(self, query: str, top_k: int = DEFAULT_TOP_K) -> list[SearchResult]:
        k = max(1, min(MAX_TOP_K, int(top_k)))
        try:
            with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
                r = client.get(
                    "https://api.duckduckgo.com/",
                    params={
                        "q": query,
                        "format": "json",
                        "no_html": 1,
                        "skip_disambig": 1,
                    },
                    headers=_HTTP_HEADERS,
                )
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPError as exc:
            raise WebSearchError(f"DuckDuckGo IA error: {exc}") from exc

        out: list[SearchResult] = []
        # The "AbstractURL" + "Heading" + "Abstract" combo is the top hit
        # when DDG has an instant answer — surface it as rank 0.
        if data.get("AbstractURL") and data.get("Heading"):
            out.append(
                SearchResult(
                    title=str(data["Heading"]).strip(),
                    url=str(data["AbstractURL"]).strip(),
                    snippet=str(data.get("Abstract") or "").strip()[:400],
                    rank=0,
                )
            )
        # RelatedTopics — flatten one level of "Topics" subgroups.
        related = data.get("RelatedTopics") or []
        flat: list[dict] = []
        for entry in related:
            if "Topics" in entry:
                flat.extend(entry["Topics"])
            else:
                flat.append(entry)
        for r in flat:
            url = str(r.get("FirstURL") or "").strip()
            if not url:
                continue
            out.append(
                SearchResult(
                    title=_first_line(str(r.get("Text") or "")),
                    url=url,
                    snippet=str(r.get("Text") or "").strip()[:400],
                    rank=len(out),
                )
            )
            if len(out) >= k:
                break
        return out[:k]


def _first_line(s: str) -> str:
    if not s:
        return ""
    head = s.split(" - ", 1)[0]  # DDG's "Title - desc" pattern
    return head.split("\n", 1)[0].strip()


# ---------------------------------------------------------------- factory


def pick_provider(cfg) -> SearchProvider:
    """Resolve a SearchProvider from a WebSearchConfig.

    Auto mode (`provider == ""`):
      1. brave_api_key set → Brave
      2. tavily_api_key set → Tavily
      3. searx_url set → Searx
      4. else → DDG IA (zero-setup fallback)

    Explicit mode (`provider in {"brave","tavily","searx","ddg"}`):
      construct that one; raises WebSearchUnconfigured if the matching
      key/url is missing.
    """
    name = (cfg.provider or "").strip().lower()
    if name == "brave":
        return BraveSearch(cfg.brave_api_key)
    if name == "tavily":
        return TavilySearch(cfg.tavily_api_key)
    if name == "searx":
        return SearxSearch(cfg.searx_url)
    if name == "ddg":
        return DDGInstantAnswer()
    if name and name not in {"brave", "tavily", "searx", "ddg", ""}:
        raise WebSearchError(f"unknown web_search.provider: {name!r}")

    # auto
    if cfg.brave_api_key:
        return BraveSearch(cfg.brave_api_key)
    if cfg.tavily_api_key:
        return TavilySearch(cfg.tavily_api_key)
    if cfg.searx_url:
        return SearxSearch(cfg.searx_url)
    return DDGInstantAnswer()
