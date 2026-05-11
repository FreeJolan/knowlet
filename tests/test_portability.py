"""Phase 2 E — vault export / import round-trip + merge import tests.

Pytest layout follows the same patterns as test_favorites.py: hot
fixtures via knowlet.core.vault.Vault into a tmp_path, then exercise
the portability module directly. Web-layer endpoint tests live in
test_web_portability.py.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from knowlet.core.note import Note, new_id
from knowlet.core.portability import (
    MANIFEST_FILENAME,
    ExportManifest,
    build_export_archive,
    detect_archive_mode,
    merge_directory,
    restore_archive,
)
from knowlet.core.vault import Vault


# ----------------------------------------------------- helpers


def _seeded_vault(tmp_path: Path) -> Vault:
    v = Vault(tmp_path / "v")
    v.init_layout()
    n1 = Note(id=new_id(), title="alpha", body="# alpha\n\nbody one")
    n2 = Note(id=new_id(), title="beta", body="# beta\n\nbody two")
    v.write_note(n1)
    v.write_note(n2)
    # An attachment.
    att_dir = v.notes_dir / "_attachments"
    att_dir.mkdir(parents=True, exist_ok=True)
    (att_dir / "fake.png").write_bytes(b"PNGBYTES")
    # A .knowlet file we expect to round-trip.
    (v.state_dir / "favorites.json").write_text(
        '{"ids": ["FAKE"]}', encoding="utf-8"
    )
    # And a sensitive file we expect to be EXCLUDED.
    (v.state_dir / "sync_credentials.json").write_text(
        '{"token": "should-not-be-in-archive"}', encoding="utf-8"
    )
    # An excluded subdir.
    snap_dir = v.state_dir / "snapshots" / "2026-05-12T00-00-00Z"
    snap_dir.mkdir(parents=True, exist_ok=True)
    (snap_dir / "marker.txt").write_text("should-not-export", encoding="utf-8")
    return v


# ----------------------------------------------------- export


def test_export_writes_archive_with_manifest(tmp_path: Path) -> None:
    v = _seeded_vault(tmp_path)
    out = tmp_path / "vault.zip"
    result = build_export_archive(vault_root=v.root, output_path=out)
    assert out.exists()
    assert result.manifest.note_count == 2
    assert result.manifest.attachment_count == 1
    with zipfile.ZipFile(out, "r") as zf:
        names = set(zf.namelist())
        # Manifest at root.
        assert MANIFEST_FILENAME in names
        manifest = ExportManifest.from_json(
            zf.read(MANIFEST_FILENAME).decode("utf-8")
        )
        assert manifest.note_count == 2
        assert manifest.attachment_count == 1
        # Notes + attachment round-trip.
        note_md = [n for n in names if n.startswith("notes/") and n.endswith(".md")]
        assert len(note_md) == 2
        assert "notes/_attachments/fake.png" in names
        # Kept .knowlet entries.
        assert ".knowlet/favorites.json" in names
        # Excluded entries.
        assert all(
            "sync_credentials.json" not in n for n in names
        ), f"credentials leaked into archive: {names}"
        assert all(
            "snapshots/" not in n for n in names
        ), f"snapshots leaked into archive: {names}"
        assert all(
            "index.sqlite" not in n for n in names
        ), f"index leaked: {names}"


def test_export_omits_excluded_paths_even_when_present(
    tmp_path: Path,
) -> None:
    v = _seeded_vault(tmp_path)
    # Drop a fake index so we verify exclusion robustly.
    (v.state_dir / "index.sqlite").write_text("FAKE", encoding="utf-8")
    out = tmp_path / "vault.zip"
    build_export_archive(vault_root=v.root, output_path=out)
    with zipfile.ZipFile(out, "r") as zf:
        names = set(zf.namelist())
    assert all("index.sqlite" not in n for n in names)


# ----------------------------------------------------- detect_archive_mode


def test_detect_mode_restore_for_knowlet_export(tmp_path: Path) -> None:
    v = _seeded_vault(tmp_path)
    out = tmp_path / "vault.zip"
    build_export_archive(vault_root=v.root, output_path=out)
    assert detect_archive_mode(out) == "restore"


def test_detect_mode_merge_for_plain_markdown_zip(tmp_path: Path) -> None:
    plain = tmp_path / "plain.zip"
    with zipfile.ZipFile(plain, "w") as zf:
        zf.writestr("foo.md", "# foo\n")
        zf.writestr("bar.md", "# bar\n")
    assert detect_archive_mode(plain) == "merge"


def test_detect_mode_merge_for_plain_directory(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "foo.md").write_text("# foo\n", encoding="utf-8")
    assert detect_archive_mode(src) == "merge"


# ----------------------------------------------------- restore


def test_restore_unpacks_to_target(tmp_path: Path) -> None:
    v = _seeded_vault(tmp_path)
    archive = tmp_path / "vault.zip"
    build_export_archive(vault_root=v.root, output_path=archive)
    target = tmp_path / "restored"
    report = restore_archive(
        archive_path=archive, target_dir=target, dry_run=False
    )
    assert report.mode == "restore"
    assert report.notes_created == 2
    assert (target / MANIFEST_FILENAME).exists()
    # Notes survived.
    restored_md = list((target / "notes").rglob("*.md"))
    assert len(restored_md) == 2


def test_restore_refuses_non_empty_target(tmp_path: Path) -> None:
    v = _seeded_vault(tmp_path)
    archive = tmp_path / "vault.zip"
    build_export_archive(vault_root=v.root, output_path=archive)
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "unrelated.txt").write_text("hi", encoding="utf-8")
    with pytest.raises(FileExistsError):
        restore_archive(
            archive_path=archive, target_dir=target, dry_run=False
        )


def test_restore_dry_run_reports_without_writing(tmp_path: Path) -> None:
    v = _seeded_vault(tmp_path)
    archive = tmp_path / "vault.zip"
    build_export_archive(vault_root=v.root, output_path=archive)
    target = tmp_path / "preview"
    report = restore_archive(
        archive_path=archive, target_dir=target, dry_run=True
    )
    assert report.dry_run is True
    assert not target.exists()  # nothing written
    assert report.notes_created == 2


def test_restore_rejects_non_knowlet_zip(tmp_path: Path) -> None:
    plain = tmp_path / "plain.zip"
    with zipfile.ZipFile(plain, "w") as zf:
        zf.writestr("foo.md", "# foo\n")
    with pytest.raises(ValueError, match="MANIFEST.json"):
        restore_archive(
            archive_path=plain,
            target_dir=tmp_path / "out",
            dry_run=False,
        )


# ----------------------------------------------------- merge


def test_merge_synthesizes_frontmatter_for_plain_md(tmp_path: Path) -> None:
    v = _seeded_vault(tmp_path)
    src = tmp_path / "import-src"
    src.mkdir()
    (src / "external.md").write_text(
        "# External\n\nfrom another tool", encoding="utf-8"
    )
    report = merge_directory(
        source_dir=src,
        vault_root=v.root,
        existing_titles=["alpha", "beta"],
        dry_run=False,
    )
    assert report.mode == "merge"
    assert report.notes_created == 1
    assert report.notes_renamed == 0
    # Imported under imported/YYYY-MM-DD/
    imported = list((v.notes_dir / "imported").rglob("*.md"))
    assert len(imported) == 1
    # The imported file has knowlet frontmatter now.
    note = Note.from_file(imported[0])
    assert note.title == "External"
    assert note.frontmatter_status == "valid"


def test_merge_renames_title_collisions(tmp_path: Path) -> None:
    v = _seeded_vault(tmp_path)
    src = tmp_path / "import-src"
    src.mkdir()
    (src / "alpha.md").write_text("# alpha\n\nfrom export", encoding="utf-8")
    report = merge_directory(
        source_dir=src,
        vault_root=v.root,
        existing_titles=["alpha", "beta"],
        dry_run=False,
    )
    assert report.notes_renamed == 1
    # Imported note title got (imported) suffix.
    imported = list((v.notes_dir / "imported").rglob("*.md"))
    assert len(imported) == 1
    note = Note.from_file(imported[0])
    assert "imported" in note.title.lower()


def test_merge_skips_empty_files(tmp_path: Path) -> None:
    v = _seeded_vault(tmp_path)
    src = tmp_path / "import-src"
    src.mkdir()
    (src / "empty.md").write_text("   \n  \n", encoding="utf-8")
    (src / "real.md").write_text("# real\n", encoding="utf-8")
    report = merge_directory(
        source_dir=src,
        vault_root=v.root,
        existing_titles=[],
        dry_run=False,
    )
    assert report.notes_created == 1
    assert report.notes_skipped == 1


def test_merge_dry_run_writes_nothing(tmp_path: Path) -> None:
    v = _seeded_vault(tmp_path)
    src = tmp_path / "import-src"
    src.mkdir()
    (src / "p.md").write_text("# p\n", encoding="utf-8")
    report = merge_directory(
        source_dir=src,
        vault_root=v.root,
        existing_titles=[],
        dry_run=True,
    )
    assert report.dry_run is True
    assert report.notes_created == 1
    assert not (v.notes_dir / "imported").exists()


def test_merge_copies_orphan_attachments(tmp_path: Path) -> None:
    v = _seeded_vault(tmp_path)
    src = tmp_path / "import-src"
    src.mkdir()
    (src / "alpha-clone.md").write_text("# alpha-clone\n", encoding="utf-8")
    (src / "_attachments").mkdir()
    (src / "_attachments" / "imported.png").write_bytes(b"NEWPNG")
    merge_directory(
        source_dir=src,
        vault_root=v.root,
        existing_titles=[],
        dry_run=False,
    )
    assert (v.notes_dir / "_attachments" / "imported.png").exists()
    # Original attachment still there.
    assert (v.notes_dir / "_attachments" / "fake.png").exists()


def test_merge_preserves_existing_knowlet_notes(tmp_path: Path) -> None:
    """If a source file already has a valid knowlet frontmatter,
    keep its ULID + metadata rather than re-synthesizing."""
    v = _seeded_vault(tmp_path)
    src = tmp_path / "import-src"
    src.mkdir()
    existing_id = new_id()
    existing_note = Note(id=existing_id, title="preserved", body="kept")
    (src / f"{existing_id}.md").write_text(
        existing_note.to_markdown(), encoding="utf-8"
    )
    merge_directory(
        source_dir=src,
        vault_root=v.root,
        existing_titles=[],
        dry_run=False,
    )
    imported = list((v.notes_dir / "imported").rglob("*.md"))
    assert len(imported) == 1
    note = Note.from_file(imported[0])
    assert note.id == existing_id
    assert note.title == "preserved"


# ----------------------------------------------------- round-trip


def test_export_then_restore_preserves_note_content(tmp_path: Path) -> None:
    v = _seeded_vault(tmp_path)
    archive = tmp_path / "vault.zip"
    build_export_archive(vault_root=v.root, output_path=archive)
    target = tmp_path / "restored"
    restore_archive(
        archive_path=archive, target_dir=target, dry_run=False
    )
    src_notes = sorted(
        Note.from_file(p).title for p in v.notes_dir.glob("*.md")
    )
    restored_notes = sorted(
        Note.from_file(p).title for p in (target / "notes").glob("*.md")
    )
    assert src_notes == restored_notes


def test_export_manifest_records_knowlet_version(tmp_path: Path) -> None:
    from knowlet import __version__

    v = _seeded_vault(tmp_path)
    archive = tmp_path / "vault.zip"
    build_export_archive(vault_root=v.root, output_path=archive)
    with zipfile.ZipFile(archive, "r") as zf:
        manifest_raw = zf.read(MANIFEST_FILENAME).decode("utf-8")
    payload = json.loads(manifest_raw)
    assert payload["knowlet_version"] == __version__
