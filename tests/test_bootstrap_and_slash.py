"""Tests for bootstrap_chat and the slash-command dispatcher."""

from pathlib import Path

import pytest

from knowlet.chat.bootstrap import (
    ChatNotReadyError,
    bootstrap_chat,
)
from knowlet.cli.main import _handle_slash
from knowlet.config import KnowletConfig, save_config
from knowlet.core.note import Note, new_id
from knowlet.core.vault import Vault


def _ready_vault(tmp_path: Path) -> tuple[Vault, KnowletConfig]:
    v = Vault(tmp_path)
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = "stub-for-tests"
    save_config(v.root, cfg)
    return v, cfg


def test_bootstrap_requires_api_key(tmp_path: Path):
    v = Vault(tmp_path)
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    save_config(v.root, cfg)
    with pytest.raises(ChatNotReadyError):
        bootstrap_chat(v, cfg)


def test_bootstrap_returns_usable_runtime(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    n = Note(id=new_id(), title="Bootstrap test", body="hello world")
    v.write_note(n)

    runtime, report = bootstrap_chat(v, cfg)
    try:
        assert runtime.config.llm.model == "claude-opus-4-7"  # default model
        assert runtime.index is not None
        assert runtime.session is not None
        # The reindex sweep should have indexed the note we just wrote.
        rows = runtime.index.list_notes(limit=10)
        assert len(rows) == 1
        assert rows[0]["title"] == "Bootstrap test"
        # Tools registry has our three atomic capabilities.
        assert {"search_notes", "get_note", "list_recent_notes"}.issubset(
            runtime.registry.tools
        )
        assert report.reindex_changed == 1
    finally:
        runtime.close()


def test_slash_quit_signals_exit(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    runtime, _ = bootstrap_chat(v, cfg)
    try:
        for spelling in (":quit", ":exit", ":q"):
            handled, should_quit = _handle_slash(spelling, runtime)
            assert handled and should_quit, spelling
    finally:
        runtime.close()


def test_slash_help_handled_no_quit(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    runtime, _ = bootstrap_chat(v, cfg)
    try:
        for spelling in (":help", ":h", "?"):
            handled, should_quit = _handle_slash(spelling, runtime)
            assert handled and not should_quit, spelling
    finally:
        runtime.close()


def test_slash_clear_resets_history(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    runtime, _ = bootstrap_chat(v, cfg)
    try:
        runtime.session.history.append({"role": "user", "content": "hi"})
        runtime.session.history.append({"role": "assistant", "content": "hello"})
        assert len(runtime.session.history) > 1
        handled, _ = _handle_slash(":clear", runtime)
        assert handled
        assert len(runtime.session.history) == 1  # only system prompt left
    finally:
        runtime.close()


def test_slash_ls_renders_without_crash(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    Note(id=new_id(), title="A", body="x")  # ensure types load
    n = Note(id=new_id(), title="Some note", body="body")
    v.write_note(n)
    runtime, _ = bootstrap_chat(v, cfg)
    try:
        handled, _ = _handle_slash(":ls", runtime)
        assert handled
        handled, _ = _handle_slash(":ls --recent", runtime)
        assert handled
    finally:
        runtime.close()


def test_slash_unknown_is_handled(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    runtime, _ = bootstrap_chat(v, cfg)
    try:
        handled, should_quit = _handle_slash(":wat", runtime)
        assert handled and not should_quit
    finally:
        runtime.close()


def test_slash_tools_lists_registry(tmp_path: Path):
    v, cfg = _ready_vault(tmp_path)
    runtime, _ = bootstrap_chat(v, cfg)
    try:
        handled, _ = _handle_slash(":tools", runtime)
        assert handled
    finally:
        runtime.close()
