"""Phase 2 E Slice 5.A — Drive sync foundation (ADR-0027).

This package is the substrate for the opt-in Google Drive sync layer
locked in by ADR-0027. Slice 5.A is **connect-only** — the surfaces
here verify "we can talk to the user's Drive" and persist tokens.
Actual sync (writes through Drive API, ETag-based OCC, change polling,
conflict UI) lands in later slices (5.B onward).

Module map:
- ``credentials`` — token storage + lazy refresh (no Drive calls).
- ``oauth`` — local-server OAuth flow (browser bounce → tokens).
- ``drive_client`` — minimal Drive API wrapper (about().get for
  identity, app folder bootstrap).

Google client libraries (``google-auth``, ``google-auth-oauthlib``,
``google-api-python-client``) are an **optional extra** (``pip install
".[sync]"``) — single-device users don't carry that weight. All
Google imports inside this package are deferred to function bodies
so the module's top-level loads cleanly even when the deps aren't
installed; the CLI wraps such calls in a friendly install hint.
"""

from __future__ import annotations

# Public re-exports — kept narrow on purpose.
from knowlet.core.sync.credentials import (  # noqa: F401
    CREDENTIALS_SCHEMA_VERSION,
    SyncCredentials,
    credentials_path,
    delete_credentials,
    load_credentials,
    save_credentials,
)


class SyncDependenciesMissingError(RuntimeError):
    """Raised when sync code paths are invoked but the Google client
    libraries aren't importable. Wraps the import error so callers
    can render a friendly install hint."""


def require_google_libs() -> None:
    """Import-time gate. Call before any function that needs the
    Google client libs. Raises SyncDependenciesMissingError with a
    clear hint when the optional extra hasn't been installed."""
    try:
        import google.auth  # noqa: F401
        import google_auth_oauthlib.flow  # noqa: F401
        import googleapiclient.discovery  # noqa: F401
    except ImportError as exc:
        raise SyncDependenciesMissingError(
            "Drive sync requires the optional `sync` extra. "
            "Install it with: uv pip install -e \".[sync]\"  "
            f"(missing: {exc.name})"
        ) from exc
