"""Vault.init_layout writes a starter wiki_schema.md (Phase 3 Stage 2)."""

from __future__ import annotations

from pathlib import Path

from knowlet.core.vault import Vault


def test_init_writes_starter_wiki_schema(tmp_path: Path) -> None:
    v = Vault(tmp_path)
    assert not (v.state_dir / "wiki_schema.md").exists()
    v.init_layout()
    schema_path = v.state_dir / "wiki_schema.md"
    assert schema_path.exists()
    body = schema_path.read_text(encoding="utf-8")
    # Starter must demonstrate the Rule + Why pattern (ADR-0024 §3.4).
    assert "**Why:**" in body
    # Mentions the two-level merge so a fresh user finds the docs.
    assert "~/.knowlet/wiki_schema.md" in body


def test_init_is_idempotent_does_not_overwrite_user_edits(
    tmp_path: Path,
) -> None:
    """If the user edits wiki_schema.md, subsequent init_layout calls
    (e.g. on reopen) must not clobber their content."""
    v = Vault(tmp_path)
    v.init_layout()
    user_body = "# My custom schema\n\nThis is mine, hands off.\n"
    (v.state_dir / "wiki_schema.md").write_text(user_body, encoding="utf-8")
    v.init_layout()  # second call
    assert (v.state_dir / "wiki_schema.md").read_text(encoding="utf-8") == user_body
