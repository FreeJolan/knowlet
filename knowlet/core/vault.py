"""Vault: filesystem layout, Note read/write, vault initialization."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

from knowlet.config import VAULT_MARKER_DIR
from knowlet.core.audit_log import AuditEvent, AuditEventStore
from knowlet.core.backups import BackupStore
from knowlet.core.note import Note, now_iso

NOTES_DIR = "notes"
USERS_DIR = "users"
PROFILE_FILENAME = "me.md"
CARDS_DIR = "cards"
TASKS_DIR = "tasks"
DRAFTS_DIR = "drafts"
DIGEST_DIR = "digest"
DIGEST_SOURCES_DIR = "sources"
DIGEST_ITEMS_DIR = "items"
INDEX_DB = "index.sqlite"
CONVERSATIONS_DIR = "conversations"
BACKUPS_DIR = "backups"


# Phase 3 Stage 2 Step 2.6 — starter wiki_schema.md.
#
# Written into a freshly-init'd vault to demonstrate (a) what the file
# is for, (b) the Rule + **Why:** pattern (per ADR-0024 §3.4 borrowed
# from mature agents' rules-file convention), and (c) how it ties into
# the multi-level merge with ``~/.knowlet/wiki_schema.md``.
#
# The starter is written exactly once on vault init; if the user
# already has a wiki_schema.md it is NOT overwritten. Subsequent
# edits are theirs.
_WIKI_SCHEMA_STARTER = """\
# Wiki Schema — Vault Writing Conventions

> This file is read by knowlet AI roles (chat / capture / linter / …)
> on every call. It's how you teach the AI **how this vault is written**:
> naming, voice, structure, the rules YOU care about.
>
> Two-level merge (per ADR-0024 §3.4):
>   1. `~/.knowlet/wiki_schema.md` — your cross-vault defaults
>   2. `<this-vault>/.knowlet/wiki_schema.md` — vault-specific overrides
>
> Empty / non-existent files are silently skipped. Delete this starter
> if you want a fully empty schema.

## Style: write rules as `Rule + Why:`

Every convention below pairs a one-line rule with a `**Why:**` line.
The Why isn't decoration — it lets the AI judge edge cases instead
of mechanically following the rule (per ADR-0024 §3.4 "Rule + Why
mode", borrowed from mature agents' rules-file convention).

## Examples

- **Default to kebab-case filenames** (e.g. `rag-vs-fine-tuning.md`).
  **Why:** Easier to type, more URL-friendly, plays well with Finder
  search.

- **Use first-person singular for personal-experience notes**.
  **Why:** This vault is mine; rewriting in passive voice signals
  the note is impersonal reference (which it isn't).

- **Headings: `##` for top-level sections inside a note** (skip `#`,
  the title is in frontmatter).
  **Why:** Lets the file render correctly in both Obsidian and the
  knowlet web UI without a duplicate H1.

## Customize this file

Add / remove rules to taste. The AI reads whatever's here on the
next prompt — no restart needed.
"""


def _ensure_wiki_schema_template(path: Path) -> None:
    """Write the starter ``wiki_schema.md`` if and only if the file
    doesn't exist yet. Idempotent: never overwrites user edits."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_WIKI_SCHEMA_STARTER, encoding="utf-8")


class Vault:
    """Filesystem operations on a knowlet vault."""

    def __init__(
        self,
        root: Path,
        *,
        audit_log: AuditEventStore | None = None,
        backups: BackupStore | None = None,
    ):
        self.root = root.resolve()
        # Optional audit log. When set, Note write/trash/restore emit
        # events through it (per ADR-0023 §3 + ADR-0018). Pass None
        # in tests / scripts that don't care about the audit trail —
        # the producer methods are no-ops in that case.
        self.audit_log = audit_log
        # Phase 2 E Slice 4.E — per-file overwrite-time backup
        # (ADR-0018 §4). When set, Note overwrites copy the prior
        # bytes into .knowlet/backups/note/<id>.<ts>.md before the
        # rename. None = no backup taken (tests / migration tools).
        self.backups = backups

    def _emit(
        self,
        kind: str,
        entity_id: str,
        payload: dict[str, object],
        *,
        actor: str = "user",
    ) -> None:
        """Emit a Note-scoped audit event. No-op when audit_log is
        None. Failures are swallowed — the audit trail must never
        break the user's actual write path."""
        if self.audit_log is None:
            return
        try:
            self.audit_log.append(
                AuditEvent(
                    kind=kind,
                    entity_type="note",
                    entity_id=entity_id,
                    actor=actor,  # type: ignore[arg-type]
                    payload=payload,
                )
            )
        except Exception:
            # Audit failure is logged but never raises into the write
            # path. (We deliberately don't import logging at module
            # top — the Vault is otherwise dep-light.)
            import logging

            logging.getLogger(__name__).warning(
                "audit log append failed for %s/%s",
                kind,
                entity_id,
                exc_info=True,
            )

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
    def digest_sources_dir(self) -> Path:
        return self.state_dir / DIGEST_DIR / DIGEST_SOURCES_DIR

    @property
    def digest_items_dir(self) -> Path:
        return self.state_dir / DIGEST_DIR / DIGEST_ITEMS_DIR

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
        self.digest_sources_dir.mkdir(parents=True, exist_ok=True)
        self.digest_items_dir.mkdir(parents=True, exist_ok=True)
        self.conversations_dir.mkdir(parents=True, exist_ok=True)
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        # Phase 3 Stage 2 — write a starter wiki_schema.md if none
        # exists. The template demonstrates the Rule + Why pattern
        # (per ADR-0024 §3.4) and explains what wiki_schema is for.
        _ensure_wiki_schema_template(self.state_dir / "wiki_schema.md")

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

    # ---------- templates (Phase 1 B slice 8) ----------
    #
    # `_templates/` is the on-disk storage convention for templates,
    # mirroring `_attachments/` — both are reserved top-level folders
    # under `notes/` that the regular file-tree UI hides and that
    # `_resolve_subpath` rejects (so users can't create / rename a
    # collision via the "+" toolbar). Templates are still ordinary
    # markdown files; a Finder user sees and edits them as such.
    # The leading underscore matches the convention `_attachments/`
    # established in M7.0.3 so power users can spot system folders
    # at a glance.

    TEMPLATE_DIR = "_templates"

    def iter_templates(self) -> list[Path]:
        """List the `.md` files under `notes/_templates/`. Returns paths
        sorted alphabetically by filename for stable picker ordering.
        Returns `[]` if the folder hasn't been created yet — callers
        must NOT special-case absence (no NPEs in the API or UI)."""
        root = self.notes_dir / self.TEMPLATE_DIR
        if not root.exists() or not root.is_dir():
            return []
        return sorted(p for p in root.glob("*.md") if p.is_file())

    @staticmethod
    def apply_template_placeholders(
        body: str,
        *,
        title: str,
        date: str | None = None,
    ) -> str:
        """Substitute `{{title}}` and `{{date}}` in a template body.

        `date` defaults to today in ISO 8601 (YYYY-MM-DD). Unknown
        placeholders are left as-is (so a template author can write
        e.g. `{{cursor}}` and rely on a future version handling it).
        Substitution is whole-token: `{{ title }}` (with spaces) also
        matches, mirroring Obsidian Templater behaviour.
        """
        from datetime import date as _date_cls

        ctx = {"title": title, "date": date or _date_cls.today().isoformat()}
        # Match `{{name}}` with optional surrounding whitespace inside
        # the braces. Anything outside the known set falls through.
        import re

        def _sub(m: re.Match[str]) -> str:
            key = m.group(1).strip().lower()
            return ctx.get(key, m.group(0))

        return re.sub(r"\{\{\s*([a-zA-Z_][\w-]*)\s*\}\}", _sub, body)

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
        """Load a Note from disk. If the file has no frontmatter at
        all (an external markdown import — task #108 case A), this
        method materializes synthesized defaults to disk on the spot
        so the next read sees a canonical ULID-stamped file. The
        in-memory note is re-loaded from the post-write file so
        parallel callers converge on the same canonical version
        rather than each holding a stale freshly-minted ULID."""
        note = Note.from_file(path)
        if note.frontmatter_status == "auto_filled":
            # Persist the synthesized frontmatter atomically. After
            # the write, the file is canonical and a fresh
            # ``from_file`` call returns a "valid" Note. We re-read
            # so our return value reflects exactly what landed on
            # disk (also handles the rare two-callers-race case:
            # whichever lost the rename still gets the winner's id
            # by reading the freshly-canonical file).
            self.write_note(note)
            return Note.from_file(note.path or path)
        # Corrupted notes are returned as-is. The UI shows a warning
        # chip + auto-repair affordance; we don't auto-mutate the
        # user's content unprompted.
        return note

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
        # Capture create-vs-update BEFORE we overwrite — the file's
        # existence at this moment is the only signal. After the
        # rename below the answer is always "yes, exists".
        is_create = not target.exists()
        # Backup the current bytes BEFORE the atomic rename overwrites
        # them. New writes (is_create) skip — there's no prior state
        # to preserve. Per ADR-0018 §4 this is best-effort: BackupStore
        # already swallows its own internal exceptions, but we ALSO
        # wrap here so a misbehaving store impl (or a custom subclass)
        # can never block the user's actual save.
        if not is_create and self.backups is not None:
            try:
                self.backups.backup_before_overwrite("note", note.id, target)
            except Exception:
                import logging

                logging.getLogger(__name__).warning(
                    "backup_before_overwrite raised for note %s",
                    note.id,
                    exc_info=True,
                )
        note.path = target
        note.updated_at = now_iso()
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(note.to_markdown(), encoding="utf-8")
        tmp.replace(target)
        # Emit AFTER the atomic rename so a failed write doesn't
        # leave a phantom event. Folder is recorded so log readers
        # can see "where did it land".
        self._emit(
            "note.created" if is_create else "note.updated",
            note.id,
            {
                "title": note.title,
                "folder": self.folder_of(target),
            },
        )
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
        """Create a folder under `notes/` (idempotent). Returns its path.

        Rejects user-explicit creation of the templates folder
        (`_templates/`) — that one's a system folder, created
        implicitly when the templates UI writes the first template.
        Letting users mkdir it from the file tree by hand would
        violate the abstraction (see slice 8 v2 dogfood note: the
        on-disk convention is meant to be opaque)."""
        rel_clean = (folder or "").strip().strip("/")
        if rel_clean.split("/", 1)[0] == self.TEMPLATE_DIR:
            raise ValueError(
                f"{self.TEMPLATE_DIR}/ is a system folder; create templates via the Templates dialog",
            )
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
        Note from the index.

        Before moving, annotate the note's frontmatter with
        `trashed_from: <folder>` so a future restore knows which
        subfolder to recreate. This is the only way restore can
        preserve the note's pre-trash location — we have no sidecar
        metadata, the file IS the source of truth.
        """
        if not path.exists():
            raise FileNotFoundError(str(path))
        # Snapshot the original folder BEFORE moving (folder_of needs
        # the path to be inside notes_dir).
        original_folder = self.folder_of(path)
        try:
            note = Note.from_file(path)
            note.trashed_from = original_folder
            path.write_text(note.to_markdown(), encoding="utf-8")
        except Exception:  # noqa: S110
            # If the note's frontmatter is malformed we still trash
            # it — restore will fall back to root. Not great, but
            # better than blocking the delete on a corrupt file.
            pass
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        target = self.trash_dir / path.name
        if target.exists():
            target = self.trash_dir / f"{path.stem}-{now_iso().replace(':', '-')}.md"
        path.rename(target)
        # Emit. note_id is the file stem (filename = "<id>.md").
        # Title may be missing if frontmatter parse failed above —
        # fall back to the stem.
        try:
            note_for_event = Note.from_file(target)
            event_title = note_for_event.title
            note_id = note_for_event.id
        except Exception:
            event_title = target.stem
            note_id = target.stem
        self._emit(
            "note.deleted",
            note_id,
            {"title": event_title, "from_folder": original_folder},
        )
        return target

    def restore_note(self, trashed_path: Path) -> Path:
        """Move a trashed Note back to `notes/`. Returns the final path.

        If the note's frontmatter carries `trashed_from`, restore into
        that subfolder (creating it if missing — covers the "user
        deleted ancestor folder, then restored a leaf" case). Strip
        the field from the frontmatter on the way out so the live
        note has clean metadata again.
        """
        if not trashed_path.exists():
            raise FileNotFoundError(str(trashed_path))
        # Read + decide target folder.
        target_dir = self.notes_dir
        try:
            note = Note.from_file(trashed_path)
            folder = note.trashed_from or ""
            if folder and self._safe_relative_path(folder):
                target_dir = self.notes_dir / folder
            note.trashed_from = None
        except Exception:
            note = None
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / trashed_path.name
        if target.exists():
            raise FileExistsError(f"cannot restore: {target} already exists in notes/")
        # If we successfully parsed the note, write the cleaned-up
        # frontmatter; otherwise just move the bytes.
        if note is not None:
            target.write_text(note.to_markdown(), encoding="utf-8")
            trashed_path.unlink()
        else:
            trashed_path.rename(target)
        # Emit. Title is best-effort; we may have failed to parse.
        try:
            restored = note if note is not None else Note.from_file(target)
            self._emit(
                "note.restored",
                restored.id,
                {
                    "title": restored.title,
                    "to_folder": self.folder_of(target),
                },
            )
        except Exception:
            self._emit(
                "note.restored",
                target.stem,
                {"to_folder": self.folder_of(target)},
            )
        return target

    def _safe_relative_path(self, rel: str) -> bool:
        """Validate a folder path string against path traversal rules
        without raising. Used by `restore_note` to fall back to root
        on a corrupt `trashed_from` instead of crashing the restore."""
        for part in rel.split("/"):
            if not part or part in (".", "..") or "\\" in part or part.startswith("."):
                return False
        return True

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
