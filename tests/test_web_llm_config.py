"""P3.0 — LLM config HTTP endpoint smoke tests."""

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
    assert body["provider"] == "anthropic"
    assert body["model"] == "claude-opus-4-7"
    # Tier is derived.
    assert body["tier"]["tier"] == "A"
    assert body["tier"]["degraded_roles"] == []


def test_get_tier_for_b_tier_model(tmp_path: Path) -> None:
    client, v, cfg = _client(tmp_path)
    cfg.llm.model = "claude-haiku-4-5"
    save_config(v.root, cfg)
    r = client.get("/api/llm/config")
    body = r.json()
    assert body["tier"]["tier"] == "B"
    # Editor advisor / linter degraded on Haiku.
    assert "editor_advisor" in body["tier"]["degraded_roles"]
    assert "linter" in body["tier"]["degraded_roles"]


def test_get_tier_for_unknown_model(tmp_path: Path) -> None:
    client, v, cfg = _client(tmp_path)
    cfg.llm.model = "some-mystery-model"
    save_config(v.root, cfg)
    r = client.get("/api/llm/config")
    body = r.json()
    assert body["tier"]["tier"] == "unknown"
    # Unknown defaults to C (safest).
    assert "linter" in body["tier"]["degraded_roles"]


def test_get_has_api_key_false_when_empty(tmp_path: Path) -> None:
    """GET /api/llm/config must not require a working LLM —— that's
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
    # Deliberately skip ``runtime_or_init()`` — that would fail
    # because the empty api_key path raises 503; but the config
    # endpoint itself must work without it (it's how the user
    # bootstraps from a fresh install).
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
    assert body["provider"] == "anthropic"


# ----------------------------------------------------- GET /api/llm/recommended


def test_recommended_returns_grouped_by_provider(tmp_path: Path) -> None:
    client, _v, _cfg = _client(tmp_path)
    r = client.get("/api/llm/recommended")
    assert r.status_code == 200
    body = r.json()
    providers = body["providers"]
    assert "cliproxyapi" in providers
    assert "anthropic" in providers
    assert "openai" in providers
    # cliproxyapi entries hint at the local port.
    cp = providers["cliproxyapi"]
    assert all(
        m["base_url_hint"].startswith("http://127.0.0.1:")
        for m in cp
    )
    # Each entry has tier annotation.
    for entries in providers.values():
        for m in entries:
            assert m["tier"] in {"A", "B", "C"}
            assert m["model_id"]
            assert m["display_name"]
