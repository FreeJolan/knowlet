"""Tests for the i18n layer (ADR-0010)."""

import os
from pathlib import Path

from fastapi.testclient import TestClient

from knowlet.config import KnowletConfig, save_config
from knowlet.core.i18n import (
    SUPPORTED_LANGUAGES,
    all_keys,
    current_language,
    init_from_env,
    set_language,
    t,
)
from knowlet.core.user_profile import (
    DEFAULT_PROFILE_TEMPLATE_EN,
    DEFAULT_PROFILE_TEMPLATE_ZH,
    default_profile_template,
)
from knowlet.core.vault import Vault
from knowlet.web.server import create_app


# ------------------------------------------------------- core/i18n


def test_default_is_english():
    set_language("en")
    assert current_language() == "en"
    assert t("vault.init.title") == "vault init"
    assert t("inbox.action.keep") == "Keep as note"


def test_zh_translation_works():
    set_language("zh")
    try:
        assert t("vault.init.title") == "vault 初始化"
        assert t("inbox.action.keep") == "收入笔记"
    finally:
        set_language("en")


def test_missing_key_returns_key_itself():
    set_language("en")
    assert t("definitely.missing.key") == "definitely.missing.key"


def test_missing_zh_falls_back_to_en():
    # Add a key only in EN by reaching into the module — easier than wiring a
    # fixture. We use a key that's guaranteed not to be translated yet.
    from knowlet.core import i18n

    i18n._EN["test.only_en"] = "only english"  # type: ignore[attr-defined]
    try:
        set_language("zh")
        assert t("test.only_en") == "only english"
    finally:
        del i18n._EN["test.only_en"]  # type: ignore[attr-defined]
        set_language("en")


def test_variable_interpolation():
    set_language("en")
    out = t("vault.created", root="/some/path")
    assert "/some/path" in out


def test_unsupported_language_falls_back():
    out = set_language("xx-YY")
    assert out == "en"
    assert current_language() == "en"


def test_set_language_normalizes_locale_code():
    out = set_language("zh-CN")
    assert out == "zh"
    set_language("en")


def test_init_from_env_reads_knowlet_lang(monkeypatch):
    monkeypatch.setenv("KNOWLET_LANG", "zh")
    out = init_from_env()
    try:
        assert out == "zh"
        assert t("inbox.action.keep") == "收入笔记"
    finally:
        set_language("en")


def test_all_keys_returns_full_catalog():
    en = all_keys("en")
    zh = all_keys("zh")
    assert "vault.init.title" in en
    assert "vault.init.title" in zh
    assert isinstance(en[next(iter(en))], str)


def test_supported_languages_contains_en_and_zh():
    assert "en" in SUPPORTED_LANGUAGES
    assert "zh" in SUPPORTED_LANGUAGES


def test_language_isolated_per_thread():
    """One thread setting language must not leak into another.

    Pre-2026-05-02 the language was a module global; a scheduler thread
    setting `zh` would silently flip the language under a request handler.
    Now backed by `contextvars.ContextVar`, contexts are isolated.
    """
    import threading

    set_language("en")
    box: dict[str, str] = {}

    def child() -> None:
        # Fresh threading.Thread starts with the default contextvars copy.
        set_language("zh")
        box["child"] = current_language()

    t = threading.Thread(target=child)
    t.start()
    t.join()

    assert box["child"] == "zh"
    # The main thread's language is unchanged by the child's set_language.
    assert current_language() == "en"


# ------------------------------------------------------- profile template


def test_default_profile_template_returns_english_by_default():
    out = default_profile_template()
    assert out == DEFAULT_PROFILE_TEMPLATE_EN
    assert "About me" in out
    assert "Current focus" in out


def test_default_profile_template_zh():
    out = default_profile_template("zh")
    assert out == DEFAULT_PROFILE_TEMPLATE_ZH
    assert "当前关注" in out


def test_default_profile_template_unknown_lang_falls_back_to_en():
    out = default_profile_template("xx")
    assert out == DEFAULT_PROFILE_TEMPLATE_EN


# ------------------------------------------------------- config


def test_config_general_defaults_to_en(tmp_path: Path):
    cfg = KnowletConfig()
    assert cfg.general.language == "en"


def test_config_round_trip_preserves_language(tmp_path: Path):
    from knowlet.config import load_config

    v = Vault(tmp_path)
    v.init_layout()
    cfg = KnowletConfig()
    cfg.general.language = "zh"
    save_config(v.root, cfg)
    loaded = load_config(v.root)
    assert loaded.general.language == "zh"


# ------------------------------------------------------- web


def test_web_health_returns_language(tmp_path: Path):
    v = Vault(tmp_path)
    v.init_layout()
    cfg = KnowletConfig()
    cfg.general.language = "zh"
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = "stub"
    save_config(v.root, cfg)

    client = TestClient(create_app(v, cfg))
    h = client.get("/api/health").json()
    assert h["language"] == "zh"
    assert "supported_languages" in h
    assert "en" in h["supported_languages"]


def test_web_i18n_endpoint_serves_catalog(tmp_path: Path):
    v = Vault(tmp_path)
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = "stub"
    save_config(v.root, cfg)

    client = TestClient(create_app(v, cfg))
    en = client.get("/api/i18n/en").json()
    assert en["vault.init.title"] == "vault init"
    zh = client.get("/api/i18n/zh").json()
    assert zh["vault.init.title"] == "vault 初始化"

    # Unknown language → fallback to default.
    bogus = client.get("/api/i18n/xx").json()
    assert bogus["vault.init.title"] == "vault init"
