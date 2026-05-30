"""Phase 2 E Slice 5.A — OAuth flow + DriveClient (ADR-0027).

The real OAuth flow needs a browser + Google. We mock at two seams:

- ``InstalledAppFlow.from_client_secrets_file`` / ``run_local_server``
  for the OAuth itself.
- ``googleapiclient.discovery.build`` so ``about().get`` returns a
  fixed identity dict.

Tests verify the state machine: success path persists creds with
captured identity; missing client_secret raises a friendly error;
disconnect path roundtrips.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from knowlet.core.sync import SyncDependenciesMissingError, require_google_libs
from knowlet.core.sync.credentials import SyncCredentials, load_credentials
from knowlet.core.sync.oauth import (
    APPDATA_FOLDER,
    SCOPES,
    ScopeUpgradeRequiredError,
    run_connect_flow,
    verify_scope,
)


def test_scope_uses_drive_appdata() -> None:
    """ADR-0027 §"权威" — drive.appdata is the lock against the
    Drive desktop client mirroring our files back to disk and the
    user editing them via Drive web UI. If a future change tries
    to add drive.file or drive.readonly scopes, this test should
    force the author to update ADR-0027 first."""
    assert SCOPES == ("https://www.googleapis.com/auth/drive.appdata",)
    assert APPDATA_FOLDER == "appDataFolder"


def test_verify_scope_accepts_token_with_required_scope() -> None:
    creds = SyncCredentials(token={"scopes": ["https://www.googleapis.com/auth/drive.appdata"]})
    verify_scope(creds)  # should not raise


def test_verify_scope_raises_when_required_scope_missing() -> None:
    creds = SyncCredentials(token={"scopes": ["https://www.googleapis.com/auth/drive.file"]})
    with pytest.raises(ScopeUpgradeRequiredError) as ei:
        verify_scope(creds)
    assert "drive.appdata" in ei.value.missing[0]


def test_verify_scope_raises_when_token_has_no_scopes() -> None:
    creds = SyncCredentials(token={})
    with pytest.raises(ScopeUpgradeRequiredError):
        verify_scope(creds)


# ----------------------------------------------------- helpers


def _write_fake_client_secrets(path: Path) -> None:
    """The Flow constructor reads + parses this file. We don't go
    further than that in unit tests — `from_client_secrets_file` is
    mocked. We still write a syntactically valid file in case we
    later remove that mock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "x.apps.googleusercontent.com",
                    "project_id": "test-project",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "client_secret": "secret",
                    "redirect_uris": ["http://localhost"],
                }
            }
        ),
        encoding="utf-8",
    )


# ----------------------------------------------------- guards


def test_require_google_libs_passes_when_installed() -> None:
    # We installed the [sync] extra in the test env; should be a no-op.
    require_google_libs()


def test_require_google_libs_raises_when_missing() -> None:
    with (
        patch.dict("sys.modules", {"google.auth": None}),
        pytest.raises(SyncDependenciesMissingError),
    ):
        require_google_libs()


# ----------------------------------------------------- happy path


def test_run_connect_flow_persists_creds_and_identity(tmp_path: Path) -> None:
    cs_path = tmp_path / "client_secret.json"
    _write_fake_client_secrets(cs_path)
    save_to = tmp_path / ".knowlet" / "sync_credentials.json"

    fake_token_json = json.dumps(
        {
            "token": "ACCESS",
            "refresh_token": "REFRESH",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "x.apps.googleusercontent.com",
            "client_secret": "secret",
            "scopes": list(SCOPES),
        }
    )

    fake_creds = MagicMock()
    fake_creds.to_json.return_value = fake_token_json

    fake_flow = MagicMock()
    fake_flow.run_local_server.return_value = fake_creds

    fake_drive = MagicMock()
    fake_drive.about.return_value.get.return_value.execute.return_value = {
        "user": {
            "emailAddress": "alice@example.com",
            "displayName": "Alice",
        }
    }

    with (
        patch(
            "google_auth_oauthlib.flow.InstalledAppFlow.from_client_config",
            return_value=fake_flow,
        ),
        patch("googleapiclient.discovery.build", return_value=fake_drive),
    ):
        result = run_connect_flow(client_secrets_path=cs_path, save_to=save_to, port=0)

    assert result.user_email == "alice@example.com"
    assert result.user_display_name == "Alice"
    assert result.saved_to == save_to
    assert save_to.exists()
    creds = load_credentials(save_to)
    assert creds is not None
    assert creds.user_email == "alice@example.com"
    assert creds.token["token"] == "ACCESS"
    assert creds.token["refresh_token"] == "REFRESH"


# ----------------------------------------------------- missing client_secret


def test_run_connect_flow_falls_through_to_embedded_when_path_missing(
    tmp_path: Path,
) -> None:
    """#115 — with the embedded OAuth client, a non-existent
    client_secrets_path no longer raises; it falls through to
    EMBEDDED_OAUTH_CLIENT. The flow should still attempt to run."""
    save_to = tmp_path / ".knowlet" / "sync_credentials.json"
    fake_creds = MagicMock()
    fake_creds.to_json.return_value = json.dumps(
        {
            "token": "ACCESS",
            "refresh_token": "REFRESH",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "x.apps.googleusercontent.com",
            "client_secret": "secret",
            "scopes": list(SCOPES),
        }
    )
    fake_flow = MagicMock()
    fake_flow.run_local_server.return_value = fake_creds
    fake_drive = MagicMock()
    fake_drive.about.return_value.get.return_value.execute.return_value = {
        "user": {"emailAddress": "bob@example.com", "displayName": "Bob"}
    }
    with (
        patch(
            "google_auth_oauthlib.flow.InstalledAppFlow.from_client_config",
            return_value=fake_flow,
        ) as from_cfg,
        patch("googleapiclient.discovery.build", return_value=fake_drive),
    ):
        result = run_connect_flow(
            client_secrets_path=tmp_path / "nope.json",
            save_to=save_to,
            port=0,
        )
    assert result.user_email == "bob@example.com"
    # Should have been called with the embedded client config.
    cfg_arg = from_cfg.call_args.args[0]
    assert "installed" in cfg_arg
    assert cfg_arg["installed"]["client_id"].startswith("50097533807-")


# ----------------------------------------------------- DriveClient


def test_drive_client_identity_round_trip() -> None:
    from knowlet.core.sync.credentials import SyncCredentials
    from knowlet.core.sync.drive_client import DriveClient

    creds = SyncCredentials(
        user_email="bob@example.com",
        user_display_name="Bob",
        token={
            "token": "ACCESS",
            "refresh_token": "REFRESH",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "x.apps.googleusercontent.com",
            "client_secret": "secret",
            "scopes": list(SCOPES),
        },
    )

    fake_drive = MagicMock()
    fake_drive.about.return_value.get.return_value.execute.return_value = {
        "user": {"emailAddress": "bob@example.com", "displayName": "Bob"}
    }

    with patch("googleapiclient.discovery.build", return_value=fake_drive):
        client = DriveClient(creds)
        ident = client.identity()
        assert ident.email == "bob@example.com"
        assert ident.display_name == "Bob"
