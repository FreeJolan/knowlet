"""Discoverable remote Vault registry in Google Drive appData.

Scoped appData names keep vault contents isolated:
``vault-<vault_id>__note-<id>.md``. That protects data once a local
vault already knows its ``vault_id``, but a brand-new device does not
know any IDs yet. The small unscoped registry below is the account-level
index that lets the desktop launcher show "restore an existing Vault"
instead of making users copy ``.knowlet/vault.json`` by hand.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from knowlet.core.note import now_iso
from knowlet.core.sync.files import download_file, force_overwrite, upload_new_file
from knowlet.core.sync.namespace import parse_vault_id_from_scoped_name
from knowlet.core.sync.oauth import APPDATA_FOLDER
from knowlet.core.vault_identity import ensure_vault_id

VAULT_REGISTRY_NAME = "knowlet-vault-registry.json"
VAULT_REGISTRY_MIME = "application/json"
_MAX_APPDATA_PAGES = 10


@dataclass(frozen=True)
class RemoteVaultSummary:
    vault_id: str
    name: str
    updated_at: str | None
    last_device_label: str | None
    item_count: int
    source: str


@dataclass(frozen=True)
class _AppDataFile:
    id: str
    name: str
    modified_time: str | None
    head_revision_id: str | None


def list_remote_vaults(service: Any) -> list[RemoteVaultSummary]:
    """Return all Drive appData Vaults visible to this Google account.

    New builds publish ``VAULT_REGISTRY_NAME``. Older builds only have
    scoped content files, so we also infer legacy Vaults by parsing
    ``vault-<id>__`` prefixes from all appData names.
    """
    files = _list_appdata_files(service)
    registry_file = next((file for file in files if file.name == VAULT_REGISTRY_NAME), None)
    registry = _download_registry(service, registry_file.id) if registry_file is not None else {}
    counts: dict[str, int] = {}
    newest: dict[str, str] = {}

    for file in files:
        vault_id = parse_vault_id_from_scoped_name(file.name)
        if vault_id is None:
            continue
        counts[vault_id] = counts.get(vault_id, 0) + 1
        if file.modified_time and file.modified_time > newest.get(vault_id, ""):
            newest[vault_id] = file.modified_time

    summaries: dict[str, RemoteVaultSummary] = {}
    for vault_id, entry in registry.items():
        if not vault_id:
            continue
        name = _string(entry.get("name")) or _fallback_name(vault_id)
        updated_at = _string(entry.get("updated_at")) or newest.get(vault_id)
        summaries[vault_id] = RemoteVaultSummary(
            vault_id=vault_id,
            name=name,
            updated_at=updated_at,
            last_device_label=_string(entry.get("last_device_label")),
            item_count=counts.get(vault_id, 0),
            source="registry",
        )

    for vault_id, item_count in counts.items():
        if vault_id in summaries:
            continue
        summaries[vault_id] = RemoteVaultSummary(
            vault_id=vault_id,
            name=_fallback_name(vault_id),
            updated_at=newest.get(vault_id),
            last_device_label=None,
            item_count=item_count,
            source="legacy",
        )

    return sorted(
        summaries.values(),
        key=lambda item: (item.updated_at or "", item.name.lower(), item.vault_id),
        reverse=True,
    )


def publish_vault_to_registry(
    service: Any,
    *,
    vault_root: Path,
    device_label: str | None = None,
) -> None:
    """Upsert this local Vault into the account-level Drive registry."""
    files = _list_appdata_files(service)
    registry_file = next((file for file in files if file.name == VAULT_REGISTRY_NAME), None)
    registry = _download_registry(service, registry_file.id) if registry_file is not None else {}
    vault_id = ensure_vault_id(vault_root)
    registry[vault_id] = {
        "vault_id": vault_id,
        "name": vault_root.name or _fallback_name(vault_id),
        "updated_at": now_iso(),
        "last_device_label": device_label,
    }
    payload = _encode_registry(registry)
    if registry_file is not None:
        force_overwrite(
            service,
            file_id=registry_file.id,
            content=payload,
            mime_type=VAULT_REGISTRY_MIME,
        )
        return
    upload_new_file(
        service,
        name=VAULT_REGISTRY_NAME,
        content=payload,
        mime_type=VAULT_REGISTRY_MIME,
        parent_folder_id=APPDATA_FOLDER,
    )


def _list_appdata_files(service: Any) -> list[_AppDataFile]:
    out: list[_AppDataFile] = []
    page_token: str | None = None
    for _ in range(_MAX_APPDATA_PAGES):
        kwargs: dict[str, Any] = {
            "spaces": "appDataFolder",
            "fields": "nextPageToken, files(id,name,modifiedTime,headRevisionId)",
            "pageSize": 1000,
            "q": "trashed=false",
        }
        if page_token:
            kwargs["pageToken"] = page_token
        resp = service.files().list(**kwargs).execute()
        if not isinstance(resp, dict):
            break
        raw_files = resp.get("files", [])
        if not isinstance(raw_files, list):
            break
        for raw in raw_files:
            if not isinstance(raw, dict):
                continue
            file_id = _string(raw.get("id"))
            name = _string(raw.get("name"))
            if not file_id or not name:
                continue
            out.append(
                _AppDataFile(
                    id=file_id,
                    name=name,
                    modified_time=_string(raw.get("modifiedTime")),
                    head_revision_id=_string(raw.get("headRevisionId")),
                )
            )
        next_token = resp.get("nextPageToken")
        if not isinstance(next_token, str) or not next_token:
            break
        page_token = next_token
    return out


def _download_registry(service: Any, file_id: str) -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(download_file(service, file_id).decode("utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    vaults = raw.get("vaults")
    if not isinstance(vaults, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, value in vaults.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        vault_id = _string(value.get("vault_id")) or key
        if vault_id:
            out[vault_id] = dict(value)
    return out


def _encode_registry(registry: dict[str, dict[str, Any]]) -> bytes:
    payload = {
        "version": 1,
        "updated_at": now_iso(),
        "vaults": registry,
    }
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _fallback_name(vault_id: str) -> str:
    return f"Vault {vault_id[-6:]}"


def _string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
