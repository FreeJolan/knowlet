"""Sync-state bookkeeping for local note writes, deletes and restores.

Every interface that changes a note on disk (web, CLI, MCP) must leave
the same trail in ``sync_state`` so the background push drainer sees the
change: a save flips the row dirty (or creates a first-push row once Drive
is connected), a delete records a Drive-side delete intent, a restore
clears it again. These functions only touch ``sync_state``; they need no
running web runtime.

Each takes the vault root and an optional open ``SyncStateStore`` (reused
and left open when given, otherwise one is opened and closed here).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from knowlet.core.sync import credentials as _credentials
from knowlet.core.sync.state import FileState, SyncStateStore, sync_state_db_path
from knowlet.core.sync.status import DEV_FAKE_DRIVE_FILE_ID

DELETE_INTENT_KINDS = ("soft", "hard")


def sync_configured(vault_root: Path) -> bool:
    """True once the vault has sync state or Drive credentials. Callers that
    run outside the web server use it to avoid creating a ``sync_state``
    database in vaults that never set up sync."""
    return (
        sync_state_db_path(vault_root).exists()
        or _credentials.credentials_path(vault_root).exists()
    )


@contextmanager
def _store_for(vault_root: Path, store: SyncStateStore | None) -> Iterator[SyncStateStore]:
    if store is not None:
        yield store
        return
    owned = SyncStateStore(vault_root)
    try:
        yield owned
    finally:
        owned.close()


def mark_note_dirty_for_push(
    vault_root: Path,
    note_id: str,
    *,
    store: SyncStateStore | None = None,
) -> bool:
    """Queue a just-written note for the push drainer.

    - Row with a Drive id → flip ``dirty=True`` (conditional update push).
    - No row and Drive credentials present → create a first-push row
      (``drive_file_id=None, dirty=True``).
    - No row and no credentials → no-op (sync not configured).
    - Dev-seeded fake-conflict row → no-op.

    Returns True when ``sync_state`` was changed."""
    with _store_for(vault_root, store) as st:
        rec = st.get_file_state("note", note_id)
        if rec is not None and rec.drive_file_id == DEV_FAKE_DRIVE_FILE_ID:
            return False
        if rec is None:
            if _credentials.load_credentials(_credentials.credentials_path(vault_root)) is None:
                return False
            st.upsert_file_state(
                FileState(
                    entity_type="note",
                    entity_id=note_id,
                    drive_file_id=None,
                    last_known_etag=None,
                    last_synced_at=None,
                    dirty=True,
                )
            )
            return True
        if rec.dirty:
            return False
        st.upsert_file_state(
            FileState(
                entity_type=rec.entity_type,
                entity_id=rec.entity_id,
                drive_file_id=rec.drive_file_id,
                last_known_etag=rec.last_known_etag,
                last_synced_at=rec.last_synced_at,
                dirty=True,
                dismissed_until=rec.dismissed_until,
            )
        )
        return True


def mark_note_delete_intent(
    vault_root: Path,
    note_id: str,
    kind: str,
    *,
    store: SyncStateStore | None = None,
) -> bool:
    """Flag a deleted note's row for Drive-side deletion by the drainer.

    ``kind`` is ``"soft"`` (Drive trash, 30-day grace) or ``"hard"``
    (permanent). A never-pushed row (no Drive id) or a dev-seeded row is
    simply dropped — there is no Drive file to clean up. The Drive id and
    etag are preserved because the drainer needs them at delete time.

    Returns True only when a delete intent was recorded."""
    if kind not in DELETE_INTENT_KINDS:
        raise ValueError(f"delete intent must be soft|hard, got {kind!r}")
    with _store_for(vault_root, store) as st:
        rec = st.get_file_state("note", note_id)
        if rec is None:
            return False
        if not rec.drive_file_id or rec.drive_file_id == DEV_FAKE_DRIVE_FILE_ID:
            st.remove_file_state("note", note_id)
            return False
        st.upsert_file_state(
            FileState(
                entity_type=rec.entity_type,
                entity_id=rec.entity_id,
                drive_file_id=rec.drive_file_id,
                last_known_etag=rec.last_known_etag,
                last_synced_at=rec.last_synced_at,
                dirty=False,  # not a push — Drive delete instead
                dismissed_until=rec.dismissed_until,
                delete_intent=kind,
            )
        )
        return True


def unmark_note_delete_intent(
    vault_root: Path,
    note_id: str,
    *,
    store: SyncStateStore | None = None,
) -> bool:
    """A trashed note was restored before the drainer propagated the
    delete: clear the intent and mark the row dirty so the restored
    content is pushed normally. Returns True when ``sync_state`` changed."""
    with _store_for(vault_root, store) as st:
        rec = st.get_file_state("note", note_id)
        if rec is None or rec.delete_intent is None:
            return False
        st.upsert_file_state(
            FileState(
                entity_type=rec.entity_type,
                entity_id=rec.entity_id,
                drive_file_id=rec.drive_file_id,
                last_known_etag=rec.last_known_etag,
                last_synced_at=rec.last_synced_at,
                dirty=True,  # restore = something changed locally
                dismissed_until=rec.dismissed_until,
                delete_intent=None,
            )
        )
        return True
