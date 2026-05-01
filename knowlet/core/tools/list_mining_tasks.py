"""list_mining_tasks — surface configured knowledge-mining tasks."""

from __future__ import annotations

from typing import Any

from knowlet.core.tools._registry import ToolContext, ToolDef


def _handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    tasks = ctx.tasks.list()
    return {
        "results": [
            {
                "task_id": t.id,
                "name": t.name,
                "enabled": t.enabled,
                "schedule": t.schedule.to_payload(),
                "sources": [s.to_payload() for s in t.sources],
                "updated_at": t.updated_at,
            }
            for t in tasks
        ],
        "count": len(tasks),
    }


TOOL = ToolDef(
    name="list_mining_tasks",
    description=(
        "List the user's configured knowledge-mining tasks (recipes that "
        "fetch sources on a schedule and use an LLM to extract drafts). "
        "Use this when the user asks 'what feeds am I tracking' or wants to "
        "edit / disable a task."
    ),
    input_schema={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    handler=_handler,
)
