"""Helpers for syncing non-note vault data files.

Digest source configs and Raw Info inbox items live under ``.knowlet``.
They are still user vault data, so once Drive sync is configured we queue
them through the same appData drainer as notes and attachments.
"""

from __future__ import annotations

from pathlib import Path

from knowlet.config import VAULT_MARKER_DIR
from knowlet.core.vault import DIGEST_DIR, DIGEST_ITEMS_DIR, DIGEST_SOURCES_DIR


def digest_sources_root(vault_root: Path) -> Path:
    return vault_root / VAULT_MARKER_DIR / DIGEST_DIR / DIGEST_SOURCES_DIR


def digest_items_root(vault_root: Path) -> Path:
    return vault_root / VAULT_MARKER_DIR / DIGEST_DIR / DIGEST_ITEMS_DIR


def infer_vault_root_from_digest_dir(root: Path) -> Path | None:
    """Return vault root for ``.knowlet/digest/{sources,items}`` paths."""
    if (
        root.name in {DIGEST_SOURCES_DIR, DIGEST_ITEMS_DIR}
        and root.parent.name == DIGEST_DIR
        and root.parent.parent.name == VAULT_MARKER_DIR
    ):
        return root.parent.parent.parent
    return None


def queue_synced_json_if_authenticated(
    *,
    vault_root: Path,
    entity_type: str,
    entity_id: str,
) -> None:
    """Mark a synced JSON file dirty when Drive credentials exist.

    If the user has not connected Drive yet, do nothing. The drainer's
    first creds-positive untracked sweep will queue existing files later.
    """
    from knowlet.core.sync.credentials import credentials_path, load_credentials
    from knowlet.core.sync.push import SYNCED_JSON_ENTITY_TYPES
    from knowlet.core.sync.state import FileState, SyncStateStore

    if entity_type not in SYNCED_JSON_ENTITY_TYPES:
        raise ValueError(f"unsupported synced file entity_type: {entity_type!r}")
    if load_credentials(credentials_path(vault_root)) is None:
        return

    store = SyncStateStore(vault_root)
    try:
        rec = store.get_file_state(entity_type, entity_id)
        if rec is None:
            store.upsert_file_state(
                FileState(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    drive_file_id=None,
                    last_known_etag=None,
                    last_synced_at=None,
                    dirty=True,
                )
            )
            return
        if rec.dirty:
            return
        store.upsert_file_state(
            FileState(
                entity_type=rec.entity_type,
                entity_id=rec.entity_id,
                drive_file_id=rec.drive_file_id,
                last_known_etag=rec.last_known_etag,
                last_synced_at=rec.last_synced_at,
                dirty=True,
                dismissed_until=rec.dismissed_until,
                delete_intent=rec.delete_intent,
            )
        )
    finally:
        store.close()


def queue_synced_json_delete_if_authenticated(
    *,
    vault_root: Path,
    entity_type: str,
    entity_id: str,
) -> None:
    """Queue Drive deletion for a synced JSON file that was removed locally."""
    from knowlet.core.sync.credentials import credentials_path, load_credentials
    from knowlet.core.sync.push import SYNCED_JSON_ENTITY_TYPES
    from knowlet.core.sync.state import FileState, SyncStateStore

    if entity_type not in SYNCED_JSON_ENTITY_TYPES:
        raise ValueError(f"unsupported synced file entity_type: {entity_type!r}")
    if load_credentials(credentials_path(vault_root)) is None:
        return

    store = SyncStateStore(vault_root)
    try:
        rec = store.get_file_state(entity_type, entity_id)
        if rec is None:
            return
        if rec.drive_file_id is None:
            store.remove_file_state(entity_type, entity_id)
            return
        store.upsert_file_state(
            FileState(
                entity_type=rec.entity_type,
                entity_id=rec.entity_id,
                drive_file_id=rec.drive_file_id,
                last_known_etag=rec.last_known_etag,
                last_synced_at=rec.last_synced_at,
                dirty=False,
                dismissed_until=rec.dismissed_until,
                delete_intent="hard",
            )
        )
    finally:
        store.close()
