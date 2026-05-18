"""Tests for the AI envelope framework (Phase 3 Stage 1 — AI 底盘).

Covers:
- Layer XML rendering (with / without src attribute).
- Role registry: all 7 ADR-0024 roles are pre-registered.
- ``build_envelope`` lazy loading: each role pulls only its
  declared layer subset, even when more source data is available.
- Static / derived / task source rendering against a real Vault
  fixture.
- ``to_chat_messages``: history + override semantics.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from knowlet.core.ai import (
    Envelope,
    EnvelopeContext,
    Layer,
    RoleConfig,
    build_envelope,
    known_roles,
    known_tags,
    register_role,
)
from knowlet.core.audit_log import AuditEvent, AuditEventStore
from knowlet.core.user_profile import UserProfile, write_profile
from knowlet.core.vault import Vault


# ----------------------------------------------------------- Layer


def test_layer_render_wraps_in_tag() -> None:
    layer = Layer(
        tag="user-profile",
        content="hello there",
        src=".knowlet/user_profile.md",
    )
    out = layer.render()
    assert out.startswith('<user-profile src=".knowlet/user_profile.md">')
    assert out.endswith("</user-profile>")
    assert "hello there" in out


def test_layer_render_without_src() -> None:
    layer = Layer(tag="rules", content="ALWAYS X")
    assert layer.render() == "<rules>\nALWAYS X\n</rules>"


def test_layer_byte_count_includes_tag_overhead() -> None:
    layer = Layer(tag="t", content="abc")
    # "<t>\nabc\n</t>" = 12 bytes
    assert layer.byte_count == 12


# ----------------------------------------------------- registry


def test_seven_adr_roles_pre_registered() -> None:
    """ADR-0024 §4 names exactly 7 roles. All must be in the registry."""
    expected = {
        "chat_companion",
        "capture_extractor",
        "editor_advisor",
        "search_booster",
        "linter",
        "tidy_advisor",
        "reorg_planner",
    }
    assert expected.issubset(set(known_roles()))


def test_canonical_tag_order() -> None:
    # The 8 tags in ADR-0024 §3.1.
    assert known_tags() == (
        "knowlet-system",
        "user-profile",
        "wiki-schema",
        "vault-shape",
        "recent-activity",
        "task",
        "rules",
        "examples",
    )


def test_register_role_idempotent_overwrites() -> None:
    register_role(
        RoleConfig(
            role="_test_role",
            layer_tags=("knowlet-system",),
            system_instruction="first",
        )
    )
    register_role(
        RoleConfig(
            role="_test_role",
            layer_tags=("knowlet-system",),
            system_instruction="second",
        )
    )
    env = build_envelope("_test_role", task=None, ctx=EnvelopeContext())
    assert "second" in env.system_prompt()
    assert "first" not in env.system_prompt()


def test_unknown_role_raises() -> None:
    with pytest.raises(KeyError):
        build_envelope("not_a_role", task=None, ctx=EnvelopeContext())


# ----------------------------------------------- build_envelope


def test_build_envelope_no_vault_still_works() -> None:
    """Roles that don't need vault context build cleanly."""
    env = build_envelope(
        "editor_advisor",
        task={"title": "X"},
        ctx=EnvelopeContext(),
    )
    assert env.role == "editor_advisor"
    # system_instruction (placeholder) is always present.
    assert "Placeholder" in env.system_prompt()
    # Task layer rendered from the task dict.
    assert env.task_layer is not None
    assert '"title": "X"' in env.task_layer.content


def test_build_envelope_includes_user_profile_when_present(
    tmp_path: Path,
) -> None:
    v = Vault(tmp_path)
    v.init_layout()
    write_profile(
        v.profile_path,
        UserProfile(body="I am Alice, an ML researcher."),
    )
    env = build_envelope(
        "chat_companion",
        task=None,
        ctx=EnvelopeContext(vault=v),
    )
    sp = env.system_prompt()
    assert "<user-profile" in sp
    assert "Alice" in sp


def test_build_envelope_skips_missing_user_profile(tmp_path: Path) -> None:
    v = Vault(tmp_path)
    v.init_layout()
    env = build_envelope(
        "chat_companion",
        task=None,
        ctx=EnvelopeContext(vault=v),
    )
    assert "<user-profile" not in env.system_prompt()


def test_lazy_loading_skips_layers_not_in_role(tmp_path: Path) -> None:
    """editor_advisor must NOT include user-profile, even when present."""
    v = Vault(tmp_path)
    v.init_layout()
    write_profile(
        v.profile_path, UserProfile(body="I am Alice.")
    )
    env = build_envelope(
        "editor_advisor",
        task={"x": 1},
        ctx=EnvelopeContext(vault=v),
    )
    assert "<user-profile" not in env.system_prompt()


# ------------------------------------------------ vault-shape


def test_vault_shape_with_notes(tmp_path: Path) -> None:
    v = Vault(tmp_path)
    v.init_layout()
    (v.notes_dir / "papers").mkdir()
    (v.notes_dir / "papers" / "rag.md").write_text(
        "---\nid: a1\n---\n# RAG\n", encoding="utf-8"
    )
    (v.notes_dir / "papers" / "llm.md").write_text(
        "---\nid: a2\n---\n# LLM\n", encoding="utf-8"
    )
    (v.notes_dir / "diary").mkdir()
    (v.notes_dir / "diary" / "today.md").write_text(
        "---\nid: a3\n---\n# Today\n", encoding="utf-8"
    )

    env = build_envelope(
        "editor_advisor",
        task={"x": 1},
        ctx=EnvelopeContext(vault=v),
    )
    sp = env.system_prompt()
    assert "<vault-shape" in sp
    assert "total_notes: 3" in sp
    # Both folders show up under top_folders.
    assert "papers: 2" in sp
    assert "diary: 1" in sp


def test_vault_shape_empty_vault_skipped(tmp_path: Path) -> None:
    v = Vault(tmp_path)
    v.init_layout()
    env = build_envelope(
        "editor_advisor",
        task={"x": 1},
        ctx=EnvelopeContext(vault=v),
    )
    assert "<vault-shape" not in env.system_prompt()


# ----------------------------------------------- recent-activity


def test_recent_activity_with_events(tmp_path: Path) -> None:
    v = Vault(tmp_path)
    v.init_layout()
    store = AuditEventStore(v.state_dir / "events.sqlite")
    store.append(
        AuditEvent(
            kind="note.created",
            entity_type="note",
            entity_id="n1",
            payload={"title": "RAG paper notes"},
        )
    )
    env = build_envelope(
        "chat_companion",
        task=None,
        ctx=EnvelopeContext(vault=v, audit_store=store),
    )
    sp = env.system_prompt()
    assert "<recent-activity" in sp
    assert "RAG paper notes" in sp


def test_recent_activity_no_events_skipped(tmp_path: Path) -> None:
    v = Vault(tmp_path)
    v.init_layout()
    store = AuditEventStore(v.state_dir / "events.sqlite")
    env = build_envelope(
        "chat_companion",
        task=None,
        ctx=EnvelopeContext(vault=v, audit_store=store),
    )
    assert "<recent-activity" not in env.system_prompt()


# ------------------------------------------- wiki-schema


def test_wiki_schema_included_when_present(tmp_path: Path) -> None:
    v = Vault(tmp_path)
    v.init_layout()
    (v.state_dir / "wiki_schema.md").write_text(
        "## Naming\nUse kebab-case for filenames.\n", encoding="utf-8"
    )
    env = build_envelope(
        "capture_extractor",
        task={"url": "https://example.com"},
        ctx=EnvelopeContext(vault=v),
    )
    sp = env.system_prompt()
    assert "<wiki-schema" in sp
    assert "kebab-case" in sp


def test_wiki_schema_empty_file_skipped(tmp_path: Path) -> None:
    v = Vault(tmp_path)
    v.init_layout()
    (v.state_dir / "wiki_schema.md").write_text("   \n  \n", encoding="utf-8")
    env = build_envelope(
        "capture_extractor",
        task={"url": "x"},
        ctx=EnvelopeContext(vault=v),
    )
    assert "<wiki-schema" not in env.system_prompt()


# -------------------------------------------- task layer


def test_task_layer_becomes_user_message(tmp_path: Path) -> None:
    env = build_envelope(
        "editor_advisor",
        task={"title": "Mintlify FS", "body_head": "..."},
        ctx=EnvelopeContext(),
    )
    msgs = env.to_chat_messages()
    assert msgs[0]["role"] == "system"
    assert msgs[-1]["role"] == "user"
    assert "Mintlify FS" in msgs[-1]["content"]


def test_empty_task_skipped() -> None:
    env = build_envelope(
        "editor_advisor", task={}, ctx=EnvelopeContext()
    )
    assert env.task_layer is None


# -------------------------------------------- to_chat_messages


def test_to_chat_messages_with_user_message_override() -> None:
    env = build_envelope(
        "editor_advisor",
        task={"x": 1},
        ctx=EnvelopeContext(),
    )
    msgs = env.to_chat_messages(user_message="explicit msg")
    # Override beats task_layer.
    assert msgs[-1]["content"] == "explicit msg"


def test_to_chat_messages_with_history() -> None:
    env = build_envelope(
        "chat_companion", task=None, ctx=EnvelopeContext()
    )
    history = [
        {"role": "user", "content": "earlier question"},
        {"role": "assistant", "content": "earlier answer"},
    ]
    msgs = env.to_chat_messages(history=history, user_message="follow up")
    assert len(msgs) == 4  # system + 2 history + final user
    assert msgs[1]["content"] == "earlier question"
    assert msgs[2]["content"] == "earlier answer"
    assert msgs[-1]["content"] == "follow up"


def test_to_chat_messages_no_user_input_returns_system_only() -> None:
    """Edge case: no task, no override, no history → just the system msg."""
    env = build_envelope(
        "chat_companion", task=None, ctx=EnvelopeContext()
    )
    msgs = env.to_chat_messages()
    assert len(msgs) == 1
    assert msgs[0]["role"] == "system"


# -------------------------------------------- total_bytes


def test_total_bytes_counts_all_layers(tmp_path: Path) -> None:
    v = Vault(tmp_path)
    v.init_layout()
    write_profile(v.profile_path, UserProfile(body="Alice"))
    env = build_envelope(
        "chat_companion",
        task=None,
        ctx=EnvelopeContext(vault=v),
    )
    # At minimum: knowlet-system placeholder + user-profile layer.
    # Each non-empty layer should add bytes.
    assert env.total_bytes > 100
