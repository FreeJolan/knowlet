"""Phase 2 E Slice 4.E — Per-file overwrite-time backup (ADR-0018 §4).

Each time a sensitive file in the vault is **overwritten**, we first
copy its current bytes to:

    vault/.knowlet/backups/<entity>/<id>.<iso-ts>.<ext>

Most recent 5 backups per ``(entity, id)`` survive an LRU prune; older
ones are deleted. The contract is:

- **Trigger**: overwrite only. New writes do nothing (there's no
  prior state to preserve).
- **Coverage**: Note (per-id, .md), QuickActions toml (single file).
  SQLite indexes are NOT covered — they're rebuildable; full vault
  state goes through ``vault snapshot`` instead.
- **Visibility**: UI never surfaces this directory. Power users find
  it via ``knowlet backups`` CLI / Finder; an upcoming ``knowlet
  doctor --restore-from-backup`` flag will use it programmatically.
- **Distinct from snapshots**: ``.knowlet/snapshots/`` is full-vault,
  user-initiated, coarse. ``.knowlet/backups/`` is per-file,
  automatic, fine. Both ship with the vault, both follow the user's
  cloud sync (iCloud / Drive / Syncthing).

This is a runtime safety net, not version control. Users serious
about history should keep their vault in their own git repo.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

# How many overwrite snapshots to retain per (entity, id). Tuned for
# the "I just hit save and immediately regretted it" recovery window
# without blowing up disk for high-edit-frequency notes. Power users
# can override later via vault config (not in this slice).
DEFAULT_KEEP = 5


# Filesystem-friendly timestamp: ISO without ``:`` (Windows-hostile),
# **with milliseconds** so two backups inside the same second don't
# collide on the filename. now_iso() in note.py uses second resolution
# which is fine for human-facing audit logs but loses fidelity here.
def _ts_for_filename() -> str:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    return now.strftime("%Y-%m-%dT%H-%M-%S-") + f"{now.microsecond // 1000:03d}Z"


@dataclass(frozen=True)
class BackupEntry:
    """One row in `list_backups`. Path + parsed metadata so callers
    don't re-implement the filename grammar."""

    path: Path
    entity_type: str
    entity_id: str
    timestamp: str  # filesystem-safe form (with - instead of :)


def backups_dir(vault_root: Path) -> Path:
    return vault_root / ".knowlet" / "backups"


class BackupStore:
    """File-level backup store. Stateless — it's just a directory
    with naming convention + LRU prune."""

    def __init__(self, vault_root: Path) -> None:
        self.vault_root = vault_root
        self._root = backups_dir(vault_root)

    # ----------------------------------------------------- mutation

    def backup_before_overwrite(
        self,
        entity_type: str,
        entity_id: str,
        current: Path,
        *,
        keep: int = DEFAULT_KEEP,
    ) -> Path | None:
        """Copy ``current`` into ``backups/<entity_type>/<entity_id>.
        <ts>.<ext>``. Returns the new backup path, or None when
        ``current`` doesn't exist (creates have nothing to back up).

        Caller is responsible for invoking this **before** the write
        that would overwrite ``current``. After the backup is made we
        prune the per-id history down to ``keep`` entries.

        Failure is non-fatal: if the copy fails we log + return None.
        The caller's actual write must NOT be blocked by a backup
        glitch (per ADR-0018 §4 — the safety net is best-effort).
        """
        if not current.exists():
            return None
        try:
            entity_dir = self._root / entity_type
            entity_dir.mkdir(parents=True, exist_ok=True)
            ext = current.suffix or ""
            ts = _ts_for_filename()
            dest = entity_dir / f"{entity_id}.{ts}{ext}"
            # ``copy2`` preserves mtime — useful for debugging /
            # for power users who eyeball the backups directly.
            shutil.copy2(current, dest)
            self._prune(entity_type, entity_id, keep=keep)
            return dest
        except Exception:
            import logging

            logging.getLogger(__name__).warning(
                "backup_before_overwrite failed for %s/%s",
                entity_type,
                entity_id,
                exc_info=True,
            )
            return None

    def _prune(self, entity_type: str, entity_id: str, *, keep: int) -> None:
        """Drop oldest entries beyond ``keep`` for this id."""
        entries = self._list_for(entity_type, entity_id)
        if len(entries) <= keep:
            return
        # `_list_for` returns newest-first; drop the tail.
        for old in entries[keep:]:
            try:
                old.path.unlink()
            except OSError:
                # Race / permissions / external delete — log and move on.
                import logging

                logging.getLogger(__name__).warning("could not delete backup %s", old.path)

    # ----------------------------------------------------- queries

    def list_backups(
        self, *, entity_type: str | None = None, entity_id: str | None = None
    ) -> list[BackupEntry]:
        """Walk the backup tree. Newest-first within each id; sort
        across ids is by ``(entity_type, entity_id, ts desc)``. Use
        the optional filters to scope to a single Note / one entity
        type."""
        if not self._root.exists():
            return []
        out: list[BackupEntry] = []
        type_dirs = [self._root / entity_type] if entity_type else list(self._root.iterdir())
        for tdir in type_dirs:
            if not tdir.is_dir():
                continue
            etype = tdir.name
            for f in tdir.iterdir():
                if not f.is_file():
                    continue
                parsed = _parse_backup_filename(f.name)
                if parsed is None:
                    continue
                eid, ts = parsed
                if entity_id is not None and eid != entity_id:
                    continue
                out.append(
                    BackupEntry(
                        path=f,
                        entity_type=etype,
                        entity_id=eid,
                        timestamp=ts,
                    )
                )
        # Newest-first within each (entity_type, entity_id).
        out.sort(key=lambda e: (e.entity_type, e.entity_id, e.timestamp), reverse=True)
        return out

    def _list_for(self, entity_type: str, entity_id: str) -> list[BackupEntry]:
        return [e for e in self.list_backups(entity_type=entity_type, entity_id=entity_id)]

    # ----------------------------------------------------- recovery

    def restore(self, backup_path: Path, dest: Path) -> Path:
        """Copy a backup file to ``dest``. Refuses to overwrite an
        existing dest — the caller is responsible for moving the
        current live file out of the way first (so a wrong restore
        can itself be undone via the next backup cycle)."""
        if not backup_path.exists():
            raise FileNotFoundError(str(backup_path))
        if dest.exists():
            raise FileExistsError(
                f"refusing to overwrite live file: {dest}. Move it aside first, then restore."
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup_path, dest)
        return dest


def _parse_backup_filename(name: str) -> tuple[str, str] | None:
    """Backup files are ``<entity_id>.<ts>.<ext>``. The id portion may
    contain dots in pathological cases (we don't generate them, but
    Card / Draft might come from elsewhere later). We split from the
    right: the ``<ext>`` is the last suffix, ``<ts>`` is the suffix
    before that, and the rest is the id.
    """
    # Strip extension — note we accept both ``.md`` (notes) and
    # ``.toml`` (quick actions) and anything else producers want.
    stem, dot, _ext = name.rpartition(".")
    if not dot:
        return None  # extensionless — not a backup we made.
    head, dot2, ts = stem.rpartition(".")
    if not dot2 or not ts:
        return None  # missing the timestamp — not ours.
    return head, ts
