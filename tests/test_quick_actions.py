"""Phase 2 D Slice 2c — Quick actions persistence + endpoints (ADR-0025).

Covers the store (toml round-trip + upsert + delete) and the web
endpoints (list / create / update / delete / run + idempotency).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from knowlet.core.note import Note, new_id
from knowlet.core.quick_actions import (
    CreateNoteParams,
    QuickAction,
    QuickActionStore,
    new_action_id,
    render_title_placeholders,
)


# ---------- store unit tests ----------


def test_store_round_trips_action_via_toml(tmp_path: Path):
    store = QuickActionStore(vault_root=tmp_path)
    action = QuickAction(
        id=new_action_id(),
        name="今日笔记",
        description="创建或打开今日笔记",
        shortcut="Cmd+Shift+D",
        params=CreateNoteParams(
            folder="daily",
            title_template="{{date}}",
            content_template_id=None,
        ),
    )
    store.upsert(action)
    loaded = store.load()
    assert len(loaded) == 1
    got = loaded[0]
    assert got.id == action.id
    assert got.name == "今日笔记"
    assert got.shortcut == "Cmd+Shift+D"
    assert got.description == "创建或打开今日笔记"
    assert isinstance(got.params, CreateNoteParams)
    assert got.params.folder == "daily"
    assert got.params.title_template == "{{date}}"


def test_store_omits_optional_fields_when_none(tmp_path: Path):
    store = QuickActionStore(vault_root=tmp_path)
    store.upsert(
        QuickAction(
            id=new_action_id(),
            name="empty",
            params=CreateNoteParams(folder="", title_template="x"),
        )
    )
    text = store.path.read_text(encoding="utf-8")
    # description / shortcut / content_template_id should not appear.
    assert "description" not in text
    assert "shortcut" not in text
    assert "content_template_id" not in text


def test_store_upsert_replaces_existing_id(tmp_path: Path):
    store = QuickActionStore(vault_root=tmp_path)
    aid = new_action_id()
    store.upsert(
        QuickAction(
            id=aid,
            name="v1",
            params=CreateNoteParams(folder="a", title_template="{{date}}"),
        )
    )
    store.upsert(
        QuickAction(
            id=aid,
            name="v2",  # changed
            params=CreateNoteParams(folder="b", title_template="{{week}}"),
        )
    )
    loaded = store.load()
    assert len(loaded) == 1
    assert loaded[0].name == "v2"
    assert loaded[0].params.folder == "b"


def test_store_delete_returns_false_for_missing(tmp_path: Path):
    store = QuickActionStore(vault_root=tmp_path)
    assert store.delete("nope") is False
    store.upsert(
        QuickAction(
            id="a1",
            name="x",
            params=CreateNoteParams(folder="", title_template="t"),
        )
    )
    assert store.delete("a1") is True
    assert store.load() == []


def test_create_note_params_rejects_traversal():
    with pytest.raises(Exception):
        CreateNoteParams(folder="../escape", title_template="x")
    with pytest.raises(Exception):
        CreateNoteParams(folder="/abs/path", title_template="x")
    with pytest.raises(Exception):
        CreateNoteParams(folder=".hidden/inside", title_template="x")


# ---------- placeholder rendering ----------


def test_render_placeholders():
    fixed = datetime(2026, 5, 9, 14, 23)
    assert render_title_placeholders("{{date}}", now=fixed) == "2026-05-09"
    assert render_title_placeholders("{{month}}", now=fixed) == "2026-05"
    assert render_title_placeholders("{{year}}", now=fixed) == "2026"
    assert render_title_placeholders("{{time}}", now=fixed) == "14:23"
    assert render_title_placeholders("{{datetime}}", now=fixed) == "2026-05-09 14:23"
    assert (
        render_title_placeholders("周报 · {{week}}", now=fixed) == "周报 · 2026-W19"
    )


def test_unknown_placeholder_left_as_is():
    fixed = datetime(2026, 5, 9, 14, 23)
    out = render_title_placeholders("{{title}} {{date}}", now=fixed)
    assert out == "{{title}} 2026-05-09"


# ---------- endpoint integration ----------


from tests.test_web import StubLLM, _client_with_stub  # noqa: E402


def _make_action(folder: str = "daily", title: str = "{{date}}") -> dict:
    return {
        "name": "test",
        "description": None,
        "shortcut": None,
        "params": {
            "kind": "create_note",
            "folder": folder,
            "title_template": title,
        },
    }


def test_endpoint_list_create_delete_round_trip(tmp_path: Path):
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    # Empty list initially.
    r = client.get("/api/quick-actions")
    assert r.status_code == 200, r.text
    assert r.json() == []
    # Create.
    r = client.post("/api/quick-actions", json=_make_action())
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["name"] == "test"
    assert created["id"]
    assert created["params"]["kind"] == "create_note"
    # List shows it.
    r = client.get("/api/quick-actions")
    assert len(r.json()) == 1
    # Delete.
    r = client.delete(f"/api/quick-actions/{created['id']}")
    assert r.status_code == 200
    r = client.get("/api/quick-actions")
    assert r.json() == []


def test_endpoint_update_replaces_in_place(tmp_path: Path):
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.post("/api/quick-actions", json=_make_action())
    assert r.status_code == 200
    aid = r.json()["id"]
    r = client.put(
        f"/api/quick-actions/{aid}",
        json={
            "name": "renamed",
            "description": "now with desc",
            "shortcut": "Cmd+Shift+W",
            "params": {
                "kind": "create_note",
                "folder": "weekly",
                "title_template": "周报 {{week}}",
            },
        },
    )
    assert r.status_code == 200, r.text
    updated = r.json()
    assert updated["id"] == aid
    assert updated["name"] == "renamed"
    assert updated["shortcut"] == "Cmd+Shift+W"
    assert updated["params"]["folder"] == "weekly"


def test_endpoint_run_creates_note_with_rendered_title(tmp_path: Path):
    client, v, _ = _client_with_stub(tmp_path, StubLLM([]))
    runtime = client.app.state.web_state.runtime_or_init()
    r = client.post(
        "/api/quick-actions",
        json=_make_action(folder="daily", title="{{date}}"),
    )
    aid = r.json()["id"]
    r = client.post(f"/api/quick-actions/{aid}/run")
    assert r.status_code == 200, r.text
    note = r.json()
    # Today's local date format YYYY-MM-DD.
    import re

    assert re.match(r"^\d{4}-\d{2}-\d{2}$", note["title"]), note["title"]
    assert note["folder"] == "daily"
    # Note exists on disk.
    on_disk = list((v.notes_dir / "daily").glob("*.md"))
    assert any(p.read_text(encoding="utf-8").find(note["title"]) > -1 for p in on_disk)


def test_endpoint_run_is_idempotent_same_day(tmp_path: Path):
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.post(
        "/api/quick-actions",
        json=_make_action(folder="daily", title="{{date}}"),
    )
    aid = r.json()["id"]
    first = client.post(f"/api/quick-actions/{aid}/run").json()
    second = client.post(f"/api/quick-actions/{aid}/run").json()
    assert first["id"] == second["id"], "second run must reuse the same note"


def test_endpoint_unknown_kind_rejected(tmp_path: Path):
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.post(
        "/api/quick-actions",
        json={
            "name": "x",
            "description": None,
            "shortcut": None,
            "params": {"kind": "ingest_url", "target_folder": "inbox"},
        },
    )
    assert r.status_code == 400
    assert "kind" in r.json()["detail"]


def test_endpoint_run_404_when_action_missing(tmp_path: Path):
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.post("/api/quick-actions/nope/run")
    assert r.status_code == 404
