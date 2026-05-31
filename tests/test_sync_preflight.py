"""#107a — preflight scan tests.

Lock the persona behaviors:

- Bob (stale auto-pulled, real conflicts surfaced)
- Carol (single conflict, single-device)
- Alice (no creds → unauthenticated bail)
- Network blip mid-scan (offline section populated)
- Empty vault (no rows → empty report)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from knowlet.core.note import new_id
from knowlet.core.sync.credentials import (
    SyncCredentials,
    credentials_path,
    save_credentials,
)
from knowlet.core.sync.files import DriveFile
from knowlet.core.sync.oauth import SCOPES
from knowlet.core.sync.preflight import preflight_scan
from knowlet.core.sync.push import RAW_INFO_ENTITY_TYPE, drive_appdata_name
from knowlet.core.sync.state import FileState, SyncStateStore


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


def _meta(rev: str) -> DriveFile:
    return DriveFile(
        id="DRIVE-FID",
        name="alpha.md",
        mime_type="text/markdown",
        modified_time="2026-05-11T12:00:00Z",
        head_revision_id=rev,
    )


def test_empty_vault_returns_empty_report(tmp_path: Path) -> None:
    state = SyncStateStore(tmp_path)
    try:
        report = preflight_scan(
            vault_root=tmp_path,
            state_store=state,
            note_meta_lookup=lambda _id: None,
            note_path_lookup=lambda _id: None,
            auto_pull_service_factory=lambda: None,
        )
    finally:
        state.close()
    assert report.scanned == 0
    assert report.conflicts == []
    assert report.offline == []
    assert report.unauthenticated is False


def test_preflight_auto_pulls_stale_tracked_raw_info_file(tmp_path: Path) -> None:
    state = SyncStateStore(tmp_path)
    materialized: list[tuple[str, DriveFile]] = []
    try:
        state.upsert_file_state(
            FileState(
                entity_type=RAW_INFO_ENTITY_TYPE,
                entity_id="01RAW-item.json",
                drive_file_id="DRIVE-RAW",
                last_known_etag="rev-1",
                last_synced_at="2026-05-30T00:00:00Z",
                dirty=False,
            )
        )
        brief = DriveFile(
            id="DRIVE-RAW",
            name=drive_appdata_name(RAW_INFO_ENTITY_TYPE, "01RAW-item.json"),
            mime_type="application/json",
            modified_time="2026-05-31T00:00:00Z",
            head_revision_id="rev-2",
        )
        with (
            patch(
                "knowlet.core.sync.preflight._maybe_heartbeat_pass",
                return_value=object(),
            ),
            patch(
                "knowlet.core.sync.files.list_appdata_revisions",
                return_value={"DRIVE-RAW": brief},
            ),
        ):
            report = preflight_scan(
                vault_root=tmp_path,
                state_store=state,
                note_meta_lookup=lambda _id: None,
                note_path_lookup=lambda _id: None,
                auto_pull_service_factory=lambda: object(),
                materialize_drive_file=lambda file_id, file: (
                    materialized.append((file_id, file)) or file_id
                ),
            )
    finally:
        state.close()

    assert materialized == [("DRIVE-RAW", brief)]
    assert report.auto_pulled_ids == ["01RAW-item.json"]


def test_preflight_materializes_only_current_vault_remote_additions(
    tmp_path: Path,
) -> None:
    current = tmp_path / "current"
    other = tmp_path / "other"
    current.mkdir()
    other.mkdir()
    state = SyncStateStore(current)
    materialized: list[tuple[str, DriveFile]] = []
    try:
        current_brief = DriveFile(
            id="DRIVE-CURRENT",
            name=drive_appdata_name("note", "01CURRENT.md", vault_root=current),
            mime_type="text/markdown",
            modified_time="2026-05-31T00:00:00Z",
            head_revision_id="rev-current",
        )
        other_brief = DriveFile(
            id="DRIVE-OTHER",
            name=drive_appdata_name("note", "01OTHER.md", vault_root=other),
            mime_type="text/markdown",
            modified_time="2026-05-31T00:00:00Z",
            head_revision_id="rev-other",
        )
        legacy_brief = DriveFile(
            id="DRIVE-LEGACY-FLAT",
            name="01LEGACY.md",
            mime_type="text/markdown",
            modified_time="2026-05-31T00:00:00Z",
            head_revision_id="rev-legacy",
        )
        with (
            patch(
                "knowlet.core.sync.preflight._maybe_heartbeat_pass",
                return_value=object(),
            ),
            patch(
                "knowlet.core.sync.files.list_appdata_revisions",
                return_value={
                    "DRIVE-CURRENT": current_brief,
                    "DRIVE-OTHER": other_brief,
                    "DRIVE-LEGACY-FLAT": legacy_brief,
                },
            ),
        ):
            report = preflight_scan(
                vault_root=current,
                state_store=state,
                note_meta_lookup=lambda _id: None,
                note_path_lookup=lambda _id: None,
                auto_pull_service_factory=lambda: object(),
                materialize_drive_file=lambda file_id, file: (
                    materialized.append((file_id, file)) or file_id
                ),
            )
    finally:
        state.close()

    assert materialized == [("DRIVE-CURRENT", current_brief)]
    assert report.cloned_from_drive_ids == ["DRIVE-CURRENT"]


def test_unauthenticated_short_circuits(tmp_path: Path) -> None:
    """Alice (single device, no Drive creds) must not see a chip.
    The scan returns ``unauthenticated=True`` and stops at the
    first row instead of trying to call Drive."""
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=new_id(),
                drive_file_id="DRIVE-FID",
                last_known_etag="rev-OLD",
                last_synced_at="2024-01-01T00:00:00Z",
                dirty=False,
            )
        )
        report = preflight_scan(
            vault_root=tmp_path,
            state_store=state,
            note_meta_lookup=lambda _id: None,
            note_path_lookup=lambda _id: None,
            auto_pull_service_factory=lambda: None,
        )
    finally:
        state.close()
    assert report.unauthenticated is True


def test_bob_stale_auto_pulled_real_conflict_surfaced(tmp_path: Path) -> None:
    """Bob persona: 2 stale + 1 real conflict. Stale auto-pulls via
    the seam; conflict ends up in the inbox list."""
    _seed_creds(tmp_path)
    nid_clean_a = new_id()
    nid_clean_b = new_id()
    nid_dirty = new_id()

    # Plant local files for the stale ones (clean = mtime in past).
    import os
    import time

    for nid in (nid_clean_a, nid_clean_b):
        p = tmp_path / f"{nid}.md"
        p.write_text(f"local body for {nid}", encoding="utf-8")
        past = time.time() - 86400
        os.utime(p, (past, past))

    # Dirty one — local file mtime in the future relative to last_synced.
    p_dirty = tmp_path / f"{nid_dirty}.md"
    p_dirty.write_text("local edits in flight", encoding="utf-8")
    os.utime(p_dirty, (time.time(), time.time()))

    state = SyncStateStore(tmp_path)
    try:
        for nid in (nid_clean_a, nid_clean_b):
            state.upsert_file_state(
                FileState(
                    entity_type="note",
                    entity_id=nid,
                    drive_file_id=f"DRIVE-{nid}",
                    last_known_etag="rev-OLD",
                    # Future-stamped so the clean local mtime sits
                    # before it → ``_is_local_dirty`` returns False
                    # → status = ``stale`` → auto-pull.
                    last_synced_at="2030-01-01T00:00:00Z",
                    dirty=False,
                )
            )
        # The dirty note keeps a past last_synced_at so the now-ish
        # local mtime reads as edited-after-sync → real conflict.
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=nid_dirty,
                drive_file_id=f"DRIVE-{nid_dirty}",
                last_known_etag="rev-OLD",
                last_synced_at="2024-01-01T00:00:00Z",
                dirty=False,
            )
        )

        # The status path uses status._drive_service for files.get;
        # patch it so the stale + conflict cases evaluate without
        # real network. Pull's metadata + download seams need
        # patching too (auto_pull_service_factory sends service to
        # pull_note_to_local).
        with (
            patch(
                "knowlet.core.sync.status._drive_service",
                return_value=MagicMock(),
            ),
            patch(
                "knowlet.core.sync.status.get_file_metadata",
                return_value=_meta("rev-NEW"),
            ),
            patch(
                "knowlet.core.sync.pull.get_file_metadata",
                return_value=_meta("rev-NEW"),
            ),
            patch(
                "knowlet.core.sync.pull.download_file",
                return_value=b"freshly pulled body",
            ),
        ):
            report = preflight_scan(
                vault_root=tmp_path,
                state_store=state,
                note_meta_lookup=lambda nid: {"title": f"title-{nid[:6]}"},
                note_path_lookup=lambda nid: tmp_path / f"{nid}.md",
                auto_pull_service_factory=lambda: MagicMock(),
            )
    finally:
        state.close()

    assert report.scanned == 3
    assert report.unauthenticated is False
    # 2 auto-pulled (clean local + remote moved).
    assert sorted(report.auto_pulled_ids) == sorted([nid_clean_a, nid_clean_b])
    # 1 real conflict.
    assert len(report.conflicts) == 1
    c = report.conflicts[0]
    assert c.note_id == nid_dirty
    assert c.note_title and "title-" in c.note_title
    assert report.synced_count == 2  # the auto-pulled ones counted as synced
    assert report.offline == []


def test_pull_failure_downgrades_to_offline(tmp_path: Path) -> None:
    """Network blips mid-scan — auto-pull throws → that note shows
    up in the offline section rather than vanishing silently."""
    _seed_creds(tmp_path)
    nid = new_id()
    p = tmp_path / f"{nid}.md"
    p.write_text("clean local body", encoding="utf-8")
    import os
    import time

    past = time.time() - 86400
    os.utime(p, (past, past))

    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=nid,
                drive_file_id="DRIVE-FID",
                last_known_etag="rev-OLD",
                last_synced_at="2030-01-01T00:00:00Z",
                dirty=False,
            )
        )
        with (
            patch(
                "knowlet.core.sync.status._drive_service",
                return_value=MagicMock(),
            ),
            patch(
                "knowlet.core.sync.status.get_file_metadata",
                return_value=_meta("rev-NEW"),
            ),
            patch(
                "knowlet.core.sync.pull.get_file_metadata",
                return_value=_meta("rev-NEW"),
            ),
            patch(
                "knowlet.core.sync.pull.download_file",
                side_effect=ConnectionError("net dropped"),
            ),
        ):
            report = preflight_scan(
                vault_root=tmp_path,
                state_store=state,
                note_meta_lookup=lambda _id: {"title": "alpha"},
                note_path_lookup=lambda _id: p,
                auto_pull_service_factory=lambda: MagicMock(),
            )
    finally:
        state.close()
    assert report.conflicts == []
    assert len(report.offline) == 1
    assert "net dropped" in (report.offline[0].detail or "")
    assert report.auto_pulled_ids == []


def test_offline_status_routed_to_offline_section(tmp_path: Path) -> None:
    """Status compute itself goes ``offline`` (Drive metadata fetch
    raised) — preflight surfaces the row in the offline section
    rather than confusing it with a real conflict."""
    _seed_creds(tmp_path)
    nid = new_id()
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=nid,
                drive_file_id="DRIVE-FID",
                last_known_etag="rev-OLD",
                last_synced_at="2024-01-01T00:00:00Z",
                dirty=False,
            )
        )
        with (
            patch(
                "knowlet.core.sync.status._drive_service",
                return_value=MagicMock(),
            ),
            patch(
                "knowlet.core.sync.status.get_file_metadata",
                side_effect=ConnectionError("dns failed"),
            ),
        ):
            report = preflight_scan(
                vault_root=tmp_path,
                state_store=state,
                note_meta_lookup=lambda _id: {"title": "alpha"},
                note_path_lookup=lambda _id: None,
                auto_pull_service_factory=lambda: MagicMock(),
            )
    finally:
        state.close()
    assert report.conflicts == []
    assert len(report.offline) == 1
    assert "dns failed" in (report.offline[0].detail or "")
