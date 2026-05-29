"""Concrete :class:`LayerSource` implementations + role registry.

Self-registers all sources and the 7 ADR-0024 roles at import time.
Real per-role ``system_instruction`` / ``rules`` / ``examples`` text
is filled in when each role's slice ships (Phase 3 Stages 3-6); for
now the role configs use a clearly-marked placeholder so the envelope
framework is exercisable end-to-end.

Source-by-source notes:

- ``user-profile`` reads ``vault/.knowlet/user_profile.md`` via
  :func:`knowlet.core.user_profile.read_profile`.
- ``wiki-schema`` does multi-level merge of
  ``$KNOWLET_HOME/wiki_schema.md`` (or ``~/.knowlet/wiki_schema.md``
  if not overridden) + ``vault/.knowlet/wiki_schema.md`` — per
  ADR-0024 §3.4 borrowed from mature agents' multi-level rules-file
  merge. Per-vault wins by appending last.
- ``vault-shape`` derives ``total_notes`` / top folders / max depth
  by walking :meth:`Vault.iter_note_paths` (cheap; no DB hit needed).
- ``recent-activity`` queries :class:`AuditEventStore` for events in
  the last ``window_days``; sorted oldest-first per the store's API,
  rendered newest-last so it reads as a timeline.
- ``task`` JSON-encodes the caller's task dict.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from knowlet.core.ai.envelope import (
    EnvelopeContext,
    Layer,
    RoleConfig,
    register_role,
    register_source,
)


def knowlet_home() -> Path:
    """User-level knowlet config dir, parallel to ``~/.codex/``.

    Defaults to ``~/.knowlet/``. Override via ``KNOWLET_HOME`` env var
    (used by tests to avoid leaking the dev's real home into fixtures,
    and by power users who want config in a non-standard location)."""
    override = os.environ.get("KNOWLET_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".knowlet"

# ----------------------------------------------------- static layers


@dataclass
class UserProfileSource:
    tag: str = "user-profile"

    def render(
        self, ctx: EnvelopeContext, task: dict[str, Any]
    ) -> Layer | None:
        vault = ctx.vault
        if vault is None:
            return None
        path = vault.profile_path
        if not path.exists():
            return None
        # Imported lazily so this module loads cleanly even if a
        # downstream tweak removes user_profile (unlikely, but the
        # envelope framework should be robust to it).
        from knowlet.core.user_profile import read_profile

        profile = read_profile(path)
        if profile is None or not profile.body.strip():
            return None
        return Layer(
            tag=self.tag,
            content=profile.body.strip(),
            src=str(path.relative_to(vault.root)),
        )


@dataclass
class WikiSchemaSource:
    """``vault/.knowlet/wiki_schema.md`` — vault writing conventions.

    Multi-level merge (Phase 3 Stage 2, per ADR-0024 §3.4 "borrowed
    from mature agents' multi-level rules-file merge"):

    1. ``~/.knowlet/wiki_schema.md`` (global, cross-vault) — your
       writing conventions that apply to **every** vault you open
       (naming, voice, default tag conventions).
    2. ``vault/.knowlet/wiki_schema.md`` (per-vault) — overrides /
       additions specific to this vault.

    Order: global first, per-vault appended (per-vault wins by
    coming last; the LLM weights later instructions more). Each
    level is independently optional; missing files collapse to skip.
    Empty result (neither file exists) → return None.
    """

    tag: str = "wiki-schema"
    filename: str = "wiki_schema.md"

    def render(
        self, ctx: EnvelopeContext, task: dict[str, Any]
    ) -> Layer | None:
        vault = ctx.vault
        if vault is None:
            return None
        parts: list[str] = []
        srcs: list[str] = []

        # Global level. ``~/.knowlet/`` is the cross-vault dotdir,
        # parallel to git's ``~/.gitconfig`` or Codex's user-level
        # ``~/.codex/AGENTS.md``. Optional — most users may only set
        # the per-vault file. Test fixtures override via ``KNOWLET_HOME``
        # so a developer's real ``~/.knowlet/`` doesn't bleed into
        # vault-scoped tests.
        global_path = knowlet_home() / self.filename
        if global_path.exists():
            global_body = global_path.read_text(encoding="utf-8").strip()
            if global_body:
                parts.append(
                    f"## (global) {global_path}\n\n{global_body}"
                )
                srcs.append("~/.knowlet/" + self.filename)

        # Per-vault level. Wins by coming last (LLMs weight later
        # instructions more heavily — by convention; not a strict rule).
        local_path = vault.state_dir / self.filename
        if local_path.exists():
            local_body = local_path.read_text(encoding="utf-8").strip()
            if local_body:
                parts.append(
                    f"## (vault) {local_path.relative_to(vault.root)}\n\n{local_body}"
                )
                srcs.append(".knowlet/" + self.filename)

        if not parts:
            return None
        return Layer(
            tag=self.tag,
            content="\n\n".join(parts),
            src=" + ".join(srcs),
        )


# ---------------------------------------------------- derived layers


@dataclass
class VaultShapeSource:
    tag: str = "vault-shape"
    top_n_folders: int = 5

    def render(
        self, ctx: EnvelopeContext, task: dict[str, Any]
    ) -> Layer | None:
        vault = ctx.vault
        if vault is None:
            return None
        folder_counts: Counter[str] = Counter()
        max_depth = 0
        total = 0
        for p in vault.iter_note_paths():
            total += 1
            rel = p.relative_to(vault.notes_dir)
            parts = rel.parts[:-1]  # exclude file itself
            if parts:
                folder_counts[parts[0]] += 1
                max_depth = max(max_depth, len(parts))
        if total == 0:
            return None  # empty vault → skip the shape layer
        lines: list[str] = [f"total_notes: {total}"]
        top = folder_counts.most_common(self.top_n_folders)
        if top:
            lines.append("top_folders:")
            lines.extend(f"  - {name}: {count}" for name, count in top)
        lines.append(f"max_depth: {max_depth}")
        return Layer(tag=self.tag, content="\n".join(lines), src="derived")


@dataclass
class RecentActivitySource:
    """Last :attr:`window_days` of audit events, oldest-first."""

    tag: str = "recent-activity"
    window_days: int = 7
    limit: int = 20

    def render(
        self, ctx: EnvelopeContext, task: dict[str, Any]
    ) -> Layer | None:
        store = ctx.audit_store
        if store is None:
            return None
        since_dt = datetime.now(UTC) - timedelta(days=self.window_days)
        try:
            events = list(
                store.query(since=since_dt.isoformat(), limit=self.limit)
            )
        except Exception:
            # Bad DB / locked / schema mismatch — skip rather than fail
            # envelope assembly. The envelope must never break LLM calls.
            return None
        if not events:
            return None
        lines: list[str] = []
        for ev in events:
            ts = (ev.ts or "")[:10]  # YYYY-MM-DD
            label = ev.payload.get("title") or ev.payload.get("name") or ev.entity_id
            lines.append(f"- {ts} {ev.kind} {label}".rstrip())
        return Layer(
            tag=self.tag, content="\n".join(lines), src="vault.events"
        )


# -------------------------------------------------------- task layer


@dataclass
class TaskSource:
    """Dynamic per-call task input, JSON-encoded.

    The role's ``system_instruction`` is responsible for telling the
    model how to interpret each field. JSON encoding keeps structured
    fields unambiguous and works well with structured-output prompts.
    """

    tag: str = "task"

    def render(
        self, ctx: EnvelopeContext, task: dict[str, Any]
    ) -> Layer | None:
        if not task:
            return None
        body = json.dumps(task, ensure_ascii=False, indent=2)
        return Layer(tag=self.tag, content=body, src="caller")


# Self-register all sources at import time. Tests / callers that import
# anything from this module will get them in the envelope registry.
register_source(UserProfileSource())
register_source(WikiSchemaSource())
register_source(VaultShapeSource())
register_source(RecentActivitySource())
register_source(TaskSource())


# ------------------------------------------------------ role registry

# Layer subsets per ADR-0024 §3.3. ``knowlet-system``, ``rules``, and
# ``examples`` are role-owned (RoleConfig fields, not LayerSource);
# all three are included by default.

_CHAT_COMPANION_LAYERS: tuple[str, ...] = (
    "knowlet-system",
    "user-profile",
    "wiki-schema",
    "vault-shape",
    "recent-activity",
    "rules",
    "examples",
)

_EDITOR_ADVISOR_LAYERS: tuple[str, ...] = (
    "knowlet-system",
    "wiki-schema",
    "vault-shape",
    "task",
    "rules",
    "examples",
)

_CAPTURE_LAYERS: tuple[str, ...] = (
    "knowlet-system",
    "wiki-schema",
    "task",
    "rules",
    "examples",
)

_LINTER_LAYERS: tuple[str, ...] = (
    "knowlet-system",
    "wiki-schema",
    "vault-shape",
    "recent-activity",
    "task",
    "rules",
    "examples",
)

_TIDY_LAYERS: tuple[str, ...] = _LINTER_LAYERS

_REORG_LAYERS: tuple[str, ...] = (
    "knowlet-system",
    "wiki-schema",
    "vault-shape",
    "task",
    "rules",
    "examples",
)

_SEARCH_BOOSTER_LAYERS: tuple[str, ...] = (
    "knowlet-system",
    "task",
    "rules",
)


_PLACEHOLDER_INSTRUCTION = (
    "Placeholder. The real system instruction for this role lands in "
    "its implementing slice (Phase 3 Stages 3-6). For now this exists "
    "so the envelope framework can be tested end-to-end."
)


def _register_placeholder_roles() -> None:
    pairs: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("chat_companion", _CHAT_COMPANION_LAYERS),
        ("editor_advisor", _EDITOR_ADVISOR_LAYERS),
        ("capture_extractor", _CAPTURE_LAYERS),
        ("linter", _LINTER_LAYERS),
        ("tidy_advisor", _TIDY_LAYERS),
        ("reorg_planner", _REORG_LAYERS),
        ("search_booster", _SEARCH_BOOSTER_LAYERS),
    )
    for role, layers in pairs:
        register_role(
            RoleConfig(
                role=role,
                layer_tags=layers,
                system_instruction=_PLACEHOLDER_INSTRUCTION,
            )
        )


_register_placeholder_roles()
