"""Phase 2 D B1 — favorites HTTP endpoint integration tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from knowlet.config import KnowletConfig, save_config
from knowlet.core.note import Note, new_id
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


def _client(tmp_path: Path) -> tuple[TestClient, Vault]:
    v, cfg = _ready_vault(tmp_path)
    app = create_app(v, cfg)
    client = TestClient(app)
    state = app.state.web_state
    state.runtime_or_init()
    return client, v


def _seed_note(v: Vault, title: str) -> Note:
    n = Note(id=new_id(), title=title, body=f"body of {title}")
    v.write_note(n)
    return n


def test_list_favorites_empty(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    r = client.get("/api/favorites")
    assert r.status_code == 200
    assert r.json() == {"favorites": []}


def test_add_then_list_returns_title(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    n = _seed_note(v, "alpha")
    client.post("/api/system/reindex")

    r = client.post(f"/api/favorites/{n.id}")
    assert r.status_code == 200, r.text
    favs = r.json()["favorites"]
    assert len(favs) == 1
    assert favs[0] == {"id": n.id, "title": "alpha"}


def test_add_unknown_note_returns_404(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    r = client.post("/api/favorites/01HMISSING")
    assert r.status_code == 404


def test_remove_favorite(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    n = _seed_note(v, "alpha")
    client.post("/api/system/reindex")
    client.post(f"/api/favorites/{n.id}")
    r = client.delete(f"/api/favorites/{n.id}")
    assert r.status_code == 200
    assert r.json() == {"favorites": []}


def test_remove_unknown_is_idempotent(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    r = client.delete("/api/favorites/01HNEVERSTARRED")
    # No 404 — DELETE on something already absent is a no-op.
    assert r.status_code == 200
    assert r.json() == {"favorites": []}


def test_listing_prunes_deleted_notes(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    n1 = _seed_note(v, "alpha")
    n2 = _seed_note(v, "beta")
    client.post("/api/system/reindex")
    client.post(f"/api/favorites/{n1.id}")
    client.post(f"/api/favorites/{n2.id}")

    # Now delete alpha at the vault level.
    r = client.delete(f"/api/notes/{n1.id}")
    assert r.status_code in (200, 204), r.text

    # Listing must drop alpha silently.
    favs = client.get("/api/favorites").json()["favorites"]
    fav_ids = [f["id"] for f in favs]
    assert n1.id not in fav_ids
    assert n2.id in fav_ids


def test_add_preserves_order(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    a = _seed_note(v, "a")
    b = _seed_note(v, "b")
    c = _seed_note(v, "c")
    client.post("/api/system/reindex")
    for n in (b, a, c):
        client.post(f"/api/favorites/{n.id}")
    favs = client.get("/api/favorites").json()["favorites"]
    assert [f["id"] for f in favs] == [b.id, a.id, c.id]
