"""run_task — orchestrates a single mining-task execution.

Steps:
  1. Fetch all source items (RSS + URLs).
  2. Drop items already seen by this task (per-task seen-set in `<vault>/.knowlet/mining/<task_id>.json`).
  3. For each new item, call `extractor.extract_one` to produce a Draft.
  4. Save successful drafts under `<vault>/drafts/`.
  5. Persist the seen-set so the next run skips them.
  6. Return a `RunReport` for telemetry / UI display.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from knowlet.core.drafts import DraftStore
from knowlet.core.llm import LLMClient
from knowlet.core.mining.extractor import extract_one
from knowlet.core.mining.sources import SourceItem, fetch_source
from knowlet.core.mining.task import MiningTask
from knowlet.core.mining.task_store import TaskStore
from knowlet.core.vault import Vault

log = logging.getLogger(__name__)


@dataclass
class RunReport:
    task_id: str
    started_at: str
    finished_at: str
    fetched: int = 0
    new_items: int = 0
    drafts_created: int = 0
    drafts_archived: int = 0  # M6.5: oldest drafts moved to .archive/ to honor max_keep
    skipped_empty: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "fetched": self.fetched,
            "new_items": self.new_items,
            "drafts_created": self.drafts_created,
            "drafts_archived": self.drafts_archived,
            "skipped_empty": self.skipped_empty,
            "errors": list(self.errors),
        }


# ----------------------------------------------------- seen-set persistence


def _seen_set_path(vault: Vault, task_id: str) -> Path:
    return vault.state_dir / "mining" / f"{task_id}.json"


def _load_seen(vault: Vault, task_id: str) -> set[str]:
    p = _seen_set_path(vault, task_id)
    if not p.exists():
        return set()
    try:
        data = json.loads(p.read_text("utf-8"))
        return set(data.get("seen", []))
    except (OSError, json.JSONDecodeError):
        return set()


def _save_seen(vault: Vault, task_id: str, seen: Iterable[str]) -> None:
    """Write-then-rename through a per-writer temp file: a torn seen-set
    loads as empty and would re-extract the whole feed."""
    p = _seen_set_path(vault, task_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"seen": sorted(set(seen))}, ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{p.name}.", suffix=".tmp", dir=p.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, p)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _record_seen(vault: Vault, task_id: str, seen: set[str]) -> None:
    # Union with whatever is on disk now: another process (CLI vs web app)
    # may have recorded ids since this run loaded the set.
    _save_seen(vault, task_id, _load_seen(vault, task_id) | seen)


# ----------------------------------------------------- in-process run guard

_running_guard = threading.Lock()
_running_tasks: set[str] = set()


def is_task_running(task_id: str) -> bool:
    with _running_guard:
        return task_id in _running_tasks


def _try_claim(task_id: str) -> bool:
    with _running_guard:
        if task_id in _running_tasks:
            return False
        _running_tasks.add(task_id)
        return True


def _release(task_id: str) -> None:
    with _running_guard:
        _running_tasks.discard(task_id)


def _persist_pause_state(vault: Vault, task: MiningTask, *, was_enabled: bool) -> None:
    """Write only ``enabled`` / ``paused_reason`` onto the task file as it
    is on disk now. Tasks that only exist in memory are left alone, and so
    is a file whose pause state changed since the caller loaded it (e.g.
    the user paused it explicitly in the meantime)."""
    store = TaskStore(vault.tasks_dir)
    try:
        current = store.get(task.id)
        if current is None or current.enabled != was_enabled:
            return
        if not was_enabled and current.paused_reason != "backlog":
            return
        current.enabled = task.enabled
        current.paused_reason = task.paused_reason
        store.save(current)
    except OSError as exc:
        log.warning("could not persist pause state for task %s: %s", task.id, exc)
        return
    task.path = current.path
    task.updated_at = current.updated_at


def reset_task_state(
    vault: Vault,
    task_id: str,
    drafts: DraftStore | None = None,
    delete_drafts: bool = False,
) -> dict[str, int]:
    """Clear the seen-set for `task_id`, so the next run treats every fetched
    item as new again. If `delete_drafts` is True, also delete every draft
    file produced by this task — useful when the user wants a clean inbox.

    Returns counts of what changed."""
    if drafts is None:
        drafts = DraftStore(vault.root / "drafts")

    seen_path = _seen_set_path(vault, task_id)
    seen_cleared = 0
    if seen_path.exists():
        try:
            seen_cleared = len(json.loads(seen_path.read_text("utf-8")).get("seen", []))
        except (OSError, json.JSONDecodeError):
            seen_cleared = 0
        seen_path.unlink()

    drafts_deleted = 0
    if delete_drafts:
        for d in drafts.all_drafts():
            if d.task_id == task_id:
                drafts.delete(d.id)
                drafts_deleted += 1
    return {
        "seen_cleared": seen_cleared,
        "drafts_deleted": drafts_deleted,
    }


# ----------------------------------------------------- runner


def run_task(
    task: MiningTask,
    vault: Vault,
    llm: LLMClient,
    drafts: DraftStore | None = None,
    default_output_language: str | None = None,
    max_items: int | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> RunReport:
    """Execute one mining task. Pure-function-ish — all side effects go
    through `vault` (drafts dir + .knowlet/mining/seen state).

    `default_output_language` is the fallback when the task itself does not
    set `output_language` — typically the caller passes
    `cfg.general.language` so existing tasks auto-pick up the user's UI
    language without editing each task file.

    `max_items` caps the number of *new* items processed in this run.
    Resolution order: explicit `max_items` arg > `task.max_items_per_run`
    > unlimited. The per-task ceiling protects against an offline daemon
    waking up and processing a multi-day backlog in a single LLM
    avalanche; the explicit arg lets `mining run --limit N` override for
    quick verification.

    `should_stop` is polled between sources and items; when it returns
    True the run records what it finished and returns early (the
    scheduler uses it on shutdown).

    A run of a task that is already running in this process is refused
    (reported as an error) rather than run concurrently."""
    started = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = RunReport(task_id=task.id, started_at=started, finished_at=started)
    if not _try_claim(task.id):
        report.errors.append("task is already running; skipped this run")
        return report
    try:
        _run_claimed(
            task,
            vault,
            llm,
            report,
            drafts=drafts if drafts is not None else DraftStore(vault.root / "drafts"),
            default_output_language=default_output_language,
            max_items=max_items,
            should_stop=should_stop or (lambda: False),
        )
    finally:
        _release(task.id)
    report.finished_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return report


def _run_claimed(
    task: MiningTask,
    vault: Vault,
    llm: LLMClient,
    report: RunReport,
    *,
    drafts: DraftStore,
    default_output_language: str | None,
    max_items: int | None,
    should_stop: Callable[[], bool],
) -> None:
    effective_cap = max_items if max_items is not None else task.max_items_per_run
    effective_lang = task.output_language or default_output_language

    # ADR-0009 amendment A2.3 #3 self-throttle. At the max_pending_drafts
    # ceiling the task auto-pauses (enabled=False, paused_reason="backlog");
    # once the user clears drafts (or turns the throttle off) the next run
    # auto-resumes it. Transitions are written to the task file so the
    # UI / CLI show paused-by-backlog, and the scheduler keeps
    # backlog-paused tasks scheduled so that resume can happen.
    limit = task.max_pending_drafts if (task.max_pending_drafts or 0) > 0 else None
    if limit is not None or task.paused_reason == "backlog":
        live_count = len(drafts.list_for_task(task.id)) if limit is not None else 0
        if task.paused_reason == "backlog" and (limit is None or live_count < limit):
            task.enabled = True
            task.paused_reason = None
            _persist_pause_state(vault, task, was_enabled=False)
        elif (
            limit is not None
            and live_count >= limit
            and (task.enabled or task.paused_reason == "backlog")
        ):
            if task.enabled:
                task.enabled = False
                task.paused_reason = "backlog"
                _persist_pause_state(vault, task, was_enabled=True)
            report.errors.append(
                f"paused-by-backlog: {live_count} pending drafts "
                f"(max_pending_drafts={limit}); "
                f"review or archive some to resume"
            )
            return

    if not task.enabled:
        report.errors.append("task is disabled")
        return

    items: list[SourceItem] = []
    for spec in task.sources:
        if should_stop():
            report.errors.append("interrupted: shutting down")
            return
        try:
            fetched = fetch_source(spec)
        except Exception as exc:
            report.errors.append(f"fetch {spec.type}:{spec.url}: {type(exc).__name__}: {exc}")
            continue
        items.extend(fetched)
    report.fetched = len(items)

    seen = _load_seen(vault, task.id)
    new_items = [it for it in items if it.item_id not in seen]
    if effective_cap is not None and len(new_items) > effective_cap:
        new_items = new_items[: int(effective_cap)]
    report.new_items = len(new_items)

    # Seen ids are recorded after every item (not once at the end) so a
    # crash / kill mid-run never re-extracts items that already produced
    # a draft.
    for item in new_items:
        if should_stop():
            report.errors.append("interrupted: shutting down")
            break
        result = extract_one(task, item, llm, output_language=effective_lang)
        if result.error:
            if result.error == "empty source content" or "LLM declined" in result.error:
                report.skipped_empty += 1
            else:
                report.errors.append(f"item {item.item_id!r}: {result.error}")
            # Mark even failed ones to avoid loops.
        elif result.draft is not None:
            drafts.save(result.draft)
            report.drafts_created += 1
        else:
            continue
        seen.add(item.item_id)
        _record_seen(vault, task.id, seen)

    # Honor `max_keep`: archive oldest drafts produced by this task once
    # the live queue exceeds the threshold (M6.5 / ADR-0011 §6).
    if task.max_keep is not None and task.max_keep > 0:
        report.drafts_archived = drafts.enforce_max_keep(task.id, task.max_keep)
