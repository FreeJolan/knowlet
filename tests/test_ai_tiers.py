"""ADR-0028 §1 — Tier 映射回归测试。"""

from __future__ import annotations

from knowlet.core.ai.tiers import (
    KNOWN_MODELS,
    RECOMMENDED_MODELS,
    ROLE_TIER_REQUIREMENTS,
    classify_model,
    is_role_enabled,
    profile_for_tier,
    recommended_for_provider,
)


# ----------------------------------------------------- classify_model


def test_classify_known_a_tier() -> None:
    assert classify_model("claude-opus-4-7") == "A"
    assert classify_model("claude-sonnet-4-6") == "A"
    assert classify_model("gpt-5") == "A"
    assert classify_model("gemini-2.5-pro") == "A"


def test_classify_known_b_tier() -> None:
    assert classify_model("claude-haiku-4-5") == "B"
    assert classify_model("gpt-4o-mini") == "B"
    assert classify_model("gemini-2.5-flash") == "B"


def test_classify_known_c_tier() -> None:
    assert classify_model("gpt-3.5-turbo") == "C"


def test_classify_unknown_model() -> None:
    """Models we don't recognize get ``"unknown"``, not silently
    promoted to A. The whole point of the tier system is to be honest
    about quality bars."""
    assert classify_model("some-local-llama") == "unknown"
    assert classify_model("") == "unknown"
    assert classify_model("claude-7000-mega") == "unknown"


def test_classify_dated_aliases() -> None:
    """Dated aliases (``claude-opus-4-7-20250929``) should resolve
    to the same tier as their stable id."""
    assert classify_model("claude-opus-4-7-20250929") == "A"
    assert classify_model("claude-sonnet-4-6-20250929") == "A"
    assert classify_model("claude-haiku-4-5-20251001") == "B"


# ----------------------------------------------------- profile_for_tier


def test_profile_tier_a_has_all_roles_enabled() -> None:
    p = profile_for_tier("A")
    assert p.tier == "A"
    # All known roles enabled at A.
    assert set(p.enabled_roles) == set(ROLE_TIER_REQUIREMENTS.keys())
    assert p.degraded_roles == []


def test_profile_tier_b_disables_high_demand_roles() -> None:
    p = profile_for_tier("B")
    assert "chat_companion" in p.enabled_roles  # chat always work
    assert "editor_advisor" in p.degraded_roles  # cross-note → A only
    assert "linter" in p.degraded_roles
    assert "tidy_advisor" in p.degraded_roles
    assert "reorg_planner" in p.degraded_roles


def test_profile_tier_c_only_chat() -> None:
    p = profile_for_tier("C")
    assert "chat_companion" in p.enabled_roles
    # Tier C is the strict floor — most everything else off.
    assert "editor_advisor" in p.degraded_roles
    assert "linter" in p.degraded_roles
    assert "capture_extractor" in p.degraded_roles


def test_profile_unknown_treated_as_c() -> None:
    """Unknown model = safest behavior = treat as C (so unrecognized
    locally-hosted small models don't accidentally get full feature
    access)."""
    unknown = profile_for_tier("unknown")
    c = profile_for_tier("C")
    assert unknown.enabled_roles == c.enabled_roles
    assert unknown.degraded_roles == c.degraded_roles


# ----------------------------------------------------- is_role_enabled


def test_is_role_enabled_a_tier_full_access() -> None:
    assert is_role_enabled("claude-opus-4-7", "linter") is True
    assert is_role_enabled("claude-opus-4-7", "editor_advisor") is True
    assert is_role_enabled("claude-opus-4-7", "chat_companion") is True


def test_is_role_enabled_b_tier_partial() -> None:
    assert is_role_enabled("claude-haiku-4-5", "chat_companion") is True
    assert is_role_enabled("claude-haiku-4-5", "capture_extractor") is True
    assert is_role_enabled("claude-haiku-4-5", "linter") is False
    assert is_role_enabled("claude-haiku-4-5", "editor_advisor") is False


def test_is_role_enabled_c_tier_chat_only() -> None:
    assert is_role_enabled("gpt-3.5-turbo", "chat_companion") is True
    assert is_role_enabled("gpt-3.5-turbo", "capture_extractor") is False
    assert is_role_enabled("gpt-3.5-turbo", "linter") is False


def test_is_role_enabled_unknown_model_treats_as_c() -> None:
    assert is_role_enabled("some-random-llama", "chat_companion") is True
    assert is_role_enabled("some-random-llama", "linter") is False


def test_is_role_enabled_unknown_role_defaults_disabled() -> None:
    """If callers ask for a role we don't know about, default to
    disabled (fail-safe; don't accidentally enable unaudited behavior)."""
    assert is_role_enabled("claude-opus-4-7", "fictional_role") is False


# ----------------------------------------------------- RECOMMENDED_MODELS


def test_recommended_models_have_consistent_tier() -> None:
    """Every entry in RECOMMENDED_MODELS should classify to its
    declared tier — drifts here indicate the table is out of sync
    with KNOWN_MODELS."""
    for rec in RECOMMENDED_MODELS:
        actual = classify_model(rec.model_id)
        assert actual == rec.tier, (
            f"{rec.display_name} declared {rec.tier} but "
            f"classify_model returned {actual}"
        )


def test_recommended_for_provider_filters() -> None:
    cliproxy = recommended_for_provider("cliproxyapi")
    assert len(cliproxy) >= 2
    assert all(m.provider == "cliproxyapi" for m in cliproxy)
    assert all(
        m.base_url_hint and m.base_url_hint.startswith("http://127.0.0.1:")
        for m in cliproxy
    )


def test_recommended_for_unknown_provider_empty() -> None:
    assert recommended_for_provider("does-not-exist") == []


def test_known_models_no_typos() -> None:
    """All tier values must be valid (catches typos like 'a' or 'b')."""
    valid = {"A", "B", "C"}
    for model_id, tier in KNOWN_MODELS.items():
        assert tier in valid, f"{model_id} has invalid tier {tier!r}"
