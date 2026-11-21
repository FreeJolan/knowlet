"""Sync bookkeeping for CLI note changes.

The web UI records every note write / delete / restore in ``sync_state`` so
the push drainer propagates it to Drive; the CLI must leave the same trail
(see ``knowlet.core.sync.note_bookkeeping``). Vaults that never set up sync
are left alone — no ``sync_state`` database is created for them.

Bookkeeping runs after the note change is already on disk, so a failure here
only warns: the user's command succeeded, and the next web-session sweep
re-queues untracked notes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING

from knowlet.cli._common import err_console

if TYPE_CHECKING:
    from knowlet.core.sync.state import SyncStateStore


def _sync_configured(vault_root: Path) -> bool:
    from knowlet.core.sync.credentials import credentials_path
    from knowlet.core.sync.state import sync_state_db_path

    return sync_state_db_path(vault_root).exists() or credentials_path(vault_root).exists()


def _apply(
    vault_root: Path,
    note_ids: Iterable[str],
    action: Callable[..., object],
    *args: str,
) -> None:
    ids = [i for i in dict.fromkeys(note_ids) if i]
    if not ids or not _sync_configured(vault_root):
        return
    from knowlet.core.sync.state import SyncStateStore

    try:
        store = SyncStateStore(vault_root)
        try:
            for note_id in ids:
                action(vault_root, note_id, *args, store=store)
        finally:
            store.close()
    except Exception as exc:
        err_console.print(f"[yellow]warning: sync bookkeeping failed: {exc}[/yellow]")


def mark_dirty(vault_root: Path, note_ids: Iterable[str]) -> None:
    from knowlet.core.sync.note_bookkeeping import mark_note_dirty_for_push

    _apply(vault_root, note_ids, mark_note_dirty_for_push)


def mark_deleted(vault_root: Path, note_ids: Iterable[str]) -> None:
    from knowlet.core.sync.note_bookkeeping import mark_note_delete_intent

    _apply(vault_root, note_ids, mark_note_delete_intent, "soft")


def mark_restored(vault_root: Path, note_ids: Iterable[str]) -> None:
    from knowlet.core.sync.note_bookkeeping import (
        mark_note_dirty_for_push,
        unmark_note_delete_intent,
    )

    def restore(root: Path, note_id: str, *, store: SyncStateStore) -> None:
        if not unmark_note_delete_intent(root, note_id, store=store):
            mark_note_dirty_for_push(root, note_id, store=store)

    _apply(vault_root, note_ids, restore)
