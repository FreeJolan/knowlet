"""Unit tests for `ConversationStore` (M6.4 Phase 1)."""

from __future__ import annotations

import json
from pathlib import Path

from knowlet.chat.conversation_store import (
    Conversation,
    ConversationStore,
)


def test_save_and_get_round_trip(tmp_path: Path):
    store = ConversationStore(tmp_path)
    conv = Conversation(
        title="hello",
        model="m",
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "yo"},
        ],
    )
    store.save(conv)

    loaded = store.get(conv.id)
    assert loaded is not None
    assert loaded.id == conv.id
    assert loaded.title == "hello"
    assert loaded.model == "m"
    assert len(loaded.messages) == 3


def test_save_updates_updated_at(tmp_path: Path):
    store = ConversationStore(tmp_path)
    conv = Conversation(messages=[{"role": "system", "content": ""}])
    store.save(conv)
    first = conv.updated_at
    # Force a different second so the timestamp changes.
    import time
    time.sleep(1.05)
    conv.messages.append({"role": "user", "content": "hi"})
    store.save(conv)
    assert conv.updated_at > first


def test_list_sorted_by_updated_at_desc(tmp_path: Path):
    store = ConversationStore(tmp_path)
    msgs = [{"role": "system", "content": ""}, {"role": "user", "content": "x"}]
    a = Conversation(title="a", messages=list(msgs))
    b = Conversation(title="b", messages=list(msgs))
    c = Conversation(title="c", messages=list(msgs))
    store.save(a)
    import time; time.sleep(1.05)
    store.save(b)
    import time; time.sleep(1.05)
    store.save(c)

    rows = store.list()
    assert [r.title for r in rows] == ["c", "b", "a"]


def test_list_only_meaningful_filters_empty_sessions(tmp_path: Path):
    """A conversation that only has the system prompt must not show up
    in the sidebar — the user opened the chat dock and never wrote
    anything; surfacing that as a session is just noise."""
    store = ConversationStore(tmp_path)
    empty = Conversation(messages=[{"role": "system", "content": "sys"}])
    real = Conversation(
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ]
    )
    store.save(empty)
    store.save(real)

    rows = store.list(only_meaningful=True)
    assert [r.id for r in rows] == [real.id]

    all_rows = store.list(only_meaningful=False)
    assert {r.id for r in all_rows} == {empty.id, real.id}


def test_most_recent_returns_full_conversation(tmp_path: Path):
    store = ConversationStore(tmp_path)
    conv = Conversation(
        messages=[
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ],
    )
    store.save(conv)
    out = store.most_recent()
    assert out is not None
    assert out.id == conv.id
    assert len(out.messages) == 2


def test_most_recent_empty_dir(tmp_path: Path):
    store = ConversationStore(tmp_path / "missing")
    assert store.most_recent() is None
    assert store.list() == []


def test_rename(tmp_path: Path):
    store = ConversationStore(tmp_path)
    conv = Conversation(title="old", messages=[{"role": "system", "content": ""}])
    store.save(conv)

    out = store.rename(conv.id, "  shiny new title  ")
    assert out is not None
    assert out.title == "shiny new title"
    assert store.get(conv.id).title == "shiny new title"


def test_rename_missing_returns_none(tmp_path: Path):
    store = ConversationStore(tmp_path)
    assert store.rename("nope", "x") is None


def test_delete_removes_file(tmp_path: Path):
    store = ConversationStore(tmp_path)
    conv = Conversation(messages=[{"role": "system", "content": ""}])
    store.save(conv)
    assert (tmp_path / f"{conv.id}.json").exists()

    assert store.delete(conv.id) is True
    assert not (tmp_path / f"{conv.id}.json").exists()
    assert store.delete(conv.id) is False  # already gone


def test_legacy_log_format_loads_with_defaults(tmp_path: Path):
    """M0 single-log files lacked `title` / `updated_at`. The new store
    must still load them so users don't lose pre-M6.4 conversations."""
    legacy_id = "01HX0000000000000000000001"
    legacy = {
        "id": legacy_id,
        "model": "claude-opus-4-7",
        "started_at": "2026-04-30T00:00:00Z",
        "ended_at": "2026-04-30T00:42:00Z",
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ],
    }
    p = tmp_path / f"{legacy_id}.json"
    p.write_text(json.dumps(legacy), encoding="utf-8")

    store = ConversationStore(tmp_path)
    loaded = store.get(legacy_id)
    assert loaded is not None
    assert loaded.id == legacy_id
    assert loaded.title == ""  # no title in legacy file
    assert loaded.updated_at == "2026-04-30T00:42:00Z"  # falls back to ended_at
    assert len(loaded.messages) == 2


def test_new_seeds_system_prompt(tmp_path: Path):
    store = ConversationStore(tmp_path)
    conv = store.new(model="claude-opus-4-7", system_prompt="be brief")
    assert conv.model == "claude-opus-4-7"
    assert conv.messages == [{"role": "system", "content": "be brief"}]
    assert not conv.is_meaningful  # system prompt only doesn't count


def test_is_meaningful_threshold(tmp_path: Path):
    a = Conversation(messages=[])
    b = Conversation(messages=[{"role": "system", "content": ""}])
    c = Conversation(
        messages=[
            {"role": "system", "content": ""},
            {"role": "user", "content": "hi"},
        ]
    )
    assert not a.is_meaningful
    assert not b.is_meaningful
    assert c.is_meaningful
