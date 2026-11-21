"""Regression tests for the misc-core audit batch — hand-written TOML.

config.toml and quick-actions.toml are written by small homegrown
serializers. A string value containing a newline / control character
used to produce a file tomllib refuses to parse, bricking every later
load (CLI, web bootstrap, quick-action endpoints).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from knowlet import config as config_mod
from knowlet.config import (
    KnowletConfig,
    config_path,
    load_config,
    save_config,
    synced_config_snapshot_path,
)
from knowlet.core.quick_actions import (
    CreateNoteParams,
    QuickAction,
    QuickActionStore,
    new_action_id,
    quick_actions_path,
)

NASTY = 'line1\nline2\r\t"quoted" back\\slash \x00\x01\x08\x0b\x0c\x1f\x7f end — 中文'


def _init_vault(tmp_path: Path) -> Path:
    (tmp_path / ".knowlet").mkdir()
    return tmp_path


# ------------------------------------------------------------- config.toml


def test_config_round_trips_control_characters(tmp_path: Path) -> None:
    vault = _init_vault(tmp_path)
    cfg = KnowletConfig()
    cfg.llm.api_key = NASTY
    cfg.llm.base_url = "http://example.test/v1\n"
    cfg.llm.model = "model\twith\ttabs"

    save_config(vault, cfg)

    # The written file is valid TOML ...
    with config_path(vault).open("rb") as f:
        tomllib.load(f)
    # ... and every value round-trips byte-for-byte.
    loaded = load_config(vault)
    assert loaded.llm.api_key == NASTY
    assert loaded.llm.base_url == "http://example.test/v1\n"
    assert loaded.llm.model == "model\twith\ttabs"


def test_synced_config_snapshot_round_trips_control_characters(tmp_path: Path) -> None:
    vault = _init_vault(tmp_path)
    cfg = KnowletConfig()
    cfg.llm.model = NASTY

    save_config(vault, cfg)

    with synced_config_snapshot_path(vault).open("rb") as f:
        data = tomllib.load(f)
    assert data["llm"]["model"] == NASTY


def test_config_save_refuses_to_write_unparseable_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Self-check: if the serializer ever produces invalid TOML, the
    existing good file must stay untouched and the save must raise."""
    vault = _init_vault(tmp_path)
    save_config(vault, KnowletConfig())
    before = config_path(vault).read_bytes()

    monkeypatch.setattr(config_mod, "_toml_value", lambda v: '"broken\n"')
    with pytest.raises(ValueError):
        save_config(vault, KnowletConfig())

    assert config_path(vault).read_bytes() == before
    leftovers = [p.name for p in config_path(vault).parent.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


# ------------------------------------------------------------- quick-actions.toml


def test_quick_action_round_trips_control_characters(tmp_path: Path) -> None:
    store = QuickActionStore(vault_root=tmp_path)
    action = QuickAction(
        id=new_action_id(),
        name=NASTY,
        description="desc\nsecond line",
        shortcut="Cmd+\tX",
        params=CreateNoteParams(folder="daily", title_template="{{date}}\n"),
    )

    store.upsert(action)

    with quick_actions_path(tmp_path).open("rb") as f:
        tomllib.load(f)
    loaded = store.load()
    assert len(loaded) == 1
    got = loaded[0]
    assert got.name == NASTY
    assert got.description == "desc\nsecond line"
    assert got.shortcut == "Cmd+\tX"
    assert got.params.title_template == "{{date}}\n"


def test_quick_actions_save_refuses_to_write_unparseable_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from knowlet.core import quick_actions as qa_mod

    store = QuickActionStore(vault_root=tmp_path)
    good = QuickAction(
        id=new_action_id(),
        name="good",
        params=CreateNoteParams(folder="", title_template="x"),
    )
    store.upsert(good)
    before = quick_actions_path(tmp_path).read_bytes()

    monkeypatch.setattr(qa_mod, "_toml_value", lambda v: '"broken\n"')
    with pytest.raises(ValueError):
        store.save([good])

    assert quick_actions_path(tmp_path).read_bytes() == before
    assert [a.id for a in store.load()] == [good.id]
