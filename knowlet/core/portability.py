"""Phase 2 E — vault export / import (ADR-0018 §"Import-Export").

Two directions over the same `.zip` envelope:

- **Export** (``build_export_archive``): walk the vault, copy a curated
  set of paths into a temporary directory, write a ``MANIFEST.json``
  describing the snapshot, then zip the whole tree to a target path.
  Excludes generated / sensitive / recursive paths (index.sqlite,
  sync_credentials.json, snapshots/, backups/).
- **Import**: peek at the archive (or directory) to decide between
  two modes:

  - **restore**: the archive is a knowlet export (root has
    ``MANIFEST.json`` + ``.knowlet/``). Unpack to a sibling vault
    next to the current one; *do not* touch the current vault. The
    user can then point knowlet at the new directory.
  - **merge**: arbitrary directory of markdown files (Obsidian /
    Bear / plain). Walk the tree, synthesize Note frontmatter for
    files that lack it (new ULID, title from H1 or filename,
    schema_version=2), and write them under
    ``<vault>/notes/imported/YYYY-MM-DD/``. Title collisions get a
    ``(imported)`` suffix; never silently overwrite.

Both paths return a structured ``ImportReport`` so callers (CLI + the
HTTP layer) can render dry-run plans + post-run summaries identically.
"""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from knowlet import __version__
from knowlet.core.note import Note, new_id

# Paths inside the vault that we ALWAYS skip when exporting.
# ``index.sqlite`` is fully derivable from notes/ via reindex.
# ``sync_credentials.json`` would leak the user's Drive OAuth token.
# ``snapshots/`` and ``backups/`` are themselves bundles — packing
# them recursively would create circular / huge archives.
EXPORT_EXCLUDE_NAMES = {
    "index.sqlite",
    "index.sqlite-shm",
    "index.sqlite-wal",
    "sync_state.sqlite",
    "sync_state.sqlite-shm",
    "sync_state.sqlite-wal",
    "sync_credentials.json",
}
EXPORT_EXCLUDE_DOTKNOWLET_SUBDIRS = {"snapshots", "backups", "dev_conflicts"}

MANIFEST_FILENAME = "MANIFEST.json"


# ----------------------------------------------------- types


@dataclass(frozen=True)
class ExportManifest:
    """Header for an exported archive. Lives at archive root as
    ``MANIFEST.json``. Future schema bumps go here under a top-level
    ``schema_version`` field."""

    schema_version: int
    knowlet_version: str
    exported_at: str
    note_count: int
    attachment_count: int

    def to_json(self) -> str:
        return json.dumps(
            {
                "schema_version": self.schema_version,
                "knowlet_version": self.knowlet_version,
                "exported_at": self.exported_at,
                "note_count": self.note_count,
                "attachment_count": self.attachment_count,
            },
            ensure_ascii=False,
            indent=2,
        )

    @classmethod
    def from_json(cls, raw: str) -> "ExportManifest":
        d = json.loads(raw)
        return cls(
            schema_version=int(d.get("schema_version", 1)),
            knowlet_version=str(d.get("knowlet_version", "")),
            exported_at=str(d.get("exported_at", "")),
            note_count=int(d.get("note_count", 0)),
            attachment_count=int(d.get("attachment_count", 0)),
        )


@dataclass
class ExportResult:
    archive_path: Path
    manifest: ExportManifest


ImportMode = Literal["restore", "merge"]


@dataclass
class ImportReport:
    """Returned from a (real or dry-run) import. Lets the UI render
    the same shape whether the user is previewing or executing."""

    mode: ImportMode
    # For restore: the new vault directory. For merge: the folder under
    # the current vault that received the merged notes.
    target_path: Path
    # Notes created (merge: net-new files). For restore, this is the
    # count from the archive's MANIFEST (we trust + verify post-unpack).
    notes_created: int = 0
    notes_skipped: int = 0
    notes_renamed: int = 0
    attachments_copied: int = 0
    # Per-note breakdown: list of ``(source_rel_path, action,
    # final_rel_path | None)``. ``action`` ∈ {"create", "skip-empty",
    # "rename"}. The rename rows include both the proposed name
    # collision and the de-conflicted result.
    items: list[tuple[str, str, str | None]] = field(default_factory=list)
    # If dry_run was True the writer skipped real filesystem changes.
    dry_run: bool = False
    # When mode == "restore", the manifest we read out of the archive.
    manifest: ExportManifest | None = None


# ----------------------------------------------------- export


def build_export_archive(
    *,
    vault_root: Path,
    output_path: Path,
) -> ExportResult:
    """Walk the vault, copy the curated path set into a temporary
    staging dir, write MANIFEST.json, and zip the result to
    ``output_path``. Returns the manifest so callers can render a
    success message."""
    if not vault_root.exists():
        raise FileNotFoundError(
            f"vault root does not exist: {vault_root}"
        )
    notes_dir = vault_root / "notes"
    dotk_dir = vault_root / ".knowlet"
    note_count, attachment_count = _count_export_payload(notes_dir)

    manifest = ExportManifest(
        schema_version=1,
        knowlet_version=__version__,
        exported_at=_now_iso(),
        note_count=note_count,
        attachment_count=attachment_count,
    )

    # Build the archive directly (no intermediate temp dir) so big
    # vaults don't double their disk footprint during export.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        output_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        # Best compromise on speed vs ratio for markdown text.
        compresslevel=6,
    ) as zf:
        zf.writestr(MANIFEST_FILENAME, manifest.to_json())
        if notes_dir.exists():
            _write_dir_to_zip(zf, notes_dir, "notes")
        if dotk_dir.exists():
            _write_dotknowlet_to_zip(zf, dotk_dir)
    return ExportResult(archive_path=output_path, manifest=manifest)


def _count_export_payload(notes_dir: Path) -> tuple[int, int]:
    if not notes_dir.exists():
        return 0, 0
    notes = 0
    attachments = 0
    for p in notes_dir.rglob("*"):
        if not p.is_file():
            continue
        if p.name in EXPORT_EXCLUDE_NAMES:
            continue
        # Anything under _attachments/ that is a file counts.
        rel = p.relative_to(notes_dir)
        if rel.parts and rel.parts[0] == "_attachments":
            attachments += 1
            continue
        if p.suffix.lower() == ".md":
            notes += 1
    return notes, attachments


def _write_dir_to_zip(
    zf: zipfile.ZipFile, src: Path, arcname_prefix: str
) -> None:
    for p in sorted(src.rglob("*")):
        if not p.is_file():
            continue
        if p.name in EXPORT_EXCLUDE_NAMES:
            continue
        rel = p.relative_to(src)
        zf.write(p, arcname=f"{arcname_prefix}/{rel.as_posix()}")


def _write_dotknowlet_to_zip(zf: zipfile.ZipFile, dotk: Path) -> None:
    """``.knowlet/`` has both kept items (config.toml, quick-actions.toml,
    favorites.json, events.sqlite) and excluded ones (snapshots/,
    backups/, dev_conflicts/, sync_*.json, index.sqlite)."""
    for p in sorted(dotk.rglob("*")):
        if not p.is_file():
            continue
        if p.name in EXPORT_EXCLUDE_NAMES:
            continue
        rel = p.relative_to(dotk)
        if rel.parts and rel.parts[0] in EXPORT_EXCLUDE_DOTKNOWLET_SUBDIRS:
            continue
        zf.write(p, arcname=f".knowlet/{rel.as_posix()}")


# ----------------------------------------------------- import: detect


def detect_archive_mode(archive_or_dir: Path) -> ImportMode:
    """Peek at a path (zip OR directory) and decide the import mode.

    A knowlet export archive has ``MANIFEST.json`` at its root **and**
    a ``.knowlet/`` directory. Any other tree is treated as an
    arbitrary markdown directory (merge mode)."""
    if archive_or_dir.is_dir():
        return _detect_from_dir(archive_or_dir)
    if archive_or_dir.suffix.lower() == ".zip":
        with zipfile.ZipFile(archive_or_dir, "r") as zf:
            names = zf.namelist()
        has_manifest = MANIFEST_FILENAME in names
        has_dotk = any(n.startswith(".knowlet/") for n in names)
        return "restore" if (has_manifest and has_dotk) else "merge"
    # Plain markdown file — treat as merge of a 1-file tree.
    return "merge"


def _detect_from_dir(path: Path) -> ImportMode:
    has_manifest = (path / MANIFEST_FILENAME).exists()
    has_dotk = (path / ".knowlet").is_dir()
    return "restore" if (has_manifest and has_dotk) else "merge"


# ----------------------------------------------------- import: restore


def restore_archive(
    *,
    archive_path: Path,
    target_dir: Path,
    dry_run: bool = False,
) -> ImportReport:
    """Restore a knowlet export archive into a fresh sibling vault.

    The caller is responsible for picking a non-conflicting
    ``target_dir`` (we refuse to write into an existing non-empty
    one — too dangerous for a non-tech user)."""
    if target_dir.exists() and any(target_dir.iterdir()):
        raise FileExistsError(
            f"target directory exists and is non-empty: {target_dir}. "
            "Pick an empty path so the restore doesn't merge into "
            "unrelated content."
        )
    with zipfile.ZipFile(archive_path, "r") as zf:
        try:
            raw = zf.read(MANIFEST_FILENAME).decode("utf-8")
        except KeyError as exc:
            raise ValueError(
                "archive is missing MANIFEST.json — not a knowlet "
                "export. Use merge mode for arbitrary markdown."
            ) from exc
        manifest = ExportManifest.from_json(raw)
        if dry_run:
            return ImportReport(
                mode="restore",
                target_path=target_dir,
                notes_created=manifest.note_count,
                attachments_copied=manifest.attachment_count,
                dry_run=True,
                manifest=manifest,
            )
        target_dir.mkdir(parents=True, exist_ok=True)
        zf.extractall(target_dir)
        # Drop the MANIFEST at archive root — it stays in the new
        # vault so a later round-trip preserves provenance.
        # (Already extracted by extractall.)
    return ImportReport(
        mode="restore",
        target_path=target_dir,
        notes_created=manifest.note_count,
        attachments_copied=manifest.attachment_count,
        dry_run=False,
        manifest=manifest,
    )


# ----------------------------------------------------- import: merge


# Recognized note filename pattern: ULID-shaped stem + .md. Used to
# decide whether to TRUST the existing filename as the note id, or
# synthesize a fresh one.
_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$", re.IGNORECASE)


def merge_directory(
    *,
    source_dir: Path,
    vault_root: Path,
    subfolder: str | None = None,
    existing_titles: Iterable[str] | None = None,
    dry_run: bool = False,
) -> ImportReport:
    """Walk ``source_dir`` and add every .md file into the vault.

    Notes without knowlet frontmatter get a fresh ULID + synthesized
    metadata; notes that already look like knowlet (ULID filename or
    valid frontmatter) keep their identity.

    All imported notes land under ``vault_root/notes/<subfolder>/``,
    defaulting to ``imported/YYYY-MM-DD``. Title collisions with the
    existing vault get a ``(imported)`` suffix on the new copy —
    silent overwrites would be data loss.

    ``existing_titles`` is the snapshot of titles already in the
    vault, used for collision detection. Passing ``None`` skips the
    check (callers usually pass ``runtime.index.list_notes()``
    titles).
    """
    if not source_dir.exists() or not source_dir.is_dir():
        raise NotADirectoryError(f"not a directory: {source_dir}")
    sub = subfolder or f"imported/{datetime.now().strftime('%Y-%m-%d')}"
    target = vault_root / "notes" / sub
    existing = set(existing_titles or ())

    report = ImportReport(mode="merge", target_path=target, dry_run=dry_run)
    md_files = sorted(p for p in source_dir.rglob("*.md") if p.is_file())
    for src in md_files:
        rel = src.relative_to(source_dir)
        rel_str = rel.as_posix()
        try:
            note = _load_or_synthesize(src)
        except _EmptyFileSkip:
            report.notes_skipped += 1
            report.items.append((rel_str, "skip-empty", None))
            continue
        # Collision handling on title — never overwrite silently.
        if note.title and note.title in existing:
            note.title = f"{note.title} (imported)"
            report.notes_renamed += 1
            action = "rename"
        else:
            action = "create"
        existing.add(note.title)

        # On disk we write to ``<target>/<note.id>.md`` to dodge
        # filename collisions; the title carries human identity.
        final_rel = (
            (Path("notes") / sub / f"{note.id}.md").as_posix()
        )
        if not dry_run:
            target.mkdir(parents=True, exist_ok=True)
            (target / f"{note.id}.md").write_text(
                note.to_markdown(), encoding="utf-8"
            )
        report.notes_created += 1
        report.items.append((rel_str, action, final_rel))

    # Also copy any ``_attachments`` siblings the source happens to
    # ship (Obsidian users often have one), into the same target.
    src_att = source_dir / "_attachments"
    if src_att.is_dir():
        for p in sorted(src_att.iterdir()):
            if not p.is_file():
                continue
            if p.name.startswith("."):
                continue
            if not dry_run:
                dest = vault_root / "notes" / "_attachments" / p.name
                # Don't overwrite existing attachment with same name.
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(p, dest)
            report.attachments_copied += 1

    return report


class _EmptyFileSkip(Exception):
    """Raised internally when a source markdown file is empty /
    whitespace-only. Skipped silently — likely a stub the user
    didn't mean to keep."""


def _load_or_synthesize(src: Path) -> Note:
    """Read a markdown file. If it has a valid knowlet frontmatter,
    return that Note as-is. Otherwise build a fresh Note with
    synthesized metadata."""
    raw = src.read_text(encoding="utf-8", errors="replace")
    if not raw.strip():
        raise _EmptyFileSkip()
    note = Note.from_text(raw)
    if note.frontmatter_status == "valid" and note.id:
        # Already a knowlet-format note — trust it.
        return note
    # Synthesize: take ULID from filename if it looks valid, else new.
    stem = src.stem
    note_id = stem if _ULID_RE.match(stem) else new_id()
    # Title: existing if any, otherwise first H1, otherwise filename.
    title = note.title or _first_h1(raw) or stem
    body = note.body or raw
    # We deliberately do NOT preserve source mtime in created_at; the
    # synthesized Note uses now_iso() from Note.__init__ defaults so
    # the user can see which notes are "freshly imported".
    return Note(id=note_id, title=title, body=body)


def _first_h1(raw: str) -> str | None:
    """Pull the first ``# heading`` from a markdown blob. Used as the
    fallback title when frontmatter doesn't supply one."""
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
        # Stop at first non-heading, non-blank line — usually means
        # the document is body-first (no H1).
        if stripped and not stripped.startswith("#"):
            break
    return None


# ----------------------------------------------------- helpers


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
