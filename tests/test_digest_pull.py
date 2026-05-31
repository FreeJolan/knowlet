"""Stage C v2 C5 — pull and normalize digest sources into Raw Info."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from knowlet.cli.main import app
from knowlet.config import KnowletConfig, save_config
from knowlet.core.digest_items import RawInfo, RawInfoStore
from knowlet.core.digest_pull import maybe_auto_pull_digest_sources, pull_digest_sources
from knowlet.core.digest_sources import DigestSource, DigestSourceStore
from knowlet.core.drafts import Draft, DraftStore
from knowlet.core.events import ReplyChunkEvent, ReplyDoneEvent
from knowlet.core.llm import AssistantMessage, ResponsesMessage
from knowlet.core.mining.sources import SourceItem
from knowlet.core.note import Note
from knowlet.core.vault import Vault
from knowlet.web.server import create_app

runner = CliRunner()


class ScriptedLLM:
    def __init__(self, payloads: list[dict[str, Any]]):
        self.payloads = list(payloads)
        self.messages: list[list[dict[str, Any]]] = []
        self.responses_calls: list[dict[str, Any]] = []

    def chat(self, messages, tools=None, max_tokens=None, temperature=None):
        self.messages.append(messages)
        payload = self.payloads.pop(0)
        return AssistantMessage(content=json.dumps(payload), tool_calls=[])

    def responses(
        self,
        input_text,
        *,
        tools=None,
        max_output_tokens=None,
        role=None,
        temperature=None,
    ):
        self.responses_calls.append(
            {
                "input_text": input_text,
                "tools": tools,
                "max_output_tokens": max_output_tokens,
                "role": role,
                "temperature": temperature,
            }
        )
        payload = self.payloads.pop(0)
        raw: dict[str, Any] = {"output": [{"type": "message"}]}
        if tools:
            raw["output"].insert(0, {"type": "web_search_call"})
        return ResponsesMessage(content=json.dumps(payload), raw=raw)


class StreamingLLM:
    def chat_stream(self, messages, tools=None, max_tokens=None, temperature=None, role=None):
        yield ReplyChunkEvent(text="Raw info answer")
        yield ReplyDoneEvent(final_text="Raw info answer")


def _ready_vault(tmp_path: Path) -> tuple[Vault, KnowletConfig]:
    vault = Vault(tmp_path)
    vault.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = "stub"
    save_config(vault.root, cfg)
    return vault, cfg


def _save_source(vault: Vault, source: DigestSource) -> DigestSource:
    DigestSourceStore(vault.digest_sources_dir).save(source)
    return source


def test_pull_rss_source_creates_raw_info_and_seen_dedupes(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path)
    source = _save_source(
        vault,
        DigestSource(name="AI feed", kind="rss", url="https://example.com/feed.xml"),
    )
    items = [
        SourceItem(
            source_url="https://example.com/feed.xml",
            item_id="entry-1",
            title="Thin RSS title",
            url="https://example.com/a",
            published="2026-05-29",
            content="short summary",
        ),
        SourceItem(
            source_url="https://example.com/feed.xml",
            item_id="entry-2",
            title="Rich RSS title",
            url="https://example.com/b",
            published=None,
            content="rich body " * 80,
        ),
    ]

    def fake_fetch(spec):
        assert spec.type == "rss"
        assert spec.url == "https://example.com/feed.xml"
        return items

    monkeypatch.setattr("knowlet.core.digest_pull.fetch_source", fake_fetch)
    llm = ScriptedLLM(
        [
            {
                "title": "Normalized thin item",
                "summary": "A thin feed item was normalized.",
                "key_points": ["kept original link"],
                "why_it_matters": "It can still be reviewed.",
                "suggested_tags": ["ai"],
                "confidence": "medium",
            },
            {
                "title": "Normalized rich item",
                "summary": "A rich feed item was summarized.",
                "key_points": ["body was available"],
                "why_it_matters": "It is useful for triage.",
                "suggested_tags": ["rss"],
                "confidence": "high",
            },
        ]
    )

    first = pull_digest_sources(vault=vault, llm=llm, source_ids=[source.id])
    assert first.fetched == 2
    assert first.new_items == 2
    assert first.created == 2
    assert not first.paused
    raw_items = RawInfoStore(vault.digest_items_dir).list()
    assert [item.title for item in raw_items] == [
        "Normalized thin item",
        "Normalized rich item",
    ]
    assert raw_items[0].source_id == source.id
    assert raw_items[0].url == "https://example.com/a"
    assert raw_items[0].status == "unprocessed"
    loaded_source = DigestSourceStore(vault.digest_sources_dir).get(source.id)
    assert loaded_source is not None
    assert loaded_source.pull_status == "ok"
    assert loaded_source.last_success_at

    second = pull_digest_sources(vault=vault, llm=llm, source_ids=[source.id])
    assert second.fetched == 2
    assert second.new_items == 0
    assert second.created == 0
    assert RawInfoStore(vault.digest_items_dir).list() == raw_items


def test_prompt_source_uses_wrapped_system_prompt_and_structured_json(tmp_path):
    vault, _cfg = _ready_vault(tmp_path)
    source = _save_source(
        vault,
        DigestSource(
            name="Agent watch",
            kind="prompt",
            prompt="Find important AI agent updates.",
        ),
    )
    llm = ScriptedLLM(
        [
            {
                "items": [
                    {
                        "title": "No URL should be skipped",
                        "summary": "Missing original link.",
                    },
                    {
                        "title": "Agent paper",
                        "url": "https://example.com/paper",
                        "source_name": "Example",
                        "published_at": "2026-05-29",
                        "summary": "A new agent paper shipped.",
                        "key_points": ["new benchmark"],
                        "why_it_matters": "Useful for agent design.",
                        "suggested_tags": ["agents"],
                        "confidence": "high",
                    },
                ],
                "warnings": ["one item had no url"],
            }
        ]
    )

    report = pull_digest_sources(vault=vault, llm=llm, source_ids=[source.id])
    assert report.fetched == 2
    assert report.new_items == 1
    assert report.created == 1
    assert report.skipped == 1
    stored = RawInfoStore(vault.digest_items_dir).list()
    assert len(stored) == 1
    assert stored[0].title == "Agent paper"
    assert stored[0].source_kind == "prompt"
    assert stored[0].summary == "A new agent paper shipped."
    prompt_text = llm.responses_calls[0]["input_text"]
    assert "Knowlet digest source editor" in prompt_text
    assert "Find important AI agent updates." in prompt_text
    assert "Output only strict JSON" in prompt_text
    assert llm.responses_calls[0]["tools"] == [{"type": "web_search", "external_web_access": True}]


def test_prompt_source_warning_without_items_marks_source_error(tmp_path):
    vault, _cfg = _ready_vault(tmp_path)
    source = _save_source(
        vault,
        DigestSource(
            name="Policy watch",
            kind="prompt",
            prompt="获取今日政治新闻",
        ),
    )
    llm = ScriptedLLM(
        [
            {
                "items": [],
                "warnings": ["无法访问实时新闻源或验证今日政治新闻"],
            }
        ]
    )

    report = pull_digest_sources(vault=vault, llm=llm, source_ids=[source.id])

    assert report.created == 0
    assert any("无法访问实时新闻源" in error for error in report.errors)
    loaded = DigestSourceStore(vault.digest_sources_dir).get(source.id)
    assert loaded is not None
    assert loaded.pull_status == "error"
    assert loaded.last_error is not None
    assert "无法访问实时新闻源" in loaded.last_error


def test_pull_pauses_when_pending_raw_info_reaches_limit(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path)
    source = _save_source(
        vault,
        DigestSource(name="AI feed", kind="rss", url="https://example.com/feed.xml"),
    )
    store = RawInfoStore(vault.digest_items_dir)
    for i in range(200):
        store.save(
            RawInfo(
                source_id="existing",
                source_name="Existing",
                source_kind="rss",
                item_key=f"existing-{i}",
                title=f"Existing {i}",
                url=f"https://example.com/{i}",
                summary="pending",
            )
        )

    called = False

    def fake_fetch(_spec):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr("knowlet.core.digest_pull.fetch_source", fake_fetch)

    report = pull_digest_sources(vault=vault, llm=ScriptedLLM([]), source_ids=[source.id])
    assert report.paused is True
    assert report.created == 0
    assert called is False
    loaded_source = DigestSourceStore(vault.digest_sources_dir).get(source.id)
    assert loaded_source is not None
    assert loaded_source.pull_status == "paused"
    assert "200" in (loaded_source.last_error or "")


def test_digest_pull_api_lists_raw_info_items(tmp_path, monkeypatch):
    vault, cfg = _ready_vault(tmp_path)
    source = _save_source(
        vault,
        DigestSource(name="AI feed", kind="rss", url="https://example.com/feed.xml"),
    )
    monkeypatch.setattr(
        "knowlet.core.digest_pull.fetch_source",
        lambda _spec: [
            SourceItem(
                source_url="https://example.com/feed.xml",
                item_id="entry-1",
                title="RSS title",
                url="https://example.com/a",
                published=None,
                content="body",
            )
        ],
    )
    client = TestClient(create_app(vault, cfg))
    runtime = client.app.state.web_state.runtime_or_init()
    runtime.llm = ScriptedLLM(
        [
            {
                "title": "API normalized item",
                "summary": "API pull created this.",
                "key_points": ["api"],
                "why_it_matters": "Visible to inbox.",
                "suggested_tags": ["api"],
                "confidence": "high",
            }
        ]
    )

    pulled = client.post(f"/api/digest/sources/{source.id}/pull")
    assert pulled.status_code == 200, pulled.text
    assert pulled.json()["created"] == 1
    listed = client.get("/api/digest/items")
    assert listed.status_code == 200
    assert listed.json()[0]["title"] == "API normalized item"
    assert listed.json()[0]["source_id"] == source.id


def test_digest_status_api_reports_pending_count_and_source_status(tmp_path):
    vault, cfg = _ready_vault(tmp_path)
    source = DigestSource(name="AI feed", kind="rss", url="https://example.com/feed.xml")
    source.pull_status = "paused"
    source.last_error = "pending raw info reached 200"
    _save_source(vault, source)
    RawInfoStore(vault.digest_items_dir).save(
        RawInfo(
            source_id=source.id,
            source_name=source.name,
            source_kind="rss",
            item_key="rss:test",
            title="Pending raw info",
            url="https://example.com/a",
            summary="Needs review.",
        )
    )
    client = TestClient(create_app(vault, cfg))
    client.app.state.web_state.digest_pull_status = "paused"
    client.app.state.web_state.digest_pull_last_error = "pending raw info reached 200"

    res = client.get("/api/digest/status")
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["status"] == "paused"
    assert payload["pending_count"] == 1
    assert payload["last_error"] == "pending raw info reached 200"
    assert payload["sources"][0]["pull_status"] == "paused"


def test_raw_info_chat_stream_marks_item_discussed(tmp_path):
    vault, cfg = _ready_vault(tmp_path)
    item = RawInfo(
        source_id="source-1",
        source_name="Research Feed",
        source_kind="rss",
        item_key="rss:item",
        title="Raw chat target",
        url="https://example.com/raw",
        summary="A raw info item to discuss.",
        key_points=["keep provenance"],
    )
    RawInfoStore(vault.digest_items_dir).save(item)
    client = TestClient(create_app(vault, cfg))
    runtime = client.app.state.web_state.runtime_or_init()
    runtime.llm = StreamingLLM()

    with client.stream(
        "POST",
        f"/api/chat/raw-info/{item.id}/stream",
        json={"text": "What matters?", "history": []},
    ) as res:
        body = "".join(res.iter_text())

    assert res.status_code == 200, body
    assert "Raw info answer" in body
    loaded = RawInfoStore(vault.digest_items_dir).get(item.id)
    assert loaded is not None
    assert loaded.status == "discussed"


def test_raw_info_draft_api_creates_review_draft_with_library_context(tmp_path):
    vault, cfg = _ready_vault(tmp_path)
    vault.mkdir_folder("ai/research")
    existing = Note(
        id="01C8EXISTINGNOTE000001",
        title="Agent systems map",
        body="Existing note about agent tool traces.",
        tags=["agents", "tooling"],
    )
    existing.path = vault.write_note(existing, folder="ai/research")
    item = RawInfo(
        source_id="source-1",
        source_name="Research Feed",
        source_kind="rss",
        item_key="rss:item",
        title="LangChain trace article",
        url="https://example.com/langchain-trace",
        summary="An article about separating tool trace from final answer.",
        key_points=["trace is not final answer", "tools should remain visible"],
        suggested_tags=["agents"],
        status="discussed",
    )
    RawInfoStore(vault.digest_items_dir).save(item)
    client = TestClient(create_app(vault, cfg))
    runtime = client.app.state.web_state.runtime_or_init()
    runtime.llm = ScriptedLLM(
        [
            {
                "title": "Tool Trace Separation",
                "body": "## 核心\n\n工具调用轨迹应该和最终答案分开展示。\n",
                "tags": ["agents", "tooling", "langchain"],
                "kind": "knowledge",
                "folder": "ai/research",
                "rationale": "The discussion added durable design judgement.",
            }
        ]
    )
    runtime.ctx.llm = runtime.llm

    res = client.post(
        f"/api/digest/items/{item.id}/draft",
        json={
            "history": [
                {"role": "user", "content": "这对我们工具 trace UI 有什么启发?"},
                {"role": "assistant", "content": "可以把 trace 和 answer 分开。"},
            ]
        },
    )

    assert res.status_code == 200, res.text
    payload = res.json()
    draft = payload["draft"]
    assert draft["title"] == "Tool Trace Separation"
    assert draft["kind"] == "knowledge"
    assert draft["folder"] == "ai/research"
    assert "langchain" in draft["tags"]
    stored_draft = DraftStore(vault.drafts_dir).get(draft["id"])
    assert stored_draft is not None
    assert stored_draft.folder == "ai/research"
    assert stored_draft.source == "https://example.com/langchain-trace"
    loaded = RawInfoStore(vault.digest_items_dir).get(item.id)
    assert loaded is not None
    assert loaded.status == "drafted"
    assert loaded.note_draft_id == draft["id"]
    assert len(list(vault.iter_note_paths())) == 1
    prompt = runtime.llm.messages[0][-1]["content"]
    assert "Existing tags" in prompt
    assert "agents" in prompt
    assert "ai/research" in prompt
    assert "资料" in prompt and "知识" in prompt

    updated = client.put(
        f"/api/drafts/{draft['id']}",
        json={
            "title": "Tool Trace Notes",
            "tags": ["agents", "notes"],
            "kind": "reference",
            "folder": "ai/notes",
        },
    )
    assert updated.status_code == 200, updated.text
    updated_payload = updated.json()
    assert updated_payload["title"] == "Tool Trace Notes"
    assert updated_payload["tags"] == ["agents", "notes"]
    assert updated_payload["kind"] == "reference"
    assert updated_payload["folder"] == "ai/notes"
    stored_draft = DraftStore(vault.drafts_dir).get(draft["id"])
    assert stored_draft is not None
    assert stored_draft.folder == "ai/notes"


def test_raw_info_draft_api_rejects_invalid_llm_payload_without_writing(tmp_path):
    vault, cfg = _ready_vault(tmp_path)
    item = RawInfo(
        source_id="source-1",
        source_name="Research Feed",
        source_kind="rss",
        item_key="rss:item",
        title="Invalid draft target",
        url="https://example.com/invalid",
        summary="A raw info item.",
    )
    RawInfoStore(vault.digest_items_dir).save(item)
    client = TestClient(create_app(vault, cfg))
    runtime = client.app.state.web_state.runtime_or_init()
    runtime.llm = ScriptedLLM([{"title": "", "body": "", "tags": [], "kind": "maybe"}])
    runtime.ctx.llm = runtime.llm

    res = client.post(f"/api/digest/items/{item.id}/draft", json={"history": []})

    assert res.status_code == 502, res.text
    assert DraftStore(vault.drafts_dir).all_drafts() == []
    loaded = RawInfoStore(vault.digest_items_dir).get(item.id)
    assert loaded is not None
    assert loaded.status == "unprocessed"
    assert loaded.note_draft_id is None


def test_create_note_draft_from_info_tool_uses_current_raw_info(tmp_path):
    vault, cfg = _ready_vault(tmp_path)
    item = RawInfo(
        source_id="source-1",
        source_name="Prompt Watch",
        source_kind="prompt",
        item_key="prompt:item",
        title="Prompt-sourced update",
        url="https://example.com/prompt-update",
        summary="A prompt source candidate.",
    )
    RawInfoStore(vault.digest_items_dir).save(item)
    client = TestClient(create_app(vault, cfg))
    runtime = client.app.state.web_state.runtime_or_init()
    runtime.llm = ScriptedLLM(
        [
            {
                "title": "Prompt Source Reference",
                "body": "Reference draft body.",
                "tags": ["prompt-source"],
                "kind": "reference",
                "folder": "",
                "rationale": "No deep discussion yet, so this is reference material.",
            }
        ]
    )
    runtime.ctx.llm = runtime.llm
    runtime.ctx.current_raw_info_id = item.id

    result = runtime.registry.dispatch(
        "create_note_draft_from_info",
        {"discussion_summary": "用户尚未深入讨论,只是想先留存。"},
        runtime.ctx,
    )

    assert result["kind"] == "raw_info_note_draft"
    assert result["info_id"] == item.id
    draft = DraftStore(vault.drafts_dir).get(result["draft_id"])
    assert draft is not None
    assert draft.kind == "reference"
    loaded = RawInfoStore(vault.digest_items_dir).get(item.id)
    assert loaded is not None
    assert loaded.status == "drafted"
    assert loaded.note_draft_id == draft.id


def test_raw_info_draft_diff_api_accepts_or_rejects_without_note_write(tmp_path):
    vault, cfg = _ready_vault(tmp_path)
    draft_store = DraftStore(vault.drafts_dir)
    draft_store.save(
        Draft(
            title="Trace draft",
            body="Tool traces are mixed into the answer.",
            tags=["agents"],
            kind="knowledge",
            folder="ai/research",
        )
    )
    saved = draft_store.all_drafts()[0]
    item = RawInfo(
        source_id="source-1",
        source_name="Research Feed",
        source_kind="rss",
        item_key="rss:item",
        title="Trace article",
        url="https://example.com/trace",
        summary="A trace article.",
        status="drafted",
        note_draft_id=saved.id,
    )
    RawInfoStore(vault.digest_items_dir).save(item)
    client = TestClient(create_app(vault, cfg))
    runtime = client.app.state.web_state.runtime_or_init()
    runtime.llm = ScriptedLLM(
        [
            {"new_body": "Tool traces should be separate from the final answer."},
            {"new_body": "Tool traces should be visible, separate, and reviewable."},
        ]
    )
    runtime.ctx.llm = runtime.llm

    proposed = client.post(
        f"/api/drafts/{saved.id}/diff",
        json={"instruction": "make this clearer"},
    )

    assert proposed.status_code == 200, proposed.text
    proposal = proposed.json()
    assert proposal["kind"] == "draft_edit_proposal"
    assert proposal["draft_id"] == saved.id
    assert proposal["changed"] is True
    assert proposal["old_body"] == "Tool traces are mixed into the answer."
    assert proposal["new_body"] == "Tool traces should be separate from the final answer."
    stored = DraftStore(vault.drafts_dir).get(saved.id)
    assert stored is not None
    assert stored.body == "Tool traces are mixed into the answer."
    assert stored.pending_diff_body == "Tool traces should be separate from the final answer."
    assert len(list(vault.iter_note_paths())) == 0

    rejected = client.post(f"/api/drafts/{saved.id}/diff/reject")
    assert rejected.status_code == 200, rejected.text
    after_reject = DraftStore(vault.drafts_dir).get(saved.id)
    assert after_reject is not None
    assert after_reject.body == "Tool traces are mixed into the answer."
    assert after_reject.pending_diff_body is None
    loaded = RawInfoStore(vault.digest_items_dir).get(item.id)
    assert loaded is not None
    assert loaded.status == "drafted"

    proposed_again = client.post(
        f"/api/drafts/{saved.id}/diff",
        json={"instruction": "make this more complete"},
    )
    assert proposed_again.status_code == 200, proposed_again.text
    accepted = client.post(f"/api/drafts/{saved.id}/diff/accept")
    assert accepted.status_code == 200, accepted.text
    after_accept = DraftStore(vault.drafts_dir).get(saved.id)
    assert after_accept is not None
    assert after_accept.body == "Tool traces should be visible, separate, and reviewable."
    assert after_accept.pending_diff_body is None
    assert len(list(vault.iter_note_paths())) == 0


def test_current_draft_tools_propose_accept_reject_and_commit(tmp_path):
    vault, cfg = _ready_vault(tmp_path)
    vault.mkdir_folder("ai/research")
    draft = Draft(
        title="Trace draft",
        body="Tool traces are mixed into the answer.",
        tags=["agents"],
        kind="knowledge",
        folder="ai/research",
    )
    DraftStore(vault.drafts_dir).save(draft)
    item = RawInfo(
        source_id="source-1",
        source_name="Research Feed",
        source_kind="rss",
        item_key="rss:item",
        title="Trace article",
        url="https://example.com/trace",
        summary="A trace article.",
        status="drafted",
        note_draft_id=draft.id,
    )
    RawInfoStore(vault.digest_items_dir).save(item)
    client = TestClient(create_app(vault, cfg))
    runtime = client.app.state.web_state.runtime_or_init()
    runtime.llm = ScriptedLLM(
        [
            {"new_body": "Tool traces should be separate from the final answer."},
            {"new_body": "Tool traces should be visible, separate, and reviewable."},
        ]
    )
    runtime.ctx.llm = runtime.llm
    runtime.ctx.current_draft_id = draft.id
    dirty_notes: list[str] = []
    runtime.ctx.mark_note_dirty = dirty_notes.append

    first = runtime.registry.dispatch(
        "propose_current_draft_edit",
        {"instruction": "make the draft clearer"},
        runtime.ctx,
    )
    assert first["kind"] == "draft_edit_proposal"
    assert first["draft_id"] == draft.id
    assert DraftStore(vault.drafts_dir).get(draft.id).pending_diff_body is not None  # type: ignore[union-attr]

    rejected = runtime.registry.dispatch("reject_all_draft_diff", {}, runtime.ctx)
    assert rejected["rejected"] is True
    assert DraftStore(vault.drafts_dir).get(draft.id).pending_diff_body is None  # type: ignore[union-attr]

    second = runtime.registry.dispatch(
        "propose_current_draft_edit",
        {"instruction": "make the draft complete"},
        runtime.ctx,
    )
    assert second["changed"] is True
    accepted = runtime.registry.dispatch("accept_all_draft_diff", {}, runtime.ctx)
    assert accepted["accepted"] is True
    assert DraftStore(vault.drafts_dir).get(draft.id).body == (  # type: ignore[union-attr]
        "Tool traces should be visible, separate, and reviewable."
    )

    committed = runtime.registry.dispatch(
        "commit_note_draft",
        {"folder": "library/final"},
        runtime.ctx,
    )
    assert committed["note_id"] == draft.id
    assert committed["path"].endswith(f"/notes/library/final/{draft.id}.md")
    assert dirty_notes == [draft.id]
    assert DraftStore(vault.drafts_dir).get(draft.id) is None
    assert (vault.notes_dir / "library" / "final" / f"{draft.id}.md").exists()
    loaded = RawInfoStore(vault.digest_items_dir).get(item.id)
    assert loaded is not None
    assert loaded.status == "included"
    assert loaded.note_id == draft.id
    meta = runtime.index.get_note_meta(draft.id)
    assert meta is not None
    assert "Trace draft" in meta["title"]


def test_commit_note_draft_rejects_empty_body_without_deleting_draft(tmp_path):
    vault, cfg = _ready_vault(tmp_path)
    draft = Draft(title="Empty draft", body="", kind="reference")
    DraftStore(vault.drafts_dir).save(draft)
    client = TestClient(create_app(vault, cfg))

    res = client.post(f"/api/drafts/{draft.id}/commit")

    assert res.status_code == 400, res.text
    assert DraftStore(vault.drafts_dir).get(draft.id) is not None
    assert len(list(vault.iter_note_paths())) == 0


def test_commit_note_draft_can_override_target_folder(tmp_path):
    vault, cfg = _ready_vault(tmp_path)
    draft = Draft(
        title="Folder reviewed draft",
        body="Reviewed body.",
        kind="knowledge",
        folder="ai/recommended",
    )
    DraftStore(vault.drafts_dir).save(draft)
    client = TestClient(create_app(vault, cfg))

    res = client.post(
        f"/api/drafts/{draft.id}/commit",
        json={"folder": "library/final"},
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["note_id"] == draft.id
    assert body["path"].endswith(f"/notes/library/final/{draft.id}.md")
    assert DraftStore(vault.drafts_dir).get(draft.id) is None
    assert (vault.notes_dir / "library" / "final" / f"{draft.id}.md").exists()


def test_discard_raw_info_api_marks_discarded_and_deletes_linked_draft(tmp_path):
    vault, cfg = _ready_vault(tmp_path)
    draft = Draft(
        title="Discard candidate",
        body="Draft body that should not enter notes.",
        tags=["digest"],
        source="https://example.com/discard",
    )
    DraftStore(vault.drafts_dir).save(draft)
    item = RawInfo(
        source_id="source-1",
        source_name="Research Feed",
        source_kind="rss",
        item_key="rss:discard",
        title="Discard this item",
        url="https://example.com/discard",
        summary="A raw info item the user chose not to keep.",
        status="drafted",
        note_draft_id=draft.id,
    )
    RawInfoStore(vault.digest_items_dir).save(item)
    client = TestClient(create_app(vault, cfg))

    res = client.post(f"/api/digest/items/{item.id}/discard")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["status"] == "discarded"
    assert payload["note_draft_id"] == draft.id
    assert DraftStore(vault.drafts_dir).get(draft.id) is None
    loaded = RawInfoStore(vault.digest_items_dir).get(item.id)
    assert loaded is not None
    assert loaded.status == "discarded"
    assert loaded.note_draft_id == draft.id
    assert RawInfoStore(vault.digest_items_dir).pending_count() == 0


def test_discard_pending_raw_info_api_marks_all_pending_and_deletes_linked_drafts(
    tmp_path,
):
    vault, cfg = _ready_vault(tmp_path)
    draft = Draft(
        title="Bulk discard candidate",
        body="Draft body",
        tags=["digest"],
        source="https://example.com/bulk-discard",
    )
    DraftStore(vault.drafts_dir).save(draft)
    pending = RawInfo(
        source_id="source-1",
        source_name="Research Feed",
        source_kind="rss",
        item_key="rss:bulk-pending",
        title="Pending bulk item",
        url="https://example.com/bulk-pending",
        summary="A pending raw info item.",
        status="drafted",
        note_draft_id=draft.id,
    )
    viewed = RawInfo(
        source_id="source-1",
        source_name="Research Feed",
        source_kind="rss",
        item_key="rss:bulk-viewed",
        title="Viewed bulk item",
        url="https://example.com/bulk-viewed",
        summary="A viewed raw info item.",
        status="viewed",
    )
    included = RawInfo(
        source_id="source-1",
        source_name="Research Feed",
        source_kind="rss",
        item_key="rss:bulk-included",
        title="Already included item",
        url="https://example.com/bulk-included",
        summary="This should not be touched.",
        status="included",
    )
    store = RawInfoStore(vault.digest_items_dir)
    for item in (pending, viewed, included):
        store.save(item)
    client = TestClient(create_app(vault, cfg))

    res = client.post("/api/digest/items/discard-pending")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload == {
        "discarded_count": 2,
        "deleted_draft_ids": [draft.id],
    }
    assert store.get(pending.id).status == "discarded"  # type: ignore[union-attr]
    assert store.get(viewed.id).status == "discarded"  # type: ignore[union-attr]
    assert store.get(included.id).status == "included"  # type: ignore[union-attr]
    assert DraftStore(vault.drafts_dir).get(draft.id) is None
    assert store.pending_count() == 0


def test_discard_raw_info_tool_uses_current_item_and_deletes_linked_draft(tmp_path):
    vault, cfg = _ready_vault(tmp_path)
    draft = Draft(
        title="Tool discard candidate",
        body="Draft body",
        tags=["digest"],
        source="https://example.com/tool-discard",
    )
    DraftStore(vault.drafts_dir).save(draft)
    item = RawInfo(
        source_id="source-1",
        source_name="Research Feed",
        source_kind="rss",
        item_key="rss:tool-discard",
        title="Tool discard item",
        url="https://example.com/tool-discard",
        summary="A raw info item for tool-driven discard.",
        status="drafted",
        note_draft_id=draft.id,
    )
    RawInfoStore(vault.digest_items_dir).save(item)
    client = TestClient(create_app(vault, cfg))
    runtime = client.app.state.web_state.runtime_or_init()
    runtime.ctx.current_raw_info_id = item.id

    result = runtime.registry.dispatch("discard_raw_info", {}, runtime.ctx)

    assert result["status"] == "discarded"
    assert result["deleted_draft_id"] == draft.id
    assert result["draft_deleted"] is True
    loaded = RawInfoStore(vault.digest_items_dir).get(item.id)
    assert loaded is not None
    assert loaded.status == "discarded"
    assert DraftStore(vault.drafts_dir).get(draft.id) is None


def test_digest_cli_discard_marks_raw_info_and_deletes_linked_draft(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path)
    monkeypatch.setenv("KNOWLET_VAULT", str(vault.root))
    draft = Draft(
        title="CLI discard candidate",
        body="Draft body",
        tags=["digest"],
        source="https://example.com/cli-discard",
    )
    DraftStore(vault.drafts_dir).save(draft)
    item = RawInfo(
        source_id="source-1",
        source_name="Research Feed",
        source_kind="rss",
        item_key="rss:cli-discard",
        title="CLI discard item",
        url="https://example.com/cli-discard",
        summary="A raw info item for CLI discard parity.",
        status="drafted",
        note_draft_id=draft.id,
    )
    RawInfoStore(vault.digest_items_dir).save(item)

    result = runner.invoke(app, ["digest", "discard", item.id])

    assert result.exit_code == 0, result.stdout
    assert "discarded" in result.stdout
    loaded = RawInfoStore(vault.digest_items_dir).get(item.id)
    assert loaded is not None
    assert loaded.status == "discarded"
    assert DraftStore(vault.drafts_dir).get(draft.id) is None


def test_digest_cli_clear_discards_all_pending_raw_info(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path)
    monkeypatch.setenv("KNOWLET_VAULT", str(vault.root))
    first = RawInfo(
        source_id="source-1",
        source_name="Research Feed",
        source_kind="rss",
        item_key="rss:cli-clear-1",
        title="CLI clear item 1",
        url="https://example.com/cli-clear-1",
        summary="First pending raw info item.",
        status="unprocessed",
    )
    second = RawInfo(
        source_id="source-1",
        source_name="Research Feed",
        source_kind="rss",
        item_key="rss:cli-clear-2",
        title="CLI clear item 2",
        url="https://example.com/cli-clear-2",
        summary="Second pending raw info item.",
        status="discussed",
    )
    store = RawInfoStore(vault.digest_items_dir)
    store.save(first)
    store.save(second)

    result = runner.invoke(app, ["digest", "clear"])

    assert result.exit_code == 0, result.stdout
    assert "discarded 2 pending raw info item" in result.stdout
    assert store.get(first.id).status == "discarded"  # type: ignore[union-attr]
    assert store.get(second.id).status == "discarded"  # type: ignore[union-attr]
    assert store.pending_count() == 0


def test_digest_cli_run_pulls_v2_source(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path)
    source = _save_source(
        vault,
        DigestSource(name="AI feed", kind="rss", url="https://example.com/feed.xml"),
    )
    monkeypatch.setenv("KNOWLET_VAULT", str(vault.root))
    monkeypatch.setattr(
        "knowlet.core.digest_pull.fetch_source",
        lambda _spec: [
            SourceItem(
                source_url="https://example.com/feed.xml",
                item_id="entry-1",
                title="RSS title",
                url="https://example.com/a",
                published=None,
                content="body",
            )
        ],
    )

    def fake_chat(self, messages, tools=None, max_tokens=None, temperature=None, role=None):
        return AssistantMessage(
            content=json.dumps(
                {
                    "title": "CLI normalized item",
                    "summary": "CLI pull created this.",
                    "key_points": ["cli"],
                    "why_it_matters": "CLI parity.",
                    "suggested_tags": ["cli"],
                    "confidence": "high",
                }
            ),
            tool_calls=[],
        )

    monkeypatch.setattr("knowlet.core.llm.LLMClient.chat", fake_chat)

    result = runner.invoke(app, ["digest", "run", source.id])
    assert result.exit_code == 0, result.stdout
    assert "created=1" in result.stdout
    stored = RawInfoStore(vault.digest_items_dir).list()
    assert [item.title for item in stored] == ["CLI normalized item"]


def test_digest_cli_run_all_honors_limit_for_v2_sources(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path)
    _save_source(
        vault,
        DigestSource(name="AI feed", kind="rss", url="https://example.com/feed.xml"),
    )
    monkeypatch.setenv("KNOWLET_VAULT", str(vault.root))
    monkeypatch.setattr(
        "knowlet.core.digest_pull.fetch_source",
        lambda _spec: [
            SourceItem(
                source_url="https://example.com/feed.xml",
                item_id="entry-1",
                title="First RSS title",
                url="https://example.com/a",
                published=None,
                content="body",
            ),
            SourceItem(
                source_url="https://example.com/feed.xml",
                item_id="entry-2",
                title="Second RSS title",
                url="https://example.com/b",
                published=None,
                content="body",
            ),
        ],
    )
    chat_calls = 0

    def fake_chat(self, messages, tools=None, max_tokens=None, temperature=None, role=None):
        nonlocal chat_calls
        chat_calls += 1
        return AssistantMessage(
            content=json.dumps(
                {
                    "title": "CLI limited item",
                    "summary": "CLI pull honored the limit.",
                    "key_points": ["cli"],
                    "why_it_matters": "Avoids surprise LLM bursts.",
                    "suggested_tags": ["cli"],
                    "confidence": "high",
                }
            ),
            tool_calls=[],
        )

    monkeypatch.setattr("knowlet.core.llm.LLMClient.chat", fake_chat)

    result = runner.invoke(app, ["digest", "run", "--limit", "1"])
    assert result.exit_code == 0, result.stdout
    assert "created=1" in result.stdout
    assert chat_calls == 1
    stored = RawInfoStore(vault.digest_items_dir).list()
    assert [item.title for item in stored] == ["CLI limited item"]


def test_auto_pull_runs_once_per_day_and_rechecks_next_day(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path)
    source = _save_source(
        vault,
        DigestSource(name="AI feed", kind="rss", url="https://example.com/feed.xml"),
    )
    calls = 0

    def fake_fetch(_spec):
        nonlocal calls
        calls += 1
        return [
            SourceItem(
                source_url="https://example.com/feed.xml",
                item_id="entry-1",
                title="RSS title",
                url="https://example.com/a",
                published=None,
                content="body",
            )
        ]

    monkeypatch.setattr("knowlet.core.digest_pull.fetch_source", fake_fetch)
    llm = ScriptedLLM(
        [
            {
                "title": "Auto normalized item",
                "summary": "Auto pull created this.",
                "key_points": ["auto"],
                "why_it_matters": "Daily first-online pull.",
                "suggested_tags": ["auto"],
                "confidence": "high",
            }
        ]
    )

    first = maybe_auto_pull_digest_sources(vault=vault, llm=llm, today="2000-01-01")
    assert first is not None
    assert first.created == 1
    assert calls == 1

    same_day = maybe_auto_pull_digest_sources(
        vault=vault,
        llm=llm,
        today="2000-01-01",
    )
    assert same_day is None
    assert calls == 1

    next_day = maybe_auto_pull_digest_sources(
        vault=vault,
        llm=llm,
        today="2000-01-02",
    )
    assert next_day is not None
    assert next_day.created == 0
    assert calls == 2
    assert DigestSourceStore(vault.digest_sources_dir).get(source.id) is not None


def test_auto_pull_skips_source_already_successful_today(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path)
    source = _save_source(
        vault,
        DigestSource(
            name="Already pulled feed",
            kind="rss",
            url="https://example.com/feed.xml",
            last_pull_at="2026-05-30T01:00:00Z",
            last_success_at="2026-05-30T01:00:00Z",
            pull_status="ok",
        ),
    )

    def fake_fetch(_spec):
        raise AssertionError("auto pull should trust today's source success")

    monkeypatch.setattr("knowlet.core.digest_pull.fetch_source", fake_fetch)

    report = maybe_auto_pull_digest_sources(
        vault=vault,
        llm=ScriptedLLM([]),
        today="2026-05-30",
    )

    assert report is None
    assert DigestSourceStore(vault.digest_sources_dir).get(source.id) is not None


def test_auto_pull_only_marks_successful_sources_done_for_the_day(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path)
    good = _save_source(
        vault,
        DigestSource(
            name="Successful feed",
            kind="rss",
            url="https://example.com/good.xml",
        ),
    )
    flaky = _save_source(
        vault,
        DigestSource(
            name="Flaky feed",
            kind="rss",
            url="https://example.com/flaky.xml",
        ),
    )
    fail_flaky = True
    calls: list[str] = []

    def fake_fetch(spec):
        nonlocal fail_flaky
        calls.append(spec.url)
        if spec.url == "https://example.com/flaky.xml" and fail_flaky:
            raise RuntimeError("temporary upstream failure")
        suffix = "flaky" if spec.url == "https://example.com/flaky.xml" else "good"
        return [
            SourceItem(
                source_url=spec.url,
                item_id=f"{suffix}-entry-1",
                title=f"{suffix.title()} RSS title",
                url=f"https://example.com/{suffix}/a",
                published=None,
                content="body",
            )
        ]

    monkeypatch.setattr("knowlet.core.digest_pull.fetch_source", fake_fetch)
    llm = ScriptedLLM(
        [
            {
                "title": "Good normalized item",
                "summary": "The successful source should count for today.",
                "key_points": ["good"],
                "why_it_matters": "A source that worked should not repeat today.",
                "suggested_tags": ["digest"],
                "confidence": "high",
            },
            {
                "title": "Flaky normalized item",
                "summary": "The flaky source should retry later the same day.",
                "key_points": ["retry"],
                "why_it_matters": "Failed sources should not be hidden until tomorrow.",
                "suggested_tags": ["digest"],
                "confidence": "medium",
            },
        ]
    )

    first = maybe_auto_pull_digest_sources(
        vault=vault,
        llm=llm,
        today="2026-05-30",
    )
    assert first is not None
    assert first.created == 1
    assert any("Flaky feed" in error for error in first.errors)
    state_path = vault.state_dir / "digest" / "auto_pull.json"
    state = json.loads(state_path.read_text("utf-8"))
    assert state["last_by_source"] == {good.id: "2026-05-30"}
    assert calls == ["https://example.com/good.xml", "https://example.com/flaky.xml"]

    fail_flaky = False
    second = maybe_auto_pull_digest_sources(
        vault=vault,
        llm=llm,
        today="2026-05-30",
    )
    assert second is not None
    assert second.source_ids == [flaky.id]
    assert second.created == 1
    state = json.loads(state_path.read_text("utf-8"))
    assert state["last_by_source"] == {
        good.id: "2026-05-30",
        flaky.id: "2026-05-30",
    }
