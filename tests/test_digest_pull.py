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
from knowlet.core.llm import AssistantMessage
from knowlet.core.mining.sources import SourceItem
from knowlet.core.vault import Vault
from knowlet.web.server import create_app

runner = CliRunner()


class ScriptedLLM:
    def __init__(self, payloads: list[dict[str, Any]]):
        self.payloads = list(payloads)
        self.messages: list[list[dict[str, Any]]] = []

    def chat(self, messages, tools=None, max_tokens=None, temperature=None):
        self.messages.append(messages)
        payload = self.payloads.pop(0)
        return AssistantMessage(content=json.dumps(payload), tool_calls=[])


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
    prompt_text = llm.messages[0][0]["content"]
    assert "Knowlet digest source editor" in prompt_text
    assert "Find important AI agent updates." in prompt_text
    assert "Output only strict JSON" in prompt_text


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

    first = maybe_auto_pull_digest_sources(vault=vault, llm=llm, today="2026-05-30")
    assert first is not None
    assert first.created == 1
    assert calls == 1

    same_day = maybe_auto_pull_digest_sources(
        vault=vault,
        llm=llm,
        today="2026-05-30",
    )
    assert same_day is None
    assert calls == 1

    next_day = maybe_auto_pull_digest_sources(
        vault=vault,
        llm=llm,
        today="2026-05-31",
    )
    assert next_day is not None
    assert next_day.created == 0
    assert calls == 2
    assert DigestSourceStore(vault.digest_sources_dir).get(source.id) is not None
