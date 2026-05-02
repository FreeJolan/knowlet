"""Tests for M3 — Card entity, CardStore, FSRS wrapper, and the four tools."""

import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from knowlet.config import KnowletConfig, save_config
from knowlet.core.card import Card, parse_due
from knowlet.core.card_store import CardStore
from knowlet.core.fsrs_wrap import (
    initial_state,
    parse_rating,
    schedule_next,
)
from knowlet.core.tools._registry import default_registry
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


# ------------------------------------------------------- Card entity


def test_card_to_from_dict_round_trip():
    c = Card(front="hello", back="world", tags=["greet"], type="basic")
    d = c.to_dict()
    c2 = Card.from_dict(d)
    assert c2.id == c.id
    assert c2.front == "hello"
    assert c2.back == "world"
    assert c2.tags == ["greet"]
    assert c2.type == "basic"


def test_card_from_file(tmp_path: Path):
    c = Card(front="q", back="a", fsrs_state=initial_state())
    p = tmp_path / f"{c.id}.json"
    p.write_text(json.dumps(c.to_dict()), encoding="utf-8")
    loaded = Card.from_file(p)
    assert loaded.id == c.id
    assert loaded.front == "q"
    assert loaded.path == p


def test_parse_due_new_card_is_due_now():
    c = Card()  # empty fsrs_state
    assert parse_due(c) <= datetime.now(UTC)


def test_parse_due_uses_fsrs_state():
    future = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    c = Card(fsrs_state={"due": future})
    assert parse_due(c) > datetime.now(UTC)


# ------------------------------------------------------- CardStore


def test_store_save_then_get(tmp_path: Path):
    store = CardStore(tmp_path / "cards")
    c = Card(front="q", back="a", fsrs_state=initial_state())
    path = store.save(c)
    assert path.exists()
    assert path.read_text()  # not empty
    loaded = store.get(c.id)
    assert loaded is not None
    assert loaded.front == "q"


def test_store_list_cards_empty(tmp_path: Path):
    store = CardStore(tmp_path / "cards")
    assert store.list_cards() == []
    assert store.list_due() == []


def test_store_list_due_includes_brand_new(tmp_path: Path):
    store = CardStore(tmp_path / "cards")
    c = Card(front="q", back="a", fsrs_state=initial_state())
    store.save(c)
    due = store.list_due()
    assert len(due) == 1
    assert due[0].id == c.id


def test_store_list_due_excludes_future(tmp_path: Path):
    store = CardStore(tmp_path / "cards")
    far_future = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    c = Card(front="q", back="a", fsrs_state={"due": far_future})
    store.save(c)
    assert store.list_due() == []


def test_store_delete(tmp_path: Path):
    store = CardStore(tmp_path / "cards")
    c = Card(front="q", back="a")
    store.save(c)
    assert store.delete(c.id) is True
    assert store.get(c.id) is None
    assert store.delete(c.id) is False  # idempotent-ish


# ------------------------------------------------------- FSRS wrapper


def test_parse_rating_int_and_str():
    assert int(parse_rating(1)) == 1
    assert int(parse_rating("good")) == 3
    with pytest.raises(ValueError):
        parse_rating(0)
    with pytest.raises(ValueError):
        parse_rating("excellent")


def test_schedule_next_pushes_due_forward():
    c = Card(front="q", back="a", fsrs_state=initial_state())
    initial_due = parse_due(c)
    # rating 3 (good) — should reschedule into the future
    schedule_next(c, 3, now=datetime.now(UTC))
    new_due = parse_due(c)
    assert new_due >= initial_due


def test_schedule_next_invalid_rating_raises():
    c = Card(front="q", back="a", fsrs_state=initial_state())
    with pytest.raises(ValueError):
        schedule_next(c, 7)


# ------------------------------------------------------- atomic tools


def _ctx(tmp_path: Path):
    """Build a minimal ToolContext for tool dispatch tests."""
    from knowlet.core.drafts import DraftStore
    from knowlet.core.embedding import DummyBackend
    from knowlet.core.index import Index
    from knowlet.core.mining.task_store import TaskStore
    from knowlet.core.tools._registry import ToolContext

    v, cfg = _ready_vault(tmp_path)
    backend = DummyBackend(dim=32)
    idx = Index(v.db_path, backend)
    idx.connect()
    return ToolContext(
        vault=v, index=idx, config=cfg,
        cards=CardStore(v.cards_dir),
        tasks=TaskStore(v.tasks_dir),
        drafts=DraftStore(v.drafts_dir),
    ), idx


def test_tool_create_card_round_trip(tmp_path: Path):
    ctx, idx = _ctx(tmp_path)
    reg = default_registry()
    res = reg.dispatch(
        "create_card",
        {"front": "what is RAG?", "back": "retrieval-augmented generation", "tags": ["rag"]},
        ctx,
    )
    assert "card_id" in res
    res2 = reg.dispatch("get_card", {"card_id": res["card_id"]}, ctx)
    assert res2["card"]["front"] == "what is RAG?"
    assert "rag" in res2["card"]["tags"]
    idx.close()


def test_tool_create_card_validates(tmp_path: Path):
    ctx, idx = _ctx(tmp_path)
    reg = default_registry()
    res = reg.dispatch("create_card", {"front": "", "back": "x"}, ctx)
    assert "error" in res
    res = reg.dispatch("create_card", {"front": "q", "back": "a", "type": "weird"}, ctx)
    assert "error" in res
    idx.close()


def test_tool_list_due_then_review(tmp_path: Path):
    ctx, idx = _ctx(tmp_path)
    reg = default_registry()
    create = reg.dispatch(
        "create_card", {"front": "q1", "back": "a1"}, ctx
    )
    listed = reg.dispatch("list_due_cards", {"limit": 5}, ctx)
    assert listed["count"] == 1
    assert listed["results"][0]["card_id"] == create["card_id"]

    reviewed = reg.dispatch(
        "review_card", {"card_id": create["card_id"], "rating": 3}, ctx
    )
    assert "next_due" in reviewed
    # After good rating, card should be pushed past now → no longer due immediately.
    listed2 = reg.dispatch("list_due_cards", {"limit": 5}, ctx)
    assert listed2["count"] == 0
    idx.close()


def test_tool_review_invalid_rating(tmp_path: Path):
    ctx, idx = _ctx(tmp_path)
    reg = default_registry()
    create = reg.dispatch("create_card", {"front": "q", "back": "a"}, ctx)
    res = reg.dispatch("review_card", {"card_id": create["card_id"], "rating": 99}, ctx)
    assert "error" in res
    idx.close()


def test_tool_get_card_missing(tmp_path: Path):
    ctx, idx = _ctx(tmp_path)
    reg = default_registry()
    res = reg.dispatch("get_card", {"card_id": "01H_NONEXISTENT"}, ctx)
    assert "error" in res
    idx.close()


# ------------------------------------------------------- web endpoints


def test_web_cards_create_and_due(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    client = TestClient(create_app(v, cfg))

    r = client.post(
        "/api/cards",
        json={"front": "what is RRF?", "back": "reciprocal rank fusion", "tags": ["rag"]},
    )
    assert r.status_code == 200
    summary = r.json()
    assert summary["front"] == "what is RRF?"

    due = client.get("/api/cards/due").json()
    assert any(c["id"] == summary["id"] for c in due)


def test_web_cards_review_advances_due(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    client = TestClient(create_app(v, cfg))

    summary = client.post(
        "/api/cards",
        json={"front": "q", "back": "a"},
    ).json()
    card_id = summary["id"]

    r = client.post(f"/api/cards/{card_id}/review", json={"rating": 3})
    assert r.status_code == 200
    out = r.json()
    assert out["id"] == card_id

    due_after = client.get("/api/cards/due").json()
    assert all(c["id"] != card_id for c in due_after)


def test_web_cards_get_full(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    client = TestClient(create_app(v, cfg))
    summary = client.post(
        "/api/cards",
        json={"front": "q", "back": "a", "tags": ["x"]},
    ).json()
    full = client.get(f"/api/cards/{summary['id']}").json()
    assert full["fsrs_state"]
    assert full["tags"] == ["x"]


def test_web_cards_validates_input(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    client = TestClient(create_app(v, cfg))
    r = client.post("/api/cards", json={"front": "", "back": "x"})
    assert r.status_code == 400


def test_web_cards_review_404(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    client = TestClient(create_app(v, cfg))
    r = client.post("/api/cards/no-such-id/review", json={"rating": 3})
    assert r.status_code == 404
