"""Phase 2 E Slice 5.B — Drive Changes API wrapper (ADR-0027).

Wraps just enough of `service.changes()` to power "what's new on
Drive since I last looked?". Slice 5.B uses this read-only — the
results are printed; nothing applied yet. Slice 5.C+ will branch on
results to refresh local caches / detect remote-newer-than-local
conflicts.

The reason this lives behind a thin wrapper rather than calling
``drive.changes().list().execute()`` directly is two-fold:
1. The Google client lib is an optional extra; lazy imports stay
   localized here.
2. Tests mock at the wrapper boundary instead of monkey-patching
   ``googleapiclient.discovery``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from knowlet.core.sync.drive_client import DriveClient


@dataclass(frozen=True)
class DriveChange:
    """One change row from Drive's perspective.

    `removed` / `trashed` mean the file is gone from the user's
    Drive (intentional or via Trash). `file` is None when removed/
    trashed; otherwise it's the latest metadata snapshot."""

    file_id: str
    removed: bool
    trashed: bool
    file: dict[str, Any] | None  # name, modifiedTime, mimeType, etc.


@dataclass
class ChangesPage:
    """One page of changes — what `changes.list` returns. The
    sync state cache stores the new ``next_token`` for the next
    pull. ``new_start_page_token`` is set when we've reached the
    end of the change stream; future polls should use IT as their
    starting token."""

    changes: list[DriveChange]
    next_token: str | None  # None when we've reached the tail
    new_start_page_token: str | None  # set on last page only


def get_initial_start_page_token(client: DriveClient) -> str:
    """First-time bootstrap: fetch a token that represents "right
    now". Future polls use this as the start; we'll only see
    changes that happen AFTER this call. Storing the token before
    any user data has been pushed avoids the "boostrap saw all my
    Drive history" pathology.

    Note: Drive's getStartPageToken doesn't accept a `spaces`
    parameter — the token is opaque + filtering happens at list
    time. Our list_changes call below scopes results to
    ``appDataFolder`` per Slice 5.C.1."""
    service = client.service()
    res = service.changes().getStartPageToken().execute()
    token = res.get("startPageToken")
    if not token:
        raise RuntimeError(
            "Drive returned no startPageToken — unexpected. "
            f"raw response: {res!r}"
        )
    return str(token)


def list_changes(
    client: DriveClient,
    *,
    page_token: str,
    page_size: int = 100,
) -> ChangesPage:
    """One round-trip to ``changes.list``. Pass ``page_token`` from
    a previous call (or ``get_initial_start_page_token`` for the
    first one). Returns a single page; the caller paginates if
    `next_token` is non-None.

    Scoped to the hidden ``appDataFolder`` per Slice 5.C.1 — under
    drive.appdata we don't see (and don't want to see) the rest of
    the user's Drive."""
    from knowlet.core.sync.oauth import APPDATA_FOLDER

    service = client.service()
    res = (
        service.changes()
        .list(
            pageToken=page_token,
            pageSize=page_size,
            spaces=APPDATA_FOLDER,
            # `headRevisionId` is what we cache locally as the OCC
            # cursor in sync_state.last_known_etag. Including it in
            # the changes payload lets the poller filter out
            # self-induced changes (a push we just made).
            fields=(
                "newStartPageToken,nextPageToken,"
                "changes(fileId,removed,file(name,modifiedTime,"
                "mimeType,trashed,headRevisionId))"
            ),
        )
        .execute()
    )
    raw_changes = res.get("changes") or []
    out: list[DriveChange] = []
    for c in raw_changes:
        f = c.get("file")
        out.append(
            DriveChange(
                file_id=str(c.get("fileId") or ""),
                removed=bool(c.get("removed")),
                trashed=bool((f or {}).get("trashed")),
                file=f if isinstance(f, dict) else None,
            )
        )
    return ChangesPage(
        changes=out,
        next_token=res.get("nextPageToken"),
        new_start_page_token=res.get("newStartPageToken"),
    )


def list_all_changes(
    client: DriveClient, *, page_token: str
) -> tuple[list[DriveChange], str]:
    """Pull every change since ``page_token``, paginating internally,
    and return (all_changes, next_start_page_token_to_persist).

    Tail-of-stream behavior: when the final page returns
    `new_start_page_token`, we use that as the persist target.
    Otherwise we fall back to the last `next_token` we saw — but
    that should rarely happen since `changes.list` always sets
    one or the other.
    """
    all_changes: list[DriveChange] = []
    current = page_token
    last_seen_token = page_token
    while True:
        page = list_changes(client, page_token=current)
        all_changes.extend(page.changes)
        if page.new_start_page_token is not None:
            return all_changes, page.new_start_page_token
        if page.next_token is None:
            # Defensive — neither newStartPageToken nor nextPageToken;
            # treat as "nothing more to read, persist the last one".
            return all_changes, last_seen_token
        last_seen_token = page.next_token
        current = page.next_token
