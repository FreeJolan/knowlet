"""Phase 1 B slice 8 — templates folder + apply-on-create.

Notes that live in `notes/templates/` are surfaced via
`/api/templates`; `POST /api/notes/new` accepts an optional
`template_id` and pre-fills the body from that template with
`{{title}}` / `{{date}}` substituted.
"""

from __future__ import annotations

from datetime import date
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


def _seed_template(
    v: Vault,
    *,
    title: str,
    body: str,
    kind: str = "knowledge",
) -> Note:
    """Write a note into the system templates folder."""
    note = Note(id=new_id(), title=title, body=body, kind=kind)  # type: ignore[arg-type]
    v.write_note(note, folder=Vault.TEMPLATE_DIR)
    return note


def test_mkdir_rejects_templates_folder(tmp_path: Path) -> None:
    """Users cannot create the system templates folder via the regular
    `mkdir_folder` path. The Templates dialog creates entries
    implicitly via `write_note` (which is allowed)."""
    import pytest

    v, _ = _ready_vault(tmp_path)
    with pytest.raises(ValueError):
        v.mkdir_folder(Vault.TEMPLATE_DIR)
    # And nested under it for good measure.
    with pytest.raises(ValueError):
        v.mkdir_folder(f"{Vault.TEMPLATE_DIR}/nested")


# -------------------------------------------------- vault helpers


def test_iter_templates_empty_when_dir_missing(tmp_path: Path) -> None:
    v, _ = _ready_vault(tmp_path)
    assert v.iter_templates() == []


def test_iter_templates_lists_only_templates_folder(tmp_path: Path) -> None:
    v, _ = _ready_vault(tmp_path)
    a = _seed_template(v, title="daily", body="x")
    b = _seed_template(v, title="meeting", body="y")
    # Plus a regular note OUTSIDE templates/ — must not be listed.
    other = Note(id=new_id(), title="not-a-template", body="z")
    v.write_note(other)
    paths = v.iter_templates()
    titles = {v.read_note(p).title for p in paths}
    assert titles == {a.title, b.title}


def test_apply_template_substitutes_known_placeholders() -> None:
    body = "# {{title}}\n\n{{date}} — created today."
    out = Vault.apply_template_placeholders(body, title="hello world")
    today = date.today().isoformat()
    assert "# hello world" in out
    assert today in out


def test_apply_template_leaves_unknown_placeholders() -> None:
    body = "{{cursor}} and {{title}} but {{unknown}} stays"
    out = Vault.apply_template_placeholders(body, title="x")
    # Known is replaced; unknown passes through.
    assert "{{cursor}}" in out
    assert "{{unknown}}" in out
    assert "x" in out


def test_apply_template_supports_whitespace_inside_braces() -> None:
    body = "{{ title }} -> {{ date }}"
    out = Vault.apply_template_placeholders(body, title="abc", date="2026-01-02")
    assert out == "abc -> 2026-01-02"


# -------------------------------------------------- /api/templates


def test_list_templates_returns_titles(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    daily = _seed_template(v, title="daily", body="d", kind="reference")
    meeting = _seed_template(v, title="meeting", body="m")
    r = client.get("/api/templates")
    assert r.status_code == 200
    rows = r.json()
    by_id = {row["id"]: row["title"] for row in rows}
    assert by_id == {daily.id: "daily", meeting.id: "meeting"}
    kind_by_id = {row["id"]: row["kind"] for row in rows}
    assert kind_by_id == {daily.id: "reference", meeting.id: "knowledge"}


def test_create_template_endpoint_writes_template_note(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    r = client.post(
        "/api/templates",
        json={
            "title": "reference clipping",
            "kind": "reference",
            "body": "# {{title}}\n\nSource: ",
        },
    )
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["title"] == "reference clipping"
    assert created["kind"] == "reference"
    assert created["folder"] == "_templates"
    path = v.notes_dir / Vault.TEMPLATE_DIR / f"{created['id']}.md"
    assert path.exists()
    assert "kind: reference" in path.read_text(encoding="utf-8")

    rows = client.get("/api/templates").json()
    assert any(row["id"] == created["id"] and row["kind"] == "reference" for row in rows)


def test_list_templates_empty_when_no_dir(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    r = client.get("/api/templates")
    assert r.status_code == 200
    assert r.json() == []


# -------------------------------------------------- /api/notes/new with template


def test_new_note_with_template_applies_body_and_substitutes(
    tmp_path: Path,
) -> None:
    client, v = _client(tmp_path)
    tpl = _seed_template(
        v,
        title="daily",
        body="# {{title}}\n\n_started {{date}}_",
    )
    r = client.post(
        "/api/notes/new",
        json={"title": "thursday", "template_id": tpl.id},
    )
    assert r.status_code == 200, r.text
    body = r.json()["body"]
    assert "# thursday" in body
    assert date.today().isoformat() in body


def test_new_note_with_template_inherits_template_kind(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    tpl = _seed_template(
        v,
        title="reference template",
        body="# {{title}}",
        kind="reference",
    )
    r = client.post(
        "/api/notes/new",
        json={"title": "clipped article", "template_id": tpl.id},
    )
    assert r.status_code == 200, r.text
    note = r.json()
    assert note["kind"] == "reference"
    path = v.notes_dir / f"{note['id']}.md"
    assert "kind: reference" in path.read_text(encoding="utf-8")


def test_new_note_with_unknown_template_404(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    r = client.post(
        "/api/notes/new",
        json={"title": "x", "template_id": "01HXNOTAREAL"},
    )
    assert r.status_code == 404


def test_new_note_without_template_keeps_blank_body(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    _seed_template(v, title="daily", body="should not appear")
    r = client.post("/api/notes/new", json={"title": "blank"})
    assert r.status_code == 200
    assert r.json()["body"] == ""
