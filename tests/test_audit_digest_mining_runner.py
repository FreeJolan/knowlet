"""Regression tests for mining runner / scheduler / task store (2026-11 audit)."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

import pytest

from knowlet.config import KnowletConfig, save_config
from knowlet.core.drafts import Draft, DraftStore
from knowlet.core.llm import AssistantMessage
from knowlet.core.mining import runner as runner_mod
from knowlet.core.mining import scheduler as scheduler_mod
from knowlet.core.mining.runner import _load_seen, _save_seen, run_task
from knowlet.core.mining.scheduler import JOB_PREFIX, MiningScheduler
from knowlet.core.mining.sources import SourceItem
from knowlet.core.mining.task import MiningTask, Schedule, SourceSpec
from knowlet.core.mining.task_store import TaskStore
from knowlet.core.note import new_id
from knowlet.core.vault import Vault


def _ready_vault(tmp_path: Path) -> Vault:
    v = Vault(tmp_path)
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    save_config(v.root, cfg)
    return v


def _items(n: int) -> list[SourceItem]:
    return [
        SourceItem(
            source_url="https://feed",
            item_id=f"item-{i}",
            title=f"Item {i}",
            url=f"https://x/{i}",
            published=None,
            content=f"content {i} " * 20,
        )
        for i in range(n)
    ]


def _good(title: str) -> AssistantMessage:
    return AssistantMessage(
        content=json.dumps({"title": title, "tags": ["t"], "body": f"body of {title}"}),
        tool_calls=[],
    )


class _CountingLLM:
    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()

    def chat(self, messages, tools=None, max_tokens=None, temperature=None):
        with self._lock:
            self.calls += 1
            n = self.calls
        return _good(f"Draft {n}")


def _task(**overrides) -> MiningTask:
    fields = {
        "name": "feed task",
        "sources": [SourceSpec(type="rss", url="https://feed")],
        "schedule": Schedule(every="1h"),
        "prompt": "summarize",
        "max_pending_drafts": None,
    }
    fields.update(overrides)
    return MiningTask(**fields)


def _seed_drafts(drafts: DraftStore, task_id: str, n: int) -> list[str]:
    ids = []
    for i in range(n):
        d = Draft(id=new_id(), title=f"pending {i}", body="b", task_id=task_id)
        drafts.save(d)
        ids.append(d.id)
    return ids


# ------------------------------------------------------- seen-set atomicity


def test_save_seen_failure_before_rename_keeps_previous_seen_set(tmp_path, monkeypatch):
    v = _ready_vault(tmp_path)
    _save_seen(v, "task-a", ["a", "b"])

    def crash(*args, **kwargs):
        raise OSError("killed mid-write")

    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(OSError):
        _save_seen(v, "task-a", ["a", "b", "c"])
    monkeypatch.undo()
    assert _load_seen(v, "task-a") == {"a", "b"}
    leftovers = [p.name for p in (v.state_dir / "mining").iterdir() if p.suffix != ".json"]
    assert leftovers == []


def test_seen_marks_survive_a_draft_save_failure_mid_run(tmp_path, monkeypatch):
    v = _ready_vault(tmp_path)
    monkeypatch.setattr(runner_mod, "fetch_source", lambda spec: _items(3))
    drafts = DraftStore(v.drafts_dir)
    real_save = drafts.save
    saved: list[str] = []

    def flaky_save(draft):
        if len(saved) == 1:
            raise OSError("disk full")
        saved.append(draft.id)
        return real_save(draft)

    monkeypatch.setattr(drafts, "save", flaky_save)
    task = _task(id="task-b")
    with pytest.raises(OSError):
        run_task(task, v, _CountingLLM(), drafts=drafts)  # type: ignore[arg-type]
    # The item whose draft was saved must not be re-extracted next run.
    assert "item-0" in _load_seen(v, "task-b")


# ------------------------------------------------------- concurrency


def test_concurrent_runs_of_the_same_task_do_not_duplicate_drafts(tmp_path, monkeypatch):
    v = _ready_vault(tmp_path)
    monkeypatch.setattr(runner_mod, "fetch_source", lambda spec: _items(3))
    entered = threading.Event()
    release = threading.Event()

    class BlockingLLM(_CountingLLM):
        def chat(self, messages, tools=None, max_tokens=None, temperature=None):
            entered.set()
            assert release.wait(10)
            return super().chat(messages, tools, max_tokens, temperature)

    task = _task(id="task-c")
    first_report: dict[str, object] = {}

    def first_run() -> None:
        first_report["r"] = run_task(task, v, BlockingLLM())  # type: ignore[arg-type]

    worker = threading.Thread(target=first_run, daemon=True)
    worker.start()
    assert entered.wait(10)
    assert runner_mod.is_task_running("task-c")
    second = run_task(_task(id="task-c"), v, _CountingLLM())  # type: ignore[arg-type]
    release.set()
    worker.join(10)
    assert not worker.is_alive()

    assert second.drafts_created == 0
    assert any("already running" in e for e in second.errors)
    assert not runner_mod.is_task_running("task-c")
    drafts = DraftStore(v.drafts_dir).list_for_task("task-c")
    assert len(drafts) == 3
    assert _load_seen(v, "task-c") == {"item-0", "item-1", "item-2"}


def test_seen_save_merges_ids_written_by_another_process(tmp_path, monkeypatch):
    """A CLI process and the web app can still run the same task; neither
    may drop the other's seen ids."""
    v = _ready_vault(tmp_path)
    items = _items(2)
    monkeypatch.setattr(runner_mod, "fetch_source", lambda spec: items)

    class SideWriterLLM(_CountingLLM):
        def chat(self, messages, tools=None, max_tokens=None, temperature=None):
            # Another process records an id while this run is extracting.
            current = _load_seen(v, "task-d")
            _save_seen(v, "task-d", current | {"other-process-item"})
            return super().chat(messages, tools, max_tokens, temperature)

    run_task(_task(id="task-d"), v, SideWriterLLM())  # type: ignore[arg-type]
    assert _load_seen(v, "task-d") == {"item-0", "item-1", "other-process-item"}


# ------------------------------------------------------- cooperative stop


def test_run_task_stops_between_items_when_asked(tmp_path, monkeypatch):
    v = _ready_vault(tmp_path)
    monkeypatch.setattr(runner_mod, "fetch_source", lambda spec: _items(4))
    llm = _CountingLLM()
    report = run_task(
        _task(id="task-e"),
        v,
        llm,  # type: ignore[arg-type]
        should_stop=lambda: llm.calls >= 1,
    )
    assert llm.calls == 1
    assert report.drafts_created == 1
    assert any("interrupted" in e for e in report.errors)
    assert _load_seen(v, "task-e") == {"item-0"}


def test_scheduler_shutdown_signals_in_flight_runs_to_stop(tmp_path, monkeypatch):
    v = _ready_vault(tmp_path)
    task = _task()
    TaskStore(v.tasks_dir).save(task)
    captured: dict[str, object] = {}

    def fake_run_task(t, vault, llm, **kwargs):
        captured["should_stop"] = kwargs.get("should_stop")
        return runner_mod.RunReport(task_id=t.id, started_at="x", finished_at="x")

    monkeypatch.setattr(scheduler_mod, "run_task", fake_run_task)
    sched = MiningScheduler(v, _CountingLLM())  # type: ignore[arg-type]
    sched.start()
    try:
        sched._run_one(task.id)
        should_stop = captured["should_stop"]
        assert callable(should_stop)
        assert should_stop() is False
    finally:
        sched.shutdown()
    assert should_stop() is True


# ------------------------------------------------------- backlog pause state


def test_backlog_pause_is_persisted_to_the_task_file(tmp_path, monkeypatch):
    v = _ready_vault(tmp_path)
    monkeypatch.setattr(runner_mod, "fetch_source", lambda spec: [])
    store = TaskStore(v.tasks_dir)
    task = _task(max_pending_drafts=2)
    store.save(task)
    _seed_drafts(DraftStore(v.drafts_dir), task.id, 2)

    report = run_task(store.get(task.id), v, _CountingLLM())  # type: ignore[arg-type]
    assert any("paused-by-backlog" in e for e in report.errors)
    on_disk = store.get(task.id)
    assert on_disk is not None
    assert on_disk.enabled is False
    assert on_disk.paused_reason == "backlog"
    assert on_disk.status == "paused-by-backlog"


def test_scheduler_auto_resumes_backlog_paused_task(tmp_path, monkeypatch, caplog):
    v = _ready_vault(tmp_path)
    monkeypatch.setattr(runner_mod, "fetch_source", lambda spec: [])
    store = TaskStore(v.tasks_dir)
    drafts = DraftStore(v.drafts_dir)
    task = _task(max_pending_drafts=2)
    store.save(task)
    user_paused = _task(name="user paused", enabled=False)
    store.save(user_paused)
    seeded = _seed_drafts(drafts, task.id, 2)

    sched = MiningScheduler(v, _CountingLLM())  # type: ignore[arg-type]
    try:
        assert sched.start() == 1
        with caplog.at_level(logging.WARNING, logger=scheduler_mod.__name__):
            sched._run_one(task.id)
        assert store.get(task.id).status == "paused-by-backlog"
        assert any("paused-by-backlog" in rec.getMessage() for rec in caplog.records)

        # Backlog-paused tasks keep their job so a later tick can resume them;
        # user-paused tasks stay unscheduled.
        assert sched.reload() == 1
        job_ids = {job.id for job in sched._sched.get_jobs()}
        assert f"{JOB_PREFIX}{task.id}" in job_ids
        assert f"{JOB_PREFIX}{user_paused.id}" not in job_ids

        drafts.delete(seeded[0])
        sched._run_one(task.id)
        resumed = store.get(task.id)
        assert resumed.enabled is True
        assert resumed.paused_reason is None
        assert resumed.status == "running"
        assert store.get(user_paused.id).status == "paused-by-user"
    finally:
        sched.shutdown()


def test_backlog_paused_task_resumes_when_throttle_is_turned_off(tmp_path, monkeypatch):
    v = _ready_vault(tmp_path)
    monkeypatch.setattr(runner_mod, "fetch_source", lambda spec: [])
    task = _task(enabled=False, paused_reason="backlog", max_pending_drafts=None)
    run_task(task, v, _CountingLLM())  # type: ignore[arg-type]
    assert task.enabled is True
    assert task.paused_reason is None


# ------------------------------------------------------- id prefix lookup


def test_task_store_get_rejects_ambiguous_prefix_and_prefers_exact(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    store.save(_task(id="01AAA", name="first"))
    store.save(_task(id="01AAB", name="second"))
    store.save(_task(id="01AAAZ", name="third"))

    with pytest.raises(LookupError) as excinfo:
        store.get("01A")
    assert "01AAA" in str(excinfo.value) and "01AAB" in str(excinfo.value)
    assert store.get("01AAA").name == "first"  # exact beats the 01AAAZ prefix hit
    assert store.get("01AAB").name == "second"
    assert store.get("01AAAZ").name == "third"
    assert store.get("") is None
    assert store.get("zzz") is None


def test_task_store_delete_with_ambiguous_prefix_deletes_nothing(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    store.save(_task(id="01AAA", name="first"))
    store.save(_task(id="01AAB", name="second"))
    with pytest.raises(LookupError):
        store.delete("01")
    assert len(list(store.iter_paths())) == 2
    assert store.delete("") is False
    assert len(list(store.iter_paths())) == 2


def test_auto_resume_does_not_override_a_user_pause_made_meanwhile(tmp_path, monkeypatch):
    v = _ready_vault(tmp_path)
    monkeypatch.setattr(runner_mod, "fetch_source", lambda spec: [])
    store = TaskStore(v.tasks_dir)
    task = _task(enabled=False, paused_reason="backlog", max_pending_drafts=5)
    store.save(task)
    stale = store.get(task.id)
    # The user pauses the task explicitly after the caller loaded it.
    user_paused = store.get(task.id)
    user_paused.paused_reason = None
    store.save(user_paused)

    run_task(stale, v, _CountingLLM())  # type: ignore[arg-type]
    on_disk = store.get(task.id)
    assert on_disk.enabled is False
    assert on_disk.status == "paused-by-user"
