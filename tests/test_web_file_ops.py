"""End-to-end API tests for Phase 1 A file ops (ADR-0021).

Drives /api/tree, /api/folders (POST/PATCH/DELETE + /move), /api/notes/{id}/move,
/api/trash, /api/trash/{name}/restore, /api/trash/{name} and /api/trash.
Index path-column resync is verified — moving a note must update the index
without re-chunking, so a follow-up GET /api/notes/{id} reads the file at
the new location without 404.
"""

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
    # Force runtime init so the index is open + bootstrap completes.
    state = app.state.web_state
    state.runtime_or_init()
    return client, v


def _seed_note(v: Vault, *, title: str, folder: str | None = None) -> Note:
    n = Note(id=new_id(), title=title, body=f"body of {title}")
    v.write_note(n, folder=folder)
    return n


# ------------------------------------------------------------------- tree


def test_tree_empty_vault(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    r = client.get("/api/tree")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == ""
    assert body["path"] == ""
    assert body["folders"] == []
    assert body["notes"] == []


def test_tree_includes_indexed_notes_and_folders(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    _seed_note(v, title="root note")
    _seed_note(v, title="nested", folder="proj/sub")
    v.mkdir_folder("empty")
    # Force a reindex so the index sees the seeded files.
    client.post("/api/system/reindex")

    body = client.get("/api/tree").json()
    folder_names = {f["name"] for f in body["folders"]}
    assert {"proj", "empty"} <= folder_names
    note_titles_at_root = {n["title"] for n in body["notes"]}
    assert "root note" in note_titles_at_root

    proj = next(f for f in body["folders"] if f["name"] == "proj")
    sub = next(f for f in proj["folders"] if f["name"] == "sub")
    assert {n["title"] for n in sub["notes"]} == {"nested"}


# ------------------------------------------------------------------- folders


def test_create_folder(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    r = client.post("/api/folders", json={"path": "projects/knowlet"})
    assert r.status_code == 200, r.text
    assert r.json()["path"] == "projects/knowlet"
    assert (v.notes_dir / "projects" / "knowlet").is_dir()


def test_create_folder_rejects_traversal(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    r = client.post("/api/folders", json={"path": "../oops"})
    assert r.status_code == 400


def test_rename_folder_resyncs_index(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    n = _seed_note(v, title="x", folder="old")
    client.post("/api/system/reindex")

    r = client.patch("/api/folders", json={"path": "old", "new_name": "new"})
    assert r.status_code == 200
    assert r.json()["path"] == "new"

    # Index path column updated → GET note follows the file at its new location.
    got = client.get(f"/api/notes/{n.id}")
    assert got.status_code == 200
    assert got.json()["path"].endswith("new/" + n.filename)


def test_rename_folder_collision(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    v.mkdir_folder("a")
    v.mkdir_folder("b")
    r = client.patch("/api/folders", json={"path": "a", "new_name": "b"})
    assert r.status_code == 409


def test_move_folder_resyncs_index(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    n = _seed_note(v, title="x", folder="src")
    v.mkdir_folder("dst")
    client.post("/api/system/reindex")

    r = client.post("/api/folders/move", json={"src": "src", "dst_parent": "dst"})
    assert r.status_code == 200
    assert r.json()["path"] == "dst/src"

    got = client.get(f"/api/notes/{n.id}")
    assert got.status_code == 200
    assert got.json()["path"].endswith("dst/src/" + n.filename)


def test_delete_folder_trashes_notes(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    n1 = _seed_note(v, title="a", folder="bin")
    n2 = _seed_note(v, title="b", folder="bin/sub")
    client.post("/api/system/reindex")

    r = client.request("DELETE", "/api/folders", json={"path": "bin"})
    assert r.status_code == 200, r.text
    assert r.json()["trashed_count"] == 2

    # Both notes gone from index; folder gone from disk.
    assert client.get(f"/api/notes/{n1.id}").status_code == 404
    assert client.get(f"/api/notes/{n2.id}").status_code == 404
    assert not (v.notes_dir / "bin").exists()


# ------------------------------------------------------------------- note move


def test_move_note(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    n = _seed_note(v, title="x")
    client.post("/api/system/reindex")

    r = client.post(f"/api/notes/{n.id}/move", json={"target_folder": "archive"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["path"].endswith("archive/" + n.filename)
    assert body["folder"] == "archive"
    assert (v.notes_dir / "archive" / n.filename).exists()
    assert not (v.notes_dir / n.filename).exists()


def test_move_note_collision(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    n = _seed_note(v, title="x")
    client.post("/api/system/reindex")
    # Block the destination by writing a same-name file there.
    v.mkdir_folder("archive")
    (v.notes_dir / "archive" / n.filename).write_text("blocker")

    r = client.post(f"/api/notes/{n.id}/move", json={"target_folder": "archive"})
    assert r.status_code == 409


def test_move_unknown_note(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    r = client.post("/api/notes/no-such/move", json={"target_folder": "x"})
    assert r.status_code == 404


# ------------------------------------------------------------------- trash


def test_trash_list_restore_purge(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    n = _seed_note(v, title="ephemeral")
    client.post("/api/system/reindex")

    # Soft-delete via the existing endpoint.
    r = client.delete(f"/api/notes/{n.id}")
    assert r.status_code == 200

    listed = client.get("/api/trash").json()
    names = [e["name"] for e in listed["entries"]]
    assert n.filename in names

    # Restore.
    r = client.post(f"/api/trash/{n.filename}/restore")
    assert r.status_code == 200
    assert r.json()["id"] == n.id
    assert client.get(f"/api/notes/{n.id}").status_code == 200

    # Soft-delete again, then purge.
    client.delete(f"/api/notes/{n.id}")
    r = client.delete(f"/api/trash/{n.filename}")
    assert r.status_code == 200
    listed = client.get("/api/trash").json()
    assert listed["entries"] == []


def test_delete_note_preserves_nested_relative_index_path(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    n = _seed_note(v, title="nested delete", folder="archive")
    client.post("/api/system/reindex")
    nested_path = v.notes_dir / "archive" / n.filename
    # Older/migrated/sync-fed index rows may store paths relative to notes/.
    # Deleting must still target the actual nested file, not notes/<basename>.
    app = client.app
    runtime = app.state.web_state.runtime_or_init()
    runtime.index.update_note_path(n.id, f"archive/{n.filename}")

    r = client.delete(f"/api/notes/{n.id}")

    assert r.status_code == 200, r.text
    assert not nested_path.exists()
    assert (v.trash_dir / n.filename).exists()
    assert client.get(f"/api/notes/{n.id}").status_code == 404


def test_trash_purge_unknown_404(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    r = client.delete("/api/trash/ghost.md")
    assert r.status_code == 404


def test_trash_restore_collision(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    n = _seed_note(v, title="dupe")
    client.post("/api/system/reindex")
    client.delete(f"/api/notes/{n.id}")
    # Manually drop a same-id file back at notes/ to trigger restore conflict.
    (v.notes_dir / n.filename).write_text("blocker")
    r = client.post(f"/api/trash/{n.filename}/restore")
    assert r.status_code == 409


def test_empty_trash(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    n1 = _seed_note(v, title="a")
    n2 = _seed_note(v, title="b")
    client.post("/api/system/reindex")
    client.delete(f"/api/notes/{n1.id}")
    client.delete(f"/api/notes/{n2.id}")
    assert len(client.get("/api/trash").json()["entries"]) == 2

    r = client.delete("/api/trash")
    assert r.status_code == 200
    assert r.json()["purged_count"] == 2
    assert client.get("/api/trash").json()["entries"] == []
