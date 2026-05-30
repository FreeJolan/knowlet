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

# OAuth scope: knowlet's hidden per-app folder ONLY. ADR-0027 §"权威"
# requires the remote to be the canonical truth and forbids any path
# that lets a second authority (Drive desktop client, user editing
# in Drive web UI) produce conflicting writes. The drive.appdata
# scope is exactly that lock:
#
# - The "appDataFolder" is invisible to the user in Drive web UI
#   AND not mirrored by Drive desktop client. So the user cannot
#   accidentally edit a synced file outside knowlet.
# - File IDs / ETags / Changes API still work just like drive.file.
# - Storage limit is per-app (~10 GB historically, plenty for note
#   text), and the data still counts against the user's Drive
#   capacity (ADR-0013 §"用户拥有" stays satisfied — they own it).
# - Drive's native version history is still available via API for
#   any of our app's files.
#
# We deliberately do NOT also request email / profile / openid:
# Google internally expands those into the full
# `https://www.googleapis.com/auth/userinfo.*` URLs, oauthlib's
# strict-scope-match check sees the literal mismatch, and the flow
# raises mid-handshake. Drive's own ``about().get`` returns user
# emailAddress + displayName under any drive scope, so we don't
# need the OpenID identity scopes for what 5.A captures.
# Embedded OAuth client (#115). Per Google's Desktop OAuth docs and
# RFC 8252, the ``client_secret`` for native apps is NOT actually
# confidential — Google explicitly says it can be distributed with
# the binary. Risks are quota abuse + brand spoofing, not user data.
# See the conversation around tasks #113/#115 for the full analysis.
#
# Override paths, in priority order:
#   1. ``$KNOWLET_OAUTH_CLIENT_JSON`` env var — full JSON inline.
#      Release builds inject the production knowlet client this way.
#   2. ``sync.client_secrets_path`` config — points at a file on
#      disk. Advanced users who want to scope the OAuth client to
#      their own Google Cloud project use this.
#   3. Fallback: the constant below — the dogfood-era client tied
#      to FreeJolan's personal Cloud Console project.
#
# IMPORTANT: rotate ``EMBEDDED_OAUTH_CLIENT`` to a production
# knowlet-branded OAuth client before this repo goes public.
EMBEDDED_OAUTH_CLIENT: dict[str, dict[str, object]] = {
    "installed": {
        "client_id": "50097533807-nihf6pus7frvi0e2gm6g8v98fhakssvf.apps.googleusercontent.com",
        "project_id": "knowlet-495706",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": "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",
        "redirect_uris": ["http://localhost"],
    }
}


def resolve_client_config(
    client_secrets_path: Path | None = None,
) -> dict[str, dict[str, object]]:
    """Resolve the OAuth client config payload to hand to
    ``InstalledAppFlow.from_client_config``. Three sources, first
    non-None wins:

    1. ``KNOWLET_OAUTH_CLIENT_JSON`` env var (release-build override).
    2. ``client_secrets_path`` file on disk (advanced user override).
    3. ``EMBEDDED_OAUTH_CLIENT`` constant (default for everyone).
    """
    import json
    import os
    from pathlib import Path

    env_blob = os.environ.get("KNOWLET_OAUTH_CLIENT_JSON")
    if env_blob:
        try:
            parsed: dict[str, dict[str, object]] = json.loads(env_blob)
            return parsed
        except ValueError:
            # Fall through to the next source rather than crash —
            # a malformed env var shouldn't lock the user out.
            pass
    if client_secrets_path is not None and Path(client_secrets_path).exists():
        with Path(client_secrets_path).open("r", encoding="utf-8") as f:
            parsed_file: dict[str, dict[str, object]] = json.load(f)
            return parsed_file
    return EMBEDDED_OAUTH_CLIENT


SCOPES: tuple[str, ...] = ("https://www.googleapis.com/auth/drive.appdata",)


# The "magic" parent ID for Google's per-app hidden folder. Used as
# `parents=[APPDATA_FOLDER]` on file creation and
# `spaces="appDataFolder"` on list / changes calls.
APPDATA_FOLDER = "appDataFolder"


class ScopeUpgradeRequiredError(RuntimeError):
    """Raised when the user's stored token lacks the scopes the
    current build needs. Caused by a scope upgrade between knowlet
    versions (e.g. Slice 5.C → 5.C.1's drive.file → drive.appdata
    transition). Caller renders the "disconnect + reconnect" hint."""

    def __init__(self, *, missing: list[str]) -> None:
        self.missing = list(missing)
        super().__init__(
            "Drive sync needs additional scopes that your stored "
            "token doesn't have: " + ", ".join(missing) + ". Run "
            "`knowlet sync disconnect` then `knowlet sync connect` "
            "to re-authorize."
        )


def verify_scope(creds: object) -> None:
    """Compare the stored token's scopes against the build's SCOPES.
    Raises ScopeUpgradeRequiredError when a required scope isn't
    present — typical after upgrading knowlet across a slice that
    changed scopes. ``creds`` is duck-typed to a SyncCredentials."""
    token = getattr(creds, "token", None) or {}
    stored = set(token.get("scopes") or [])
    required = set(SCOPES)
    missing = required - stored
    if missing:
        raise ScopeUpgradeRequiredError(missing=sorted(missing))


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
    client_secrets_path: Path | None = None,
    save_to: Path,
    port: int = 0,
    timeout_seconds: int = 300,
) -> ConnectResult:
    """Block until the user finishes consent in the browser, then
    persist tokens and return the captured identity.

    ``client_secrets_path`` is optional (#115) — when omitted, the
    embedded OAuth client is used. Pass a path to override with an
    on-disk client_secret.json (advanced users running their own
    Cloud Console project).

    ``port=0`` lets the OS pick a free loopback port — required when
    the configured Google OAuth client lists multiple
    ``http://localhost:*`` redirects, or when the user wants to
    avoid binding 8080 specifically.
    """
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

    # #115 — resolve OAuth client config via the three-tier override
    # chain. The passed-in path is only ONE of three sources;
    # ``resolve_client_config`` also checks env var + embedded.
    client_config = resolve_client_config(client_secrets_path)
    flow = InstalledAppFlow.from_client_config(client_config, scopes=list(SCOPES))
    try:
        # `run_local_server` opens the browser, spins a tiny HTTP
        # server on the chosen loopback port, blocks until the
        # callback arrives, then exchanges the code for tokens.
        # `open_browser=True` is its default; we keep it explicit.
        # ``timeout_seconds`` makes the loopback server abort if the
        # user never finishes consent (typically closes the tab) —
        # without this the call blocks the background thread forever
        # and the UI shows a perpetual "Opening browser…" spinner.
        creds = flow.run_local_server(
            port=port,
            open_browser=True,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:
        raise OAuthFlowError(f"OAuth flow failed: {exc}") from exc

    # Capture identity. about().get with fields=user(emailAddress, displayName)
    # is the smallest call that proves the token works.
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    about = drive.about().get(fields="user(emailAddress,displayName)").execute()
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
