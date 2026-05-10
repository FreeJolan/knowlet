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


def test_post_resolve_clears_poller_pending(tmp_path: Path) -> None:
    """After resolve succeeds, the in-memory pending dict for that
    note must be empty — otherwise the banner sticks even though
    the user just dismissed via UI."""
    from knowlet.core.sync.poller import (
        RemoteChangeNotification,
        SyncPoller,
    )

    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    _seed_creds(tmp_path)
    note, drive_id = _seed_synced_note(tmp_path)

    poller = SyncPoller(tmp_path)
    poller._pending[note.id] = RemoteChangeNotification(  # noqa: SLF001
        note_id=note.id,
        drive_file_id=drive_id,
        detected_at="2026-05-10T12:00:00Z",
        new_revision="rev-remote",
        drive_file_name="alpha.md",
        removed=False,
    )
    client.app.state.sync_poller = poller

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
            return_value=_drive_file(revision="rev-mine"),
        ),
    ):
        r = client.post(
            f"/api/sync/conflicts/{note.id}/resolve",
            json={"strategy": "mine"},
        )
    assert r.status_code == 200
    assert poller.pending_notifications() == []
