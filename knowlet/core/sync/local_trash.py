"""Local side of a Drive-side deletion for non-note vault files.

When preflight sees that Drive no longer has an attachment / card /
draft / profile / ... that this device still holds, the local copy is
moved into the vault trash rather than unlinked: a deletion inferred
from a remote listing must stay recoverable.

Layout: ``notes/.trash/_sync_deleted/<entity_type>/<stem>.<ts><ext>``.
Kept in a subdirectory so these files never show up as trashed notes
(``Vault.iter_trashed_paths`` only lists top-level ``*.md``).
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

from knowlet.core.sync.push import ATTACHMENT_ENTITY_TYPE
from knowlet.core.sync.tracked_files import (
    SYNCABLE_VAULT_FILE_ENTITY_TYPES,
    resolve_syncable_vault_file_path,
)
from knowlet.core.vault import Vault

SYNC_DELETED_TRASH_DIR = "_sync_deleted"


def trash_local_vault_file_for_drive_deleted(
    vault_root: Path,
    entity_type: str,
    entity_id: str,
) -> Path | None:
    """Move the local copy of a Drive-deleted attachment or syncable
    vault file into the vault trash. Returns the trash path, or None
    when the id does not name a file inside the vault or no local copy
    exists. The caller removes the sync_state row."""
    target = _local_path(vault_root, entity_type, entity_id)
    if target is None or not target.is_file():
        return None
    trash_root = Vault(vault_root).trash_dir / SYNC_DELETED_TRASH_DIR / entity_type
    trash_root.mkdir(parents=True, exist_ok=True)
    dest = _unique_destination(trash_root, target.name)
    shutil.move(str(target), str(dest))
    return dest


def _local_path(vault_root: Path, entity_type: str, entity_id: str) -> Path | None:
    if entity_type == ATTACHMENT_ENTITY_TYPE:
        if not entity_id or entity_id in {".", ".."} or Path(entity_id).name != entity_id:
            return None
        return Vault(vault_root).attachments_dir / entity_id
    if entity_type in SYNCABLE_VAULT_FILE_ENTITY_TYPES:
        return resolve_syncable_vault_file_path(vault_root, entity_type, entity_id)
    return None


def _unique_destination(trash_root: Path, name: str) -> Path:
    stem = Path(name).stem
    suffix = Path(name).suffix
    now = datetime.now(UTC)
    ts = now.strftime("%Y-%m-%dT%H-%M-%S-") + f"{now.microsecond // 1000:03d}Z"
    candidate = trash_root / f"{stem}.{ts}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = trash_root / f"{stem}.{ts}-{counter}{suffix}"
        counter += 1
    return candidate
