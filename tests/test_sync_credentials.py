"""Phase 2 E Slice 5.A — sync credentials persistence (ADR-0027).

Covers the on-disk shape, atomic write, perms, and the load/save/
delete contract. Does NOT exercise OAuth flow or Drive API — that's
mocked in test_sync_oauth.py because the real flow needs a browser.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from knowlet.core.sync.credentials import (
    CREDENTIALS_SCHEMA_VERSION,
    SyncCredentials,
    credentials_path,
    delete_credentials,
    load_credentials,
    save_credentials,
)


def test_credentials_path_default(tmp_path: Path) -> None:
    p = credentials_path(tmp_path)
    assert p == tmp_path / ".knowlet" / "sync_credentials.json"


def test_credentials_path_relative_under_vault(tmp_path: Path) -> None:
    p = credentials_path(tmp_path, "custom/sub/cred.json")
    assert p == tmp_path / "custom" / "sub" / "cred.json"


def test_credentials_path_absolute_used_as_is(tmp_path: Path) -> None:
    abs_path = tmp_path / "outside" / "cred.json"
    p = credentials_path(tmp_path, str(abs_path))
    assert p == abs_path


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    target = tmp_path / "creds.json"
    creds = SyncCredentials(
        user_email="alice@example.com",
        user_display_name="Alice",
        token={"access": "x", "refresh": "y", "scopes": ["email"]},
    )
    save_credentials(target, creds)
    loaded = load_credentials(target)
    assert loaded is not None
    assert loaded.user_email == "alice@example.com"
    assert loaded.user_display_name == "Alice"
    assert loaded.token == {"access": "x", "refresh": "y", "scopes": ["email"]}
    assert loaded.schema_version == CREDENTIALS_SCHEMA_VERSION


def test_load_returns_none_when_missing(tmp_path: Path) -> None:
    assert load_credentials(tmp_path / "nope.json") is None


def test_save_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "nested" / "cred.json"
    save_credentials(
        target, SyncCredentials(token={"a": 1})
    )
    assert target.exists()


def test_save_writes_with_owner_only_permissions(tmp_path: Path) -> None:
    """Refresh token is long-lived; treat the file like an SSH key."""
    target = tmp_path / "cred.json"
    save_credentials(target, SyncCredentials(token={"a": 1}))
    mode = stat.S_IMODE(os.stat(target).st_mode)
    # On macOS / Linux we get 0o600. Skip on Windows where chmod is
    # a no-op — the save path's try/except already handles it.
    if os.name == "posix":
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_delete_credentials_returns_true_on_remove(tmp_path: Path) -> None:
    target = tmp_path / "cred.json"
    save_credentials(target, SyncCredentials(token={"a": 1}))
    assert target.exists()
    assert delete_credentials(target) is True
    assert not target.exists()


def test_delete_credentials_returns_false_on_missing(tmp_path: Path) -> None:
    assert delete_credentials(tmp_path / "nope.json") is False


def test_legacy_payload_without_schema_version_defaults_to_v1(
    tmp_path: Path,
) -> None:
    """A hand-edited cred file (or one written by a forgotten earlier
    version) without ``schema_version`` parses as v1. Mirrors the
    Note v1 forward-compat clause of ADR-0018 §1."""
    target = tmp_path / "cred.json"
    target.write_text(
        json.dumps(
            {
                "provider": "google",
                "user_email": "x@example.com",
                "token": {"access": "abc"},
            }
        ),
        encoding="utf-8",
    )
    loaded = load_credentials(target)
    assert loaded is not None
    assert loaded.schema_version == 1
    assert loaded.user_email == "x@example.com"
