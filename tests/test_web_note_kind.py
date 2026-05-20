"""POST /api/notes/{id}/kind — promote / demote semantics
(Phase 3 Stage 2 — ADR-0029 §4.5).

Covers:
- Default kind on a freshly-seeded note is "knowledge"
- reference → knowledge (upgrade) is instant, no confirm required
- knowledge → reference (downgrade) without confirm → 409
- knowledge → reference (downgrade) with confirm=true → 200
- Same-kind no-op succeeds and returns current shape
- Unknown note id → 404
- GET /api/notes/{id} returns kind in NoteFull
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from knowlet.config import KnowletConfig, save_config
from knowlet.core.note import Note, new_id
from knowlet.core.vault import Vault
from knowlet.web.server import create_app


def _client(tmp_path: Path) -> tuple[TestClient, Vault]:
    v = Vault(tmp_path)
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = "stub"
    save_config(v.root, cfg)
    app = create_app(v, cfg)
    client = TestClient(app)
    app.state.web_state.runtime_or_init()
    return client, v


def _seed_note(client: TestClient, v: Vault, *, kind: str = "knowledge") -> str:
    n = Note(id=new_id(), title="seed", body="body", kind=kind)
    v.write_note(n)
    # Ensure it's in the index so /api/notes/{id} can find it.
    state = client.app.state.web_state  # type: ignore[attr-defined]
    runtime = state.runtime_or_init()
    runtime.index.upsert_note(n, chunk_size=500, chunk_overlap=100)
    return n.id


# ----------------------------------------------- GET returns kind


def test_get_note_includes_kind(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    note_id = _seed_note(client, v, kind="reference")
    r = client.get(f"/api/notes/{note_id}")
    assert r.status_code == 200
    assert r.json()["kind"] == "reference"


def test_default_kind_is_knowledge(tmp_path: Path) -> None:
    """Notes created without an explicit kind default to knowledge
    (manual-create path per ADR-0029 §4.5)."""
    client, v = _client(tmp_path)
    note_id = _seed_note(client, v)
    r = client.get(f"/api/notes/{note_id}")
    assert r.json()["kind"] == "knowledge"


# ----------------------------------------------- upgrade


def test_upgrade_reference_to_knowledge_is_instant(tmp_path: Path) -> None:
    """资料 → 知识 is an upgrade per ADR-0029 §4.5 — no confirm needed."""
    client, v = _client(tmp_path)
    note_id = _seed_note(client, v, kind="reference")
    r = client.post(
        f"/api/notes/{note_id}/kind",
        json={"kind": "knowledge"},  # no confirm
    )
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "knowledge"
    # Verify it actually persisted.
    raw = (v.notes_dir / f"{note_id}.md").read_text(encoding="utf-8")
    assert "kind: knowledge" in raw


# ----------------------------------------------- downgrade asymmetry


def test_downgrade_without_confirm_returns_409(tmp_path: Path) -> None:
    """知识 → 资料 without confirm=true is rejected. This is the
    anti-drift / escape-hatch guard from ADR-0029 §4.5."""
    client, v = _client(tmp_path)
    note_id = _seed_note(client, v, kind="knowledge")
    r = client.post(
        f"/api/notes/{note_id}/kind",
        json={"kind": "reference"},  # no confirm
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "demote_requires_confirm"
    # Note should be unchanged on disk.
    raw = (v.notes_dir / f"{note_id}.md").read_text(encoding="utf-8")
    assert "kind: knowledge" in raw


def test_downgrade_with_confirm_succeeds(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    note_id = _seed_note(client, v, kind="knowledge")
    r = client.post(
        f"/api/notes/{note_id}/kind",
        json={"kind": "reference", "confirm": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "reference"


# ----------------------------------------------- no-op + edge cases


def test_same_kind_is_noop_200(tmp_path: Path) -> None:
    """POSTing the current kind succeeds (no-op). Useful so the UI
    can call with current state without special-casing."""
    client, v = _client(tmp_path)
    note_id = _seed_note(client, v, kind="reference")
    r = client.post(
        f"/api/notes/{note_id}/kind",
        json={"kind": "reference"},
    )
    assert r.status_code == 200
    assert r.json()["kind"] == "reference"


def test_unknown_note_id_returns_404(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    r = client.post(
        "/api/notes/01NONEXISTENT/kind",
        json={"kind": "reference", "confirm": True},
    )
    assert r.status_code == 404
