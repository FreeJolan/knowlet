"""web_search — LLM-callable web search tool (M7.5, ADR-0017).

Two-stage pattern (ADR-0017 §5):
  1. `web_search(query)` returns top-K {title, url, snippet}
  2. `fetch_url(url)` — separate tool — pulls the article body for the
     handful the LLM judges worth deep-reading.

Per-turn budget enforced via ToolContext.per_turn["web_search"] vs
config.web_search.max_per_turn. Over-budget raises a tool error the
LLM can react to (typically: "stop and answer with what you have").
"""

from __future__ import annotations

from typing import Any

from knowlet.core.tools._registry import ToolContext, ToolDef
from knowlet.core.web_search import (
    DEFAULT_TOP_K,
    WebSearchError,
    WebSearchUnconfigured,
    pick_provider,
)

_PER_TURN_KEY = "web_search"


def _handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    query = (args.get("query") or "").strip()
    if not query:
        return {
            "error": "query is empty",
            "suggestion": "pass a non-empty natural-language query",
        }
    top_k = int(args.get("top_k") or DEFAULT_TOP_K)
    top_k = max(1, min(10, top_k))

    cap = max(1, int(ctx.config.web_search.max_per_turn))
    used = ctx.per_turn.get(_PER_TURN_KEY, 0)
    if used >= cap:
        return {
            "error": f"web_search budget for this turn exhausted ({used}/{cap})",
            "suggestion": (
                "stop searching and answer with what you have, or ask the user "
                "to phrase a single more-specific query"
            ),
        }

    try:
        provider = pick_provider(ctx.config.web_search)
    except WebSearchUnconfigured as exc:
        return {
            "error": f"web_search provider not configured: {exc}",
            "suggestion": (
                "ask the user to set web_search.brave_api_key (recommended), "
                "tavily_api_key, or searx_url; the user can also remove the "
                "explicit `provider` field to fall back to DuckDuckGo"
            ),
        }
    except WebSearchError as exc:
        return {
            "error": f"web_search provider error: {exc}",
            "suggestion": "try a different query or skip the search",
        }

    try:
        results = provider.search(query, top_k=top_k)
    except WebSearchUnconfigured as exc:
        return {"error": str(exc), "suggestion": "see web_search config"}
    except WebSearchError as exc:
        return {
            "error": f"search failed: {exc}",
            "suggestion": "try a different query or answer without web context",
        }

    ctx.per_turn[_PER_TURN_KEY] = used + 1

    return {
        "provider": provider.name,
        "query": query,
        "results": [
            {
                "rank": r.rank,
                "title": r.title,
                "url": r.url,
                "snippet": r.snippet,
            }
            for r in results
        ],
        "count": len(results),
        "budget_remaining": cap - (used + 1),
    }


TOOL = ToolDef(
    name="web_search",
    description=(
        "Search the live web for real-time / post-training-cutoff information. "
        "Returns up to top_k results (default 5) as title + url + snippet — "
        "NOT full page bodies. After scanning the snippets, call `fetch_url` "
        "on the 1-2 most relevant URLs to pull article content. Use this tool "
        "ONLY when the user is asking about something that genuinely requires "
        "real-time or recent information (current news, today's prices, the "
        "latest version of a library, etc.). Don't search for things you "
        "already know from training."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "natural-language search query, in the user's language. "
                    "Be specific — vague queries return noise."
                ),
            },
            "top_k": {
                "type": "integer",
                "description": "max results to return (1-10, default 5)",
                "minimum": 1,
                "maximum": 10,
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    handler=_handler,
)
