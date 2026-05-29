"""Stage C v2 source configuration tests.

C4 replaces the old digest source setup surface with first-class RSS /
Prompt Source configuration. Website URL subscriptions are intentionally
not part of this surface.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from knowlet.cli.main import app
from knowlet.config import KnowletConfig, save_config
from knowlet.core.digest_sources import DigestSource, DigestSourceStore
from knowlet.core.vault import Vault
from knowlet.web.server import create_app

runner = CliRunner()


def _ready_vault(tmp_path):
    vault = Vault(tmp_path)
    vault.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = "stub"
    save_config(vault.root, cfg)
    return vault, cfg


def test_digest_source_store_round_trips_rss_and_prompt(tmp_path):
    vault, _cfg = _ready_vault(tmp_path)
    store = DigestSourceStore(vault.digest_sources_dir)

    rss = DigestSource(
        name="AI feed",
        kind="rss",
        url="https://example.com/feed.xml",
    )
    prompt = DigestSource(
        name="Agent prompt",
        kind="prompt",
        prompt="Find today's important AI agent updates.",
        enabled=False,
    )
    store.save(rss)
    store.save(prompt)

    loaded = store.list()
    assert [s.name for s in loaded] == ["AI feed", "Agent prompt"]
    assert loaded[0].kind == "rss"
    assert loaded[0].url == "https://example.com/feed.xml"
    assert loaded[1].kind == "prompt"
    assert loaded[1].prompt == "Find today's important AI agent updates."
    assert loaded[1].enabled is False


def test_digest_source_validation_rejects_bad_rss_or_empty_prompt(tmp_path):
    vault, _cfg = _ready_vault(tmp_path)
    store = DigestSourceStore(vault.digest_sources_dir)

    bad_rss = DigestSource(name="Broken feed", kind="rss", url="not-a-url")
    assert "URL" in "; ".join(bad_rss.validate())

    bad_prompt = DigestSource(name="Empty prompt", kind="prompt", prompt=" ")
    assert "prompt" in "; ".join(bad_prompt.validate()).lower()

    ok = DigestSource(name="HN RSS", kind="rss", url="https://news.ycombinator.com/rss")
    store.save(ok)
    assert store.get(ok.id) is not None


def test_digest_sources_api_create_update_delete(tmp_path):
    vault, cfg = _ready_vault(tmp_path)
    client = TestClient(create_app(vault, cfg))

    created = client.post(
        "/api/digest/sources",
        json={
            "name": "Daily AI",
            "kind": "rss",
            "url": "https://example.com/feed.xml",
            "enabled": True,
        },
    )
    assert created.status_code == 200, created.text
    source = created.json()
    assert source["name"] == "Daily AI"
    assert source["kind"] == "rss"
    assert source["url"] == "https://example.com/feed.xml"
    assert source["prompt"] is None

    updated = client.put(
        f"/api/digest/sources/{source['id']}",
        json={
            "name": "Daily AI",
            "kind": "rss",
            "url": "https://example.com/feed.xml",
            "enabled": False,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["enabled"] is False

    prompt = client.post(
        "/api/digest/sources",
        json={
            "name": "Agent watch",
            "kind": "prompt",
            "prompt": "Find important local-first software updates.",
        },
    )
    assert prompt.status_code == 200, prompt.text
    assert prompt.json()["kind"] == "prompt"

    bad = client.post(
        "/api/digest/sources",
        json={"name": "Website", "kind": "url", "url": "https://example.com"},
    )
    assert bad.status_code == 422

    listed = client.get("/api/digest/sources")
    assert listed.status_code == 200
    assert [s["name"] for s in listed.json()] == ["Daily AI", "Agent watch"]

    deleted = client.delete(f"/api/digest/sources/{prompt.json()['id']}")
    assert deleted.status_code == 200
    listed_after = client.get("/api/digest/sources").json()
    assert [s["name"] for s in listed_after] == ["Daily AI"]


def test_digest_cli_add_list_toggle_remove_v2_sources(tmp_path, monkeypatch):
    vault, _cfg = _ready_vault(tmp_path)
    monkeypatch.setenv("KNOWLET_VAULT", str(vault.root))

    rss = runner.invoke(
        app,
        [
            "digest",
            "add",
            "--name",
            "Daily AI",
            "--rss",
            "https://example.com/feed.xml",
        ],
    )
    assert rss.exit_code == 0, rss.stdout

    prompt = runner.invoke(
        app,
        [
            "digest",
            "add",
            "--name",
            "Agent watch",
            "--prompt",
            "Find important AI agent updates.",
            "--disabled",
        ],
    )
    assert prompt.exit_code == 0, prompt.stdout

    store = DigestSourceStore(vault.digest_sources_dir)
    sources = store.list()
    assert [s.kind for s in sources] == ["rss", "prompt"]
    assert sources[1].enabled is False

    listed = runner.invoke(app, ["digest", "list"])
    assert listed.exit_code == 0, listed.stdout
    assert "Daily AI" in listed.stdout
    assert "Agent watch" in listed.stdout
    assert "prompt" in listed.stdout

    enabled = runner.invoke(app, ["digest", "enable", sources[1].id])
    assert enabled.exit_code == 0, enabled.stdout
    assert DigestSourceStore(vault.digest_sources_dir).get(sources[1].id).enabled is True

    removed = runner.invoke(app, ["digest", "remove", sources[0].id])
    assert removed.exit_code == 0, removed.stdout
    assert [s.name for s in DigestSourceStore(vault.digest_sources_dir).list()] == [
        "Agent watch"
    ]
