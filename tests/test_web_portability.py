"""Phase 2 E — vault export / import HTTP endpoint smoke tests."""

from __future__ import annotations

import io
import zipfile
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


def _seed(v: Vault) -> None:
    v.write_note(Note(id=new_id(), title="alpha", body="hello"))
    v.write_note(Note(id=new_id(), title="beta", body="world"))


def test_export_endpoint_returns_zip(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    _seed(v)
    r = client.get("/api/vault/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/zip")
    # Parse the returned zip in memory.
    with zipfile.ZipFile(io.BytesIO(r.content), "r") as zf:
        names = zf.namelist()
    assert "MANIFEST.json" in names
    md = [n for n in names if n.startswith("notes/") and n.endswith(".md")]
    assert len(md) == 2


def test_import_preview_for_merge_zip(tmp_path: Path) -> None:
    client, _v = _client(tmp_path)
    # Build a "merge" zip (plain markdown, no MANIFEST).
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("foo.md", "# foo\n")
        zf.writestr("bar.md", "# bar\n")
    buf.seek(0)
    r = client.post(
        "/api/vault/import-preview",
        files={"file": ("foo.zip", buf.read(), "application/zip")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "merge"
    assert body["dry_run"] is True
    assert body["notes_created"] == 2


def test_import_commit_merges_into_current_vault(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    # Pre-seed an alpha note to test collision rename.
    _seed(v)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("foo.md", "# foo\n")
        zf.writestr("alpha.md", "# alpha\n")  # collides
    buf.seek(0)
    r = client.post(
        "/api/vault/import",
        files={"file": ("foo.zip", buf.read(), "application/zip")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "merge"
    assert body["dry_run"] is False
    assert body["notes_created"] == 2
    assert body["notes_renamed"] == 1
    # Files landed.
    imported_dir = v.notes_dir / "imported"
    assert imported_dir.exists()
    assert sum(1 for _ in imported_dir.rglob("*.md")) == 2


def test_export_then_import_merges_into_target_vault(tmp_path: Path) -> None:
    """Export from one vault, upload the archive to a different
    (empty) vault. UI-level import always merges, so the notes show
    up under ``imported/YYYY-MM-DD/`` inside the destination
    vault — no surprise sibling directory."""
    # Source vault
    src_client, src_v = _client(tmp_path / "src")
    _seed(src_v)
    archive_bytes = src_client.get("/api/vault/export").content

    # Target vault (empty)
    dst_client, dst_v = _client(tmp_path / "dst")
    r = dst_client.post(
        "/api/vault/import",
        files={
            "file": (
                "knowlet-vault-test.zip",
                archive_bytes,
                "application/zip",
            )
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "merge"
    assert body["dry_run"] is False
    assert body["notes_created"] == 2
    # Notes landed in the destination vault's imported/ folder.
    imported = list((dst_v.notes_dir / "imported").rglob("*.md"))
    assert len(imported) == 2


def test_import_skips_duplicate_ids_idempotently(tmp_path: Path) -> None:
    """Re-importing the same archive twice into the same vault
    must not duplicate notes — second pass should skip them all."""
    client, v = _client(tmp_path)
    _seed(v)
    archive_bytes = client.get("/api/vault/export").content
    # First import: merges into imported/. Now we have duplicates of
    # the original IDs across notes/ and notes/imported/.
    # Wait — first import goes into THE SAME vault that was exported
    # from, so ID collisions should immediately trip.
    r = client.post(
        "/api/vault/import",
        files={
            "file": (
                "self-backup.zip",
                archive_bytes,
                "application/zip",
            )
        },
    )
    assert r.status_code == 200
    body = r.json()
    # All notes already exist in the vault (we just exported them) —
    # the merge should skip every single one.
    assert body["mode"] == "merge"
    assert body["notes_skipped"] >= 2
    assert body["notes_created"] == 0
