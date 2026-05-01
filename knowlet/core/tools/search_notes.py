"""search_notes — hybrid retrieval over the user's vault."""

from __future__ import annotations

from typing import Any

from knowlet.core.tools._registry import ToolContext, ToolDef


def _handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    query = (args.get("query") or "").strip()
    limit = int(args.get("limit") or ctx.config.retrieval.top_k)
    if not query:
        return {
            "error": "query is empty",
            "suggestion": "pass a non-empty natural-language query",
        }
    limit = max(1, min(limit, 20))
    hits = ctx.index.search(
        query, top_k=limit, rrf_k=ctx.config.retrieval.rrf_k
    )
    return {
        "results": [
            {
                "note_id": h.note_id,
                "title": h.title,
                "snippet": h.snippet,
                "score": round(h.score, 6),
            }
            for h in hits
        ],
        "count": len(hits),
    }


TOOL = ToolDef(
    name="search_notes",
    description=(
        "Search the user's local knowledge base of Notes. Returns the most "
        "relevant Notes with id, title, and a short snippet. Always call this "
        "before answering a question that may benefit from the user's own notes."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "natural-language query, in Chinese or English",
            },
            "limit": {
                "type": "integer",
                "description": "max number of Notes to return (1-20)",
                "minimum": 1,
                "maximum": 20,
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    handler=_handler,
)
