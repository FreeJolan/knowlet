"""Vault-scoped names for Google Drive appData.

Drive's appDataFolder is flat and scoped only by application + Google
account. We therefore include the Knowlet vault id in every new remote
file name so one Google account can safely sync multiple vaults.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from knowlet.core.vault_identity import ensure_vault_id

VAULT_NAME_PREFIX = "vault-"
VAULT_NAME_SEPARATOR = "__"


@dataclass(frozen=True)
class AppDataEntityName:
    entity_type: str
    entity_id: str
    vault_id: str | None
    scoped: bool


def vault_appdata_prefix(vault_root: Path) -> str:
    return f"{VAULT_NAME_PREFIX}{ensure_vault_id(vault_root)}{VAULT_NAME_SEPARATOR}"


def scoped_appdata_name(vault_root: Path, type_prefix: str, entity_id: str) -> str:
    return f"{vault_appdata_prefix(vault_root)}{type_prefix}{entity_id}"


def name_belongs_to_vault(name: str | None, vault_root: Path) -> bool:
    if not name:
        return False
    return name.startswith(vault_appdata_prefix(vault_root))


def parse_vault_id_from_scoped_name(name: str | None) -> str | None:
    if not name or not name.startswith(VAULT_NAME_PREFIX):
        return None
    tail = name[len(VAULT_NAME_PREFIX) :]
    separator = tail.find(VAULT_NAME_SEPARATOR)
    if separator <= 0:
        return None
    vault_id = tail[:separator].strip()
    return vault_id or None


def strip_current_vault_prefix(name: str, vault_root: Path) -> str | None:
    prefix = vault_appdata_prefix(vault_root)
    if not name.startswith(prefix):
        return None
    return name[len(prefix) :]


def parse_scoped_appdata_name(
    name: str | None,
    *,
    vault_root: Path,
    type_prefixes: dict[str, str],
) -> AppDataEntityName | None:
    if not name:
        return None
    tail = strip_current_vault_prefix(name, vault_root)
    if tail is None:
        return None
    for entity_type, prefix in type_prefixes.items():
        if tail.startswith(prefix):
            entity_id = tail[len(prefix) :]
            if entity_id:
                return AppDataEntityName(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    vault_id=ensure_vault_id(vault_root),
                    scoped=True,
                )
    return None
