"""Restore a local Vault from Drive appData after binding its vault_id."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from knowlet.core.note import Note, now_iso
from knowlet.core.sync.files import download_file, list_appdata_revisions
from knowlet.core.sync.push import (
    ATTACHMENT_ENTITY_TYPE,
    DIGEST_SOURCE_ENTITY_TYPE,
    NOTE_ENTITY_TYPE,
    RAW_INFO_ENTITY_TYPE,
    appdata_entity_from_drive_name,
)
from knowlet.core.sync.state import FileState, SyncStateStore
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
            if Path(entity_id).name != entity_id:
                skipped += 1
                continue
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
            if entity_type in {
                DIGEST_SOURCE_ENTITY_TYPE,
                RAW_INFO_ENTITY_TYPE,
                ATTACHMENT_ENTITY_TYPE,
            }:
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
    if entity_type == DIGEST_SOURCE_ENTITY_TYPE:
        target_dir = vault.digest_sources_dir
    elif entity_type == RAW_INFO_ENTITY_TYPE:
        target_dir = vault.digest_items_dir
    elif entity_type == ATTACHMENT_ENTITY_TYPE:
        target_dir = vault.attachments_dir
    else:
        return False
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / entity_id
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(body)
    tmp.replace(target)
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
