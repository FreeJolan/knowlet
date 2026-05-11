"""Phase 2 E Slice 5.C — push orchestration (ADR-0027).

Mocks the Drive Files API entirely (the wrapper is exercised in
test_sync_files.py). Verifies the state machine + conflict capture +
resolution paths.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from knowlet.core.note import Note, new_id
from knowlet.core.sync.files import DriveFile
from knowlet.core.sync.push import (
    ATTACHMENT_ENTITY_TYPE,
    AttachmentFileMissingError,
    ConflictReport,
    PushResult,
    push_attachment,
    push_note,
    resolve_keep_both,
    resolve_use_mine,
    resolve_use_remote,
)
from knowlet.core.sync.state import FileState, SyncStateStore
from knowlet.core.vault import Vault


def _vault_with_note(tmp_path: Path) -> tuple[Vault, Note]:
    root = tmp_path / "v"
    root.mkdir()
    v = Vault(root)
    v.init_layout()
    n = Note(id=new_id(), title="alpha", body="local-v1")
    v.write_note(n)
    return v, n


def _drive_file(*, id_: str = "FID-1", revision: str = "rev-1") -> DriveFile:
    return DriveFile(
        id=id_,
        name="alpha.md",
        mime_type="text/markdown",
        modified_time="2026-05-10T12:00:00Z",
        head_revision_id=revision,
    )


# ----------------------------------------------------- first push (create)


def test_push_first_time_uploads_and_records(tmp_path: Path) -> None:
    _vault, note = _vault_with_note(tmp_path)
    state = SyncStateStore(tmp_path)
    try:
        with patch(
            "knowlet.core.sync.push.upload_new_file",
            return_value=_drive_file(),
        ) as up:
            result = push_note(service=object(), state=state, note=note)
        assert isinstance(result, PushResult)
        assert result.created is True
        assert result.drive_file.id == "FID-1"
        # State recorded.
        rec = state.get_file_state("note", note.id)
        assert rec is not None
        assert rec.drive_file_id == "FID-1"
        assert rec.last_known_etag == "rev-1"
        assert rec.dirty is False
        # The upload was called with the note's bytes.
        kwargs = up.call_args.kwargs
        assert kwargs["name"] == note.path.name
        assert kwargs["content"] == note.path.read_bytes()
        # 5.C.1: first push must land in the hidden appDataFolder,
        # NOT in the user's main Drive root. Without a parent under
        # drive.appdata scope the Drive API 403s.
        assert kwargs["parent_folder_id"] == "appDataFolder"
    finally:
        state.close()


# ----------------------------------------------------- update (clean)


def test_push_subsequent_uses_conditional_update(tmp_path: Path) -> None:
    _vault, note = _vault_with_note(tmp_path)
    state = SyncStateStore(tmp_path)
    try:
        # Pre-seed sync_state with a previous push.
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note.id,
                drive_file_id="FID-1",
                last_known_etag="rev-1",
                last_synced_at="2026-05-10T00:00:00Z",
                dirty=True,
            )
        )
        with patch(
            "knowlet.core.sync.push.update_file_conditional",
            return_value=_drive_file(revision="rev-2"),
        ) as upd:
            result = push_note(service=object(), state=state, note=note)
        assert isinstance(result, PushResult)
        assert result.created is False
        kwargs = upd.call_args.kwargs
        assert kwargs["expected_revision"] == "rev-1"
        # State advanced.
        rec = state.get_file_state("note", note.id)
        assert rec is not None
        assert rec.last_known_etag == "rev-2"
        assert rec.dirty is False
    finally:
        state.close()


# ----------------------------------------------------- conflict path


def test_push_remote_moved_returns_conflict_report(tmp_path: Path) -> None:
    _vault, note = _vault_with_note(tmp_path)
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note.id,
                drive_file_id="FID-1",
                last_known_etag="rev-stale",
                last_synced_at="2026-05-10T00:00:00Z",
                dirty=True,
            )
        )
        from knowlet.core.sync.files import RemoteVersionMismatchError

        with (
            patch(
                "knowlet.core.sync.push.update_file_conditional",
                side_effect=RemoteVersionMismatchError(
                    file_id="FID-1",
                    expected_revision="rev-stale",
                    actual_revision="rev-remote",
                ),
            ),
            patch(
                "knowlet.core.sync.push.get_file_metadata",
                return_value=_drive_file(revision="rev-remote"),
            ),
            patch(
                "knowlet.core.sync.push.download_file",
                return_value=b"REMOTE-BYTES",
            ),
        ):
            result = push_note(service=object(), state=state, note=note)
        assert isinstance(result, ConflictReport)
        assert result.entity_id == note.id
        assert result.expected_revision == "rev-stale"
        assert result.local_bytes == note.path.read_bytes()
        assert result.remote_bytes == b"REMOTE-BYTES"
        assert result.remote_metadata.head_revision_id == "rev-remote"
        # State NOT advanced (still dirty; revision still stale).
        rec = state.get_file_state("note", note.id)
        assert rec is not None
        assert rec.last_known_etag == "rev-stale"
        assert rec.dirty is True
    finally:
        state.close()


# ----------------------------------------------------- resolve: mine


def test_resolve_use_mine_force_overwrites_and_advances_etag(
    tmp_path: Path,
) -> None:
    _vault, note = _vault_with_note(tmp_path)
    state = SyncStateStore(tmp_path)
    try:
        conflict = ConflictReport(
            entity_type="note",
            entity_id=note.id,
            drive_file_id="FID-1",
            expected_revision="rev-stale",
            local_bytes=b"LOCAL",
            remote_bytes=b"REMOTE",
            remote_metadata=_drive_file(revision="rev-remote"),
        )
        with patch(
            "knowlet.core.sync.push.force_overwrite",
            return_value=_drive_file(revision="rev-mine-wins"),
        ) as fo:
            result = resolve_use_mine(
                service=object(), state=state, conflict=conflict
            )
        assert result.drive_file.head_revision_id == "rev-mine-wins"
        # force_overwrite was called with LOCAL bytes (the user
        # explicitly chose to clobber remote with their version).
        assert fo.call_args.kwargs["content"] == b"LOCAL"
        rec = state.get_file_state("note", note.id)
        assert rec is not None
        assert rec.last_known_etag == "rev-mine-wins"
        assert rec.dirty is False
    finally:
        state.close()


# ----------------------------------------------------- resolve: remote


def test_resolve_use_remote_overwrites_local_and_advances_etag(
    tmp_path: Path,
) -> None:
    _vault, note = _vault_with_note(tmp_path)
    state = SyncStateStore(tmp_path)
    try:
        conflict = ConflictReport(
            entity_type="note",
            entity_id=note.id,
            drive_file_id="FID-1",
            expected_revision="rev-stale",
            local_bytes=b"LOCAL",
            remote_bytes=b"REMOTE-WINS",
            remote_metadata=_drive_file(revision="rev-remote"),
        )
        assert note.path is not None
        resolve_use_remote(
            state=state, conflict=conflict, local_path=note.path
        )
        # Local file now has remote bytes.
        assert note.path.read_bytes() == b"REMOTE-WINS"
        # State advanced.
        rec = state.get_file_state("note", note.id)
        assert rec is not None
        assert rec.last_known_etag == "rev-remote"
        assert rec.dirty is False
    finally:
        state.close()


# ----------------------------------------------------- resolve: both


# ----------------------------------------------------- attachments (#121)


def _attachment_drive_file(*, name: str = "01HX.png") -> DriveFile:
    return DriveFile(
        id="FID-ATT-1",
        name=name,
        mime_type="image/png",
        modified_time="2026-05-11T12:00:00Z",
        head_revision_id="att-rev-1",
    )


def test_push_attachment_uploads_with_correct_mime_and_records(
    tmp_path: Path,
) -> None:
    att_path = tmp_path / "01HX.png"
    att_path.write_bytes(b"\x89PNG fake bytes")
    state = SyncStateStore(tmp_path)
    try:
        with patch(
            "knowlet.core.sync.push.upload_new_file",
            return_value=_attachment_drive_file(),
        ) as up:
            result = push_attachment(
                service=object(),
                state=state,
                filename="01HX.png",
                path=att_path,
            )
        assert isinstance(result, PushResult)
        assert result.entity_type == ATTACHMENT_ENTITY_TYPE
        assert result.entity_id == "01HX.png"
        assert result.created is True
        kwargs = up.call_args.kwargs
        assert kwargs["name"] == "01HX.png"
        assert kwargs["content"] == b"\x89PNG fake bytes"
        assert kwargs["mime_type"] == "image/png"
        assert kwargs["parent_folder_id"] == "appDataFolder"
        rec = state.get_file_state(ATTACHMENT_ENTITY_TYPE, "01HX.png")
        assert rec is not None
        assert rec.drive_file_id == "FID-ATT-1"
        assert rec.dirty is False
    finally:
        state.close()


def test_push_attachment_is_idempotent_when_already_pushed(
    tmp_path: Path,
) -> None:
    att_path = tmp_path / "01HX.png"
    att_path.write_bytes(b"PNG")
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type=ATTACHMENT_ENTITY_TYPE,
                entity_id="01HX.png",
                drive_file_id="FID-ATT-1",
                last_known_etag="att-rev-1",
                last_synced_at="2026-05-11T12:00:00Z",
                dirty=False,
            )
        )
        with patch(
            "knowlet.core.sync.push.upload_new_file",
        ) as up:
            result = push_attachment(
                service=object(),
                state=state,
                filename="01HX.png",
                path=att_path,
            )
        assert up.call_count == 0
        assert result.created is False
        assert result.drive_file.id == "FID-ATT-1"
    finally:
        state.close()


def test_push_attachment_raises_when_file_missing(tmp_path: Path) -> None:
    state = SyncStateStore(tmp_path)
    try:
        gone = tmp_path / "missing.png"
        try:
            push_attachment(
                service=object(),
                state=state,
                filename="missing.png",
                path=gone,
            )
        except AttachmentFileMissingError:
            pass
        else:
            raise AssertionError("expected AttachmentFileMissingError")
    finally:
        state.close()


def test_push_attachment_falls_back_to_octet_stream_for_unknown_ext(
    tmp_path: Path,
) -> None:
    """Drive doesn't strictly care about mime, but we should not crash
    on an unknown extension (e.g. ``.bin``)."""
    att_path = tmp_path / "01HX.weirdext"
    att_path.write_bytes(b"opaque")
    state = SyncStateStore(tmp_path)
    try:
        with patch(
            "knowlet.core.sync.push.upload_new_file",
            return_value=_attachment_drive_file(name="01HX.weirdext"),
        ) as up:
            push_attachment(
                service=object(),
                state=state,
                filename="01HX.weirdext",
                path=att_path,
            )
        assert up.call_args.kwargs["mime_type"] == "application/octet-stream"
    finally:
        state.close()


def test_resolve_keep_both_writes_sibling_and_keeps_local_dirty(
    tmp_path: Path,
) -> None:
    _vault, note = _vault_with_note(tmp_path)
    state = SyncStateStore(tmp_path)
    try:
        conflict = ConflictReport(
            entity_type="note",
            entity_id=note.id,
            drive_file_id="FID-1",
            expected_revision="rev-stale",
            local_bytes=b"LOCAL",
            remote_bytes=b"REMOTE-COPY",
            remote_metadata=_drive_file(revision="rev-remote"),
        )
        assert note.path is not None
        local_before = note.path.read_bytes()
        copy_path = resolve_keep_both(
            state=state,
            conflict=conflict,
            local_path=note.path,
            device_label="MacBook",
        )
        # Local untouched.
        assert note.path.read_bytes() == local_before
        # Copy holds remote bytes + sibling location.
        assert copy_path.exists()
        assert copy_path.read_bytes() == b"REMOTE-COPY"
        assert copy_path.parent == note.path.parent
        assert "conflict from MacBook" in copy_path.name
        # State: etag advanced to remote, but dirty=True so the next
        # push retries pushing local.
        rec = state.get_file_state("note", note.id)
        assert rec is not None
        assert rec.last_known_etag == "rev-remote"
        assert rec.dirty is True
    finally:
        state.close()
