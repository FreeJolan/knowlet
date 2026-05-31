"""Phase 2 E Slice 5.C — Drive Files API wrapper (ADR-0027).

Tight wrapper over ``service.files()`` covering just the verbs Slice
5.C needs:

- ``upload_new_file`` — first-time create. No precondition needed.
- ``update_file_conditional`` — subsequent overwrite, conditional on
  the file's current ``headRevisionId``. We fetch the current
  revision id, compare to the caller's expected value, and only
  proceed with the upload if they match. Mismatch →
  ``RemoteVersionMismatchError``.
- ``download_file`` — bytes for a Drive file id; used during conflict
  resolution to fetch the remote version for comparison.
- ``get_file_metadata`` — current ``headRevisionId`` /
  ``modifiedTime`` / ``name`` for diagnostics + as the cheap "did
  anything change since we last looked?" check.

OCC cursor — why headRevisionId, not HTTP ETag:
  Drive API v3 stopped returning the ``etag`` field in the file
  resource (requesting it 400s with "Invalid field selection etag").
  HTTP ``If-Match`` against the response ETag header is hard to
  thread through googleapiclient cleanly. We instead use
  ``headRevisionId`` (Google's recommended stable revision identifier
  for OCC) and do a get-then-compare-then-upload sequence. The race
  window is one HTTP RTT (~200ms) — fine for opt-in single-user
  multi-device sync where two writes inside the same RTT are
  vanishingly rare. If we ever need true atomic OCC, we revisit
  with explicit HTTP-layer If-Match handling.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

# These imports are only used inside function bodies to keep the
# google libs as an optional [sync] extra.

NOTE_MIME_TYPE = "text/markdown"


@dataclass(frozen=True)
class DriveFile:
    """Slim view of a Drive file resource — only the fields Slice
    5.C / S5 need. Bigger surfaces (parents, owners) come later.

    ``head_revision_id`` is the OCC cursor we persist in
    sync_state.file_state.last_known_etag (the column name predates
    the v3 etag-removal; semantically it's now ``headRevisionId``).

    ``last_modifying_user_display_name`` (S5 v2) feeds the merge
    editor's "who made the remote edit" label so users see
    "drive · 17:08 by alice" instead of an opaque revision id."""

    id: str
    name: str
    mime_type: str
    modified_time: str | None
    head_revision_id: str | None
    last_modifying_user_display_name: str | None = None


class RemoteVersionMismatchError(RuntimeError):
    """The user's expected revision id no longer matches Drive's
    current head — someone (likely another device) wrote in between.
    Caller fetches the remote version and presents the conflict UI."""

    def __init__(
        self,
        *,
        file_id: str,
        expected_revision: str,
        actual_revision: str,
        message: str = "",
    ) -> None:
        self.file_id = file_id
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        super().__init__(
            message
            or (
                f"Drive file {file_id} moved past expected revision "
                f"{expected_revision} (now {actual_revision}). "
                "Resolve the conflict before retrying."
            )
        )


# ----------------------------------------------------- helpers


def _file_resource_to_drive_file(res: dict[str, Any]) -> DriveFile:
    luser = res.get("lastModifyingUser") or {}
    return DriveFile(
        id=str(res.get("id") or ""),
        name=str(res.get("name") or ""),
        mime_type=str(res.get("mimeType") or ""),
        modified_time=res.get("modifiedTime"),
        head_revision_id=res.get("headRevisionId"),
        last_modifying_user_display_name=(luser.get("displayName") or luser.get("emailAddress")),
    )


# Drive v3 doesn't accept ``etag`` in fields; using it returns
# 400 "Invalid field selection". headRevisionId is our OCC cursor.
# lastModifyingUser(displayName,emailAddress) feeds S5's merge
# editor — we'd rather show "alice" than "rev-abc123".
_FIELDS = "id,name,mimeType,modifiedTime,headRevisionId,lastModifyingUser(displayName,emailAddress)"


# ----------------------------------------------------- upload (create)


def upload_new_file(
    service: Any,
    *,
    name: str,
    content: bytes,
    mime_type: str = NOTE_MIME_TYPE,
    parent_folder_id: str | None = None,
) -> DriveFile:
    """Create a new file in the user's Drive. With drive.file scope,
    knowlet only sees files it created — so ``parent_folder_id``
    can be left None to land at the Drive root, or pinned to a
    knowlet-owned folder once we have one."""
    from googleapiclient.http import MediaIoBaseUpload

    body: dict[str, Any] = {"name": name, "mimeType": mime_type}
    if parent_folder_id:
        body["parents"] = [parent_folder_id]
    media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime_type, resumable=False)
    request = service.files().create(body=body, media_body=media, fields=_FIELDS)
    res = request.execute()
    return _file_resource_to_drive_file(res)


# ----------------------------------------------------- update (with If-Match)


def update_file_conditional(
    service: Any,
    *,
    file_id: str,
    content: bytes,
    expected_revision: str,
    mime_type: str = NOTE_MIME_TYPE,
    name: str | None = None,
) -> DriveFile:
    """Conditional overwrite via GET-then-compare-then-upload.

    Drive v3 doesn't expose a clean If-Match path through
    googleapiclient (the body ``etag`` field was removed; HTTP-layer
    ETag handling is hidden). We instead fetch the file's current
    ``headRevisionId``, compare to the caller's
    ``expected_revision``, and only proceed if they match.

    Race window: one HTTP RTT between the GET and the upload. For
    opt-in single-user multi-device sync this is acceptable; two
    writes inside the same RTT are vanishingly rare. If ever needed,
    revisit with explicit HTTP-layer If-Match handling.

    Raises RemoteVersionMismatchError if the current revision differs
    from expected — caller resolves via the conflict UI."""
    from googleapiclient.http import MediaIoBaseUpload

    current = get_file_metadata(service, file_id)
    if current.head_revision_id != expected_revision:
        raise RemoteVersionMismatchError(
            file_id=file_id,
            expected_revision=expected_revision,
            actual_revision=current.head_revision_id or "(none)",
        )
    media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime_type, resumable=False)
    kwargs: dict[str, Any] = {"fileId": file_id, "media_body": media, "fields": _FIELDS}
    if name:
        kwargs["body"] = {"name": name}
    res = service.files().update(**kwargs).execute()
    return _file_resource_to_drive_file(res)


# ----------------------------------------------------- read paths


def download_file(service: Any, file_id: str) -> bytes:
    """Pull the raw bytes of a Drive file. Used during conflict
    resolution so the user can compare local vs remote."""
    from googleapiclient.http import MediaIoBaseDownload

    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _status, done = downloader.next_chunk()
    return buf.getvalue()


def get_file_metadata(service: Any, file_id: str) -> DriveFile:
    res = service.files().get(fileId=file_id, fields=_FIELDS).execute()
    return _file_resource_to_drive_file(res)


@dataclass(frozen=True)
class DriveFileBrief:
    """Minimal fields we pull for the bulk reconciliation path —
    just enough to attribute changes back to local notes and render
    a friendly row label in the inbox."""

    head_revision_id: str | None
    name: str | None


def list_appdata_revisions(service: Any) -> dict[str, DriveFileBrief]:
    """Slice 5.D.3.A — bulk fetch ``file_id → DriveFileBrief`` for
    every file in the appDataFolder. One paginated round-trip
    regardless of file count, so the conflict-detection path stays
    cheap as a vault grows.

    Drive caps page size at 1000; few users will have >1000 synced
    notes, so the loop usually exits after the first call. Tracked
    files no longer present on Drive aren't in the returned dict —
    caller treats that as a "remote was deleted/trashed" conflict
    signal.
    """
    out: dict[str, DriveFileBrief] = {}
    page_token: str | None = None
    # Hard cap pages so a misbehaving service (or a unit-test
    # MagicMock that truthy-loops on ``nextPageToken``) can't hang
    # the scan. 1000 entries per page x 10 pages = 10k files,
    # well past any single-user vault.
    for _ in range(10):
        kwargs: dict[str, Any] = {
            "spaces": "appDataFolder",
            "fields": "nextPageToken, files(id,name,headRevisionId)",
            "pageSize": 1000,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        resp = service.files().list(**kwargs).execute()
        if not isinstance(resp, dict):
            break
        files = resp.get("files", [])
        if not isinstance(files, list):
            break
        for f in files:
            if not isinstance(f, dict):
                continue
            out[str(f.get("id"))] = DriveFileBrief(
                head_revision_id=f.get("headRevisionId"),
                name=f.get("name"),
            )
        next_token = resp.get("nextPageToken")
        if not isinstance(next_token, str) or not next_token:
            break
        page_token = next_token
    return out


# ----------------------------------------------------- forced overwrite


def force_overwrite(
    service: Any,
    *,
    file_id: str,
    content: bytes,
    mime_type: str = NOTE_MIME_TYPE,
    name: str | None = None,
) -> DriveFile:
    """Used by the conflict UI's "use mine — overwrite remote" path.
    Does NOT set If-Match (i.e. unconditional update). The caller
    must have already shown the user both versions; this is the
    explicit "I know I'm clobbering" exit."""
    from googleapiclient.http import MediaIoBaseUpload

    media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime_type, resumable=False)
    kwargs: dict[str, Any] = {"fileId": file_id, "media_body": media, "fields": _FIELDS}
    if name:
        kwargs["body"] = {"name": name}
    res = service.files().update(**kwargs).execute()
    return _file_resource_to_drive_file(res)
