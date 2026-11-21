"""Regression tests for note / folder endpoints in the web server.

Covers: folder rename / move and single-note move duplicating notes whose
filename is not ``<id>.md``, folder rename refreshing ``updated_at``,
folder delete using the trash filename stem as the note id, corrupted
note saves drifting to a new id, missing ``folder`` on single-note
responses, POST /api/notes not queueing a push, empty tree tags, and the
PUT handler re-adding chip-removed inline tags.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from knowlet.config import KnowletConfig, save_config
from knowlet.core.audit_log import AuditEventStore
from knowlet.core.backups import BackupStore
from knowlet.core.note import Note, new_id
from knowlet.core.sync.state import FileState, SyncStateStore
from knowlet.core.vault import Vault
from knowlet.web.server import create_app


def _app(tmp_path: Path):
    v = Vault(tmp_path, audit_log=AuditEventStore(tmp_path), backups=BackupStore(tmp_path))
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = "stub"
    save_config(v.root, cfg)
    app = create_app(v, cfg)
    runtime = app.state.web_state.runtime_or_init()
    return app, TestClient(app), v, runtime


def _index(runtime, note: Note) -> None:
    runtime.index.upsert_note(note, chunk_size=400, chunk_overlap=40)


def _external_note(v: Vault, runtime, folder: str, filename: str, title: str) -> Note:
    """A note imported from another tool: valid frontmatter, but the
    filename is not ``<id>.md``."""
    (v.notes_dir / folder).mkdir(parents=True, exist_ok=True)
    note = Note(id=new_id(), title=title, body=f"body of {title}")
    path = v.notes_dir / folder / filename
    path.write_text(note.to_markdown(), encoding="utf-8")
    loaded = v.read_note(path)
    assert loaded.id == note.id
    _index(runtime, loaded)
    return loaded


def _md_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.md") if ".trash" not in p.parts)


def _track(v: Vault, note_id: str) -> None:
    store = SyncStateStore(v.root)
    try:
        store.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note_id,
                drive_file_id=f"drive-{note_id}",
                last_known_etag="rev-1",
                last_synced_at="2020-01-01T00:00:00Z",
                dirty=False,
            )
        )
    finally:
        store.close()


def _sync_row(v: Vault, note_id: str):
    store = SyncStateStore(v.root)
    try:
        return store.get_file_state("note", note_id)
    finally:
        store.close()


# ------------------------------------------------ folder rename / move


def test_folder_rename_keeps_external_filenames_without_duplicates(tmp_path: Path) -> None:
    _, client, v, runtime = _app(tmp_path)
    note = _external_note(v, runtime, "books", "读书笔记.md", "Reading")
    r = client.patch("/api/folders", json={"path": "books", "new_name": "library"})
    assert r.status_code == 200, r.text

    files = _md_files(v.notes_dir)
    assert files == [v.notes_dir / "library" / "读书笔记.md"]
    moved = Note.from_file(files[0])
    assert moved.id == note.id
    assert moved.folder == "library"
    meta = runtime.index.get_note_meta(note.id)
    assert v.resolve_note_path_from_index(meta["path"]) == files[0].resolve()


def test_folder_move_keeps_external_filenames_without_duplicates(tmp_path: Path) -> None:
    _, client, v, runtime = _app(tmp_path)
    note = _external_note(v, runtime, "inbox/sub", "readme.md", "Readme")
    v.mkdir_folder("archive")
    r = client.post("/api/folders/move", json={"src": "inbox/sub", "dst_parent": "archive"})
    assert r.status_code == 200, r.text
    files = _md_files(v.notes_dir)
    assert files == [v.notes_dir / "archive" / "sub" / "readme.md"]
    assert Note.from_file(files[0]).id == note.id
    assert runtime.index.get_note_meta(note.id) is not None


def test_single_note_move_keeps_external_filename_without_duplicate(tmp_path: Path) -> None:
    _, client, v, runtime = _app(tmp_path)
    note = _external_note(v, runtime, "inbox", "读书笔记.md", "Reading")
    v.mkdir_folder("archive")
    r = client.post(f"/api/notes/{note.id}/move", json={"target_folder": "archive"})
    assert r.status_code == 200, r.text
    assert r.json()["folder"] == "archive"
    files = _md_files(v.notes_dir)
    assert files == [v.notes_dir / "archive" / "读书笔记.md"]
    assert Note.from_file(files[0]).folder == "archive"


def test_folder_rename_preserves_updated_at_and_backup_slots(tmp_path: Path) -> None:
    _, client, v, runtime = _app(tmp_path)
    old_stamp = "2020-05-05T05:05:05Z"
    note = Note(id=new_id(), title="Old", body="aged", updated_at=old_stamp)
    v.mkdir_folder("proj")
    path = v.notes_dir / "proj" / note.filename
    path.write_text(note.to_markdown(), encoding="utf-8")
    note.path = path
    _index(runtime, note)
    backups_before = sorted(p for p in v.backups_dir.rglob("*") if p.is_file())

    r = client.patch("/api/folders", json={"path": "proj", "new_name": "project"})
    assert r.status_code == 200, r.text

    moved = Note.from_file(v.notes_dir / "project" / note.filename)
    assert moved.folder == "project"
    assert moved.updated_at == old_stamp
    assert runtime.index.get_note_meta(note.id)["updated_at"] == old_stamp
    backups_after = sorted(p for p in v.backups_dir.rglob("*") if p.is_file())
    assert backups_after == backups_before


def test_folder_rename_does_not_rewrite_corrupted_notes(tmp_path: Path) -> None:
    _, client, v, runtime = _app(tmp_path)
    v.mkdir_folder("raw")
    nid = new_id()
    path = v.notes_dir / "raw" / f"{nid}.md"
    raw = "---\nid: [unterminated\ntitle: x\n---\nbody text\n"
    path.write_text(raw, encoding="utf-8")
    note = Note.from_file(path)
    assert note.frontmatter_status == "corrupted"
    _index(runtime, note)

    r = client.patch("/api/folders", json={"path": "raw", "new_name": "cooked"})
    assert r.status_code == 200, r.text
    files = _md_files(v.notes_dir)
    assert files == [v.notes_dir / "cooked" / f"{nid}.md"]
    assert files[0].read_text(encoding="utf-8") == raw
    meta = runtime.index.get_note_meta(note.id)
    assert v.resolve_note_path_from_index(meta["path"]) == files[0].resolve()


# ------------------------------------------------ folder delete


def test_folder_delete_removes_index_rows_by_real_id(tmp_path: Path) -> None:
    _, client, v, runtime = _app(tmp_path)
    external = _external_note(v, runtime, "old", "readme.md", "Readme")
    # A note whose trash filename will collide with an earlier trashed copy.
    colliding = Note(id=new_id(), title="Collide", body="c")
    v.write_note(colliding, folder="old")
    _index(runtime, colliding)
    v.trash_dir.mkdir(parents=True, exist_ok=True)
    (v.trash_dir / colliding.filename).write_text("older trashed copy", encoding="utf-8")
    _track(v, external.id)
    _track(v, colliding.id)

    r = client.request("DELETE", "/api/folders", json={"path": "old"})
    assert r.status_code == 200, r.text
    assert runtime.index.get_note_meta(external.id) is None
    assert runtime.index.get_note_meta(colliding.id) is None
    assert _sync_row(v, external.id).delete_intent == "soft"
    assert _sync_row(v, colliding.id).delete_intent == "soft"
    tree_ids = {n["id"] for n in client.get("/api/tree").json()["notes"]}
    assert external.id not in tree_ids and colliding.id not in tree_ids


# ------------------------------------------------ corrupted note id drift


def _corrupted(v: Vault, runtime, folder: str | None, filename: str) -> str:
    target_dir = v.notes_dir / folder if folder else v.notes_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / filename
    path.write_text("---\nid: [broken\ntitle: oops\n---\nsalvage me\n", encoding="utf-8")
    note = Note.from_file(path)
    assert note.frontmatter_status == "corrupted"
    _index(runtime, note)
    return note.id


def test_put_on_corrupted_note_keeps_url_id(tmp_path: Path) -> None:
    _, client, v, runtime = _app(tmp_path)
    nid = _corrupted(v, runtime, None, "external.md")
    r = client.put(f"/api/notes/{nid}", json={"title": "Fixed", "tags": [], "body": "edited"})
    assert r.status_code == 200, r.text
    assert r.json()["id"] == nid
    assert Note.from_file(v.notes_dir / "external.md").id == nid
    assert [n["id"] for n in runtime.index.list_notes()] == [nid]
    # A second save from the same open tab keeps working on the same id.
    r2 = client.put(f"/api/notes/{nid}", json={"title": "Fixed", "tags": [], "body": "again"})
    assert r2.status_code == 200
    assert [n["id"] for n in runtime.index.list_notes()] == [nid]


def test_set_kind_on_corrupted_note_in_subfolder_keeps_id_and_file(tmp_path: Path) -> None:
    _, client, v, runtime = _app(tmp_path)
    nid = _corrupted(v, runtime, "sub", "external.md")
    r = client.post(f"/api/notes/{nid}/kind", json={"kind": "reference", "confirm": True})
    assert r.status_code == 200, r.text
    assert r.json()["id"] == nid
    assert _md_files(v.notes_dir) == [v.notes_dir / "sub" / "external.md"]
    assert Note.from_file(v.notes_dir / "sub" / "external.md").id == nid
    assert [n["id"] for n in runtime.index.list_notes()] == [nid]


# ------------------------------------------------ folder on single-note responses


def test_single_note_responses_carry_folder(tmp_path: Path) -> None:
    _, client, v, runtime = _app(tmp_path)
    note = Note(id=new_id(), title="Deep", body="b")
    v.write_note(note, folder="a/b")
    _index(runtime, note)
    assert client.get(f"/api/notes/{note.id}").json()["folder"] == "a/b"
    r = client.put(f"/api/notes/{note.id}", json={"title": "Deep", "tags": [], "body": "c"})
    assert r.json()["folder"] == "a/b"

    nid = _corrupted(v, runtime, "x/y", f"{new_id()}.md")
    r = client.post(f"/api/notes/{nid}/repair-frontmatter")
    assert r.status_code == 200, r.text
    assert r.json()["folder"] == "x/y"


# ------------------------------------------------ POST /api/notes push queue


def test_commit_note_queues_push_when_drive_connected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import knowlet.core.sync.credentials as creds_mod

    _, client, v, _runtime = _app(tmp_path)
    monkeypatch.setattr(creds_mod, "load_credentials", lambda _p: object())
    r = client.post("/api/notes", json={"title": "Sediment", "tags": [], "body": "b"})
    assert r.status_code == 200, r.text
    row = _sync_row(v, r.json()["note_id"])
    assert row is not None and row.dirty is True


# ------------------------------------------------ tree tags


def test_tree_notes_carry_tags(tmp_path: Path) -> None:
    _, client, v, runtime = _app(tmp_path)
    note = Note(id=new_id(), title="Tagged", body="b", tags=["alpha", "beta"])
    v.write_note(note)
    _index(runtime, note)
    tree = client.get("/api/tree").json()
    assert tree["notes"][0]["tags"] == ["alpha", "beta"]


# ------------------------------------------------ PUT inline tags


def test_put_does_not_re_add_inline_tag_removed_from_chips(tmp_path: Path) -> None:
    _, client, v, runtime = _app(tmp_path)
    note = Note(id=new_id(), title="T", body="hello #project world", tags=["project"])
    v.write_note(note)
    _index(runtime, note)
    r = client.put(
        f"/api/notes/{note.id}",
        json={"title": "T", "tags": [], "body": "hello #project world"},
    )
    assert r.status_code == 200
    assert r.json()["tags"] == []
    # A newly typed inline tag is still picked up.
    r = client.put(
        f"/api/notes/{note.id}",
        json={"title": "T", "tags": [], "body": "hello #project world #fresh"},
    )
    assert r.json()["tags"] == ["fresh"]
