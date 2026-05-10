"""Phase 2 E Slice 5.A — OAuth flow (ADR-0027).

Drives the connect step:
  1. Read the user-provided ``client_secret.json`` (Google Cloud
     Console → APIs & Services → Credentials → OAuth 2.0 Client ID
     → Desktop app).
  2. Spawn a temporary localhost server (``Flow.run_local_server``)
     and open the browser; user grants consent in their normal
     browser session.
  3. Receive the auth code at the loopback redirect, exchange for
     access + refresh tokens.
  4. Call Drive's ``about().get`` to capture the user's email — this
     proves the token works AND gives us something to show in
     ``sync status`` without burning a round trip later.
  5. Persist via ``save_credentials``.

Google client libraries are imported lazily inside ``run_connect_flow``
so the rest of the package stays importable when the optional ``sync``
extra isn't installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from knowlet.core.sync.credentials import (
    SyncCredentials,
    save_credentials,
)

# OAuth scope: read + write the application-created files in the
# user's Drive. We deliberately AVOID drive.readonly / drive (full
# access) — knowlet should only ever see the files it created.
SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/drive.file",
    "openid",
    "email",
    "profile",
)


@dataclass
class ConnectResult:
    """Returned from ``run_connect_flow`` so the caller (CLI / web)
    can render success messaging without knowing the cred shape."""

    user_email: str
    user_display_name: str | None
    saved_to: Path


class ClientSecretsMissingError(FileNotFoundError):
    """The user hasn't pointed us at a client_secret.json yet."""


class OAuthFlowError(RuntimeError):
    """Wrap any non-success outcome from the OAuth flow itself
    (browser closed, network error during code exchange, etc.)."""


def run_connect_flow(
    *,
    client_secrets_path: Path,
    save_to: Path,
    port: int = 0,
) -> ConnectResult:
    """Block until the user finishes consent in the browser, then
    persist tokens and return the captured identity.

    ``port=0`` lets the OS pick a free loopback port — required when
    the configured Google OAuth client lists multiple
    ``http://localhost:*`` redirects, or when the user wants to
    avoid binding 8080 specifically.
    """
    if not client_secrets_path.exists():
        raise ClientSecretsMissingError(
            f"client_secret.json not found at {client_secrets_path}. "
            "Download from Google Cloud Console → APIs & Services → "
            "Credentials → OAuth 2.0 Client ID (Desktop app) and "
            "set sync.client_secrets_path to its path."
        )

    # Lazy imports — the Google libs are an optional extra (ADR-0027
    # §pyproject.sync). Caller should have already passed
    # require_google_libs() before getting here, but we re-check at
    # the actual import to be defensive.
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover — covered by package-init gate
        from knowlet.core.sync import SyncDependenciesMissingError

        raise SyncDependenciesMissingError(str(exc)) from exc

    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_secrets_path), scopes=list(SCOPES)
    )
    try:
        # `run_local_server` opens the browser, spins a tiny HTTP
        # server on the chosen loopback port, blocks until the
        # callback arrives, then exchanges the code for tokens.
        # `open_browser=True` is its default; we keep it explicit.
        creds = flow.run_local_server(port=port, open_browser=True)
    except Exception as exc:
        raise OAuthFlowError(f"OAuth flow failed: {exc}") from exc

    # Capture identity. about().get with fields=user(emailAddress, displayName)
    # is the smallest call that proves the token works.
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    about = (
        drive.about()
        .get(fields="user(emailAddress,displayName)")
        .execute()
    )
    user_email = about.get("user", {}).get("emailAddress") or "(unknown)"
    user_display_name = about.get("user", {}).get("displayName")

    # Persist. `creds.to_json()` returns a JSON STRING; we want a dict
    # in our envelope so future refresh paths don't double-stringify.
    import json as _json

    bundle = SyncCredentials(
        user_email=user_email,
        user_display_name=user_display_name,
        token=_json.loads(creds.to_json()),
    )
    save_credentials(save_to, bundle)
    return ConnectResult(
        user_email=user_email,
        user_display_name=user_display_name,
        saved_to=save_to,
    )


def credentials_to_google(creds: SyncCredentials) -> object:
    """Re-hydrate a stored bundle into a
    ``google.oauth2.credentials.Credentials`` so callers can hand it
    to googleapiclient. Returns ``object`` in the type stub here to
    avoid forcing google-auth onto every importer.
    """
    try:
        from google.oauth2.credentials import Credentials
    except ImportError as exc:  # pragma: no cover
        from knowlet.core.sync import SyncDependenciesMissingError

        raise SyncDependenciesMissingError(str(exc)) from exc
    # google-auth doesn't ship typed stubs (see pyproject mypy
    # overrides); the boundary is intentionally untyped.
    return Credentials.from_authorized_user_info(  # type: ignore[no-untyped-call]
        creds.token, list(SCOPES)
    )
