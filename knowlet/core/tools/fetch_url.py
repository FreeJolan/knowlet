"""fetch_url — LLM-callable single-page article fetcher (M7.5, ADR-0017 §5).

Companion to web_search. The LLM gets snippets from web_search, picks
which URLs look genuinely worth reading, and fetches them one by one.

Reuses `core/url_capture.fetch_and_extract` (M7.2) so JS-heavy / paywall
detection + trafilatura behavior stay consistent across the URL-capsule
flow and the tool flow. Same `max_per_turn` budget pool as web_search
shares with itself? No — fetch_url has its own pool so a long answer
that legitimately needs to read 3 articles isn't penalized for the
3 web_search calls that already happened.
"""

from __future__ import annotations

from typing import Any

from knowlet.core.tools._registry import ToolContext, ToolDef
from knowlet.core.url_capture import (
    ExtractionError,
    FetchError,
    fetch_and_extract,
)

_PER_TURN_KEY = "fetch_url"
# Cap on body chars returned to the LLM. Trafilatura can produce 20+ KB
# for a long-form article; that's fine for a single fetch but tokens
# stack quickly across multiple fetches per turn.
_MAX_BODY_CHARS = 6000


def _handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    url = (args.get("url") or "").strip()
    if not url:
        return {
            "error": "url is empty",
            "suggestion": "pass a full http(s):// URL from web_search results",
        }
    if not (url.startswith("http://") or url.startswith("https://")):
        return {
            "error": f"unsupported url: {url!r}",
            "suggestion": "only http(s) URLs are fetchable",
        }

    cap = max(1, int(ctx.config.web_search.max_per_turn))
    used = ctx.per_turn.get(_PER_TURN_KEY, 0)
    if used >= cap:
        return {
            "error": f"fetch_url budget for this turn exhausted ({used}/{cap})",
            "suggestion": "answer with what you have; don't fetch more pages",
        }

    try:
        title, content = fetch_and_extract(url)
    except FetchError as exc:
        return {
            "error": f"fetch failed: {exc}",
            "suggestion": "skip this URL or try a different result",
        }
    except ExtractionError as exc:
        return {
            "error": f"extraction failed: {exc}",
            "suggestion": (
                "this page is JS-heavy / paywalled / non-article; "
                "try a different URL from the search results"
            ),
        }

    ctx.per_turn[_PER_TURN_KEY] = used + 1
    return {
        "url": url,
        "title": title,
        "body": content[:_MAX_BODY_CHARS],
        "truncated": len(content) > _MAX_BODY_CHARS,
        "budget_remaining": cap - (used + 1),
    }


TOOL = ToolDef(
    name="fetch_url",
    description=(
        "Fetch and extract the main article body from a single web URL. "
        "Use this AFTER web_search to deep-read the 1-2 results whose "
        "title+snippet looks most relevant. Returns trafilatura-extracted "
        "plain text (up to 6000 chars; longer articles are truncated). "
        "Skips JS-heavy / paywall pages with a clear error so you can "
        "try a different URL."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "http(s) URL, typically picked from web_search results",
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    },
    handler=_handler,
)
