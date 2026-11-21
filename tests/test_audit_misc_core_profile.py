"""Regression tests for the misc-core audit batch — users/me.md.

The profile template invites hand-editing; a YAML typo in its
frontmatter (``name: John: Doe``) used to raise straight out of
``read_profile`` and take down chat bootstrap (web + desktop).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from knowlet.chat.bootstrap import bootstrap_chat
from knowlet.config import KnowletConfig, save_config
from knowlet.core.user_profile import (
    edit_profile_in_editor,
    ensure_profile,
    read_profile,
)
from knowlet.core.vault import Vault

BROKEN_YAML_PROFILE = "---\nname: John: Doe\ncreated_at: 2026-01-01\n---\nI study physics.\n"
UNCLOSED_FENCE_PROFILE = "---\nname: Jane\nI forgot the closing fence.\n"


def _ready_vault(tmp_path: Path) -> tuple[Vault, KnowletConfig]:
    v = Vault(tmp_path)
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = "stub"
    save_config(v.root, cfg)
    return v, cfg


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_read_profile_degrades_on_broken_yaml(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    p = tmp_path / "users" / "me.md"
    _write(p, BROKEN_YAML_PROFILE)

    with caplog.at_level(logging.WARNING, logger="knowlet.core.user_profile"):
        profile = read_profile(p)

    assert profile is not None
    assert profile.name is None
    assert profile.body.strip() == "I study physics."
    assert profile.frontmatter_error
    assert any("me.md" in r.getMessage() for r in caplog.records)


def test_read_profile_unclosed_fence_keeps_full_text(tmp_path: Path) -> None:
    p = tmp_path / "users" / "me.md"
    _write(p, UNCLOSED_FENCE_PROFILE)

    profile = read_profile(p)

    assert profile is not None
    assert "I forgot the closing fence." in profile.body


def test_read_profile_non_mapping_frontmatter(tmp_path: Path) -> None:
    p = tmp_path / "users" / "me.md"
    _write(p, "---\n- just\n- a list\n---\nbody text\n")

    profile = read_profile(p)

    assert profile is not None
    assert profile.body.strip() == "body text"


def test_ensure_profile_does_not_overwrite_corrupt_file(tmp_path: Path) -> None:
    p = tmp_path / "users" / "me.md"
    _write(p, BROKEN_YAML_PROFILE)

    ensure_profile(p)

    assert p.read_text(encoding="utf-8") == BROKEN_YAML_PROFILE


def test_edit_profile_in_editor_leaves_corrupt_file_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After the editor exits we normally re-stamp updated_at; with a
    still-broken frontmatter that rewrite would silently drop the
    user's (unparseable) fields, so it must be skipped."""
    p = tmp_path / "users" / "me.md"
    _write(p, BROKEN_YAML_PROFILE)
    monkeypatch.setenv("EDITOR", "true")

    profile = edit_profile_in_editor(p)

    assert profile.body.strip() == "I study physics."
    assert p.read_text(encoding="utf-8") == BROKEN_YAML_PROFILE


def test_bootstrap_survives_corrupt_profile(tmp_path: Path) -> None:
    v, cfg = _ready_vault(tmp_path)
    _write(v.profile_path, BROKEN_YAML_PROFILE)

    runtime, report = bootstrap_chat(v, cfg)
    try:
        assert report.user_profile_loaded is True
        first = runtime.session.history[0]
        assert first["role"] == "system"
        assert "I study physics." in first["content"]
    finally:
        runtime.close()
