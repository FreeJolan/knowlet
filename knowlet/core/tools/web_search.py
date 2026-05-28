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

import json
import re
from typing import Any

from knowlet.config import LLMConfig
from knowlet.core.llm import LLMClient, response_has_output_type
from knowlet.core.tools._registry import ToolContext, ToolDef
from knowlet.core.web_search import (
    DEFAULT_TOP_K,
    SearchResult,
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

    hosted_error: str | None = None
    if not (ctx.config.web_search.provider or "").strip():
        try:
            results = _hosted_web_search(ctx.config.llm, query, top_k=top_k)
            ctx.per_turn[_PER_TURN_KEY] = used + 1
            return _payload(
                provider="hosted_web_search",
                query=query,
                results=results,
                budget_remaining=cap - (used + 1),
            )
        except WebSearchError as exc:
            hosted_error = str(exc)

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
        suggestion = "try a different query or answer without web context"
        if hosted_error:
            suggestion += f"; hosted_web_search also failed first: {hosted_error}"
        return {
            "error": f"search failed: {exc}",
            "suggestion": suggestion,
        }

    ctx.per_turn[_PER_TURN_KEY] = used + 1

    return _payload(
        provider=provider.name,
        query=query,
        results=results,
        budget_remaining=cap - (used + 1),
    )


def _payload(
    *,
    provider: str,
    query: str,
    results: list[SearchResult],
    budget_remaining: int,
) -> dict[str, Any]:
    return {
        "provider": provider,
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
        "budget_remaining": budget_remaining,
    }


def _hosted_web_search(
    llm_cfg: LLMConfig,
    query: str,
    *,
    top_k: int,
) -> list[SearchResult]:
    """Use the configured LLM endpoint's hosted Responses web_search.

    This is the primary auto path for cliproxyapi/Codex-style endpoints.
    It deliberately returns the same SearchResult shape as local providers
    so the rest of the tool loop stays unchanged.
    """
    if not llm_cfg.api_key:
        raise WebSearchUnconfigured("LLM api_key is empty")

    prompt = (
        "Use web search to find relevant pages for this query.\n"
        f"Query: {query}\n"
        f"Return at most {top_k} results.\n"
        "Return ONLY valid JSON in this exact shape:\n"
        '{"results":[{"title":"...","url":"https://...","snippet":"..."}]}\n'
        "No prose outside JSON."
    )
    client = LLMClient(llm_cfg)
    last_error: Exception | None = None
    tool_variants: list[list[dict[str, Any]]] = [
        [{"type": "web_search", "external_web_access": True}],
        [{"type": "web_search"}],
        [{"type": "web_search_preview"}],
    ]
    for tools in tool_variants:
        try:
            resp = client.responses(
                prompt,
                tools=tools,
                max_output_tokens=900,
                role="web_search_tool",
            )
            if not response_has_output_type(resp.raw, "web_search_call"):
                raise WebSearchError("Responses returned no web_search_call")
            results = _parse_hosted_results(resp.content, top_k=top_k)
            if results:
                return results
            raise WebSearchError("hosted search returned no parseable results")
        except Exception as exc:
            last_error = exc
    assert last_error is not None
    raise WebSearchError(f"hosted web_search failed: {last_error}") from last_error


def _parse_hosted_results(content: str, *, top_k: int) -> list[SearchResult]:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        text = text.removeprefix("json").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return _results_from_urls(text, top_k=top_k)
    raw_results = data.get("results") if isinstance(data, dict) else data
    if not isinstance(raw_results, list):
        return _results_from_urls(text, top_k=top_k)
    out: list[SearchResult] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        title = str(item.get("title") or url).strip()
        snippet = str(item.get("snippet") or item.get("description") or "").strip()[:400]
        out.append(SearchResult(title=title, url=url, snippet=snippet, rank=len(out)))
        if len(out) >= top_k:
            break
    return out


def _results_from_urls(text: str, *, top_k: int) -> list[SearchResult]:
    urls = []
    for match in re.finditer(r"https?://[^\s)>\]\"']+", text):
        url = match.group(0).rstrip(".,;")
        if url not in urls:
            urls.append(url)
        if len(urls) >= top_k:
            break
    return [
        SearchResult(title=url, url=url, snippet=text[:400], rank=i)
        for i, url in enumerate(urls)
    ]


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
