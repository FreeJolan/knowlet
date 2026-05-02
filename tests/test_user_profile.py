"""Tests for the M1 user-profile layer."""

from pathlib import Path

from knowlet.chat.bootstrap import bootstrap_chat
from knowlet.chat.prompts import (
    CHAT_SYSTEM_PROMPT_BASE,
    build_chat_system_prompt,
)
from knowlet.cli.chat_repl import _handle_slash
from knowlet.config import KnowletConfig, save_config
from knowlet.core.tools._registry import ToolContext, default_registry
from knowlet.core.user_profile import (
    PROFILE_BODY_CHAR_LIMIT,
    UserProfile,
    ensure_profile,
    read_profile,
    write_profile,
)
from knowlet.core.vault import Vault


def _ready_vault(tmp_path: Path) -> tuple[Vault, KnowletConfig]:
    v = Vault(tmp_path)
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = "stub"
    save_config(v.root, cfg)
    return v, cfg


# -------------------------------------------------- core/user_profile module


def test_read_profile_returns_none_when_missing(tmp_path: Path):
    v = Vault(tmp_path)
    v.init_layout()
    assert read_profile(v.profile_path) is None


def test_write_then_read_round_trip(tmp_path: Path):
    v = Vault(tmp_path)
    v.init_layout()
    p = UserProfile(body="# hi\n\nI am a programmer.", name="Jolan")
    path = write_profile(v.profile_path, p)
    assert path.exists()
    loaded = read_profile(v.profile_path)
    assert loaded is not None
    assert loaded.name == "Jolan"
    assert "I am a programmer" in loaded.body


def test_write_profile_is_0600(tmp_path: Path):
    v = Vault(tmp_path)
    v.init_layout()
    p = UserProfile(body="some private info")
    path = write_profile(v.profile_path, p)
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600


def test_ensure_profile_creates_default(tmp_path: Path):
    v = Vault(tmp_path)
    v.init_layout()
    assert read_profile(v.profile_path) is None
    p = ensure_profile(v.profile_path)
    assert p.body  # default template is non-empty
    again = ensure_profile(v.profile_path)
    assert again.body == p.body  # idempotent


def test_truncated_for_prompt_caps_length():
    p = UserProfile(body="x" * (PROFILE_BODY_CHAR_LIMIT + 5000))
    out = p.truncated_for_prompt()
    assert len(out) <= PROFILE_BODY_CHAR_LIMIT + 200  # plus the truncation note


# -------------------------------------------------- prompt assembly


def test_build_system_prompt_no_profile():
    out = build_chat_system_prompt(None)
    assert out == CHAT_SYSTEM_PROMPT_BASE
    out = build_chat_system_prompt("   ")
    assert out == CHAT_SYSTEM_PROMPT_BASE


def test_build_system_prompt_with_profile():
    out = build_chat_system_prompt("I prefer concise answers.")
    assert "User profile" in out
    assert "I prefer concise answers." in out
    assert out.startswith(CHAT_SYSTEM_PROMPT_BASE)


# -------------------------------------------------- bootstrap_chat integration


def test_bootstrap_loads_profile_into_system_prompt(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    write_profile(
        v.profile_path,
        UserProfile(body="My focus right now is RAG retrieval.", name="Jolan"),
    )
    runtime, report = bootstrap_chat(v, cfg)
    try:
        assert report.user_profile_loaded is True
        assert runtime.user_profile is not None
        first = runtime.session.history[0]
        assert first["role"] == "system"
        assert "RAG retrieval" in first["content"]
    finally:
        runtime.close()


def test_bootstrap_without_profile_uses_base_prompt(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    runtime, report = bootstrap_chat(v, cfg)
    try:
        assert report.user_profile_loaded is False
        assert runtime.user_profile is None
        assert runtime.session.history[0]["content"] == CHAT_SYSTEM_PROMPT_BASE
    finally:
        runtime.close()


# -------------------------------------------------- get_user_profile tool


def test_get_user_profile_tool_present_in_default_registry():
    reg = default_registry()
    assert "get_user_profile" in reg.tools


def test_get_user_profile_tool_when_missing(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    runtime, _ = bootstrap_chat(v, cfg)
    try:
        ctx = ToolContext(
            vault=v, index=runtime.index, config=cfg,
            cards=runtime.ctx.cards, tasks=runtime.ctx.tasks, drafts=runtime.ctx.drafts,
        )
        res = runtime.registry.dispatch("get_user_profile", {}, ctx)
        assert res["exists"] is False
        assert "suggestion" in res
    finally:
        runtime.close()


def test_get_user_profile_tool_when_present(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    write_profile(v.profile_path, UserProfile(body="I read AI papers.", name="Jolan"))
    runtime, _ = bootstrap_chat(v, cfg)
    try:
        ctx = ToolContext(
            vault=v, index=runtime.index, config=cfg,
            cards=runtime.ctx.cards, tasks=runtime.ctx.tasks, drafts=runtime.ctx.drafts,
        )
        res = runtime.registry.dispatch("get_user_profile", {}, ctx)
        assert res["exists"] is True
        assert res["name"] == "Jolan"
        assert "AI papers" in res["body"]
    finally:
        runtime.close()


# -------------------------------------------------- slash command


def test_slash_user_show(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    write_profile(v.profile_path, UserProfile(body="hello"))
    runtime, _ = bootstrap_chat(v, cfg)
    try:
        handled, should_quit = _handle_slash(":user", runtime)
        assert handled and not should_quit
        handled, _ = _handle_slash(":user show", runtime)
        assert handled
    finally:
        runtime.close()


def test_slash_user_show_when_missing(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    runtime, _ = bootstrap_chat(v, cfg)
    try:
        handled, should_quit = _handle_slash(":user", runtime)
        assert handled and not should_quit
    finally:
        runtime.close()


def test_slash_user_unknown_subcommand(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    runtime, _ = bootstrap_chat(v, cfg)
    try:
        handled, _ = _handle_slash(":user wat", runtime)
        assert handled
    finally:
        runtime.close()
