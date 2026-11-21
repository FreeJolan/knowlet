"""2026-11 audit — sync-core batch regression tests.

Each test locks the fix for one finding from the sync-core audit batch:

- preflight must not treat a failed / truncated Drive listing as
  "everything was deleted remotely" (data-safety, preflight.py).
- preflight Pass A must not trash a note that has unpushed local edits
  (delete/edit conflict, preflight.py).
- drainer must treat "runtime not ready" as "skip this tick", not as
  "file deleted" (drainer.py + RuntimeNotReadyError sentinel).
- pull must abort when the local file / dirty flag changed during the
  download window (pull.py).
- push must not clear a dirty flag set while the upload was in flight
  (push.py push_note / push_vault_file).
- resolve_use_remote must back up the local bytes it overwrites.
- first push must adopt (or conflict on) an existing same-name appData
  file instead of creating a duplicate (push.py).
- resolve_keep_both must not write a second file with the same note id.
- merge_notes must carry kind + folder through a conflict merge.
- preflight must reuse the bulk appData listing instead of one
  files.get (+ token refresh) per note.
- freshness probe must advance the changes cursor when every change in
  the batch is irrelevant.
- CLI `sync push` must derive a stable note id for frontmatterless
  files (via Vault.read_note materialization).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from knowlet.core.note import Note, new_id
from knowlet.core.sync.credentials import (
    SyncCredentials,
    credentials_path,
    save_credentials,
)
from knowlet.core.sync.files import DriveFile
from knowlet.core.sync.oauth import SCOPES
from knowlet.core.sync.preflight import preflight_scan
from knowlet.core.sync.pull import pull_note_to_local
from knowlet.core.sync.push import (
    ConflictReport,
    PushResult,
    push_note,
    push_vault_file,
    resolve_keep_both,
    resolve_use_remote,
)
from knowlet.core.sync.state import FileState, SyncStateStore
from knowlet.core.sync.tracked_files import CARD_ENTITY_TYPE
from knowlet.core.vault import Vault


def _seed_creds(tmp_path: Path) -> None:
    save_credentials(
        credentials_path(tmp_path),
        SyncCredentials(
            user_email="alice@example.com",
            token={
                "scopes": list(SCOPES),
                "token": "x",
                "refresh_token": "y",
                "client_id": "c",
                "client_secret": "s",
                "token_uri": "https://oauth2.googleapis.com/token",
            },
        ),
    )


def _meta(rev: str, *, id_: str = "DRIVE-FID") -> DriveFile:
    return DriveFile(
        id=id_,
        name="alpha.md",
        mime_type="text/markdown",
        modified_time="2026-05-11T12:00:00Z",
        head_revision_id=rev,
    )


def _vault_with_note(tmp_path: Path) -> tuple[Vault, Note]:
    root = tmp_path / "v"
    root.mkdir()
    v = Vault(root)
    v.init_layout()
    n = Note(id=new_id(), title="alpha", body="local-v1")
    v.write_note(n)
    return v, n


class _ExplodingListService:
    """Drive service whose files() access raises — network down."""

    def files(self):
        raise ConnectionError("drive unreachable")


class _PagedListService:
    """Drive service returning canned files().list() pages. The last
    page is returned forever (lets a nextPageToken-carrying page
    simulate an endless/truncated listing)."""

    def __init__(self, pages: list[dict]) -> None:
        self._pages = list(pages)

    def files(self):
        return self

    def list(self, **_kwargs):
        return self

    def execute(self) -> dict:
        if len(self._pages) > 1:
            return self._pages.pop(0)
        return self._pages[0]


# ------------------------------------------------------------------
# preflight: Drive listing failed / truncated must NOT mean "deleted"
# ------------------------------------------------------------------


def test_preflight_drive_list_failure_skips_deletion_pass(tmp_path: Path) -> None:
    """Listing raised (offline / 5xx): rows whose drive_file_id is
    missing from the (empty) result must NOT be trashed or deleted."""
    _seed_creds(tmp_path)
    nid = new_id()
    state = SyncStateStore(tmp_path)
    trashed: list[str] = []
    deleted: list[tuple[str, str]] = []
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=nid,
                drive_file_id="DRIVE-NOTE",
                last_known_etag="rev-1",
                last_synced_at="2026-06-01T00:00:00Z",
                dirty=False,
            )
        )
        state.upsert_file_state(
            FileState(
                entity_type=CARD_ENTITY_TYPE,
                entity_id="01CARD.json",
                drive_file_id="DRIVE-CARD",
                last_known_etag="rev-1",
                last_synced_at="2026-06-01T00:00:00Z",
                dirty=False,
            )
        )
        with (
            patch(
                "knowlet.core.sync.preflight._maybe_heartbeat_pass",
                return_value=_ExplodingListService(),
            ),
            patch(
                "knowlet.core.sync.status._drive_service",
                return_value=MagicMock(),
            ),
            patch(
                "knowlet.core.sync.status.get_file_metadata",
                return_value=_meta("rev-1"),
            ),
        ):
            report = preflight_scan(
                vault_root=tmp_path,
                state_store=state,
                note_meta_lookup=lambda _id: None,
                note_path_lookup=lambda _id: None,
                auto_pull_service_factory=lambda: _ExplodingListService(),
                trash_local_for_drive_deleted=trashed.append,
                delete_local_vault_file_for_drive_deleted=lambda et, eid: deleted.append((et, eid)),
            )
    finally:
        state.close()

    assert trashed == []
    assert deleted == []
    assert report.trashed_for_drive_delete_ids == []
    assert report.deleted_for_drive_delete_ids == []


def test_preflight_truncated_listing_skips_deletion_pass(tmp_path: Path) -> None:
    """Pagination cap reached while Drive still reports nextPageToken:
    the listing is NOT authoritative, so deletion propagation must be
    skipped for the tick."""
    state = SyncStateStore(tmp_path)
    deleted: list[tuple[str, str]] = []
    endless_page = {
        "files": [{"id": "F-OTHER", "name": "other", "headRevisionId": "r1"}],
        "nextPageToken": "more",
    }
    try:
        state.upsert_file_state(
            FileState(
                entity_type=CARD_ENTITY_TYPE,
                entity_id="01CARD.json",
                drive_file_id="DRIVE-CARD",
                last_known_etag="rev-1",
                last_synced_at="2026-06-01T00:00:00Z",
                dirty=False,
            )
        )
        with patch(
            "knowlet.core.sync.preflight._maybe_heartbeat_pass",
            return_value=_PagedListService([endless_page]),
        ):
            report = preflight_scan(
                vault_root=tmp_path,
                state_store=state,
                note_meta_lookup=lambda _id: None,
                note_path_lookup=lambda _id: None,
                auto_pull_service_factory=lambda: object(),
                delete_local_vault_file_for_drive_deleted=lambda et, eid: deleted.append((et, eid)),
            )
    finally:
        state.close()

    assert deleted == []
    assert report.deleted_for_drive_delete_ids == []


def test_preflight_listing_failure_is_reported_offline(tmp_path: Path) -> None:
    """The scan skipped remote additions/deletions, so it must not look
    'cleared' (the server advances the freshness cursor on a cleared
    report and would hide those remote changes)."""
    from knowlet.core.sync.preflight import DRIVE_LISTING_OFFLINE_ID

    state = SyncStateStore(tmp_path)
    try:
        with patch(
            "knowlet.core.sync.preflight._maybe_heartbeat_pass",
            return_value=_ExplodingListService(),
        ):
            report = preflight_scan(
                vault_root=tmp_path,
                state_store=state,
                note_meta_lookup=lambda _id: None,
                note_path_lookup=lambda _id: None,
                auto_pull_service_factory=lambda: _ExplodingListService(),
                materialize_drive_file=lambda _fid, _brief: None,
                trash_local_for_drive_deleted=lambda _id: None,
                delete_local_vault_file_for_drive_deleted=lambda _et, _eid: None,
            )
    finally:
        state.close()

    assert [o.note_id for o in report.offline] == [DRIVE_LISTING_OFFLINE_ID]
    assert "drive unreachable" in (report.offline[0].detail or "")


def test_preflight_lazily_created_service_does_not_enable_deletion_pass(
    tmp_path: Path,
) -> None:
    """Heartbeat pass got no service, so the listing never ran; a stale
    note then creates a service lazily for its pull. Pass A must not run
    against the never-fetched (empty) listing."""
    _seed_creds(tmp_path)
    nid = new_id()
    p = tmp_path / f"{nid}.md"
    p.write_text("clean local", encoding="utf-8")
    past = time.time() - 86400
    os.utime(p, (past, past))
    state = SyncStateStore(tmp_path)
    deleted: list[tuple[str, str]] = []
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=nid,
                drive_file_id="DRIVE-NOTE",
                last_known_etag="rev-OLD",
                last_synced_at="2030-01-01T00:00:00Z",
                dirty=False,
            )
        )
        state.upsert_file_state(
            FileState(
                entity_type=CARD_ENTITY_TYPE,
                entity_id="01CARD.json",
                drive_file_id="DRIVE-CARD",
                last_known_etag="rev-1",
                last_synced_at="2026-06-01T00:00:00Z",
                dirty=False,
            )
        )
        with (
            patch("knowlet.core.sync.preflight._maybe_heartbeat_pass", return_value=None),
            patch("knowlet.core.sync.status._drive_service", return_value=MagicMock()),
            patch("knowlet.core.sync.status.get_file_metadata", return_value=_meta("rev-NEW")),
            patch("knowlet.core.sync.pull.get_file_metadata", return_value=_meta("rev-NEW")),
            patch("knowlet.core.sync.pull.download_file", return_value=b"remote"),
        ):
            report = preflight_scan(
                vault_root=tmp_path,
                state_store=state,
                note_meta_lookup=lambda _id: None,
                note_path_lookup=lambda _id: p,
                auto_pull_service_factory=lambda: MagicMock(),
                delete_local_vault_file_for_drive_deleted=lambda et, eid: deleted.append((et, eid)),
            )
    finally:
        state.close()

    assert report.auto_pulled_ids == [nid]
    assert deleted == []


def test_preflight_remote_delete_requeues_kept_rows_as_first_push(tmp_path: Path) -> None:
    """A kept row (note with unpushed edits, or a dirty non-note file)
    must be detached from the dead Drive id so the drainer re-uploads
    it, instead of pushing into a trashed Drive file and then losing
    the local copy on the next scan."""
    _seed_creds(tmp_path)
    nid = new_id()
    p = tmp_path / f"{nid}.md"
    p.write_text("unpushed edit", encoding="utf-8")
    state = SyncStateStore(tmp_path)
    deleted: list[tuple[str, str]] = []
    trashed: list[str] = []
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=nid,
                drive_file_id="DRIVE-NOTE",
                last_known_etag="rev-1",
                last_synced_at="2030-01-01T00:00:00Z",
                dirty=True,
            )
        )
        state.upsert_file_state(
            FileState(
                entity_type=CARD_ENTITY_TYPE,
                entity_id="01CARD.json",
                drive_file_id="DRIVE-CARD",
                last_known_etag="rev-1",
                last_synced_at="2026-06-01T00:00:00Z",
                dirty=True,
            )
        )
        with patch(
            "knowlet.core.sync.preflight._maybe_heartbeat_pass",
            return_value=_PagedListService([{"files": []}]),
        ):
            preflight_scan(
                vault_root=tmp_path,
                state_store=state,
                note_meta_lookup=lambda _id: None,
                note_path_lookup=lambda _id: p,
                auto_pull_service_factory=lambda: MagicMock(),
                trash_local_for_drive_deleted=trashed.append,
                delete_local_vault_file_for_drive_deleted=lambda et, eid: deleted.append((et, eid)),
            )
        note_row = state.get_file_state("note", nid)
        card_row = state.get_file_state(CARD_ENTITY_TYPE, "01CARD.json")
    finally:
        state.close()

    assert trashed == [] and deleted == []
    assert p.read_text(encoding="utf-8") == "unpushed edit"
    for row in (note_row, card_row):
        assert row is not None
        assert row.drive_file_id is None
        assert row.dirty is True


def test_preflight_pass_b_skips_duplicate_copy_of_tracked_entity(tmp_path: Path) -> None:
    """An untracked Drive file whose name maps to an already-tracked
    note (orphan of a first push whose response was lost) must not be
    materialized over the local note."""
    from knowlet.core.sync.push import drive_appdata_name

    _seed_creds(tmp_path)
    nid_bound = new_id()
    nid_pending = new_id()
    nid_new = new_id()
    state = SyncStateStore(tmp_path)
    materialized: list[str] = []
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=nid_bound,
                drive_file_id="DRIVE-REAL",
                last_known_etag="rev-1",
                last_synced_at="2030-01-01T00:00:00Z",
                dirty=False,
            )
        )
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=nid_pending,
                drive_file_id=None,
                last_known_etag=None,
                last_synced_at=None,
                dirty=True,
            )
        )

        def _entry(fid: str, nid: str) -> dict:
            return {
                "id": fid,
                "name": drive_appdata_name("note", f"{nid}.md", vault_root=tmp_path),
                "headRevisionId": "rev-1",
            }

        listing = {
            "files": [
                _entry("DRIVE-REAL", nid_bound),
                _entry("DRIVE-ORPHAN", nid_bound),
                _entry("DRIVE-LOST-RESPONSE", nid_pending),
                _entry("DRIVE-NEW", nid_new),
            ]
        }
        with patch(
            "knowlet.core.sync.preflight._maybe_heartbeat_pass",
            return_value=_PagedListService([listing]),
        ):
            report = preflight_scan(
                vault_root=tmp_path,
                state_store=state,
                note_meta_lookup=lambda _id: None,
                note_path_lookup=lambda _id: None,
                auto_pull_service_factory=lambda: MagicMock(),
                materialize_drive_file=lambda fid, _brief: materialized.append(fid) or fid,
            )
    finally:
        state.close()

    assert materialized == ["DRIVE-NEW"]
    assert report.cloned_from_drive_ids == ["DRIVE-NEW"]


# ------------------------------------------------------------------
# remote-deleted non-note files go to the vault trash, never unlink
# ------------------------------------------------------------------


def test_trash_local_vault_file_for_drive_deleted_moves_into_trash(tmp_path: Path) -> None:
    from knowlet.core.sync.local_trash import trash_local_vault_file_for_drive_deleted

    vault = Vault(tmp_path)
    vault.init_layout()
    card = vault.cards_dir / "01CARD.json"
    vault.attachments_dir.mkdir(parents=True, exist_ok=True)
    att = vault.attachments_dir / "01ATT.png"

    card.write_text('{"v": 1}', encoding="utf-8")
    att.write_bytes(b"PNG")
    first = trash_local_vault_file_for_drive_deleted(tmp_path, CARD_ENTITY_TYPE, "01CARD.json")
    att_trashed = trash_local_vault_file_for_drive_deleted(tmp_path, "attachment", "01ATT.png")
    # Same entity recreated + deleted remotely again: must not clobber
    # the first trashed copy.
    card.write_text('{"v": 2}', encoding="utf-8")
    second = trash_local_vault_file_for_drive_deleted(tmp_path, CARD_ENTITY_TYPE, "01CARD.json")

    assert not card.exists() and not att.exists()
    assert first is not None and second is not None and att_trashed is not None
    assert first != second
    trash_root = vault.trash_dir.resolve()
    for p in (first, second, att_trashed):
        assert p.resolve().is_relative_to(trash_root)
    assert first.read_text(encoding="utf-8") == '{"v": 1}'
    assert second.read_text(encoding="utf-8") == '{"v": 2}'
    assert att_trashed.read_bytes() == b"PNG"
    # Not listed as trashed *notes*.
    assert list(vault.iter_trashed_paths()) == []


def test_trash_local_vault_file_for_drive_deleted_rejects_unsafe_ids(tmp_path: Path) -> None:
    from knowlet.core.sync.local_trash import trash_local_vault_file_for_drive_deleted

    vault = Vault(tmp_path)
    vault.init_layout()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"keep")
    assert (
        trash_local_vault_file_for_drive_deleted(tmp_path, "attachment", "../../outside.png")
        is None
    )
    assert (
        trash_local_vault_file_for_drive_deleted(
            tmp_path, CARD_ENTITY_TYPE, "..%2F..%2Foutside.png"
        )
        is None
    )
    assert trash_local_vault_file_for_drive_deleted(tmp_path, "note", "01X") is None
    assert (
        trash_local_vault_file_for_drive_deleted(tmp_path, CARD_ENTITY_TYPE, "missing.json") is None
    )
    assert outside.read_bytes() == b"keep"


# ------------------------------------------------------------------
# preflight Pass A: remote delete vs local unpushed edits
# ------------------------------------------------------------------


def test_preflight_remote_delete_spares_note_with_unpushed_edits(tmp_path: Path) -> None:
    """Device B deleted a note remotely while this device holds
    unpushed edits (dirty flag OR local mtime newer than last sync):
    preflight must keep the local file. A genuinely clean note still
    propagates the deletion (control)."""
    _seed_creds(tmp_path)
    nid_dirty_flag = new_id()
    nid_dirty_mtime = new_id()
    nid_clean = new_id()

    paths: dict[str, Path] = {}
    for nid in (nid_dirty_flag, nid_dirty_mtime, nid_clean):
        p = tmp_path / f"{nid}.md"
        p.write_text(f"body {nid}", encoding="utf-8")
        paths[nid] = p
    past = time.time() - 86400
    os.utime(paths[nid_clean], (past, past))

    state = SyncStateStore(tmp_path)
    trashed: list[str] = []
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=nid_dirty_flag,
                drive_file_id="DRIVE-A",
                last_known_etag="rev-1",
                last_synced_at="2030-01-01T00:00:00Z",
                dirty=True,
            )
        )
        # mtime (now) > last_synced_at (2024) → unpushed local edits.
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=nid_dirty_mtime,
                drive_file_id="DRIVE-B",
                last_known_etag="rev-1",
                last_synced_at="2024-01-01T00:00:00Z",
                dirty=False,
            )
        )
        # mtime (yesterday) < last_synced_at (2030) → clean.
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=nid_clean,
                drive_file_id="DRIVE-C",
                last_known_etag="rev-1",
                last_synced_at="2030-01-01T00:00:00Z",
                dirty=False,
            )
        )
        with (
            patch(
                "knowlet.core.sync.preflight._maybe_heartbeat_pass",
                return_value=_PagedListService([{"files": []}]),
            ),
            patch(
                "knowlet.core.sync.status._drive_service",
                return_value=MagicMock(),
            ),
            patch(
                "knowlet.core.sync.status.get_file_metadata",
                side_effect=ConnectionError("per-note metadata offline"),
            ),
        ):
            report = preflight_scan(
                vault_root=tmp_path,
                state_store=state,
                note_meta_lookup=lambda _id: None,
                note_path_lookup=paths.get,
                auto_pull_service_factory=lambda: MagicMock(),
                trash_local_for_drive_deleted=trashed.append,
            )
    finally:
        state.close()

    assert trashed == [nid_clean]
    assert report.trashed_for_drive_delete_ids == [nid_clean]


# ------------------------------------------------------------------
# drainer: runtime-not-ready must not read as "file deleted"
# ------------------------------------------------------------------


def test_drainer_runtime_not_ready_skips_orphan_sweep(tmp_path: Path) -> None:
    from knowlet.core.sync.drainer import PushDrainer, RuntimeNotReadyError

    _seed_creds(tmp_path)
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="attachment",
                entity_id="01ATT.png",
                drive_file_id="D-ATT",
                last_known_etag="rev-1",
                last_synced_at="2026-06-01T00:00:00Z",
                dirty=False,
            )
        )
    finally:
        state.close()

    def _lookup(_fid: str) -> Path | None:
        raise RuntimeNotReadyError("bootstrap in progress")

    drainer = PushDrainer(
        vault_root=tmp_path,
        note_lookup=lambda _id: None,
        attachment_lookup=_lookup,
    )
    with patch(
        "knowlet.core.sync.drive_client.DriveClient.service",
        return_value=MagicMock(),
    ):
        drainer.tick_once()

    check = SyncStateStore(tmp_path)
    try:
        row = check.get_file_state("attachment", "01ATT.png")
    finally:
        check.close()
    assert row is not None, "attachment row must survive a not-ready tick"
    assert row.delete_intent is None, "must not be marked for Drive hard-delete"


def test_drainer_untracked_sweep_retries_after_runtime_not_ready(tmp_path: Path) -> None:
    from knowlet.core.sync.drainer import PushDrainer, RuntimeNotReadyError

    _seed_creds(tmp_path)
    nid = new_id()
    calls: list[int] = []

    def _sweep() -> list[tuple[str, str]]:
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeNotReadyError("bootstrap in progress")
        return [("note", nid)]

    drainer = PushDrainer(
        vault_root=tmp_path,
        note_lookup=lambda _id: None,
        untracked_sweep=_sweep,
    )
    with patch(
        "knowlet.core.sync.drive_client.DriveClient.service",
        return_value=MagicMock(),
    ):
        drainer.tick_once()  # runtime not ready — must NOT latch
        drainer.tick_once()  # runtime ready — backlog must queue now

    assert len(calls) == 2, "sweep must retry after a not-ready tick"
    check = SyncStateStore(tmp_path)
    try:
        row = check.get_file_state("note", nid)
    finally:
        check.close()
    assert row is not None
    assert row.dirty is True


def test_drainer_runtime_not_ready_keeps_dirty_rows(tmp_path: Path) -> None:
    from knowlet.core.sync.drainer import PushDrainer, RuntimeNotReadyError

    _seed_creds(tmp_path)
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="attachment",
                entity_id="01ATT.png",
                drive_file_id=None,
                last_known_etag=None,
                last_synced_at=None,
                dirty=True,
            )
        )
        state.upsert_file_state(
            FileState(
                entity_type=CARD_ENTITY_TYPE,
                entity_id="01CARD.json",
                drive_file_id=None,
                last_known_etag=None,
                last_synced_at=None,
                dirty=True,
            )
        )
    finally:
        state.close()

    def _not_ready(*_args: object) -> Path | None:
        raise RuntimeNotReadyError("bootstrap in progress")

    drainer = PushDrainer(
        vault_root=tmp_path,
        note_lookup=lambda _id: None,
        attachment_lookup=_not_ready,
        synced_file_lookup=_not_ready,
    )
    with patch(
        "knowlet.core.sync.drive_client.DriveClient.service",
        return_value=MagicMock(),
    ):
        drainer.tick_once()

    check = SyncStateStore(tmp_path)
    try:
        att = check.get_file_state("attachment", "01ATT.png")
        card = check.get_file_state(CARD_ENTITY_TYPE, "01CARD.json")
    finally:
        check.close()
    assert att is not None and att.dirty is True
    assert card is not None and card.dirty is True


def test_drainer_lookup_none_with_file_on_disk_is_not_an_orphan(tmp_path: Path) -> None:
    """A host that still answers None while bootstrapping (no sentinel)
    must not trigger a permanent Drive delete or drop dirty rows when
    the file is plainly present at its canonical vault path."""
    from knowlet.core.sync.drainer import PushDrainer

    _seed_creds(tmp_path)
    vault = Vault(tmp_path)
    vault.attachments_dir.mkdir(parents=True)
    (vault.attachments_dir / "01ATT.png").write_bytes(b"PNG")
    (vault.attachments_dir / "01NEW.png").write_bytes(b"PNG2")
    vault.cards_dir.mkdir(parents=True)
    (vault.cards_dir / "01CARD.json").write_text("{}", encoding="utf-8")
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="attachment",
                entity_id="01ATT.png",
                drive_file_id="D-ATT",
                last_known_etag="rev-1",
                last_synced_at="2026-06-01T00:00:00Z",
                dirty=False,
            )
        )
        for entity_type, entity_id in (
            ("attachment", "01NEW.png"),
            (CARD_ENTITY_TYPE, "01CARD.json"),
        ):
            state.upsert_file_state(
                FileState(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    drive_file_id=None,
                    last_known_etag=None,
                    last_synced_at=None,
                    dirty=True,
                )
            )
    finally:
        state.close()

    service = MagicMock()
    drainer = PushDrainer(
        vault_root=tmp_path,
        note_lookup=lambda _id: None,
        attachment_lookup=lambda _name: None,
        synced_file_lookup=lambda _et, _eid: None,
    )
    with patch("knowlet.core.sync.drive_client.DriveClient.service", return_value=service):
        drainer.tick_once()

    assert service.files().delete.call_count == 0
    check = SyncStateStore(tmp_path)
    try:
        att = check.get_file_state("attachment", "01ATT.png")
        new_att = check.get_file_state("attachment", "01NEW.png")
        card = check.get_file_state(CARD_ENTITY_TYPE, "01CARD.json")
    finally:
        check.close()
    assert att is not None and att.delete_intent is None
    assert new_att is not None and new_att.dirty is True
    assert card is not None and card.dirty is True


# ------------------------------------------------------------------
# pull: local save landing during the download window must win
# ------------------------------------------------------------------


def test_pull_aborts_when_local_file_changes_during_download(tmp_path: Path) -> None:
    nid = new_id()
    local_path = tmp_path / f"{nid}.md"
    local_path.write_text("version N (pre-pull)", encoding="utf-8")

    store = SyncStateStore(tmp_path)
    try:
        store.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=nid,
                drive_file_id="DRIVE-FID",
                last_known_etag="rev-OLD",
                last_synced_at="2026-06-01T00:00:00Z",
                dirty=False,
            )
        )

        def _download(_service: object, _fid: str) -> bytes:
            # Simulate the autosave endpoint landing mid-download.
            local_path.write_text("version N+1 (autosave during pull)", encoding="utf-8")
            store.upsert_file_state(
                FileState(
                    entity_type="note",
                    entity_id=nid,
                    drive_file_id="DRIVE-FID",
                    last_known_etag="rev-OLD",
                    last_synced_at="2026-06-01T00:00:00Z",
                    dirty=True,
                )
            )
            return b"remote bytes"

        raised = False
        with (
            patch(
                "knowlet.core.sync.pull.get_file_metadata",
                return_value=_meta("rev-NEW"),
            ),
            patch("knowlet.core.sync.pull.download_file", side_effect=_download),
        ):
            try:
                pull_note_to_local(
                    service=MagicMock(),
                    state=store,
                    note_id=nid,
                    local_path=local_path,
                )
            except Exception:
                raised = True

        content = local_path.read_text(encoding="utf-8")
        row = store.get_file_state("note", nid)
    finally:
        store.close()

    assert content == "version N+1 (autosave during pull)", (
        "pull must not overwrite a save that landed during the download"
    )
    assert row is not None and row.dirty is True, (
        "pull must not clear the dirty flag the save endpoint just set"
    )
    assert row.last_known_etag == "rev-OLD", "etag must not advance on an aborted pull"
    assert raised, "pull must signal that it did not apply the remote bytes"


# ------------------------------------------------------------------
# push: a save landing during the upload must keep the row dirty
# ------------------------------------------------------------------


def test_push_note_keeps_dirty_when_file_changes_during_upload(tmp_path: Path) -> None:
    vault, note = _vault_with_note(tmp_path)
    state = SyncStateStore(vault.root)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=note.id,
                drive_file_id="FID-1",
                last_known_etag="rev-OLD",
                last_synced_at="2026-06-01T00:00:00Z",
                dirty=True,
            )
        )

        def _upload(*_args: object, **_kwargs: object) -> DriveFile:
            # Autosave lands while the upload round-trip is in flight.
            assert note.path is not None
            note.path.write_text("version N+1 saved during upload", encoding="utf-8")
            return _meta("rev-NEW", id_="FID-1")

        with patch(
            "knowlet.core.sync.push.update_file_conditional",
            side_effect=_upload,
        ):
            result = push_note(service=object(), state=state, note=note)
        assert isinstance(result, PushResult)
        rec = state.get_file_state("note", note.id)
    finally:
        state.close()

    assert rec is not None
    assert rec.last_known_etag == "rev-NEW"
    assert rec.dirty is True, "a save during the upload window must keep the row queued for push"


def test_push_vault_file_keeps_dirty_when_file_changes_during_upload(
    tmp_path: Path,
) -> None:
    path = tmp_path / "01CARD.json"
    path.write_text('{"v": 1}', encoding="utf-8")
    state = SyncStateStore(tmp_path)
    try:

        def _upload(*_args: object, **_kwargs: object) -> DriveFile:
            path.write_text('{"v": 2, "saved": "during upload"}', encoding="utf-8")
            return _meta("rev-NEW", id_="FID-CARD")

        with patch("knowlet.core.sync.push.upload_new_file", side_effect=_upload):
            push_vault_file(
                service=object(),
                state=state,
                entity_type=CARD_ENTITY_TYPE,
                entity_id="01CARD.json",
                path=path,
            )
        rec = state.get_file_state(CARD_ENTITY_TYPE, "01CARD.json")
    finally:
        state.close()

    assert rec is not None
    assert rec.dirty is True


# ------------------------------------------------------------------
# resolve_use_remote: back up the local bytes it discards
# ------------------------------------------------------------------


def test_resolve_use_remote_backs_up_local_before_overwrite(tmp_path: Path) -> None:
    vault, note = _vault_with_note(tmp_path)
    assert note.path is not None
    local_before = note.path.read_bytes()
    state = SyncStateStore(vault.root)
    try:
        conflict = ConflictReport(
            entity_type="note",
            entity_id=note.id,
            drive_file_id="FID-1",
            expected_revision="rev-OLD",
            local_bytes=local_before,
            remote_bytes=b"remote wins",
            remote_metadata=_meta("rev-NEW", id_="FID-1"),
        )
        resolve_use_remote(state=state, conflict=conflict, local_path=note.path)
    finally:
        state.close()

    assert note.path.read_bytes() == b"remote wins"
    backup_dir = vault.root / ".knowlet" / "backups" / "note"
    backups = sorted(backup_dir.glob(f"{note.id}.*")) if backup_dir.exists() else []
    assert backups, (
        "resolve_use_remote must snapshot the local version it overwrites "
        "into .knowlet/backups/ (the CLI tells the user it is there)"
    )
    assert backups[-1].read_bytes() == local_before


# ------------------------------------------------------------------
# first push: adopt / conflict on an existing same-name remote file
# ------------------------------------------------------------------


class _NameListService:
    """files().list() returns the canned file list (used by the
    first-push duplicate guard); everything else is unused because the
    upload/download seams are patched."""

    def __init__(self, files: list[dict]) -> None:
        self._files = files
        self.list_queries: list[dict] = []

    def files(self):
        return self

    def list(self, **kwargs):
        self.list_queries.append(kwargs)
        return self

    def execute(self) -> dict:
        return {"files": self._files}


def test_first_push_adopts_identical_existing_remote_file(tmp_path: Path) -> None:
    """Crash-after-upload retry: a same-name appData file already
    exists with identical bytes → adopt it instead of creating a
    duplicate Drive file."""
    vault, note = _vault_with_note(tmp_path)
    state = SyncStateStore(vault.root)
    try:
        content = note.to_markdown().encode("utf-8")
        from knowlet.core.sync.push import drive_appdata_name

        assert note.path is not None
        name = drive_appdata_name("note", note.path.name, vault_root=vault.root)
        service = _NameListService(
            [
                {
                    "id": "FID-EXIST",
                    "name": name,
                    "mimeType": "text/markdown",
                    "modifiedTime": "2026-06-01T00:00:00Z",
                    "headRevisionId": "rev-exist",
                }
            ]
        )
        upload_mock = MagicMock()
        with (
            patch("knowlet.core.sync.push.upload_new_file", upload_mock),
            patch("knowlet.core.sync.push.download_file", return_value=content),
        ):
            result = push_note(service=service, state=state, note=note)
        rec = state.get_file_state("note", note.id)
    finally:
        state.close()

    upload_mock.assert_not_called()
    assert isinstance(result, PushResult)
    assert result.drive_file.id == "FID-EXIST"
    assert rec is not None
    assert rec.drive_file_id == "FID-EXIST"
    assert rec.last_known_etag == "rev-exist"
    assert rec.dirty is False


def test_first_push_conflicts_on_divergent_existing_remote_file(tmp_path: Path) -> None:
    """Same-name remote file exists but with different bytes (e.g.
    another device pushed first, or local edits after the crashed
    upload): surface a conflict instead of duplicating or clobbering."""
    vault, note = _vault_with_note(tmp_path)
    state = SyncStateStore(vault.root)
    try:
        from knowlet.core.sync.push import drive_appdata_name

        assert note.path is not None
        name = drive_appdata_name("note", note.path.name, vault_root=vault.root)
        service = _NameListService(
            [
                {
                    "id": "FID-EXIST",
                    "name": name,
                    "mimeType": "text/markdown",
                    "modifiedTime": "2026-06-01T00:00:00Z",
                    "headRevisionId": "rev-exist",
                }
            ]
        )
        upload_mock = MagicMock()
        with (
            patch("knowlet.core.sync.push.upload_new_file", upload_mock),
            patch(
                "knowlet.core.sync.push.download_file",
                return_value=b"someone else's bytes",
            ),
        ):
            result = push_note(service=service, state=state, note=note)
        rec = state.get_file_state("note", note.id)
    finally:
        state.close()

    upload_mock.assert_not_called()
    assert isinstance(result, ConflictReport)
    assert result.drive_file_id == "FID-EXIST"
    assert result.remote_bytes == b"someone else's bytes"
    # The row is bound to the existing Drive file (so the merge editor /
    # `sync resolve` can address it) but with a base revision that can
    # never match Drive's head: the next push must conflict again rather
    # than silently overwrite the divergent remote copy.
    from knowlet.core.sync.push import UNKNOWN_BASE_REVISION

    assert rec is not None
    assert rec.drive_file_id == "FID-EXIST"
    assert rec.last_known_etag == UNKNOWN_BASE_REVISION
    assert rec.last_known_etag != "rev-exist"
    assert rec.dirty is True


# ------------------------------------------------------------------
# resolve_keep_both: the sibling copy must get its own note id
# ------------------------------------------------------------------


def test_resolve_keep_both_assigns_fresh_id_to_conflict_copy(tmp_path: Path) -> None:
    vault, note = _vault_with_note(tmp_path)
    assert note.path is not None
    remote_note = Note(id=note.id, title="alpha", body="remote body")
    state = SyncStateStore(vault.root)
    try:
        conflict = ConflictReport(
            entity_type="note",
            entity_id=note.id,
            drive_file_id="FID-1",
            expected_revision="rev-OLD",
            local_bytes=note.path.read_bytes(),
            remote_bytes=remote_note.to_markdown().encode("utf-8"),
            remote_metadata=_meta("rev-NEW", id_="FID-1"),
        )
        copy_path = resolve_keep_both(
            state=state,
            conflict=conflict,
            local_path=note.path,
            device_label="other device",
        )
    finally:
        state.close()

    assert copy_path.exists()
    copy_note = Note.from_file(copy_path)
    assert copy_note.id != note.id, (
        "conflict copy must not share the original note id — duplicate ids "
        "make reindex/push flip-flop between the two files"
    )
    assert copy_note.body.strip() == "remote body"
    # Original untouched.
    assert Note.from_file(note.path).id == note.id


# ------------------------------------------------------------------
# merge_notes: kind + folder must survive a conflict merge
# ------------------------------------------------------------------


def test_merge_notes_preserves_kind_and_folder() -> None:
    from knowlet.core.sync.frontmatter_merge import merge_notes

    mine = Note(
        id=new_id(),
        title="alpha",
        body="mine",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-02T00:00:00Z",
        kind="reference",
        folder="projects/x",
    )
    theirs = Note(
        id=mine.id,
        title="alpha",
        body="theirs",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-03T00:00:00Z",
        kind="reference",
        folder=None,
    )
    merged = merge_notes(mine=mine, theirs=theirs, merged_body="merged")
    assert merged.kind == "reference", "conflict merge must not reset kind"
    assert merged.folder == "projects/x", "conflict merge must not drop the folder hint"


def test_merge_notes_unions_extra_meta_newer_side_wins() -> None:
    from knowlet.core.sync.frontmatter_merge import merge_notes

    mine = Note(
        id=new_id(),
        title="alpha",
        body="mine",
        updated_at="2026-01-02T00:00:00Z",
        extra_meta={"cssclasses": ["wide"], "publish": False},
    )
    theirs = Note(
        id=mine.id,
        title="alpha",
        body="theirs",
        updated_at="2026-01-03T00:00:00Z",
        extra_meta={"publish": True, "rating": 5},
    )
    merged = merge_notes(mine=mine, theirs=theirs, merged_body="merged")
    assert merged.extra_meta == {"cssclasses": ["wide"], "publish": True, "rating": 5}
    assert "rating: 5" in merged.to_markdown()


# ------------------------------------------------------------------
# preflight perf: bulk listing replaces per-note files.get
# ------------------------------------------------------------------


def test_preflight_bulk_listing_avoids_per_note_drive_calls(tmp_path: Path) -> None:
    _seed_creds(tmp_path)
    nid_synced = new_id()
    nid_stale = new_id()
    paths: dict[str, Path] = {}
    for nid in (nid_synced, nid_stale):
        p = tmp_path / f"{nid}.md"
        p.write_text(f"body {nid}", encoding="utf-8")
        past = time.time() - 86400
        os.utime(p, (past, past))
        paths[nid] = p

    listing_page = {
        "files": [
            {"id": "DRIVE-A", "name": "a", "headRevisionId": "rev-1"},
            {"id": "DRIVE-B", "name": "b", "headRevisionId": "rev-2"},
        ]
    }
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=nid_synced,
                drive_file_id="DRIVE-A",
                last_known_etag="rev-1",
                last_synced_at="2030-01-01T00:00:00Z",
                dirty=False,
            )
        )
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=nid_stale,
                drive_file_id="DRIVE-B",
                last_known_etag="rev-1",
                last_synced_at="2030-01-01T00:00:00Z",
                dirty=False,
            )
        )
        per_note_metadata = MagicMock(return_value=_meta("rev-1"))
        per_note_service = MagicMock(return_value=MagicMock())
        with (
            patch(
                "knowlet.core.sync.preflight._maybe_heartbeat_pass",
                return_value=_PagedListService([listing_page]),
            ),
            patch("knowlet.core.sync.status.get_file_metadata", per_note_metadata),
            patch("knowlet.core.sync.status._drive_service", per_note_service),
            patch(
                "knowlet.core.sync.pull.get_file_metadata",
                return_value=_meta("rev-2", id_="DRIVE-B"),
            ),
            patch(
                "knowlet.core.sync.pull.download_file",
                return_value=b"fresh remote body",
            ),
        ):
            report = preflight_scan(
                vault_root=tmp_path,
                state_store=state,
                note_meta_lookup=lambda _id: None,
                note_path_lookup=paths.get,
                auto_pull_service_factory=lambda: MagicMock(),
            )
    finally:
        state.close()

    assert per_note_metadata.call_count == 0, (
        "preflight already holds the bulk head-revision listing; it must "
        "not issue one files.get (plus client/token refresh) per note"
    )
    assert per_note_service.call_count == 0
    assert report.auto_pulled_ids == [nid_stale]
    assert report.synced_count == 2
    assert report.conflicts == []


# ------------------------------------------------------------------
# freshness: all-irrelevant change batches must advance the cursor
# ------------------------------------------------------------------


def test_freshness_up_to_date_advances_cursor(tmp_path: Path) -> None:
    from knowlet.core.sync.changes import DriveChange
    from knowlet.core.sync.freshness import check_sync_freshness

    store = SyncStateStore(tmp_path)
    try:
        store.set_start_page_token("tok-1")
        store.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id="01NOTE",
                drive_file_id="drive-note",
                last_known_etag="rev-2",
                last_synced_at="2026-05-30T00:00:00Z",
                dirty=False,
            )
        )
        changes = [
            # Our own push echoed back: revision already known.
            DriveChange(
                file_id="drive-note",
                removed=False,
                trashed=False,
                file={"name": "01NOTE.md", "headRevisionId": "rev-2"},
            ),
        ]
        with patch(
            "knowlet.core.sync.freshness.list_all_changes",
            return_value=(changes, "tok-2"),
        ):
            report = check_sync_freshness(
                state_store=store,
                client_factory=lambda: MagicMock(),
            )
        token_after = store.start_page_token()
    finally:
        store.close()

    assert report.state == "up_to_date"
    assert token_after == "tok-2", (
        "an all-irrelevant batch is consumed knowledge; leaving the cursor "
        "behind replays the whole backlog on every poll"
    )


# ------------------------------------------------------------------
# CLI push: stable id for frontmatterless imports
# ------------------------------------------------------------------


def test_cli_note_for_push_stable_id_for_frontmatterless_file(tmp_path: Path) -> None:
    from knowlet.cli.sync import _note_for_push

    root = tmp_path / "v"
    root.mkdir()
    vault = Vault(root)
    vault.init_layout()
    imported = vault.notes_dir / "读书笔记.md"
    imported.write_text("# 读书笔记\n\n正文内容。\n", encoding="utf-8")

    first = _note_for_push(vault, imported)
    second = _note_for_push(vault, imported)

    assert first.id == second.id, (
        "a frontmatterless import must not get a fresh ULID per read — "
        "each `knowlet sync push` run would create a new Drive file"
    )
    # The id must have been materialized into the file itself.
    assert f"id: {first.id}" in imported.read_text(encoding="utf-8")


def test_cli_note_for_push_refuses_corrupted_note_without_stable_id(tmp_path: Path) -> None:
    """A corrupted note is never rewritten, so its id is only stable
    when the filename is the id; otherwise it must be skipped rather
    than pushed under a fresh ULID per run."""
    from knowlet.cli.sync import _note_for_push

    root = tmp_path / "v"
    root.mkdir()
    vault = Vault(root)
    vault.init_layout()
    broken = "---\ntitle: [unclosed\n---\nbody\n"
    unanchored = vault.notes_dir / "imported.md"
    unanchored.write_text(broken, encoding="utf-8")
    anchored_id = new_id()
    anchored = vault.notes_dir / f"{anchored_id}.md"
    anchored.write_text(broken, encoding="utf-8")

    assert _note_for_push(vault, unanchored) is None
    assert unanchored.read_text(encoding="utf-8") == broken
    note = _note_for_push(vault, anchored)
    assert note is not None and note.id == anchored_id
    assert anchored.read_text(encoding="utf-8") == broken
