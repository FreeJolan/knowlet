"""Vault: filesystem layout, Note read/write, vault initialization."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

from knowlet.config import VAULT_MARKER_DIR
from knowlet.core.note import Note, now_iso

NOTES_DIR = "notes"
USERS_DIR = "users"
PROFILE_FILENAME = "me.md"
CARDS_DIR = "cards"
TASKS_DIR = "tasks"
DRAFTS_DIR = "drafts"
INDEX_DB = "index.sqlite"
CONVERSATIONS_DIR = "conversations"
BACKUPS_DIR = "backups"


class Vault:
    """Filesystem operations on a knowlet vault."""

    def __init__(self, root: Path):
        self.root = root.resolve()

    @property
    def notes_dir(self) -> Path:
        return self.root / NOTES_DIR

    @property
    def users_dir(self) -> Path:
        return self.root / USERS_DIR

    @property
    def profile_path(self) -> Path:
        return self.users_dir / PROFILE_FILENAME

    @property
    def cards_dir(self) -> Path:
        return self.root / CARDS_DIR

    @property
    def tasks_dir(self) -> Path:
        return self.root / TASKS_DIR

    @property
    def drafts_dir(self) -> Path:
        return self.root / DRAFTS_DIR

    @property
    def state_dir(self) -> Path:
        return self.root / VAULT_MARKER_DIR

    @property
    def db_path(self) -> Path:
        return self.state_dir / INDEX_DB

    @property
    def conversations_dir(self) -> Path:
        return self.state_dir / CONVERSATIONS_DIR

    @property
    def backups_dir(self) -> Path:
        return self.state_dir / BACKUPS_DIR

    def init_layout(self) -> None:
        """Create the directory structure. Idempotent."""
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.users_dir.mkdir(parents=True, exist_ok=True)
        self.cards_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.conversations_dir.mkdir(parents=True, exist_ok=True)
        self.backups_dir.mkdir(parents=True, exist_ok=True)

    def iter_note_paths(self) -> Iterator[Path]:
        """Yield every Note file under `notes/` recursively.

        M7.0.2: previously this was a non-recursive `glob("*.md")` which
        silently skipped any user-organized subdirectory. Now we walk the
        whole tree and skip dotdirs (`.trash/` from M7.0.1, plus any
        future hidden bookkeeping). Subdir layout is **user-controlled**
        — we never write into nested dirs ourselves; users move files
        from Finder, then `knowlet reindex` picks them up.
        """
        if not self.notes_dir.exists():
            return iter(())

        def _ok(p: Path) -> bool:
            if not p.is_file():
                return False
            try:
                rel = p.relative_to(self.notes_dir)
            except ValueError:
                return False
            if any(part.startswith(".") for part in rel.parts):
                return False
            # `_attachments/` holds binaries pasted via M7.0.3 — never a Note.
            return rel.parts[0] != "_attachments"

        return (p for p in self.notes_dir.rglob("*.md") if _ok(p))

    def folder_of(self, note_path: Path) -> str:
        """Return the folder of `note_path` relative to `notes/`, with `/`
        as separator. Empty string means top-level. Used by the index +
        web API to give the sidebar a tree structure (M7.0.2)."""
        try:
            rel = note_path.relative_to(self.notes_dir)
        except ValueError:
            return ""
        if len(rel.parts) <= 1:
            return ""
        return "/".join(rel.parts[:-1])

    def read_note(self, path: Path) -> Note:
        return Note.from_file(path)

    def write_note(self, note: Note, *, folder: str | None = None) -> Path:
        """Atomically write a Note. Returns the final path.

        Resolution order for the destination folder (under `notes/`):
          1. Explicit `folder` arg (e.g. "projects/knowlet").
          2. `note.path` if already set (in-place rewrite preserves location).
          3. `notes/` root (flat) — the original M0 behavior.

        Filename is always `<id>.md` — moving across folders preserves the
        ULID, so the index stays stable.
        """
        if folder is not None:
            parent = self._resolve_subpath(folder)
            parent.mkdir(parents=True, exist_ok=True)
            target = parent / note.filename
        elif note.path is not None:
            target = note.path
            target.parent.mkdir(parents=True, exist_ok=True)
        else:
            self.notes_dir.mkdir(parents=True, exist_ok=True)
            target = self.notes_dir / note.filename
        note.path = target
        note.updated_at = now_iso()
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(note.to_markdown(), encoding="utf-8")
        tmp.replace(target)
        return target

    # ----------------------------------------------------- folder ops (Phase 1 A)

    def _resolve_subpath(self, rel: str) -> Path:
        """Resolve a forward-slash relative path under `notes_dir`.

        Rejects path traversal (`..`), absolute paths, dotdirs, and the
        reserved `_attachments` top-level. Empty / "/" returns notes_dir.
        Returned path is `.resolve()`d and re-checked to be inside notes_dir.
        """
        rel_clean = (rel or "").strip().strip("/")
        if not rel_clean:
            return self.notes_dir
        parts = rel_clean.split("/")
        for part in parts:
            if not part or part in (".", ".."):
                raise ValueError(f"invalid path segment: {part!r}")
            if part.startswith("."):
                raise ValueError(f"dotfiles/dotdirs are reserved: {part!r}")
            if "\\" in part or "/" in part:
                raise ValueError(f"path segment contains slash: {part!r}")
        if parts[0] == "_attachments":
            raise ValueError("_attachments/ is reserved for image-paste")
        target = self.notes_dir.joinpath(*parts).resolve()
        notes_root = self.notes_dir.resolve()
        try:
            target.relative_to(notes_root)
        except ValueError as exc:
            raise ValueError(f"path escapes notes_dir: {rel!r}") from exc
        return target

    def mkdir_folder(self, folder: str) -> Path:
        """Create a folder under `notes/` (idempotent). Returns its path."""
        target = self._resolve_subpath(folder)
        if target == self.notes_dir:
            return target
        target.mkdir(parents=True, exist_ok=True)
        return target

    def iter_folders(self) -> Iterator[Path]:
        """Yield every folder under `notes/` (recursive). Skips dotdirs and
        the `_attachments/` reserved tree."""
        if not self.notes_dir.exists():
            return iter(())

        def _ok(p: Path) -> bool:
            if not p.is_dir():
                return False
            rel = p.relative_to(self.notes_dir)
            if any(part.startswith(".") for part in rel.parts):
                return False
            return rel.parts[0] != "_attachments"

        return (p for p in self.notes_dir.rglob("*") if _ok(p))

    def move_note(self, note_path: Path, target_folder: str) -> Path:
        """Move a note file to `notes/<target_folder>/<filename>`.

        Preserves filename (ULID-based) so the index id stays stable; caller
        must call `Index.update_note_path` to keep the path column in sync.
        Idempotent: moving to current folder is a no-op.
        """
        if not note_path.exists():
            raise FileNotFoundError(str(note_path))
        parent = self._resolve_subpath(target_folder)
        parent.mkdir(parents=True, exist_ok=True)
        new_path = parent / note_path.name
        if new_path.resolve() == note_path.resolve():
            return note_path
        if new_path.exists():
            raise FileExistsError(f"target exists: {new_path}")
        note_path.rename(new_path)
        return new_path

    def rename_folder(self, folder: str, new_name: str) -> Path:
        """Rename a folder in place. `new_name` is the new basename — `/` not
        allowed. The index needs `update_note_path` for every note inside
        afterwards (caller handles)."""
        if "/" in new_name or new_name in ("", ".", "..") or new_name.startswith("."):
            raise ValueError(f"invalid new folder name: {new_name!r}")
        if "\\" in new_name:
            raise ValueError(f"path segment contains slash: {new_name!r}")
        src_path = self._resolve_subpath(folder)
        if src_path == self.notes_dir:
            raise ValueError("cannot rename notes/ root")
        if not src_path.is_dir():
            raise FileNotFoundError(f"folder not found: {folder}")
        new_path = src_path.parent / new_name
        if new_path.exists():
            raise FileExistsError(f"target exists: {new_path}")
        src_path.rename(new_path)
        return new_path

    def move_folder(self, folder: str, dst_parent: str) -> Path:
        """Move folder under a different parent. The basename is preserved."""
        src_path = self._resolve_subpath(folder)
        if src_path == self.notes_dir:
            raise ValueError("cannot move notes/ root")
        if not src_path.is_dir():
            raise FileNotFoundError(f"folder not found: {folder}")
        parent = self._resolve_subpath(dst_parent)
        parent.mkdir(parents=True, exist_ok=True)
        new_path = parent / src_path.name
        if new_path.resolve() == src_path.resolve():
            return src_path
        # Forbid moving into self or descendants — would orphan everything.
        try:
            new_path.resolve().relative_to(src_path.resolve())
        except ValueError:
            pass
        else:
            raise ValueError(f"cannot move folder into its own descendant: {dst_parent!r}")
        if new_path.exists():
            raise FileExistsError(f"target exists: {new_path}")
        src_path.rename(new_path)
        return new_path

    def delete_folder(self, folder: str) -> list[Path]:
        """Trash every note under `folder`, then remove the empty tree.

        Returns the new locations of the trashed notes. Caller is
        responsible for removing each note from the index by id.
        """
        src_path = self._resolve_subpath(folder)
        if src_path == self.notes_dir:
            raise ValueError("cannot delete notes/ root")
        if not src_path.is_dir():
            raise FileNotFoundError(f"folder not found: {folder}")
        trashed: list[Path] = []
        for note_md in src_path.rglob("*.md"):
            if note_md.is_file():
                trashed.append(self.trash_note(note_md))
        # `trash_note` only moved files; remove the now-empty subtree.
        shutil.rmtree(src_path, ignore_errors=False)
        return trashed

    def backup_note(self, path: Path) -> Path:
        """Copy a Note into backups/ before overwriting/deleting it."""
        if not path.exists():
            return path
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        target = self.backups_dir / f"{now_iso().replace(':', '-')}-{path.name}"
        shutil.copy2(path, target)
        return target

    # ----------------------------------------------------- soft-delete (M7.0.1)

    @property
    def trash_dir(self) -> Path:
        """Recoverable Note bin. `notes/.trash/` keeps deleted Notes intact
        (frontmatter + body) so the user can restore by hand or via the
        `knowlet notes restore` CLI. Hidden from `iter_note_paths` because
        it's a dotfolder."""
        return self.notes_dir / ".trash"

    def trash_note(self, path: Path) -> Path:
        """Move a Note's on-disk file into `notes/.trash/`. Returns the
        new path. Idempotent on the file location (a same-name collision
        gets a timestamp suffix). Caller is responsible for removing the
        Note from the index."""
        if not path.exists():
            raise FileNotFoundError(str(path))
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        target = self.trash_dir / path.name
        if target.exists():
            target = self.trash_dir / f"{path.stem}-{now_iso().replace(':', '-')}.md"
        path.rename(target)
        return target

    def restore_note(self, trashed_path: Path) -> Path:
        """Move a trashed Note back to `notes/`. Returns the final path."""
        if not trashed_path.exists():
            raise FileNotFoundError(str(trashed_path))
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        target = self.notes_dir / trashed_path.name
        if target.exists():
            raise FileExistsError(f"cannot restore: {target} already exists in notes/")
        trashed_path.rename(target)
        return target

    def iter_trashed_paths(self) -> Iterator[Path]:
        if not self.trash_dir.exists():
            return iter(())
        return (p for p in self.trash_dir.glob("*.md") if p.is_file())

    def purge_trashed(self, name: str) -> Path:
        """Permanently delete one file from `notes/.trash/`. `name` is the
        basename only (no slashes — there are no subfolders in trash).

        Returns the deleted path (already gone from disk on success).
        Raises FileNotFoundError if the entry doesn't exist.
        """
        if "/" in name or "\\" in name or name in ("", ".", "..") or name.startswith("."):
            raise ValueError(f"invalid trash entry name: {name!r}")
        target = self.trash_dir / name
        if not target.exists():
            raise FileNotFoundError(str(target))
        target.unlink()
        return target

    # ----------------------------------------------------- attachments (M7.0.3)

    @property
    def attachments_dir(self) -> Path:
        """`notes/_attachments/`. Image-paste lands here; markdown links use
        a relative path (`_attachments/<id>.png`) so notes stay portable
        across Obsidian / iCloud / plain Finder."""
        return self.notes_dir / "_attachments"

    def write_attachment(self, data: bytes, ext: str) -> Path:
        """Save raw bytes as `_attachments/<ULID>.<ext>` and return the full
        path. Caller decides the ext (we validate the allowlist at the
        HTTP layer, not here, so unit tests don't need a fake mimetype)."""
        from knowlet.core.note import new_id

        self.attachments_dir.mkdir(parents=True, exist_ok=True)
        clean_ext = ext.lstrip(".").lower()
        target = self.attachments_dir / f"{new_id()}.{clean_ext}"
        target.write_bytes(data)
        return target

    def attachment_relpath(self, attachment_path: Path) -> str:
        """Return the path relative to `notes/`, slash-joined. Used to
        compose the markdown link the editor inserts."""
        rel = attachment_path.relative_to(self.notes_dir)
        return "/".join(rel.parts)
