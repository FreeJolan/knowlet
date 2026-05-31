"""S4 / #111 — cross-device heartbeat in Drive appData.

Each running knowlet instance writes a tiny JSON file into the
Drive appData folder named ``<device_id>.heartbeat.json``. Other
devices list those files to figure out how many distinct knowlet
installations are touching the same vault recently. Auto sync
mode uses this signal to auto-promote to Strict when ≥2 devices
are alive within the TTL window.

Why appData (not Drive root): the user never sees these files in
their main Drive — they're scoped to knowlet only. Naming
``<device_id>.heartbeat.json`` keeps the filename idempotent so
the same device overwrites its own file on every tick instead of
fanning out to ``heartbeat (2).json`` style copies.

Why no body download in ``list_alive_devices``: Drive's
``modifiedTime`` is returned in ``files.list``, and that's the
last-seen signal we need. Skipping the per-file ``files.get_media``
keeps the list cheap regardless of device count.

device_label (host name, etc.) is NOT stored cross-device in this
slice — the chip-level UX shows "N devices detected" rather than
"Bob's Mac + Bob's iPad". Friendly labels can come later via
Drive custom file properties.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from knowlet.core.note import now_iso
from knowlet.core.sync.files import force_overwrite, upload_new_file
from knowlet.core.sync.namespace import scoped_appdata_name, strip_current_vault_prefix
from knowlet.core.sync.oauth import APPDATA_FOLDER

logger = logging.getLogger(__name__)

HEARTBEAT_SUFFIX = ".heartbeat.json"
HEARTBEAT_TTL_DAYS = 30
HEARTBEAT_MIME = "application/json"


@dataclass(frozen=True)
class AliveDevice:
    """One row from the heartbeat scan — a device knowlet has seen
    talk to this vault's appData within the TTL window."""

    device_id: str
    last_seen_at: str  # Drive's modifiedTime, ISO 8601 UTC


def write_my_heartbeat(
    service: Any,
    *,
    device_id: str,
    device_label: str,
    vault_root: Path | None = None,
) -> None:
    """Idempotent upload of THIS device's heartbeat. If the file
    already exists in appData, overwrite it (Drive bumps
    ``modifiedTime`` automatically). If not, create it."""
    payload = json.dumps(
        {
            "device_id": device_id,
            "device_label": device_label,
            "last_seen_at": now_iso(),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    legacy_name = f"{device_id}{HEARTBEAT_SUFFIX}"
    fname = (
        scoped_appdata_name(vault_root, "", legacy_name) if vault_root is not None else legacy_name
    )

    existing_id = _find_heartbeat_file_id(service, fname)
    if existing_id is not None:
        force_overwrite(
            service,
            file_id=existing_id,
            content=payload,
            mime_type=HEARTBEAT_MIME,
        )
        return
    upload_new_file(
        service,
        name=fname,
        content=payload,
        mime_type=HEARTBEAT_MIME,
        parent_folder_id=APPDATA_FOLDER,
    )


def list_alive_devices(
    service: Any,
    ttl_days: int = HEARTBEAT_TTL_DAYS,
    *,
    vault_root: Path | None = None,
) -> list[AliveDevice]:
    """List all ``*.heartbeat.json`` files in appData; return ones
    whose ``modifiedTime`` is within ``ttl_days``. Uses metadata
    only — no body downloads — so cost is O(pages) regardless of
    file count.

    Pagination is hard-capped by ``_MAX_HEARTBEAT_PAGES`` so a
    misbehaving Drive client (or a unit-test MagicMock that
    truthy-loops on ``nextPageToken``) can't hang the scan."""
    cutoff_epoch = datetime.now(UTC).timestamp() - ttl_days * 86400
    out: list[AliveDevice] = []
    page_token: str | None = None
    for _ in range(_MAX_HEARTBEAT_PAGES):
        kwargs: dict[str, Any] = {
            "spaces": "appDataFolder",
            "fields": "nextPageToken, files(id,name,modifiedTime)",
            "pageSize": 100,
            "q": "name contains '.heartbeat.json'",
        }
        if page_token:
            kwargs["pageToken"] = page_token
        resp = service.files().list(**kwargs).execute()
        files = resp.get("files", []) if isinstance(resp, dict) else []
        if not isinstance(files, list):
            break
        for f in files:
            if not isinstance(f, dict):
                continue
            name = str(f.get("name") or "")
            if not name.endswith(HEARTBEAT_SUFFIX):
                continue
            if vault_root is not None:
                tail = strip_current_vault_prefix(name, vault_root)
                if tail is None:
                    continue
                device_id = tail[: -len(HEARTBEAT_SUFFIX)]
            else:
                device_id = name[: -len(HEARTBEAT_SUFFIX)]
            if not device_id:
                continue
            mtime = f.get("modifiedTime")
            if not mtime:
                continue
            ts = _iso_epoch(str(mtime))
            if ts < cutoff_epoch:
                continue
            out.append(AliveDevice(device_id=device_id, last_seen_at=str(mtime)))
        next_token = resp.get("nextPageToken") if isinstance(resp, dict) else None
        if not isinstance(next_token, str) or not next_token:
            break
        page_token = next_token
    return out


# Sanity cap so even a vault with thousands of devices terminates
# in reasonable time. At pageSize=100 this allows up to 1000
# heartbeats per scan, way past any realistic single-user setup.
_MAX_HEARTBEAT_PAGES = 10


def _find_heartbeat_file_id(service: Any, fname: str) -> str | None:
    """Drive ``files.list`` filtered by exact filename. Returns the
    Drive id if exactly one match exists; None if not found. Two
    matches (shouldn't happen — filenames are device-scoped) → log
    and return the first.

    Defensive against non-dict responses (unit-test MagicMock will
    return MagicMock from ``.execute()`` unless explicitly stubbed)."""
    resp = (
        service.files()
        .list(
            spaces="appDataFolder",
            fields="files(id,name)",
            q=f"name = '{fname}'",
            pageSize=10,
        )
        .execute()
    )
    if not isinstance(resp, dict):
        return None
    files = resp.get("files", [])
    if not isinstance(files, list) or not files:
        return None
    if len(files) > 1:
        logger.warning(
            "multiple heartbeats found for %s (count=%d); using first",
            fname,
            len(files),
        )
    first = files[0]
    if not isinstance(first, dict):
        return None
    fid = first.get("id")
    return str(fid) if fid else None


def _iso_epoch(iso: str) -> float:
    """Parse an ISO-8601 UTC string to epoch seconds. Drive's
    ``modifiedTime`` is RFC 3339; Python's ``fromisoformat`` handles
    that when we normalize the trailing Z."""
    s = iso.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return 0.0
