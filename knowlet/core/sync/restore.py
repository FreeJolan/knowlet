"""Restore a local Vault from Drive appData after binding its vault_id."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from knowlet.core.note import Note, now_iso
from knowlet.core.sync.files import download_file, list_appdata_revisions
from knowlet.core.sync.push import (
    ATTACHMENT_ENTITY_TYPE,
    NOTE_ENTITY_TYPE,
    appdata_entity_from_drive_name,
)
from knowlet.core.sync.state import FileState, SyncStateStore
from knowlet.core.sync.tracked_files import (
    CONFIG_SNAPSHOT_ENTITY_TYPE,
    SYNCABLE_VAULT_FILE_ENTITY_TYPES,
    resolve_syncable_vault_file_path,
)
from knowlet.core.vault import Vault


@dataclass(frozen=True)
class RestoreVaultReport:
    materialized_count: int
    skipped_count: int
    materialized_ids: list[str] = field(default_factory=list)


def restore_vault_from_drive(service: Any, *, vault_root: Path) -> RestoreVaultReport:
    """Materialize every Drive appData file scoped to ``vault_root``.

    The caller must write ``.knowlet/vault.json`` to the remote
    ``vault_id`` before invoking this function. That makes
    ``appdata_entity_from_drive_name`` reject files from other Vaults
    automatically.
    """
    vault = Vault(vault_root)
    state = SyncStateStore(vault.root)
    materialized: list[str] = []
    skipped = 0
    try:
        drive_files = list_appdata_revisions(service)
        for drive_file_id, brief in drive_files.items():
            name = brief.name or ""
            parsed = appdata_entity_from_drive_name(name, vault_root=vault.root)
            if parsed is None:
                skipped += 1
                continue
            entity_type, entity_id = parsed
            try:
                body = download_file(service, drive_file_id)
            except Exception:
                skipped += 1
                continue
            if entity_type == NOTE_ENTITY_TYPE:
                if _restore_note(
                    vault=vault,
                    state=state,
                    drive_file_id=drive_file_id,
                    entity_id=entity_id,
                    revision=brief.head_revision_id,
                    body=body,
                ):
                    materialized.append(entity_id)
                else:
                    skipped += 1
                continue
            if entity_type == ATTACHMENT_ENTITY_TYPE:
                if Path(entity_id).name != entity_id:
                    skipped += 1
                    continue
                if _restore_file(
                    vault=vault,
                    state=state,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    drive_file_id=drive_file_id,
                    revision=brief.head_revision_id,
                    body=body,
                ):
                    materialized.append(entity_id)
                else:
                    skipped += 1
                continue
            if entity_type in SYNCABLE_VAULT_FILE_ENTITY_TYPES:
                if _restore_syncable_vault_file(
                    vault=vault,
                    state=state,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    drive_file_id=drive_file_id,
                    revision=brief.head_revision_id,
                    body=body,
                ):
                    materialized.append(entity_id)
                else:
                    skipped += 1
                continue
            skipped += 1
    finally:
        state.close()
    return RestoreVaultReport(
        materialized_count=len(materialized),
        skipped_count=skipped,
        materialized_ids=materialized,
    )


def _restore_note(
    *,
    vault: Vault,
    state: SyncStateStore,
    drive_file_id: str,
    entity_id: str,
    revision: str | None,
    body: bytes,
) -> bool:
    try:
        raw = body.decode("utf-8")
    except UnicodeDecodeError:
        return False
    note = Note.from_text(raw)
    if entity_id:
        note.id = entity_id
    try:
        vault.write_note(note, folder=note.folder)
    except ValueError:
        note.folder = None
        vault.write_note(note)
    state.upsert_file_state(
        FileState(
            entity_type=NOTE_ENTITY_TYPE,
            entity_id=note.id,
            drive_file_id=drive_file_id,
            last_known_etag=revision,
            last_synced_at=now_iso(),
            dirty=False,
        )
    )
    return True


def _restore_file(
    *,
    vault: Vault,
    state: SyncStateStore,
    entity_type: str,
    entity_id: str,
    drive_file_id: str,
    revision: str | None,
    body: bytes,
) -> bool:
    if entity_type != ATTACHMENT_ENTITY_TYPE:
        return False
    target = vault.attachments_dir / entity_id
    return _write_materialized_file(
        state=state,
        entity_type=entity_type,
        entity_id=entity_id,
        target=target,
        drive_file_id=drive_file_id,
        revision=revision,
        body=body,
    )


def _restore_syncable_vault_file(
    *,
    vault: Vault,
    state: SyncStateStore,
    entity_type: str,
    entity_id: str,
    drive_file_id: str,
    revision: str | None,
    body: bytes,
) -> bool:
    target = resolve_syncable_vault_file_path(vault.root, entity_type, entity_id)
    if target is None:
        return False
    return _write_materialized_file(
        state=state,
        entity_type=entity_type,
        entity_id=entity_id,
        target=target,
        drive_file_id=drive_file_id,
        revision=revision,
        body=body,
    )


def _write_materialized_file(
    *,
    state: SyncStateStore,
    entity_type: str,
    entity_id: str,
    target: Path,
    drive_file_id: str,
    revision: str | None,
    body: bytes,
) -> bool:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(body)
    tmp.replace(target)
    if entity_type == CONFIG_SNAPSHOT_ENTITY_TYPE:
        from knowlet.config import apply_synced_config_snapshot

        apply_synced_config_snapshot(state.vault_root)
    state.upsert_file_state(
        FileState(
            entity_type=entity_type,
            entity_id=entity_id,
            drive_file_id=drive_file_id,
            last_known_etag=revision,
            last_synced_at=now_iso(),
            dirty=False,
        )
    )
    return True
