"""Tests for Stage C1 — digest source configuration.

Digest sources are intentionally a thin product wrapper over the
existing MiningTask runner/scheduler: C1 configures RSS/URL sources and
schedule, C2 can later render the produced drafts as a digest inbox.
"""

from __future__ import annotations

from typer.testing import CliRunner

from knowlet.cli.main import app
from knowlet.config import KnowletConfig, save_config
from knowlet.core.digest import (
    DIGEST_TASK_MARKER,
    build_digest_task,
    is_digest_task,
    list_digest_tasks,
)
from knowlet.core.mining.scheduler import MiningScheduler
from knowlet.core.mining.task import MiningTask, Schedule, SourceSpec
from knowlet.core.mining.task_store import TaskStore
from knowlet.core.vault import Vault

runner = CliRunner()


def _ready_vault(tmp_path):
    vault = Vault(tmp_path)
    vault.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    save_config(vault.root, cfg)
    return vault


def test_build_digest_task_is_regular_scheduled_mining_task(tmp_path):
    task = build_digest_task(
        name="AI news",
        sources=[
            SourceSpec(type="rss", url="https://example.com/feed.xml"),
            SourceSpec(type="url", url="https://example.com/news"),
        ],
        schedule=Schedule(every="1d"),
        output_language="zh",
    )
    store = TaskStore(tmp_path / "tasks")
    store.save(task)

    loaded = store.get(task.id)
    assert loaded is not None
    assert is_digest_task(loaded)
    assert DIGEST_TASK_MARKER in loaded.body
    assert loaded.schedule.every == "1d"
    assert [s.to_payload() for s in loaded.sources] == [
        {"rss": "https://example.com/feed.xml"},
        {"url": "https://example.com/news"},
    ]
    assert loaded.output_language == "zh"
    assert "digest" in loaded.prompt.lower()


def test_list_digest_tasks_filters_regular_mining_tasks(tmp_path):
    store = TaskStore(tmp_path / "tasks")
    digest = build_digest_task(
        name="Digest",
        sources=[SourceSpec(type="rss", url="https://example.com/feed.xml")],
        schedule=Schedule(every="1d"),
    )
    regular = MiningTask(
        name="Regular mining",
        sources=[SourceSpec(type="rss", url="https://example.com/other.xml")],
        schedule=Schedule(every="1d"),
        prompt="summarize",
    )
    store.save(regular)
    store.save(digest)

    assert [t.id for t in list_digest_tasks(store)] == [digest.id]


def test_digest_task_loads_into_existing_scheduler(tmp_path):
    vault = Vault(tmp_path)
    vault.init_layout()
    store = TaskStore(vault.tasks_dir)
    task = build_digest_task(
        name="Daily digest",
        sources=[SourceSpec(type="rss", url="https://example.com/feed.xml")],
        schedule=Schedule(every="1d"),
    )
    store.save(task)
    scheduler = MiningScheduler(vault, object())  # type: ignore[arg-type]
    try:
        assert scheduler.start() == 1
    finally:
        scheduler.shutdown()


def test_digest_cli_add_list_remove_round_trip(tmp_path, monkeypatch):
    vault = _ready_vault(tmp_path)
    monkeypatch.setenv("KNOWLET_VAULT", str(vault.root))

    created = runner.invoke(
        app,
        [
            "digest",
            "add",
            "--name",
            "Daily AI",
            "--rss",
            "https://example.com/feed.xml",
            "--every",
            "6h",
        ],
    )
    assert created.exit_code == 0, created.stdout
    tasks = list_digest_tasks(TaskStore(vault.tasks_dir))
    assert len(tasks) == 1
    assert tasks[0].name == "Daily AI"
    assert tasks[0].schedule.every == "6h"

    listed = runner.invoke(app, ["digest", "list"])
    assert listed.exit_code == 0, listed.stdout
    assert "Daily AI" in listed.stdout

    removed = runner.invoke(app, ["digest", "remove", tasks[0].id[:8]])
    assert removed.exit_code == 0, removed.stdout
    assert list_digest_tasks(TaskStore(vault.tasks_dir)) == []
