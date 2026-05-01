"""run_mining_task — execute a configured task immediately."""

from __future__ import annotations

from typing import Any

from knowlet.core.llm import LLMClient
from knowlet.core.mining.runner import run_task
from knowlet.core.tools._registry import ToolContext, ToolDef


def _handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    task_id = (args.get("task_id") or "").strip()
    if not task_id:
        return {
            "error": "task_id is required",
            "suggestion": "call list_mining_tasks to find the id",
        }
    task = ctx.tasks.get(task_id)
    if task is None:
        return {
            "error": f"task not found: {task_id}",
            "suggestion": "call list_mining_tasks for valid ids",
        }
    llm = LLMClient(ctx.config.llm)
    report = run_task(task, ctx.vault, llm, drafts=ctx.drafts)
    return {"report": report.to_dict()}


TOOL = ToolDef(
    name="run_mining_task",
    description=(
        "Run a knowledge-mining task immediately (regardless of schedule). "
        "Fetches all sources, runs the LLM extractor on new items, and saves "
        "drafts under <vault>/drafts/. Returns a structured run report."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "task_id": {
                "type": "string",
                "description": "the mining task ULID (or 8-char prefix accepted)",
            },
        },
        "required": ["task_id"],
        "additionalProperties": False,
    },
    handler=_handler,
)
