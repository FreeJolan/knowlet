"""Tests for M4 — mining tasks, drafts, runner, atomic tools, web endpoints.

Stubs the LLM and the source fetcher so tests don't hit the network.
"""

import json
from pathlib import Path
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from knowlet.config import KnowletConfig, save_config
from knowlet.core.drafts import Draft, DraftStore
from knowlet.core.llm import AssistantMessage
from knowlet.core.mining.extractor import extract_one
from knowlet.core.mining.runner import run_task
from knowlet.core.mining.scheduler import MiningScheduler
from knowlet.core.mining.sources import SourceItem
from knowlet.core.mining.task import (
    MiningTask,
    Schedule,
    SourceSpec,
    parse_interval_seconds,
)
from knowlet.core.mining.tasks import TaskStore
from knowlet.core.note import Note
from knowlet.core.vault import Vault
from knowlet.web.server import create_app


def _ready_vault(tmp_path: Path) -> tuple[Vault, KnowletConfig]:
    v = Vault(tmp_path)
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = "stub"
    save_config(v.root, cfg)
    return v, cfg


# ------------------------------------------------------- task module


def test_parse_interval_seconds():
    assert parse_interval_seconds("30s") == 30
    assert parse_interval_seconds("15m") == 900
    assert parse_interval_seconds("2h") == 7200
    assert parse_interval_seconds("1d") == 86400
    with pytest.raises(ValueError):
        parse_interval_seconds("forever")


def test_source_spec_parse_dict_or_str():
    assert SourceSpec.parse({"rss": "https://x"}).type == "rss"
    assert SourceSpec.parse({"url": "https://x"}).type == "url"
    assert SourceSpec.parse("https://bare").type == "url"
    with pytest.raises(ValueError):
        SourceSpec.parse({"weird": "x"})


def test_mining_task_round_trip(tmp_path: Path):
    t = MiningTask(
        name="AI papers",
        sources=[SourceSpec(type="rss", url="https://feed/a"), SourceSpec(type="url", url="https://x")],
        schedule=Schedule(every="1h"),
        prompt="summarize each item",
        body="some explanation",
        output_language="zh",
    )
    p = tmp_path / t.filename
    p.write_text(t.to_markdown(), encoding="utf-8")
    loaded = MiningTask.from_file(p)
    assert loaded.id == t.id
    assert loaded.name == "AI papers"
    assert len(loaded.sources) == 2
    assert loaded.schedule.every == "1h"
    assert loaded.prompt == "summarize each item"
    assert loaded.output_language == "zh"


def test_mining_task_default_output_language_is_none(tmp_path: Path):
    t = MiningTask(name="x", sources=[SourceSpec(type="rss", url="https://x")], prompt="p")
    p = tmp_path / t.filename
    p.write_text(t.to_markdown(), encoding="utf-8")
    loaded = MiningTask.from_file(p)
    assert loaded.output_language is None


def test_mining_task_validate():
    t = MiningTask()
    assert "name is empty" in t.validate()
    t.name = "x"
    assert "at least one source is required" in t.validate()
    t.sources = [SourceSpec(type="rss", url="https://feed")]
    assert "prompt is empty" in t.validate()
    t.prompt = "summarize"
    t.schedule = Schedule(every="1h", cron="0 * * * *")
    assert any("both" in p for p in t.validate())


# ------------------------------------------------------- TaskStore


def test_task_store_save_get_list_delete(tmp_path: Path):
    store = TaskStore(tmp_path / "tasks")
    t = MiningTask(
        name="t1",
        sources=[SourceSpec(type="rss", url="https://feed")],
        prompt="p",
    )
    store.save(t)
    assert store.get(t.id) is not None
    assert store.get(t.id[:8]) is not None  # prefix lookup
    listed = store.list()
    assert len(listed) == 1
    assert store.delete(t.id) is True
    assert store.list() == []


def test_task_store_rename_on_save(tmp_path: Path):
    store = TaskStore(tmp_path / "tasks")
    t = MiningTask(name="old", sources=[SourceSpec(type="rss", url="https://x")], prompt="p")
    p1 = store.save(t)
    t.name = "new"
    p2 = store.save(t)
    assert p1 != p2
    assert not p1.exists()
    assert p2.exists()


# ------------------------------------------------------- Draft + DraftStore


def test_draft_round_trip(tmp_path: Path):
    d = Draft(title="hi", body="body", tags=["a"], source="https://src", task_id="task-x")
    store = DraftStore(tmp_path / "drafts")
    p = store.save(d)
    loaded = Draft.from_file(p)
    assert loaded.title == "hi"
    assert loaded.tags == ["a"]
    assert loaded.source == "https://src"
    assert loaded.task_id == "task-x"


def test_draft_to_note():
    d = Draft(id="abc", title="hi", body="b", tags=["t"], source="https://x")
    n = d.to_note()
    assert isinstance(n, Note)
    assert n.id == "abc"
    assert n.title == "hi"
    assert n.source == "https://x"


def test_draft_store_list_get_delete(tmp_path: Path):
    store = DraftStore(tmp_path / "drafts")
    d1 = Draft(title="A", body="x")
    d2 = Draft(title="B", body="y")
    store.save(d1)
    store.save(d2)
    listed = store.list()
    assert len(listed) == 2
    assert store.get(d1.id) is not None
    assert store.delete(d1.id) is True
    assert store.delete(d1.id) is False  # idempotent
    assert len(store.list()) == 1


# ------------------------------------------------------- runner


class StubLLM:
    def __init__(self, scripted: list[AssistantMessage]):
        self.scripted = list(scripted)

    def chat(self, messages, tools=None, max_tokens=None, temperature=None):
        return self.scripted.pop(0)


def _stub_fetch(items_by_url: dict[str, list[SourceItem]]):
    def fake(spec: SourceSpec):
        return items_by_url.get(spec.url, [])

    return fake


def _good_extraction_response(title: str, body: str = "## Summary\nfoo") -> AssistantMessage:
    payload = {"title": title, "tags": ["t1"], "body": body}
    return AssistantMessage(content=json.dumps(payload), tool_calls=[])


def test_runner_creates_drafts_for_new_items(tmp_path: Path, monkeypatch):
    v, cfg = _ready_vault(tmp_path)
    items = [
        SourceItem(
            source_url="https://feed",
            item_id="item-1",
            title="A",
            url="https://x/1",
            published=None,
            content="content one " * 10,
        ),
        SourceItem(
            source_url="https://feed",
            item_id="item-2",
            title="B",
            url="https://x/2",
            published=None,
            content="content two " * 10,
        ),
    ]
    monkeypatch.setattr(
        "knowlet.core.mining.runner.fetch_source",
        _stub_fetch({"https://feed": items}),
    )

    task = MiningTask(
        name="t",
        sources=[SourceSpec(type="rss", url="https://feed")],
        schedule=Schedule(every="1h"),
        prompt="summarize",
    )
    llm = StubLLM(
        [_good_extraction_response("Draft A"), _good_extraction_response("Draft B")]
    )
    report = run_task(task, v, llm)  # type: ignore[arg-type]
    assert report.fetched == 2
    assert report.new_items == 2
    assert report.drafts_created == 2
    assert not report.errors
    drafts = DraftStore(v.drafts_dir).list()
    assert {d.title for d in drafts} == {"Draft A", "Draft B"}


def test_runner_skips_already_seen(tmp_path: Path, monkeypatch):
    v, cfg = _ready_vault(tmp_path)
    items = [
        SourceItem(
            source_url="https://feed",
            item_id="dup",
            title="X",
            url="https://x",
            published=None,
            content="hello world " * 30,
        )
    ]
    monkeypatch.setattr(
        "knowlet.core.mining.runner.fetch_source",
        _stub_fetch({"https://feed": items}),
    )

    task = MiningTask(
        name="t",
        sources=[SourceSpec(type="rss", url="https://feed")],
        prompt="summarize",
    )
    llm1 = StubLLM([_good_extraction_response("Once")])
    r1 = run_task(task, v, llm1)
    assert r1.drafts_created == 1

    llm2 = StubLLM([])  # would error if called
    r2 = run_task(task, v, llm2)
    assert r2.fetched == 1
    assert r2.new_items == 0
    assert r2.drafts_created == 0


def test_runner_fetch_error_surfaces(tmp_path: Path, monkeypatch):
    v, cfg = _ready_vault(tmp_path)

    def explode(spec: SourceSpec):
        raise RuntimeError("network down")

    monkeypatch.setattr("knowlet.core.mining.runner.fetch_source", explode)

    task = MiningTask(
        name="t",
        sources=[SourceSpec(type="rss", url="https://feed")],
        prompt="summarize",
    )
    report = run_task(task, v, StubLLM([]))  # type: ignore[arg-type]
    assert report.fetched == 0
    assert any("network down" in e for e in report.errors)


def test_extract_one_handles_empty_llm_reply(tmp_path: Path):
    item = SourceItem(
        source_url="https://x",
        item_id="i",
        title="t",
        url="https://x",
        published=None,
        content="some content",
    )
    task = MiningTask(name="t", prompt="p")
    res = extract_one(task, item, StubLLM([AssistantMessage(content="", tool_calls=[])]))  # type: ignore[arg-type]
    assert res.draft is None
    assert "empty" in (res.error or "").lower()


def test_extract_one_with_output_language_injects_translation_directive(tmp_path: Path):
    """Verify the LLM message embeds a 'translate to Chinese' instruction."""
    item = SourceItem(
        source_url="https://x",
        item_id="i",
        title="t",
        url="https://x",
        published=None,
        content="some english content",
    )
    task = MiningTask(name="t", prompt="p")
    captured: list[list[dict]] = []

    class CapturingLLM:
        def chat(self, messages, tools=None, max_tokens=None, temperature=None):
            captured.append(messages)
            return AssistantMessage(
                content='{"title": "标题", "tags": [], "body": "主体"}',
                tool_calls=[],
            )

    res = extract_one(task, item, CapturingLLM(), output_language="zh")  # type: ignore[arg-type]
    assert res.draft is not None
    user_msg = captured[0][0]["content"]
    assert "Chinese" in user_msg or "中文" in user_msg
    assert "Translate" in user_msg


def test_extract_one_without_output_language_keeps_source_language(tmp_path: Path):
    item = SourceItem(
        source_url="https://x",
        item_id="i",
        title="t",
        url="https://x",
        published=None,
        content="some content",
    )
    task = MiningTask(name="t", prompt="p")  # no output_language set
    captured: list[str] = []

    class CapturingLLM:
        def chat(self, messages, tools=None, max_tokens=None, temperature=None):
            captured.append(messages[0]["content"])
            return AssistantMessage(
                content='{"title": "X", "tags": [], "body": "y"}', tool_calls=[]
            )

    extract_one(task, item, CapturingLLM())  # type: ignore[arg-type]
    assert "Translate" not in captured[0]
    assert "in the source's main language" in captured[0]


def test_runner_passes_default_output_language(tmp_path: Path, monkeypatch):
    v, _ = _ready_vault(tmp_path)
    items = [
        SourceItem(
            source_url="https://feed",
            item_id="x1",
            title="english title",
            url="https://x",
            published=None,
            content="hello world " * 30,
        )
    ]
    monkeypatch.setattr(
        "knowlet.core.mining.runner.fetch_source",
        _stub_fetch({"https://feed": items}),
    )

    captured: list[str] = []

    class CapturingLLM:
        def chat(self, messages, tools=None, max_tokens=None, temperature=None):
            captured.append(messages[0]["content"])
            return AssistantMessage(
                content='{"title": "标题", "tags": [], "body": "主体"}',
                tool_calls=[],
            )

    task = MiningTask(
        name="t",
        sources=[SourceSpec(type="rss", url="https://feed")],
        prompt="summarize",
    )
    run_task(task, v, CapturingLLM(), default_output_language="zh")  # type: ignore[arg-type]
    assert captured  # at least one extraction call
    assert "Chinese" in captured[0] or "中文" in captured[0]


def test_runner_task_lang_overrides_default(tmp_path: Path, monkeypatch):
    """Task-level output_language wins over the run-time default."""
    v, _ = _ready_vault(tmp_path)
    items = [
        SourceItem(
            source_url="https://feed",
            item_id="x1",
            title="title",
            url="https://x",
            published=None,
            content="content " * 30,
        )
    ]
    monkeypatch.setattr(
        "knowlet.core.mining.runner.fetch_source",
        _stub_fetch({"https://feed": items}),
    )

    captured: list[str] = []

    class CapturingLLM:
        def chat(self, messages, tools=None, max_tokens=None, temperature=None):
            captured.append(messages[0]["content"])
            return AssistantMessage(
                content='{"title": "X", "tags": [], "body": "Y"}', tool_calls=[]
            )

    task = MiningTask(
        name="t",
        sources=[SourceSpec(type="rss", url="https://feed")],
        prompt="p",
        output_language="en",  # explicit on task
    )
    # default says zh, but task says en — task wins
    run_task(task, v, CapturingLLM(), default_output_language="zh")  # type: ignore[arg-type]
    assert "English" in captured[0]
    assert "Chinese" not in captured[0]


# ------------------------------------------------------- scheduler


def test_scheduler_trigger_for_interval_and_cron(tmp_path: Path):
    v, _ = _ready_vault(tmp_path)
    sched = MiningScheduler(v, llm=mock.Mock())

    t_int = MiningTask(
        name="i",
        sources=[SourceSpec(type="rss", url="https://x")],
        prompt="p",
        schedule=Schedule(every="1h"),
    )
    trigger = sched._trigger_for(t_int)
    assert trigger is not None
    assert trigger.__class__.__name__ == "IntervalTrigger"

    t_cron = MiningTask(
        name="c",
        sources=[SourceSpec(type="rss", url="https://x")],
        prompt="p",
        schedule=Schedule(cron="0 9 * * *"),
    )
    trigger = sched._trigger_for(t_cron)
    assert trigger is not None
    assert trigger.__class__.__name__ == "CronTrigger"


def test_scheduler_start_loads_enabled_only(tmp_path: Path):
    v, _ = _ready_vault(tmp_path)
    store = TaskStore(v.tasks_dir)
    store.save(
        MiningTask(
            name="on",
            sources=[SourceSpec(type="rss", url="https://x")],
            prompt="p",
            schedule=Schedule(every="1h"),
            enabled=True,
        )
    )
    store.save(
        MiningTask(
            name="off",
            sources=[SourceSpec(type="rss", url="https://x")],
            prompt="p",
            schedule=Schedule(every="1h"),
            enabled=False,
        )
    )

    sched = MiningScheduler(v, llm=mock.Mock())
    try:
        scheduled = sched.start()
        assert scheduled == 1
    finally:
        sched.shutdown()


# ------------------------------------------------------- web endpoints


def test_web_create_list_get_update_delete_task(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    client = TestClient(create_app(v, cfg))
    payload = {
        "name": "AI papers",
        "sources": [{"rss": "https://arxiv.org/rss/cs.AI"}],
        "schedule": {"every": "1h"},
        "prompt": "summarize",
        "enabled": True,
        "body": "",
    }
    full = client.post("/api/mining/tasks", json=payload).json()
    assert full["name"] == "AI papers"
    listed = client.get("/api/mining/tasks").json()
    assert any(t["id"] == full["id"] for t in listed)

    fetched = client.get(f"/api/mining/tasks/{full['id']}").json()
    assert fetched["prompt"] == "summarize"

    upd = dict(payload, name="renamed")
    out = client.put(f"/api/mining/tasks/{full['id']}", json=upd).json()
    assert out["name"] == "renamed"

    r = client.delete(f"/api/mining/tasks/{full['id']}")
    assert r.status_code == 200
    assert client.get("/api/mining/tasks").json() == []


def test_web_run_task_uses_stub_llm(tmp_path: Path, monkeypatch):
    v, cfg = _ready_vault(tmp_path)
    items = [
        SourceItem(
            source_url="https://feed",
            item_id="x1",
            title="x",
            url="https://x",
            published=None,
            content="hi " * 30,
        )
    ]
    monkeypatch.setattr(
        "knowlet.core.mining.runner.fetch_source",
        _stub_fetch({"https://feed": items}),
    )

    app = create_app(v, cfg)
    client = TestClient(app)
    state = app.state.web_state
    runtime = state.runtime_or_init()
    runtime.llm = StubLLM([_good_extraction_response("D1")])  # type: ignore[assignment]

    full = client.post(
        "/api/mining/tasks",
        json={
            "name": "t",
            "sources": [{"rss": "https://feed"}],
            "schedule": {"every": "1h"},
            "prompt": "p",
            "enabled": True,
            "body": "",
        },
    ).json()
    report = client.post(f"/api/mining/tasks/{full['id']}/run").json()
    assert report["drafts_created"] == 1


def test_web_drafts_round_trip(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    DraftStore(v.drafts_dir).save(
        Draft(title="hi", body="hello world", tags=["t"], source="https://x")
    )
    client = TestClient(create_app(v, cfg))
    drafts = client.get("/api/drafts").json()
    assert len(drafts) == 1
    did = drafts[0]["id"]
    full = client.get(f"/api/drafts/{did}").json()
    assert full["body"] == "hello world"

    out = client.post(f"/api/drafts/{did}/approve").json()
    assert out["note_id"]
    assert client.get("/api/drafts").json() == []
    # Approved → now appears in /api/notes
    notes = client.get("/api/notes").json()
    assert any(n["id"] == out["note_id"] for n in notes)


def test_web_drafts_reject(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    DraftStore(v.drafts_dir).save(Draft(title="x", body="y"))
    client = TestClient(create_app(v, cfg))
    drafts = client.get("/api/drafts").json()
    did = drafts[0]["id"]
    r = client.post(f"/api/drafts/{did}/reject")
    assert r.status_code == 200
    assert client.get("/api/drafts").json() == []
    r = client.post(f"/api/drafts/{did}/reject")
    assert r.status_code == 404


def test_web_task_validation(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    client = TestClient(create_app(v, cfg))
    r = client.post(
        "/api/mining/tasks",
        json={"name": "", "sources": [], "schedule": {}, "prompt": "", "enabled": True, "body": ""},
    )
    assert r.status_code == 400
