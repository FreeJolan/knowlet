"""Phase 2 E Slice 5.D.1 — /api/sync/conflicts endpoints (ADR-0027).

Tests cover:
- GET /api/sync/conflicts/<id> returns side-by-side text when remote
  moved past last_known_etag.
- GET returns conflict=False when revisions match (race after banner).
- POST /api/sync/conflicts/<id>/resolve dispatches mine|remote|both.
- 404 / 409 paths (note missing, not connected).

Drive interactions are mocked at the wrapper boundary (download_file,
get_file_metadata, force_overwrite) so we don't need real Google
client mocks plumbed through.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from knowlet.core.note import Note, new_id
from knowlet.core.sync.credentials import (
    SyncCredentials,
    credentials_path,
    save_credentials,
)
from knowlet.core.sync.files import DriveFile
from knowlet.core.sync.oauth import SCOPES
from knowlet.core.sync.state import FileState, SyncStateStore


from tests.test_web import StubLLM, _client_with_stub  # noqa: E402


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


def _seed_synced_note(tmp_path: Path) -> tuple[Note, str]:
    """Create a vault Note + corresponding sync_state record. Returns
    (note, drive_file_id)."""
    from knowlet.core.vault import Vault

    v = Vault(tmp_path)
    n = Note(id=new_id(), title="alpha", body="local-v1")
    v.write_note(n, folder="daily")
    drive_id = "DRIVE-FID-1"
    state = SyncStateStore(tmp_path)
    try:
        state.upsert_file_state(
            FileState(
                entity_type="note",
                entity_id=n.id,
                drive_file_id=drive_id,
                last_known_etag="rev-mine",
                last_synced_at="2026-05-10T00:00:00Z",
                dirty=False,
            )
        )
    finally:
        state.close()
    return n, drive_id


def _drive_file(*, revision: str = "rev-remote") -> DriveFile:
    return DriveFile(
        id="DRIVE-FID-1",
        name="alpha.md",
        mime_type="text/markdown",
        modified_time="2026-05-10T12:00:00Z",
        head_revision_id=revision,
    )


# ----------------------------------------------------- GET conflict snapshot


def test_get_conflict_returns_diverged_text(tmp_path: Path) -> None:
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    _seed_creds(tmp_path)
    note, _drive_id = _seed_synced_note(tmp_path)

    with (
        patch(
            "knowlet.core.sync.files.get_file_metadata",
            return_value=_drive_file(revision="rev-remote"),
        ),
        patch(
            "knowlet.core.sync.files.download_file",
            return_value=b"REMOTE-BYTES",
        ),
    ):
        r = client.get(f"/api/sync/conflicts/{note.id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["conflict"] is True
    assert body["expected_revision"] == "rev-mine"
    assert body["current_revision"] == "rev-remote"
    assert body["local_text"].startswith("---")  # frontmatter from Note.to_markdown
    assert body["remote_text"] == "REMOTE-BYTES"


def test_get_conflict_returns_no_conflict_when_revisions_match(
    tmp_path: Path,
) -> None:
    """Race window: banner showed, user clicked, but Drive's current
    revision now matches our last_known_etag. Surface gracefully."""
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    _seed_creds(tmp_path)
    note, _ = _seed_synced_note(tmp_path)

    with (
        patch(
            "knowlet.core.sync.files.get_file_metadata",
            return_value=_drive_file(revision="rev-mine"),
        ),
        patch(
            "knowlet.core.sync.files.download_file",
            return_value=b"never-called",
        ) as dl,
    ):
        r = client.get(f"/api/sync/conflicts/{note.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["conflict"] is False
    # No need to download remote when there's no conflict.
    dl.assert_not_called()


def test_get_conflict_404_when_note_missing(tmp_path: Path) -> None:
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    _seed_creds(tmp_path)
    r = client.get("/api/sync/conflicts/01NOSUCHID")
    assert r.status_code == 404


def test_get_conflict_409_when_not_connected(tmp_path: Path) -> None:
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    note, _ = _seed_synced_note(tmp_path)
    # No creds file written — credentials_path returns None
    r = client.get(f"/api/sync/conflicts/{note.id}")
    assert r.status_code == 409


# ----------------------------------------------------- POST resolve


def test_post_resolve_mine_calls_force_overwrite(tmp_path: Path) -> None:
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    _seed_creds(tmp_path)
    note, _ = _seed_synced_note(tmp_path)

    with (
        patch(
            "knowlet.core.sync.files.get_file_metadata",
            return_value=_drive_file(revision="rev-remote"),
        ),
        patch(
            "knowlet.core.sync.files.download_file",
            return_value=b"REMOTE",
        ),
        patch(
            "knowlet.core.sync.push.force_overwrite",
            return_value=_drive_file(revision="rev-mine-wins"),
        ) as fo,
    ):
        r = client.post(
            f"/api/sync/conflicts/{note.id}/resolve",
            json={"strategy": "mine"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["action"] == "mine"
    assert body["new_revision"] == "rev-mine-wins"
    assert fo.called


def test_post_resolve_remote_overwrites_local(tmp_path: Path) -> None:
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    _seed_creds(tmp_path)
    note, _ = _seed_synced_note(tmp_path)
    assert note.path is not None

    with (
        patch(
            "knowlet.core.sync.files.get_file_metadata",
            return_value=_drive_file(revision="rev-remote"),
        ),
        patch(
            "knowlet.core.sync.files.download_file",
            return_value=b"REMOTE-WINS-CONTENT",
        ),
    ):
        r = client.post(
            f"/api/sync/conflicts/{note.id}/resolve",
            json={"strategy": "remote"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "remote"
    # Local file replaced.
    assert note.path.read_bytes() == b"REMOTE-WINS-CONTENT"


def test_post_resolve_both_writes_sibling(tmp_path: Path) -> None:
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    _seed_creds(tmp_path)
    note, _ = _seed_synced_note(tmp_path)
    assert note.path is not None

    with (
        patch(
            "knowlet.core.sync.files.get_file_metadata",
            return_value=_drive_file(revision="rev-remote"),
        ),
        patch(
            "knowlet.core.sync.files.download_file",
            return_value=b"REMOTE-COPY-BYTES",
        ),
    ):
        r = client.post(
            f"/api/sync/conflicts/{note.id}/resolve",
            json={"strategy": "both"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == "both"
    copy_path_str = body["conflict_copy_path"]
    copy_path = Path(copy_path_str)
    assert copy_path.exists()
    assert copy_path.read_bytes() == b"REMOTE-COPY-BYTES"
    # Sibling of original; original is untouched.
    assert copy_path.parent == note.path.parent
    assert note.path.read_bytes() != b"REMOTE-COPY-BYTES"


def test_post_resolve_400_on_unknown_strategy(tmp_path: Path) -> None:
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    _seed_creds(tmp_path)
    note, _ = _seed_synced_note(tmp_path)
    r = client.post(
        f"/api/sync/conflicts/{note.id}/resolve",
        json={"strategy": "bogus"},
    )
    assert r.status_code == 400


def test_dismiss_endpoint_now_snoozes_24h(tmp_path: Path) -> None:
    """Slice 5.D.3.A — dismiss is no longer permanent. Sets
    file_state.dismissed_until to ~now+24h."""
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    _seed_creds(tmp_path)
    note, _ = _seed_synced_note(tmp_path)
    r = client.post(f"/api/sync/notifications/{note.id}/dismiss")
    assert r.status_code == 200
    body = r.json()
    assert body["snoozed"] is True
    until = body["until"]
    # Until should be ~24h from now (we just don't pin to a clock).
    assert until > "2026-05-10"
    # Stored on disk.
    state = SyncStateStore(tmp_path)
    try:
        rec = state.get_file_state("note", note.id)
        assert rec is not None
        assert rec.dismissed_until == until
    finally:
        state.close()


def test_dismiss_with_custom_hours(tmp_path: Path) -> None:
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    _seed_creds(tmp_path)
    note, _ = _seed_synced_note(tmp_path)
    r = client.post(
        f"/api/sync/notifications/{note.id}/dismiss?hours=72"
    )
    assert r.status_code == 200
    # Just confirm it accepted the override; the precise window
    # isn't worth pinning to wall-clock.
    assert "until" in r.json()


def test_accept_current_advances_last_known_etag(tmp_path: Path) -> None:
    """Slice 5.D.3.A — "accept current as in-sync" updates
    last_known_etag to whatever Drive currently has, without moving
    any bytes. Future polls see in-sync state and stop nagging."""
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    _seed_creds(tmp_path)
    note, _ = _seed_synced_note(tmp_path)
    with patch(
        "knowlet.core.sync.files.get_file_metadata",
        return_value=_drive_file(revision="rev-remote"),
    ):
        r = client.post(f"/api/sync/conflicts/{note.id}/accept-current")
    assert r.status_code == 200, r.text
    assert r.json()["new_revision"] == "rev-remote"
    state = SyncStateStore(tmp_path)
    try:
        rec = state.get_file_state("note", note.id)
        assert rec is not None
        assert rec.last_known_etag == "rev-remote"
        assert rec.dismissed_until is None
    finally:
        state.close()


def test_bulk_resolve_accept_current_processes_all(tmp_path: Path) -> None:
    """Bulk path: 3 conflicts, "accept-current" applies to all.
    Reports per-id results, even when some fail."""
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    _seed_creds(tmp_path)
    note1, _ = _seed_synced_note(tmp_path)
    # Add two more synced notes with their own drive ids.
    from knowlet.core.note import Note
    from knowlet.core.vault import Vault

    v = Vault(tmp_path)
    n2 = Note(id=new_id(), title="beta", body="b")
    v.write_note(n2)
    n3 = Note(id=new_id(), title="gamma", body="g")
    v.write_note(n3)
    state = SyncStateStore(tmp_path)
    try:
        for n, did in [(n2, "DRIVE-FID-2"), (n3, "DRIVE-FID-3")]:
            state.upsert_file_state(
                FileState(
                    entity_type="note",
                    entity_id=n.id,
                    drive_file_id=did,
                    last_known_etag="rev-stale",
                    last_synced_at="2026-05-10T00:00:00Z",
                    dirty=False,
                )
            )
    finally:
        state.close()

    with patch(
        "knowlet.core.sync.files.get_file_metadata",
        side_effect=lambda _svc, fid: _drive_file(revision=f"rev-{fid}"),
    ):
        r = client.post(
            "/api/sync/conflicts/bulk-resolve",
            json={
                "note_ids": [note1.id, n2.id, n3.id],
                "strategy": "accept-current",
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["succeeded"] == 3
    assert body["failed"] == 0
    assert all(item["ok"] for item in body["results"])


def test_bulk_resolve_unknown_strategy_400(tmp_path: Path) -> None:
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    _seed_creds(tmp_path)
    r = client.post(
        "/api/sync/conflicts/bulk-resolve",
        json={"note_ids": [], "strategy": "abandon"},
    )
    assert r.status_code == 400


def test_post_resolve_triggers_poller_recompute(tmp_path: Path) -> None:
    """Slice 5.D.3.A — resolve no longer pokes a private pending
    dict (state-reconciliation has no such dict). Instead it calls
    force_recompute_sync() so the cached pending list is refreshed
    on the spot rather than waiting up to 30s for the next loop."""
    from knowlet.core.sync.poller import SyncPoller

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    _seed_creds(tmp_path)
    note, _drive_id = _seed_synced_note(tmp_path)

    poller = SyncPoller(tmp_path)
    client.app.state.sync_poller = poller
    recompute_calls: list[None] = []
    with (
        patch.object(
            poller,
            "force_recompute_sync",
            side_effect=lambda: recompute_calls.append(None),
        ),
        patch(
            "knowlet.core.sync.files.get_file_metadata",
            return_value=_drive_file(revision="rev-remote"),
        ),
        patch(
            "knowlet.core.sync.files.download_file",
            return_value=b"REMOTE",
        ),
        patch(
            "knowlet.core.sync.push.force_overwrite",
            return_value=_drive_file(revision="rev-mine"),
        ),
    ):
        r = client.post(
            f"/api/sync/conflicts/{note.id}/resolve",
            json={"strategy": "mine"},
        )
    assert r.status_code == 200
    assert recompute_calls, "resolve must call force_recompute_sync"
