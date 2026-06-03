from pathlib import Path

from knowlet.core.vault import Vault
from knowlet.core.vault_identity import ensure_vault_id, vault_identity_path, write_vault_id


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


def test_restore_can_bind_vault_to_existing_remote_identity(tmp_path: Path) -> None:
    vault = Vault(tmp_path / "restored")
    vault.init_layout()
    first = ensure_vault_id(vault.root)

    write_vault_id(vault.root, "01REMOTEVAULTID000000000000")

    assert first != "01REMOTEVAULTID000000000000"
    assert ensure_vault_id(vault.root) == "01REMOTEVAULTID000000000000"
    assert '"01REMOTEVAULTID000000000000"' in vault_identity_path(vault.root).read_text(
        encoding="utf-8"
    )
