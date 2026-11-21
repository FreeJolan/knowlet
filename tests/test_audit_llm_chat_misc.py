"""Regression tests for llm-chat audit findings outside llm.py / routing:
output budget for full-body JSON replies (note_chat.py:274), conversation
pruning (log.py:57), reject_draft soft delete (reject_draft.py:17) and
web_search auto mode (tools/web_search.py:56)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from knowlet.chat.conversation_store import Conversation, ConversationStore
from knowlet.chat.log import prune_old
from knowlet.chat.note_chat import propose_draft_internalization, propose_note_edit
from knowlet.config import KnowletConfig, LLMConfig, WebSearchConfig
from knowlet.core.card_store import CardStore
from knowlet.core.drafts import Draft, DraftStore
from knowlet.core.embedding import make_backend
from knowlet.core.index import Index
from knowlet.core.llm import AssistantMessage, LLMClient
from knowlet.core.mining.task_store import TaskStore
from knowlet.core.note import Note, new_id
from knowlet.core.tools import reject_draft as reject_draft_tool
from knowlet.core.tools import web_search as web_search_tool
from knowlet.core.tools._registry import ToolContext
from knowlet.core.vault import Vault

# ------------------------------------------------------ note_chat.py:274


class _BudgetRecordingLLM:
    def __init__(self, reply_body: str) -> None:
        self.cfg = LLMConfig(api_key="stub")  # default max_tokens=1024
        self.reply_body = reply_body
        self.max_tokens: list[int | None] = []

    def chat(self, messages, tools=None, max_tokens=None, temperature=None):
        self.max_tokens.append(max_tokens)
        return AssistantMessage(content=json.dumps({"new_body": self.reply_body}), tool_calls=[])


def _long_body(chars: int) -> str:
    return ("这是一段需要润色的中文笔记正文。" * (chars // 16 + 1))[:chars]


def test_propose_note_edit_output_budget_scales_with_body() -> None:
    body = _long_body(3000)
    llm = _BudgetRecordingLLM(body + "润色")
    proposal = propose_note_edit(
        llm=llm, note=Note(id=new_id(), title="t", body=body), instruction="润色"
    )
    assert proposal.changed
    budget = llm.max_tokens[-1]
    assert budget is not None
    # Whole body has to fit back into the JSON reply: well above the
    # 1024 default and at least one token per CJK character.
    assert budget >= len(body)


def test_propose_note_edit_short_body_keeps_configured_floor() -> None:
    llm = _BudgetRecordingLLM("short!")
    propose_note_edit(llm=llm, note=Note(id=new_id(), title="t", body="short"), instruction="x")
    budget = llm.max_tokens[-1]
    assert budget is not None and budget >= llm.cfg.max_tokens


def test_propose_draft_internalization_output_budget_scales_with_body() -> None:
    body = _long_body(4000)
    llm = _BudgetRecordingLLM("内化后的正文")
    propose_draft_internalization(
        llm=llm, note=Note(id=new_id(), title="t", body=body), instruction=""
    )
    budget = llm.max_tokens[-1]
    assert budget is not None and budget >= len(body)


def test_sediment_output_budget_scales_with_conversation() -> None:
    from knowlet.chat.sediment import draft_from_conversation

    class _SedimentLLM(_BudgetRecordingLLM):
        def chat(self, messages, tools=None, max_tokens=None, temperature=None):
            self.max_tokens.append(max_tokens)
            return AssistantMessage(
                content=json.dumps({"title": "t", "tags": [], "body": "b"}), tool_calls=[]
            )

    llm = _SedimentLLM("")
    history = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": _long_body(3000)},
        {"role": "assistant", "content": _long_body(3000)},
    ]
    draft_from_conversation(llm, history)  # type: ignore[arg-type]
    budget = llm.max_tokens[-1]
    assert budget is not None and budget > llm.cfg.max_tokens


def test_raw_info_draft_output_budget_scales_with_source(tmp_path: Path) -> None:
    from knowlet.chat.digest_draft import create_note_draft_from_info
    from knowlet.core.digest_items import RawInfo, RawInfoStore

    class _DraftLLM(_BudgetRecordingLLM):
        def chat(self, messages, tools=None, max_tokens=None, temperature=None):
            self.max_tokens.append(max_tokens)
            return AssistantMessage(
                content=json.dumps({"title": "t", "body": "b", "kind": "knowledge"}),
                tool_calls=[],
            )

    vault = Vault(tmp_path)
    vault.init_layout()
    backend = make_backend("dummy", "x", 16)
    index = Index(vault.db_path, backend)
    index.connect()
    store = RawInfoStore(vault.digest_items_dir)
    excerpt = _long_body(4000)
    item = RawInfo(
        source_id="s",
        source_name="Feed",
        source_kind="rss",
        item_key="rss:1",
        title="Long article",
        url="https://example.com/a",
        summary="s",
        content_excerpt=excerpt,
    )
    store.save(item)
    llm = _DraftLLM("")
    create_note_draft_from_info(
        llm=llm,
        vault=vault,
        index=index,
        drafts=DraftStore(vault.drafts_dir),
        item_store=store,
        info_id=item.id,
    )
    budget = llm.max_tokens[-1]
    assert budget is not None and budget >= len(excerpt)


# ------------------------------------------------------------ log.py:57


def test_prune_old_moves_aged_conversations_to_archive(tmp_path: Path) -> None:
    d = tmp_path / "conversations"
    d.mkdir()
    fresh = d / "fresh.json"
    fresh.write_text('{"id": "fresh"}', encoding="utf-8")
    aged = d / "aged.json"
    aged.write_text('{"id": "aged", "title": "研究会话"}', encoding="utf-8")
    long_ago = time.time() - 60 * 86400
    os.utime(aged, (long_ago, long_ago))

    assert prune_old(d, days=30) == 1

    assert fresh.exists()
    assert not aged.exists()
    archived = [p for p in d.rglob("aged*.json") if p.parent != d]
    assert len(archived) == 1, list(d.rglob("*"))
    assert json.loads(archived[0].read_text(encoding="utf-8"))["title"] == "研究会话"
    # Archived conversations leave the live listing.
    assert [s.id for s in ConversationStore(d).list(only_meaningful=False)] == ["fresh"]


def test_prune_old_does_not_clobber_previously_archived_copy(tmp_path: Path) -> None:
    d = tmp_path / "conversations"
    d.mkdir()
    long_ago = time.time() - 60 * 86400
    for content in ("first", "second"):
        p = d / "same.json"
        p.write_text(json.dumps({"id": "same", "v": content}), encoding="utf-8")
        os.utime(p, (long_ago, long_ago))
        assert prune_old(d, days=30) == 1
    versions = sorted(json.loads(p.read_text(encoding="utf-8"))["v"] for p in d.rglob("same*.json"))
    assert versions == ["first", "second"]


def test_conversation_delete_is_recoverable(tmp_path: Path) -> None:
    store = ConversationStore(tmp_path)
    conv = Conversation(title="keep me", messages=[{"role": "system", "content": ""}])
    store.save(conv)

    assert store.delete(conv.id) is True
    assert not (tmp_path / f"{conv.id}.json").exists()
    assert store.get(conv.id) is None
    leftovers = [p for p in tmp_path.rglob(f"{conv.id}*.json")]
    assert len(leftovers) == 1
    assert json.loads(leftovers[0].read_text(encoding="utf-8"))["title"] == "keep me"


# ---------------------------------------------------- reject_draft.py:17


def _ctx(tmp_path: Path, web_search_cfg: WebSearchConfig | None = None) -> ToolContext:
    v = Vault(tmp_path)
    v.init_layout()
    cfg = KnowletConfig(web_search=web_search_cfg or WebSearchConfig())
    backend = make_backend("dummy", "x", 16)
    cfg.embedding.dim = backend.dim
    idx = Index(v.db_path, backend)
    idx.connect()
    return ToolContext(
        vault=v,
        index=idx,
        config=cfg,
        cards=CardStore(v.cards_dir),
        tasks=TaskStore(v.tasks_dir),
        drafts=DraftStore(v.drafts_dir),
    )


def test_reject_draft_tool_archives_instead_of_unlinking(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    draft = Draft(id=new_id(), title="Mined item", body="valuable body")
    ctx.drafts.save(draft)

    out = reject_draft_tool.TOOL.handler({"draft_id": draft.id}, ctx)

    assert "error" not in out, out
    assert ctx.drafts.get(draft.id) is None  # gone from the live queue
    archived = list(ctx.drafts.archive_dir.rglob("*.md"))
    assert len(archived) == 1
    assert "valuable body" in archived[0].read_text(encoding="utf-8")
    assert out["archived"] is True


def test_reject_draft_tool_unknown_id_is_an_error(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    out = reject_draft_tool.TOOL.handler({"draft_id": "01NOPE"}, ctx)
    assert "not found" in out["error"]


def test_reject_draft_tool_description_no_longer_claims_irreversible() -> None:
    assert "irreversible" not in reject_draft_tool.TOOL.description.lower()


# -------------------------------------------------- tools/web_search.py:56


def _brave_response(url: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "web": {
                "results": [
                    {"title": "Brave hit", "url": "https://example.com/b", "description": "d"}
                ]
            }
        },
        request=httpx.Request("GET", url),
    )


def test_auto_mode_with_brave_key_uses_brave_without_hosted_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def hosted_should_not_run(*args: Any, **kwargs: Any):
        raise AssertionError("hosted search must not run when a search key is configured")

    monkeypatch.setattr(web_search_tool, "_hosted_web_search", hosted_should_not_run)
    monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kw: _brave_response(url))
    ctx = _ctx(tmp_path, WebSearchConfig(brave_api_key="bsa-xxx"))
    ctx.config.llm.api_key = "stub-key"

    out = web_search_tool.TOOL.handler({"query": "knowlet"}, ctx)
    assert out["provider"] == "brave", out
    assert out["results"][0]["url"] == "https://example.com/b"


class _HostedFailingLLM(LLMClient):
    """Real LLMClient whose Responses calls always fail like an endpoint
    without hosted web_search."""

    def __init__(self, cfg: LLMConfig) -> None:
        super().__init__(cfg)
        self.responses_calls = 0

    def responses(self, input_text, **kwargs):  # type: ignore[override]
        self.responses_calls += 1
        raise RuntimeError("tool type web_search is not supported")


def test_hosted_failure_is_remembered_across_turns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    web_search_tool._HOSTED_SEARCH_STATUS.clear()
    ddg_calls: list[str] = []

    def fake_ddg(self, url, **kw):
        ddg_calls.append(url)
        return httpx.Response(
            200,
            json={
                "Heading": "K",
                "AbstractURL": "https://example.com/k",
                "Abstract": "a",
                "RelatedTopics": [],
            },
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx.Client, "get", fake_ddg)
    ctx = _ctx(tmp_path, WebSearchConfig())
    ctx.config.llm.api_key = "stub-key"
    llm = _HostedFailingLLM(ctx.config.llm)
    ctx.llm = llm

    first = web_search_tool.TOOL.handler({"query": "one"}, ctx)
    assert first["provider"] == "ddg"
    calls_after_first = llm.responses_calls
    assert calls_after_first >= 1

    ctx.per_turn = {}  # next turn
    second = web_search_tool.TOOL.handler({"query": "two"}, ctx)
    assert second["provider"] == "ddg"
    # No new round-trips to an endpoint already known to lack hosted search.
    assert llm.responses_calls == calls_after_first
    web_search_tool._HOSTED_SEARCH_STATUS.clear()


def test_hosted_search_uses_session_llm_client_for_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hosted path must go through the runtime's LLMClient (which
    carries the audit store) instead of an ad-hoc client."""
    web_search_tool._HOSTED_SEARCH_STATUS.clear()
    monkeypatch.setattr(
        httpx.Client,
        "get",
        lambda self, url, **kw: httpx.Response(
            200,
            json={"Heading": "", "AbstractURL": "", "Abstract": "", "RelatedTopics": []},
            request=httpx.Request("GET", url),
        ),
    )
    ctx = _ctx(tmp_path, WebSearchConfig())
    ctx.config.llm.api_key = "stub-key"
    llm = _HostedFailingLLM(ctx.config.llm)
    ctx.llm = llm
    web_search_tool.TOOL.handler({"query": "one"}, ctx)
    assert llm.responses_calls >= 1
    web_search_tool._HOSTED_SEARCH_STATUS.clear()


def test_hosted_search_stops_trying_variants_after_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hung endpoint must cost one timed-out request, not one per tool
    variant."""
    from openai import APITimeoutError

    web_search_tool._HOSTED_SEARCH_STATUS.clear()

    class _TimingOutLLM(_HostedFailingLLM):
        def responses(self, input_text, **kwargs):  # type: ignore[override]
            self.responses_calls += 1
            raise APITimeoutError(request=httpx.Request("POST", "http://proxy/v1/responses"))

    monkeypatch.setattr(
        httpx.Client,
        "get",
        lambda self, url, **kw: httpx.Response(
            200,
            json={"Heading": "", "AbstractURL": "", "Abstract": "", "RelatedTopics": []},
            request=httpx.Request("GET", url),
        ),
    )
    ctx = _ctx(tmp_path, WebSearchConfig())
    ctx.config.llm.api_key = "stub-key"
    llm = _TimingOutLLM(ctx.config.llm)
    ctx.llm = llm
    out = web_search_tool.TOOL.handler({"query": "one"}, ctx)
    assert out["provider"] == "ddg"
    assert llm.responses_calls == 1
    web_search_tool._HOSTED_SEARCH_STATUS.clear()
