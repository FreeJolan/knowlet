"""Stage 3 Step 3.3 — Mining task backlog auto-throttle.

Per ADR-0009 amendment A2.3 #3: a mining task auto-pauses when its
live drafts queue hits ``max_pending_drafts`` (default 5), and auto-
resumes when the user clears some on the next run. The transition is
visible (``task.status`` reflects paused-by-backlog), not silent.
"""

from __future__ import annotations

from pathlib import Path

from knowlet.config import KnowletConfig, save_config
from knowlet.core.drafts import Draft, DraftStore
from knowlet.core.mining.runner import run_task
from knowlet.core.mining.task import MiningTask, SourceSpec
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


class _StubLLM:
    def chat(self, *a, **kw):
        from knowlet.core.llm import AssistantMessage

        return AssistantMessage(content="ok", tool_calls=[])


def _seed_drafts(drafts: DraftStore, *, task_id: str, n: int) -> None:
    for i in range(n):
        drafts.save(
            Draft(
                id=new_id(),
                title=f"draft {i}",
                body="b",
                task_id=task_id,
                created_at=f"2026-05-{i + 1:02d}T00:00:00Z",
            )
        )


# ----------------------------------- status property


def test_status_running_when_enabled() -> None:
    t = MiningTask(name="t", enabled=True)
    assert t.status == "running"


def test_status_paused_by_user_default() -> None:
    t = MiningTask(name="t", enabled=False, paused_reason=None)
    assert t.status == "paused-by-user"


def test_status_paused_by_backlog_when_set() -> None:
    t = MiningTask(name="t", enabled=False, paused_reason="backlog")
    assert t.status == "paused-by-backlog"


# ----------------------------------- auto-pause


def test_auto_pause_when_backlog_hits_limit(tmp_path: Path, monkeypatch) -> None:
    v = _ready_vault(tmp_path)
    drafts = DraftStore(v.drafts_dir)
    _seed_drafts(drafts, task_id="task-1", n=5)
    monkeypatch.setattr("knowlet.core.mining.runner.fetch_source", lambda spec: [])
    task = MiningTask(
        id="task-1",
        name="t",
        sources=[SourceSpec(type="rss", url="https://feed")],
        prompt="p",
        max_pending_drafts=5,
    )
    report = run_task(task, v, _StubLLM())  # type: ignore[arg-type]
    # task auto-paused
    assert task.enabled is False
    assert task.paused_reason == "backlog"
    assert task.status == "paused-by-backlog"
    # report carries the explanatory error per A2.3 visibility
    assert any("paused-by-backlog" in e for e in report.errors)


def test_no_auto_pause_below_limit(tmp_path: Path, monkeypatch) -> None:
    v = _ready_vault(tmp_path)
    drafts = DraftStore(v.drafts_dir)
    _seed_drafts(drafts, task_id="task-2", n=2)
    monkeypatch.setattr("knowlet.core.mining.runner.fetch_source", lambda spec: [])
    task = MiningTask(
        id="task-2",
        name="t",
        sources=[SourceSpec(type="rss", url="https://feed")],
        prompt="p",
        max_pending_drafts=5,
    )
    run_task(task, v, _StubLLM())  # type: ignore[arg-type]
    assert task.enabled is True
    assert task.paused_reason is None
    assert task.status == "running"


def test_max_pending_drafts_none_disables_throttle(tmp_path: Path, monkeypatch) -> None:
    v = _ready_vault(tmp_path)
    drafts = DraftStore(v.drafts_dir)
    _seed_drafts(drafts, task_id="task-3", n=20)
    monkeypatch.setattr("knowlet.core.mining.runner.fetch_source", lambda spec: [])
    task = MiningTask(
        id="task-3",
        name="t",
        sources=[SourceSpec(type="rss", url="https://feed")],
        prompt="p",
        max_pending_drafts=None,  # opt out
    )
    run_task(task, v, _StubLLM())  # type: ignore[arg-type]
    assert task.enabled is True


# ----------------------------------- auto-resume


def test_auto_resume_when_user_clears_backlog(tmp_path: Path, monkeypatch) -> None:
    """A task previously paused-by-backlog auto-resumes once the live
    queue drops below the limit on the next eligible run."""
    v = _ready_vault(tmp_path)
    drafts = DraftStore(v.drafts_dir)
    _seed_drafts(drafts, task_id="task-4", n=2)  # below limit
    monkeypatch.setattr("knowlet.core.mining.runner.fetch_source", lambda spec: [])
    task = MiningTask(
        id="task-4",
        name="t",
        sources=[SourceSpec(type="rss", url="https://feed")],
        prompt="p",
        # Pre-set as if a previous run had paused it.
        enabled=False,
        paused_reason="backlog",
        max_pending_drafts=5,
    )
    run_task(task, v, _StubLLM())  # type: ignore[arg-type]
    assert task.enabled is True
    assert task.paused_reason is None


def test_user_pause_not_auto_resumed(tmp_path: Path, monkeypatch) -> None:
    """A task explicitly paused by the user (paused_reason=None,
    enabled=False) must NOT be auto-resumed by the backlog logic —
    that would override the user's explicit decision."""
    v = _ready_vault(tmp_path)
    monkeypatch.setattr("knowlet.core.mining.runner.fetch_source", lambda spec: [])
    task = MiningTask(
        id="task-5",
        name="t",
        sources=[SourceSpec(type="rss", url="https://feed")],
        prompt="p",
        enabled=False,
        paused_reason=None,  # = paused by user
        max_pending_drafts=5,
    )
    run_task(task, v, _StubLLM())  # type: ignore[arg-type]
    assert task.enabled is False
    assert task.paused_reason is None


# ----------------------------------- frontmatter round-trip


def test_max_pending_drafts_and_paused_reason_round_trip(
    tmp_path: Path,
) -> None:
    task = MiningTask(
        id="rt-task",
        name="rt",
        sources=[],
        prompt="p",
        max_pending_drafts=10,
        paused_reason="backlog",
        enabled=False,
    )
    raw = task.to_markdown()
    assert "max_pending_drafts: 10" in raw
    assert "paused_reason: backlog" in raw
    path = tmp_path / f"{task.filename}"
    path.write_text(raw, encoding="utf-8")
    re_read = MiningTask.from_file(path)
    assert re_read.max_pending_drafts == 10
    assert re_read.paused_reason == "backlog"
    assert re_read.enabled is False
    assert re_read.status == "paused-by-backlog"
