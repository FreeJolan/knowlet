"""Stable per-vault identity.

The filesystem path is not a durable identity: users can rename or move
a vault folder, and desktop recent-vault records can be removed without
touching the data. Sync needs a path-independent id so Google Drive
appData can hold multiple vaults under one account without mixing them.
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from knowlet.config import VAULT_MARKER_DIR
from knowlet.core.note import new_id

VAULT_IDENTITY_FILENAME = "vault.json"


def vault_identity_path(vault_root: Path) -> Path:
    return vault_root / VAULT_MARKER_DIR / VAULT_IDENTITY_FILENAME


def ensure_vault_id(vault_root: Path) -> str:
    """Return the stable vault id, creating it if this is an older vault."""
    path = vault_identity_path(vault_root)
    existing = _read_vault_id(path)
    if existing:
        return existing
    vault_id = new_id()
    _write_vault_id(path, vault_id)
    return vault_id


def write_vault_id(vault_root: Path, vault_id: str) -> None:
    """Bind a local vault folder to an existing remote vault identity.

    Normal vault creation should use ``ensure_vault_id`` so each new
    vault gets a fresh identity. Restore-from-cloud is the exception:
    the Drive-side ``vault_id`` is the canonical sync identity, so the
    local folder must adopt it before any scoped appData names are
    materialized.
    """
    value = vault_id.strip()
    if not value:
        raise ValueError("vault_id must not be empty")
    if any(ch in value for ch in ("/", "\\", "\0")):
        raise ValueError("vault_id contains invalid path characters")
    _write_vault_id(vault_identity_path(vault_root), value)


def _read_vault_id(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    value = raw.get("id")
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _write_vault_id(path: Path, vault_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "version": 1,
        "id": vault_id,
    }
    fd, tmp_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        os.chmod(tmp, 0o600)
        tmp.replace(path)
    except Exception:
        with suppress(OSError):
            tmp.unlink()
        raise
