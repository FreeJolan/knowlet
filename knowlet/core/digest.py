"""Digest sources — product-facing wrapper over MiningTask.

Stage C uses the existing mining runner/scheduler for RSS/URL fetches,
but exposes a narrower "digest source" concept: recurring intake items
that later feed the digest triage UI.
"""

from __future__ import annotations

from collections.abc import Iterable

from knowlet.core.mining.task import MiningTask, Schedule, SourceSpec
from knowlet.core.mining.task_store import TaskStore

DIGEST_TASK_MARKER = "<!-- knowlet:digest-source/v1 -->"

DEFAULT_DIGEST_PROMPT = """\
Create one concise digest draft for this source item.

Optimize the draft for later triage and discussion, not permanent storage:
- lead with what happened / what changed
- preserve concrete claims, numbers, names, and links
- include why it may matter to the user
- avoid generic praise or hype
- keep enough context that the user can decide: skip, save as reference, or internalize
"""


def build_digest_task(
    *,
    name: str,
    sources: Iterable[SourceSpec],
    schedule: Schedule,
    output_language: str | None = None,
    enabled: bool = True,
) -> MiningTask:
    """Build a regular MiningTask tagged as a digest source."""
    return MiningTask(
        name=name,
        enabled=enabled,
        sources=list(sources),
        schedule=schedule,
        prompt=DEFAULT_DIGEST_PROMPT,
        output_language=output_language,
        body=(
            f"{DIGEST_TASK_MARKER}\n\n"
            "This task feeds the Stage C digest inbox. It is stored as a normal "
            "MiningTask so the existing scheduler, runner, seen-set, and draft "
            "review flow remain the single implementation path."
        ),
        max_items_per_run=20,
        max_keep=50,
        max_pending_drafts=20,
    )


def is_digest_task(task: MiningTask) -> bool:
    return DIGEST_TASK_MARKER in (task.body or "")


def list_digest_tasks(store: TaskStore) -> list[MiningTask]:
    return [task for task in store.list() if is_digest_task(task)]
