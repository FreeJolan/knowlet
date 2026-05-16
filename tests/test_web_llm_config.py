"""P3.0 — LLM config HTTP endpoint smoke tests.

knowlet does not evaluate, classify, or comment on user-chosen
models (per ADR-0028 §1 amendment 2026-05-16). Tests only cover:
- GET returns config minus api_key
- PUT semantics (partial update, empty-key keeps existing,
  non-empty overwrites)
- /test endpoint exists (actual LLM connectivity not tested here)
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from knowlet.config import KnowletConfig, save_config
from knowlet.core.vault import Vault
from knowlet.web.server import create_app


def _client(tmp_path: Path) -> tuple[TestClient, Vault, KnowletConfig]:
    v = Vault(tmp_path)
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = "starting-secret"
    cfg.llm.model = "claude-opus-4-7"
    cfg.llm.provider = "anthropic"
    save_config(v.root, cfg)
    app = create_app(v, cfg)
    client = TestClient(app)
    app.state.web_state.runtime_or_init()
    return client, v, cfg


# ----------------------------------------------------- GET /api/llm/config


def test_get_returns_config_without_api_key(tmp_path: Path) -> None:
    client, _v, _cfg = _client(tmp_path)
    r = client.get("/api/llm/config")
    assert r.status_code == 200
    body = r.json()
    # Sensitive fields never exposed.
    assert "api_key" not in body
    # has_api_key signals presence to the UI.
    assert body["has_api_key"] is True
    # Other fields round-trip.
    assert body["model"] == "claude-opus-4-7"
    # No tier field — knowlet doesn't classify models.
    assert "tier" not in body
    # No provider field — removed 2026-05-16 (vestigial label,
    # actual call only uses base_url + api_key + model).
    assert "provider" not in body


def test_get_has_api_key_false_when_empty(tmp_path: Path) -> None:
    """GET /api/llm/config must not require a working LLM — that's
    the whole point of a config endpoint that surfaces 'not yet
    configured' state."""
    v = Vault(tmp_path)
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = ""  # no key
    cfg.llm.model = "claude-opus-4-7"
    save_config(v.root, cfg)
    app = create_app(v, cfg)
    client = TestClient(app)
    # Skip runtime_or_init — empty api_key would raise 503; the config
    # endpoint must work without it (it's how users bootstrap from
    # a fresh install).
    r = client.get("/api/llm/config")
    assert r.status_code == 200
    assert r.json()["has_api_key"] is False


# ----------------------------------------------------- PUT /api/llm/config


def test_put_updates_model_and_keeps_existing_key(tmp_path: Path) -> None:
    client, v, _cfg = _client(tmp_path)
    # Empty api_key in payload = leave existing intact (so UI doesn't
    # have to round-trip the secret to save other fields).
    r = client.put(
        "/api/llm/config",
        json={"model": "claude-sonnet-4-6", "api_key": ""},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model"] == "claude-sonnet-4-6"
    assert body["has_api_key"] is True  # existing key preserved

    # Verify by reading config file.
    from knowlet.config import load_config

    persisted = load_config(v.root)
    assert persisted.llm.model == "claude-sonnet-4-6"
    assert persisted.llm.api_key == "starting-secret"


def test_put_overwrites_api_key_when_non_empty(tmp_path: Path) -> None:
    client, v, _cfg = _client(tmp_path)
    r = client.put(
        "/api/llm/config",
        json={"api_key": "fresh-secret"},
    )
    assert r.status_code == 200
    from knowlet.config import load_config

    persisted = load_config(v.root)
    assert persisted.llm.api_key == "fresh-secret"


def test_put_partial_update(tmp_path: Path) -> None:
    """Only fields present in the payload should change."""
    client, v, _cfg = _client(tmp_path)
    r = client.put(
        "/api/llm/config",
        json={"max_tokens": 4096},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["max_tokens"] == 4096
    # Other fields unchanged.
    assert body["model"] == "claude-opus-4-7"


# ----------------------------------------------------- /api/llm/recommended


def test_recommended_endpoint_removed(tmp_path: Path) -> None:
    """Endpoint was removed in 2026-05-16 cleanup — knowlet doesn't
    recommend specific models (we have no qualified evaluation
    pipeline, per ADR-0028 §1 amendment)."""
    client, _v, _cfg = _client(tmp_path)
    r = client.get("/api/llm/recommended")
    assert r.status_code == 404
