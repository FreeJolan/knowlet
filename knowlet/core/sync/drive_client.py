"""Phase 2 E Slice 5.A — Drive API client (ADR-0027).

Slice 5.A scope is **connect-verification only** — this module wraps
just enough of Drive v3 to answer "are we connected" + "who are we
connected as" without exercising any sync write paths. Future slices
(5.B+) extend it for files.list / files.update with ETag / changes.list.

The wrapper exists so future slices and tests can mock at a single
seam (DriveClient class) rather than reaching into googleapiclient
internals everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from knowlet.core.sync.credentials import SyncCredentials


@dataclass
class DriveIdentity:
    """The minimal "who is this token attached to" payload returned
    by ``DriveClient.identity()``."""

    email: str
    display_name: str | None


class DriveClient:
    """Thin wrapper over the Google Drive v3 discovery client.

    Constructed from a ``SyncCredentials`` bundle. The actual
    googleapiclient resource is built lazily on first use so simple
    "do we have creds" checks (`status` CLI) don't have to import
    the heavy library.
    """

    def __init__(self, credentials: SyncCredentials) -> None:
        self._credentials = credentials
        self._service: Any | None = None

    def _build_service(self) -> Any:
        if self._service is not None:
            return self._service
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:  # pragma: no cover
            from knowlet.core.sync import SyncDependenciesMissingError

            raise SyncDependenciesMissingError(str(exc)) from exc
        from knowlet.core.sync.oauth import credentials_to_google

        google_creds = credentials_to_google(self._credentials)
        # cache_discovery=False — the on-disk discovery cache mostly
        # invites permission warnings on multi-user systems and we
        # don't need it for a small surface.
        self._service = build(
            "drive", "v3", credentials=google_creds, cache_discovery=False
        )
        return self._service

    def identity(self) -> DriveIdentity:
        """Round-trip Drive's ``about().get`` to confirm the token
        still works AND the captured email is fresh. Used by ``sync
        status --verify`` (future) and as a smoke test in 5.A."""
        service = self._build_service()
        about = (
            service.about()
            .get(fields="user(emailAddress,displayName)")
            .execute()
        )
        user = about.get("user", {})
        return DriveIdentity(
            email=user.get("emailAddress") or "(unknown)",
            display_name=user.get("displayName"),
        )
