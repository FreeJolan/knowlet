from pathlib import Path

from knowlet.core.vault import Vault
from knowlet.core.vault_identity import ensure_vault_id, vault_identity_path


def test_vault_init_creates_stable_vault_identity(tmp_path: Path) -> None:
    vault = Vault(tmp_path)
    vault.init_layout()

    first = ensure_vault_id(vault.root)
    second = ensure_vault_id(vault.root)

    assert first == second
    assert first.startswith("01")
    assert vault_identity_path(vault.root).is_file()


def test_each_vault_gets_distinct_identity(tmp_path: Path) -> None:
    left = Vault(tmp_path / "left")
    right = Vault(tmp_path / "right")
    left.init_layout()
    right.init_layout()

    assert ensure_vault_id(left.root) != ensure_vault_id(right.root)
