"""Phase 2 E Slice 5.C — push local notes to Drive (ADR-0027).

Orchestrates the read+write+state dance for a single note:

1. Read sync_state.file_state for this entity_id.
2. If we've never seen it on Drive (no record / no drive_file_id):
   ``upload_new_file`` and persist (drive_file_id, etag).
3. If we have a record: ``update_file_with_etag`` conditional on
   ``last_known_etag``.
   - Success → persist new etag, dirty=0.
   - 412 ConflictDetected → return a ConflictReport so the caller
     can render the resolution UI; **don't** silently overwrite.

Keep in mind the trust boundary: this module assumes the caller has
already loaded valid credentials. It does NOT initiate OAuth, run
sync_pull, or hook the Vault.write_note autosave. Slice 5.C is
**explicit-trigger-only**; integration with autosave lands in 5.D
or later, with its own UX design.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from knowlet.core.note import Note, now_iso
from knowlet.core.sync.files import (
    DriveFile,
    RemoteVersionMismatchError,
    download_file,
    force_overwrite,
    get_file_metadata,
    update_file_conditional,
    upload_new_file,
)
from knowlet.core.sync.state import FileState, SyncStateStore


@dataclass
class PushResult:
    """Returned from a successful push. ``created`` distinguishes
    first-upload from update so the CLI / UI can word success
    appropriately."""

    entity_type: str
    entity_id: str
    drive_file: DriveFile
    created: bool


@dataclass
class ConflictReport:
    """Returned from ``push_note`` when the remote version has moved
    since our last-known revision. The caller — CLI today, UI later —
    presents the user with both versions and resolves via
    ``resolve_conflict``."""

    entity_type: str
    entity_id: str
    drive_file_id: str
    expected_revision: str
    local_bytes: bytes
    remote_bytes: bytes
    remote_metadata: DriveFile


class NoteFileMissingError(FileNotFoundError):
    """The Note row pointed at a vault path that no longer exists.
    Means the caller deleted the Note locally but didn't clean up
    sync_state. Surface explicitly."""


# ----------------------------------------------------- core ops


def push_note(
    *,
    service: Any,
    state: SyncStateStore,
    note: Note,
) -> PushResult | ConflictReport:
    """Push one Note. Returns either a PushResult (success) or a
    ConflictReport (412 — user must resolve)."""
    if note.path is None or not note.path.exists():
        raise NoteFileMissingError(
            f"Note {note.id} has no on-disk path; cannot push."
        )
    content = note.path.read_bytes()
    record = state.get_file_state("note", note.id)
    name = note.path.name
    if record is None or not record.drive_file_id:
        # First push: create on Drive.
        df = upload_new_file(
            service, name=name, content=content
        )
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note.id,
                drive_file_id=df.id,
                last_known_etag=df.head_revision_id,
                last_synced_at=now_iso(),
                dirty=False,
            )
        )
        return PushResult(
            entity_type="note",
            entity_id=note.id,
            drive_file=df,
            created=True,
        )
    # Update path: conditional on last-known head revision id.
    # The column is named `last_known_etag` for historical reasons;
    # since Drive v3 dropped the etag field, it now stores
    # headRevisionId values.
    if not record.last_known_etag:
        # Drive ID exists but we lost the cursor — fetch current
        # metadata to bootstrap. Graceful recovery from a corrupt
        # sync_state; we don't blindly overwrite.
        record_meta = get_file_metadata(service, record.drive_file_id)
        if not record_meta.head_revision_id:
            raise RuntimeError(
                f"Drive returned no headRevisionId for "
                f"{record.drive_file_id}; can't do conditional update."
            )
        expected = record_meta.head_revision_id
    else:
        expected = record.last_known_etag
    try:
        df = update_file_conditional(
            service,
            file_id=record.drive_file_id,
            content=content,
            expected_revision=expected,
        )
    except RemoteVersionMismatchError:
        # Build the conflict report — fetch remote bytes + metadata
        # so the caller has everything it needs to render UI.
        remote_meta = get_file_metadata(service, record.drive_file_id)
        remote_content = download_file(service, record.drive_file_id)
        return ConflictReport(
            entity_type="note",
            entity_id=note.id,
            drive_file_id=record.drive_file_id,
            expected_revision=expected,
            local_bytes=content,
            remote_bytes=remote_content,
            remote_metadata=remote_meta,
        )
    state.upsert_file_state(
        FileState(
            entity_type="note",
            entity_id=note.id,
            drive_file_id=df.id,
            last_known_etag=df.head_revision_id,
            last_synced_at=now_iso(),
            dirty=False,
        )
    )
    return PushResult(
        entity_type="note",
        entity_id=note.id,
        drive_file=df,
        created=False,
    )


# ----------------------------------------------------- conflict resolution


def resolve_use_mine(
    *,
    service: Any,
    state: SyncStateStore,
    conflict: ConflictReport,
) -> PushResult:
    """User picked "use my version, overwrite remote". Force update
    without If-Match — this is the explicit "I know I'm clobbering"
    exit. The remote file's prior contents are still recoverable
    via Drive's native version history (30 days)."""
    df = force_overwrite(
        service,
        file_id=conflict.drive_file_id,
        content=conflict.local_bytes,
    )
    state.upsert_file_state(
        FileState(
            entity_type=conflict.entity_type,
            entity_id=conflict.entity_id,
            drive_file_id=df.id,
            last_known_etag=df.head_revision_id,
            last_synced_at=now_iso(),
            dirty=False,
        )
    )
    return PushResult(
        entity_type=conflict.entity_type,
        entity_id=conflict.entity_id,
        drive_file=df,
        created=False,
    )


def resolve_use_remote(
    *,
    state: SyncStateStore,
    conflict: ConflictReport,
    local_path: Path,
) -> None:
    """User picked "use remote, drop my version". Overwrite the
    local file with the remote bytes; sync_state advances to the
    remote etag. The pre-overwrite bytes are still in
    .knowlet/backups/ (Slice 4.E) so this is reversible.

    NOTE: Vault.write_note's atomic .tmp+rename + audit log + backup
    semantics are NOT used here — the local-side change is "I'm
    accepting Drive's truth", not a user edit. We bypass Vault and
    write the raw bytes directly. Audit will reflect this via a
    `note.synced_from_remote` event (future slice)."""
    tmp = local_path.with_suffix(local_path.suffix + ".tmp")
    tmp.write_bytes(conflict.remote_bytes)
    tmp.replace(local_path)
    state.upsert_file_state(
        FileState(
            entity_type=conflict.entity_type,
            entity_id=conflict.entity_id,
            drive_file_id=conflict.drive_file_id,
            last_known_etag=conflict.remote_metadata.head_revision_id,
            last_synced_at=now_iso(),
            dirty=False,
        )
    )


def resolve_keep_both(
    *,
    state: SyncStateStore,
    conflict: ConflictReport,
    local_path: Path,
    device_label: str,
) -> Path:
    """User picked "preserve both" — write the remote version as a
    sibling conflict copy, leave the local untouched. Returns the
    path the conflict copy was written to.

    Naming: ``<stem> (conflict from <device>) <ts>.<ext>``. Distinct
    enough to be obvious in Finder; close enough to the original that
    a sort groups them together.
    """
    ts = now_iso().replace(":", "-")
    label_safe = device_label.replace("/", "-").replace(" ", "_")
    conflict_name = (
        f"{local_path.stem} (conflict from {label_safe}) {ts}{local_path.suffix}"
    )
    conflict_path = local_path.parent / conflict_name
    conflict_path.write_bytes(conflict.remote_bytes)
    # The local stays untouched + advances to the remote's etag —
    # next push will reconcile our version against where the remote
    # is now (the "we just split the timeline" state). The conflict
    # copy is the user's manual-merge fodder.
    state.upsert_file_state(
        FileState(
            entity_type=conflict.entity_type,
            entity_id=conflict.entity_id,
            drive_file_id=conflict.drive_file_id,
            last_known_etag=conflict.remote_metadata.head_revision_id,
            last_synced_at=now_iso(),
            dirty=True,  # local still has un-pushed changes!
        )
    )
    return conflict_path
