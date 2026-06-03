from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from knowlet.core.sync.oauth import APPDATA_FOLDER
from knowlet.core.sync.vault_registry import (
    VAULT_REGISTRY_NAME,
    list_remote_vaults,
    publish_vault_to_registry,
)
from knowlet.core.vault import Vault
from knowlet.core.vault_identity import ensure_vault_id


def _registry_bytes() -> bytes:
    return json.dumps(
        {
            "version": 1,
            "vaults": {
                "01REMOTEVAULTID000000000000": {
                    "vault_id": "01REMOTEVAULTID000000000000",
                    "name": "Research Vault",
                    "updated_at": "2026-06-03T08:00:00Z",
                    "last_device_label": "MacBook",
                }
            },
        }
    ).encode("utf-8")


def test_list_remote_vaults_merges_registry_and_legacy_scoped_names(monkeypatch) -> None:
    service = MagicMock()
    service.files.return_value.list.return_value.execute.return_value = {
        "files": [
            {
                "id": "REGISTRY",
                "name": VAULT_REGISTRY_NAME,
                "modifiedTime": "2026-06-03T08:00:00Z",
                "headRevisionId": "rev-registry",
            },
            {
                "id": "LEGACY-NOTE",
                "name": "vault-01LEGACYVAULTID0000000000__note-01NOTE.md",
                "modifiedTime": "2026-06-02T09:30:00Z",
                "headRevisionId": "rev-note",
            },
            {
                "id": "REMOTE-NOTE",
                "name": "vault-01REMOTEVAULTID000000000000__note-01REMOTE.md",
                "modifiedTime": "2026-06-03T09:00:00Z",
                "headRevisionId": "rev-remote-note",
            },
        ]
    }
    monkeypatch.setattr(
        "knowlet.core.sync.vault_registry.download_file",
        lambda _service, file_id: _registry_bytes() if file_id == "REGISTRY" else b"",
    )

    vaults = list_remote_vaults(service)

    by_id = {vault.vault_id: vault for vault in vaults}
    assert by_id["01REMOTEVAULTID000000000000"].name == "Research Vault"
    assert by_id["01REMOTEVAULTID000000000000"].source == "registry"
    assert by_id["01REMOTEVAULTID000000000000"].item_count == 1
    assert by_id["01LEGACYVAULTID0000000000"].name.endswith("000000")
    assert by_id["01LEGACYVAULTID0000000000"].source == "legacy"
    assert by_id["01LEGACYVAULTID0000000000"].item_count == 1


def test_publish_vault_to_registry_merges_existing_registry(monkeypatch, tmp_path: Path) -> None:
    vault = Vault(tmp_path / "Local Research")
    vault.init_layout()
    vault_id = ensure_vault_id(vault.root)
    service = MagicMock()
    service.files.return_value.list.return_value.execute.return_value = {
        "files": [
            {
                "id": "REGISTRY",
                "name": VAULT_REGISTRY_NAME,
                "modifiedTime": "2026-06-03T08:00:00Z",
                "headRevisionId": "rev-registry",
            }
        ]
    }
    monkeypatch.setattr(
        "knowlet.core.sync.vault_registry.download_file",
        lambda _service, _file_id: _registry_bytes(),
    )
    captured: dict[str, object] = {}

    def fake_force_overwrite(_service, *, file_id, content, mime_type="application/json"):
        captured["file_id"] = file_id
        captured["content"] = content
        captured["mime_type"] = mime_type

    monkeypatch.setattr(
        "knowlet.core.sync.vault_registry.force_overwrite",
        fake_force_overwrite,
    )

    publish_vault_to_registry(service, vault_root=vault.root, device_label="Studio Mac")

    payload = json.loads(bytes(captured["content"]).decode("utf-8"))
    assert captured["file_id"] == "REGISTRY"
    assert payload["vaults"]["01REMOTEVAULTID000000000000"]["name"] == "Research Vault"
    assert payload["vaults"][vault_id]["name"] == "Local Research"
    assert payload["vaults"][vault_id]["last_device_label"] == "Studio Mac"


def test_publish_vault_to_registry_creates_registry_when_missing(
    monkeypatch, tmp_path: Path
) -> None:
    vault = Vault(tmp_path / "First Vault")
    vault.init_layout()
    service = MagicMock()
    service.files.return_value.list.return_value.execute.return_value = {"files": []}
    captured: dict[str, object] = {}

    def fake_upload_new_file(_service, *, name, content, mime_type, parent_folder_id=None):
        captured["name"] = name
        captured["content"] = content
        captured["mime_type"] = mime_type
        captured["parent_folder_id"] = parent_folder_id

    monkeypatch.setattr(
        "knowlet.core.sync.vault_registry.upload_new_file",
        fake_upload_new_file,
    )

    publish_vault_to_registry(service, vault_root=vault.root, device_label="MacBook")

    payload = json.loads(bytes(captured["content"]).decode("utf-8"))
    vault_id = ensure_vault_id(vault.root)
    assert captured["name"] == VAULT_REGISTRY_NAME
    assert captured["parent_folder_id"] == APPDATA_FOLDER
    assert payload["vaults"][vault_id]["name"] == "First Vault"
