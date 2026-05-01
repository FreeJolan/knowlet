"""APScheduler integration — runs tasks on their declared schedule.

Lifecycle is owned by the FastAPI lifespan in the web layer. CLI mode does
not start the scheduler; users invoke `knowlet mining run-all` directly (or
wire `cron` themselves).

Per ADR-0009:
- BackgroundScheduler runs in-process (same Python process as the web app).
- `misfire_grace_time` is generous (300s) so daemon restarts don't trigger
  bursty catch-up runs of news feeds.
- Each task fires `runner.run_task(...)` with the live LLM client.
- We re-read `<vault>/tasks/*.md` on `start()` and `reload()`; we do NOT
  watch the filesystem (kept minimal for MVP).
"""

from __future__ import annotations

import logging
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from knowlet.core.llm import LLMClient
from knowlet.core.mining.runner import RunReport, run_task
from knowlet.core.mining.task import MiningTask, parse_interval_seconds
from knowlet.core.mining.tasks import TaskStore
from knowlet.core.vault import Vault

log = logging.getLogger(__name__)

JOB_PREFIX = "knowlet.mining."


class MiningScheduler:
    """Owns an APScheduler BackgroundScheduler and the task → job mapping."""

    def __init__(
        self,
        vault: Vault,
        llm: LLMClient,
        on_run: Callable[[MiningTask, RunReport], None] | None = None,
    ):
        self.vault = vault
        self.llm = llm
        self.on_run = on_run
        self._sched: BackgroundScheduler | None = None
        self._task_store = TaskStore(vault.root / "tasks")

    # ----------------------------------------------------- lifecycle

    def start(self) -> int:
        """Start the scheduler if not running and load all enabled tasks.

        Returns the number of jobs scheduled."""
        if self._sched is None:
            self._sched = BackgroundScheduler(timezone="UTC")
            self._sched.start()
        return self._reload_jobs()

    def shutdown(self) -> None:
        if self._sched is not None:
            self._sched.shutdown(wait=False)
            self._sched = None

    @property
    def running(self) -> bool:
        return self._sched is not None and self._sched.running

    # ----------------------------------------------------- jobs

    def reload(self) -> int:
        """Drop all jobs and reload from disk. Use after task add/edit/delete."""
        if self._sched is None:
            return 0
        return self._reload_jobs()

    def _reload_jobs(self) -> int:
        assert self._sched is not None
        for job in list(self._sched.get_jobs()):
            if job.id.startswith(JOB_PREFIX):
                self._sched.remove_job(job.id)
        scheduled = 0
        for task in self._task_store.list():
            if not task.enabled:
                continue
            trigger = self._trigger_for(task)
            if trigger is None:
                log.warning("task %s has no usable schedule; skipping", task.id)
                continue
            problems = task.validate()
            if problems:
                log.warning("task %s invalid: %s", task.id, "; ".join(problems))
                continue
            self._sched.add_job(
                self._run_one,
                trigger=trigger,
                args=[task.id],
                id=f"{JOB_PREFIX}{task.id}",
                name=task.name or task.id,
                misfire_grace_time=300,
                coalesce=True,
                max_instances=1,
            )
            scheduled += 1
        return scheduled

    def _trigger_for(self, task: MiningTask) -> object | None:
        sched = task.schedule
        if sched.cron:
            try:
                return CronTrigger.from_crontab(sched.cron)
            except Exception as exc:  # noqa: BLE001
                log.warning("task %s bad cron %r: %s", task.id, sched.cron, exc)
                return None
        if sched.every:
            try:
                seconds = parse_interval_seconds(sched.every)
                return IntervalTrigger(seconds=seconds)
            except ValueError as exc:
                log.warning("task %s bad interval %r: %s", task.id, sched.every, exc)
                return None
        return None

    # ----------------------------------------------------- job entrypoint

    def _run_one(self, task_id: str) -> None:
        # Re-read from disk on each run so edits land without a reload call.
        task = self._task_store.get(task_id)
        if task is None:
            log.warning("scheduled task %s no longer on disk", task_id)
            return
        if not task.enabled:
            return
        try:
            report = run_task(task, self.vault, self.llm)
        except Exception:  # noqa: BLE001
            log.exception("task %s crashed", task_id)
            return
        if self.on_run is not None:
            try:
                self.on_run(task, report)
            except Exception:  # noqa: BLE001
                log.exception("on_run callback raised for %s", task_id)
