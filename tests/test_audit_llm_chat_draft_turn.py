"""Regression tests: the draft-anchored chat prompt must steer the model to
the draft tools, not the current-note tools (server.py:4102 cross-batch
item, llm-chat audit batch). A draft is not in the index, so every
*_current_note_* call from a draft chat fails with "current note not
found"."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from knowlet.chat.note_chat import TONE_GUIDANCE, build_draft_grounded_turn
from knowlet.core.drafts import Draft, DraftStore
from knowlet.core.events import ReplyChunkEvent, ReplyDoneEvent, ToolCallEvent
from knowlet.core.llm import AssistantMessage
from knowlet.core.note import new_id
from knowlet.core.vault import Vault
from tests.test_web_note_chat import StreamStubLLM, _client_with_draft, _parse_sse

_DRAFT_TOOLS = (
    "propose_current_draft_edit",
    "accept_all_draft_diff",
    "reject_all_draft_diff",
    "commit_note_draft",
)


def _draft(**overrides: Any) -> Draft:
    fields: dict[str, Any] = {
        "id": new_id(),
        "title": "Feed item",
        "body": "UNIQUE_DRAFT_BODY_MARKER_77",
        "tags": ["digest"],
    }
    fields.update(overrides)
    return Draft(**fields)


def test_draft_turn_grounds_body_and_names_only_draft_tools() -> None:
    draft = _draft()
    turn = build_draft_grounded_turn(draft, "帮我润色一下")

    assert TONE_GUIDANCE in turn
    assert re.search(
        r"<anchored-draft[^>]*>\s*UNIQUE_DRAFT_BODY_MARKER_77\s*</anchored-draft>", turn
    )
    assert "Feed item" in turn
    assert turn.rstrip().endswith("帮我润色一下")
    for name in _DRAFT_TOOLS:
        assert name in turn, name
    assert "current_note" not in turn
    assert "check_current_note" not in turn


def test_draft_turn_reports_pending_diff_state() -> None:
    without = build_draft_grounded_turn(_draft(), "x")
    with_diff = build_draft_grounded_turn(
        _draft(pending_diff_base="UNIQUE_DRAFT_BODY_MARKER_77", pending_diff_body="new"),
        "x",
    )
    assert "待审阅 diff:无" in without
    assert "待审阅 diff:有" in with_diff


# ------------------------------------------------- HTTP: /api/chat/draft


def test_draft_chat_stream_sends_draft_prompt_to_the_model(tmp_path: Path) -> None:
    stub = StreamStubLLM([ReplyDoneEvent(final_text="draft answer")])
    client, draft = _client_with_draft(tmp_path, body="UNIQUE_DRAFT_BODY_MARKER_77", stub=stub)

    r = client.post(f"/api/chat/draft/{draft.id}/stream", json={"text": "这条讲了什么?"})

    assert r.status_code == 200
    assert "turn_done" in [e["type"] for e in _parse_sse(r.text)]
    assert stub.seen_messages is not None
    user_turn = stub.seen_messages[-1]
    assert user_turn["role"] == "user"
    assert "<anchored-draft" in user_turn["content"]
    assert "UNIQUE_DRAFT_BODY_MARKER_77" in user_turn["content"]
    assert "propose_current_draft_edit" in user_turn["content"]
    assert "current_note" not in user_turn["content"]
    assert "<anchored-note" not in user_turn["content"]


class _ProposesDraftEdit:
    """Follows the draft prompt: calls propose_current_draft_edit, then
    answers. ``chat`` serves the nested proposal call."""

    def __init__(self) -> None:
        self.stream_calls = 0

    def chat_stream(self, messages, tools=None, max_tokens=None, temperature=None) -> Iterator[Any]:
        self.stream_calls += 1
        if self.stream_calls == 1:
            yield ToolCallEvent(
                id="draft_edit_1",
                name="propose_current_draft_edit",
                arguments={"instruction": "把第一句改得更具体"},
            )
            yield ReplyDoneEvent(final_text="")
            return
        yield ReplyChunkEvent(text="已生成草稿 diff。")
        yield ReplyDoneEvent(final_text="已生成草稿 diff。")

    def chat(self, messages, tools=None, max_tokens=None, temperature=None):
        return AssistantMessage(
            content=json.dumps({"new_body": "revised draft body"}), tool_calls=[]
        )


def test_draft_chat_edit_request_reaches_a_working_draft_tool(tmp_path: Path) -> None:
    client, draft = _client_with_draft(
        tmp_path, body="original draft body", stub=_ProposesDraftEdit()
    )

    r = client.post(f"/api/chat/draft/{draft.id}/stream", json={"text": "帮我改得更具体"})

    assert r.status_code == 200
    events = _parse_sse(r.text)
    result = next(e for e in events if e["type"] == "tool_result")
    assert result["name"] == "propose_current_draft_edit"
    assert "error" not in result["payload"], result["payload"]
    assert result["payload"]["changed"] is True
    stored = DraftStore(Vault(tmp_path).drafts_dir).get(draft.id)
    assert stored is not None
    assert stored.pending_diff_body == "revised draft body"
    assert stored.body == "original draft body"
