"""Regression tests for the keyword routers that bypass the LLM and run
write tools directly (raw_info_chat.py:133 / note_chat.py:144,
llm-chat audit batch).

New contract: a direct route fires only for a sentence-initial,
imperative command (optionally after a polite / affirmative lead-in);
questions and negations never route directly — they fall through to the
model, which still has the same tools.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from knowlet.chat.current_note_tools import APPLY_CURRENT_NOTE_EDIT_TOOL
from knowlet.chat.note_chat import wants_current_note_edit_apply
from knowlet.chat.raw_info_chat import (
    wants_accept_all_draft_diff,
    wants_commit_note_draft,
    wants_discard_raw_info,
    wants_reject_all_draft_diff,
)
from knowlet.config import KnowletConfig, save_config
from knowlet.core.digest_items import RawInfo, RawInfoStore
from knowlet.core.drafts import Draft, DraftStore
from knowlet.core.events import ReplyChunkEvent, ReplyDoneEvent
from knowlet.core.llm import AssistantMessage
from knowlet.core.note import Note, new_id
from knowlet.core.vault import Vault

# ------------------------------------------------------- raw_info_chat.py


@pytest.mark.parametrize(
    "text",
    [
        "这份草稿和正式笔记有什么区别?",
        "这份草稿和正式笔记有什么区别？",  # noqa: RUF001
        "should I add this to my knowledge base?",
        "要不要落库?",
        "落库吗",
        "先不要落库",
        "别落库",
        "不用入库",
        "这条值得纳入考虑",
        "我在想正式笔记应该怎么写",
    ],
)
def test_commit_router_ignores_questions_negations_and_nouns(text: str) -> None:
    assert not wants_commit_note_draft(text)


@pytest.mark.parametrize(
    "text",
    ["落库", "落库吧", "好的，落库", "请入库", "保存为笔记", "commit", "Commit this draft"],  # noqa: RUF001
)
def test_commit_router_still_accepts_plain_commands(text: str) -> None:
    assert wants_commit_note_draft(text)


def test_commit_router_respects_english_word_boundary() -> None:
    assert not wants_commit_note_draft("committee notes look fine")


@pytest.mark.parametrize(
    "text",
    ["不要应用修改", "先不要应用修改,再帮我改下开头", "应用修改吗?", "为什么要接受修改"],
)
def test_accept_router_ignores_questions_and_negations(text: str) -> None:
    assert not wants_accept_all_draft_diff(text)


@pytest.mark.parametrize("text", ["应用修改", "请接受所有修改", "accept all", "Apply all changes"])
def test_accept_router_still_accepts_plain_commands(text: str) -> None:
    assert wants_accept_all_draft_diff(text)


@pytest.mark.parametrize("text", ["不要撤回", "先别撤回", "为什么要撤回?", "don't revert"])
def test_reject_router_ignores_questions_and_negations(text: str) -> None:
    assert not wants_reject_all_draft_diff(text)


@pytest.mark.parametrize("text", ["撤回", "全部撤回", "放弃修改", "reject all", "revert"])
def test_reject_router_still_accepts_plain_commands(text: str) -> None:
    assert wants_reject_all_draft_diff(text)


@pytest.mark.parametrize(
    "text",
    ["不要舍弃这条", "要丢弃这条吗？", "为什么要 discard this item", "别丢弃这条"],  # noqa: RUF001
)
def test_discard_router_ignores_questions_and_negations(text: str) -> None:
    assert not wants_discard_raw_info(text)


@pytest.mark.parametrize("text", ["舍弃这条", "丢弃这条吧", "discard this item"])
def test_discard_router_still_accepts_plain_commands(text: str) -> None:
    assert wants_discard_raw_info(text)


# ----------------------------------------------------------- note_chat.py


@pytest.mark.parametrize(
    "text",
    [
        "先不要应用修改,再帮我改下开头",
        "不要应用修改",
        "别接受这个 diff",
        "应用修改吗?",
        "为什么要接受这个 diff",
        "don't apply the diff",
        "应用修改,然后再把标题改短一点",
    ],
)
def test_apply_router_ignores_questions_negations_and_compound_requests(text: str) -> None:
    assert not wants_current_note_edit_apply(text)


@pytest.mark.parametrize(
    "text",
    [
        "请应用当前改动",
        "接受这个 diff",
        "接受当前修改",
        "应用修改",
        "好的，应用修改",  # noqa: RUF001
        "apply the diff",
    ],
)
def test_apply_router_still_accepts_plain_commands(text: str) -> None:
    assert wants_current_note_edit_apply(text)


# ----------------------------------------------- current_note_tools guard


def _apply_ctx(tmp_path: Path, body: str) -> tuple[SimpleNamespace, Vault, Path]:
    vault = Vault(tmp_path)
    vault.init_layout()
    note = Note(id=new_id(), title="T", body=body)
    path = vault.write_note(note)
    ctx = SimpleNamespace(
        vault=vault,
        index=None,
        config=KnowletConfig(),
        current_note_id=note.id,
        pending_note_edit={"old_body": body, "new_body": "REPLACED"},
        mark_note_dirty=None,
        user_request_text=None,
    )
    return ctx, vault, path


def test_apply_tool_guard_rejects_negated_request(tmp_path: Path) -> None:
    ctx, vault, path = _apply_ctx(tmp_path, "original body")
    out = APPLY_CURRENT_NOTE_EDIT_TOOL.handler({"explicit_user_request": "不要应用修改"}, ctx)
    assert out["kind"] == "note_edit_apply_rejected"
    assert vault.read_note(path).body == "original body"


def test_apply_tool_guard_prefers_real_user_text_over_model_argument(tmp_path: Path) -> None:
    """When the session knows what the user actually typed, a model-made
    ``explicit_user_request`` cannot override it."""
    ctx, vault, path = _apply_ctx(tmp_path, "original body")
    ctx.user_request_text = "先不要应用,我再想想"
    out = APPLY_CURRENT_NOTE_EDIT_TOOL.handler({"explicit_user_request": "apply this"}, ctx)
    assert out["kind"] == "note_edit_apply_rejected"
    assert vault.read_note(path).body == "original body"


# ------------------------------------------------- HTTP integration (web)


def _parse_sse(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in text.strip().split("\n\n"):
        block = block.strip()
        if block.startswith("data:"):
            events.append(json.loads(block[len("data:") :].strip()))
    return events


class _DiscussOnlyLLM:
    """Answers in prose; never calls tools. ``chat`` serves the proposal
    tool if a request is (correctly) routed there."""

    def chat_stream(self, messages, tools=None, max_tokens=None, temperature=None, role=None):
        yield ReplyChunkEvent(text="讨论回答")
        yield ReplyDoneEvent(final_text="讨论回答")

    def chat(self, messages, tools=None, max_tokens=None, temperature=None):
        return AssistantMessage(content=json.dumps({"new_body": "proposal body"}), tool_calls=[])


def _ready(tmp_path: Path) -> tuple[Vault, KnowletConfig]:
    vault = Vault(tmp_path)
    vault.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = "stub"
    save_config(vault.root, cfg)
    return vault, cfg


def test_note_chat_negated_apply_does_not_write_note(tmp_path: Path) -> None:
    from knowlet.web.server import create_app

    vault, cfg = _ready(tmp_path)
    note = Note(id=new_id(), title="RAG", body="RAG puts everything into the prompt.")
    vault.write_note(note)
    client = TestClient(create_app(vault, cfg))
    runtime = client.app.state.web_state.runtime_or_init()
    runtime.llm = _DiscussOnlyLLM()  # type: ignore[assignment]
    runtime.session.llm = _DiscussOnlyLLM()  # type: ignore[assignment]

    r = client.post(
        f"/api/chat/note/{note.id}/stream",
        json={
            "text": "先不要应用修改,再帮我改下开头",
            "pending_edit": {
                "old_body": "RAG puts everything into the prompt.",
                "new_body": "RAG retrieves relevant chunks, then generates.",
            },
        },
    )
    assert r.status_code == 200
    names = [e.get("name") for e in _parse_sse(r.text) if e["type"] == "tool_call"]
    assert "apply_current_note_edit" not in names
    after = client.get(f"/api/notes/{note.id}").json()
    assert after["body"] == "RAG puts everything into the prompt."


def test_raw_info_chat_question_does_not_commit_draft(tmp_path: Path) -> None:
    from knowlet.web.server import create_app

    vault, cfg = _ready(tmp_path)
    draft = Draft(id=new_id(), title="Digest draft", body="draft body", tags=["digest"])
    DraftStore(vault.drafts_dir).save(draft)
    item = RawInfo(
        source_id="source-1",
        source_name="Feed",
        source_kind="rss",
        item_key="rss:x",
        title="Raw item",
        url="https://example.com/raw",
        summary="s",
        key_points=["k"],
    )
    item.note_draft_id = draft.id
    item.status = "drafted"
    RawInfoStore(vault.digest_items_dir).save(item)

    client = TestClient(create_app(vault, cfg))
    runtime = client.app.state.web_state.runtime_or_init()
    runtime.llm = _DiscussOnlyLLM()  # type: ignore[assignment]

    with client.stream(
        "POST",
        f"/api/chat/raw-info/{item.id}/stream",
        json={"text": "这份草稿和正式笔记有什么区别?", "history": []},
    ) as res:
        body = "".join(res.iter_text())

    assert res.status_code == 200, body
    names = [e.get("name") for e in _parse_sse(body) if e["type"] == "tool_call"]
    assert "commit_note_draft" not in names
    assert DraftStore(vault.drafts_dir).get(draft.id) is not None
    loaded = RawInfoStore(vault.digest_items_dir).get(item.id)
    assert loaded is not None and loaded.status != "included"
    assert list(vault.iter_note_paths()) == []
