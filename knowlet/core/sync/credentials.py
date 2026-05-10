"""Phase 2 E Slice 5.A — token persistence (ADR-0027).

Stores the user's OAuth refresh + access tokens at
``<vault>/.knowlet/sync_credentials.json`` (path overridable via
``KnowletConfig.sync.token_path``). The shape is JSON to mirror what
the Google client library round-trips through `Credentials.to_json()`,
plus a knowlet schema_version envelope and a captured user identity
(so ``knowlet sync status`` can show the connected email without
calling the network).

This module deliberately does NOT import the Google client libraries.
The credentials object on disk is a plain dict; converting to/from a
``google.oauth2.credentials.Credentials`` happens in the oauth /
drive_client modules where those imports are localized.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Bumped if the on-disk shape changes. v1 is the inaugural format.
CREDENTIALS_SCHEMA_VERSION = 1


@dataclass
class SyncCredentials:
    """The serializable cred bundle. Mirrors Google's Credentials JSON
    keys plus a tiny header (provider, schema_version, captured
    identity)."""

    # --- knowlet header ---
    schema_version: int = CREDENTIALS_SCHEMA_VERSION
    provider: str = "google"
    # Captured at first connect via Drive about().get(). Used by
    # `sync status` so we don't have to hit the network just to show
    # "connected as <email>".
    user_email: str | None = None
    user_display_name: str | None = None

    # --- google credentials payload (passed straight through) ---
    # We store as a flat dict so future refresh-flow can re-hydrate
    # `google.oauth2.credentials.Credentials` via from_authorized_user_info.
    token: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> SyncCredentials:
        d = json.loads(raw)
        return cls(
            schema_version=int(d.get("schema_version") or 1),
            provider=str(d.get("provider") or "google"),
            user_email=d.get("user_email"),
            user_display_name=d.get("user_display_name"),
            token=dict(d.get("token") or {}),
        )


def credentials_path(vault_root: Path, configured: str | None = None) -> Path:
    """Resolve where the cred file lives.

    Resolution order:
      1. Explicit ``configured`` arg (typically ``config.sync.token_path``).
         Absolute paths used as-is; relative paths resolve under vault_root.
      2. Default: ``<vault>/.knowlet/sync_credentials.json``.
    """
    if configured:
        p = Path(configured).expanduser()
        if not p.is_absolute():
            p = vault_root / p
        return p
    return vault_root / ".knowlet" / "sync_credentials.json"


def load_credentials(path: Path) -> SyncCredentials | None:
    """None when nothing is on disk yet. Raises on parse error so the
    caller can surface a clear "credentials file is corrupt — disconnect
    + reconnect" hint."""
    if not path.exists():
        return None
    return SyncCredentials.from_json(path.read_text(encoding="utf-8"))


def save_credentials(path: Path, creds: SyncCredentials) -> None:
    """Atomic write + chmod 600. The token contains a long-lived
    refresh_token; treat it like an SSH key."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(creds.to_json(), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        # Windows / weird FS — best-effort. The atomic rename below
        # still completes; we just couldn't tighten perms.
        pass
    tmp.replace(path)


def delete_credentials(path: Path) -> bool:
    """Used by ``knowlet sync disconnect``. True if a file was
    removed; False if there was nothing to do."""
    if not path.exists():
        return False
    path.unlink()
    return True
