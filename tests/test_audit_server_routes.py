"""Regression tests for read routes that resolve index paths / tags:
/api/graph with folder-relative index paths, and nested tags
(``project/knowlet``) on /api/tags/{tag}/notes."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from knowlet.config import KnowletConfig, save_config
from knowlet.core.note import Note, new_id
from knowlet.core.vault import Vault
from knowlet.web.server import create_app


def _app(tmp_path: Path):
    v = Vault(tmp_path)
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = "stub"
    save_config(v.root, cfg)
    app = create_app(v, cfg)
    runtime = app.state.web_state.runtime_or_init()
    return TestClient(app), v, runtime


def _add(v: Vault, runtime, note: Note, folder: str | None = None) -> Note:
    v.write_note(note, folder=folder)
    runtime.index.upsert_note(note, chunk_size=400, chunk_overlap=40)
    return note


def test_graph_reads_notes_in_subfolders_via_relative_index_paths(tmp_path: Path) -> None:
    client, v, runtime = _app(tmp_path)
    target = _add(v, runtime, Note(id=new_id(), title="Target", body="t"))
    source = _add(v, runtime, Note(id=new_id(), title="Source", body="see [[Target]]"), "sub/deep")
    # Older / sync-fed index rows store the path relative to notes/.
    runtime.index.update_note_path(source.id, f"sub/deep/{source.filename}")

    graph = client.get("/api/graph").json()
    assert {"source": source.id, "target": target.id} in graph["edges"]
    folders = {n["id"]: n["folder"] for n in graph["nodes"]}
    assert folders[source.id] == "sub/deep"


def test_graph_does_not_read_a_same_named_root_file(tmp_path: Path) -> None:
    client, v, runtime = _app(tmp_path)
    _add(v, runtime, Note(id=new_id(), title="Target", body="t"))
    source = _add(v, runtime, Note(id=new_id(), title="Source", body="no links"), "sub")
    runtime.index.update_note_path(source.id, f"sub/{source.filename}")
    # A stray root-level file with the same basename links somewhere else.
    stray = Note(id=source.id, title="Stray", body="[[Target]]")
    (v.notes_dir / source.filename).write_text(stray.to_markdown(), encoding="utf-8")

    graph = client.get("/api/graph").json()
    assert graph["edges"] == []


def test_tag_notes_lists_folder_for_relative_index_paths(tmp_path: Path) -> None:
    client, v, runtime = _app(tmp_path)
    note = _add(v, runtime, Note(id=new_id(), title="T", body="b", tags=["x"]), "a/b")
    runtime.index.update_note_path(note.id, f"a/b/{note.filename}")
    rows = client.get("/api/tags/x/notes").json()
    assert [(r["id"], r["folder"]) for r in rows] == [(note.id, "a/b")]


def test_nested_tag_route_returns_matching_notes(tmp_path: Path) -> None:
    client, v, runtime = _app(tmp_path)
    nested = _add(v, runtime, Note(id=new_id(), title="N", body="b", tags=["project/knowlet"]))
    _add(v, runtime, Note(id=new_id(), title="Other", body="b", tags=["project"]))
    r = client.get("/api/tags/project/knowlet/notes")
    assert r.status_code == 200, r.text
    assert [row["id"] for row in r.json()] == [nested.id]
    # Percent-encoded segments decode to the same tag.
    r = client.get("/api/tags/project%2Fknowlet/notes")
    assert r.status_code == 200
    assert [row["id"] for row in r.json()] == [nested.id]


def test_sibling_tag_routes_still_match(tmp_path: Path) -> None:
    client, v, runtime = _app(tmp_path)
    _add(v, runtime, Note(id=new_id(), title="N", body="b", tags=["project/knowlet"]))
    r = client.get("/api/tags/all-with-notes")
    assert r.status_code == 200
    assert [t["tag"] for t in r.json()] == ["project/knowlet"]
    assert client.get("/api/tags").status_code == 200
