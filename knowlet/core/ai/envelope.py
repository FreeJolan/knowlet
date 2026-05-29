"""7-layer prompt envelope (ADR-0024 §3.1).

All AI roles in knowlet (chat companion / capture extractor / editor
advisor / search booster / linter / tidy advisor / reorg planner)
share this envelope so they get consistent context, audit, and
per-role lazy loading.

Each "layer" is an XML-tagged block in the system prompt. The ADR
documents 8 named layers; only those the role's :class:`RoleConfig`
declares are rendered. Missing source data (no ``user_profile.md``,
no audit events yet, empty vault) collapses cleanly to "skip the
layer" — the framework never raises just because optional context
is absent.

Public surface:

- :class:`Layer`           — one rendered envelope layer
- :class:`LayerSource`     — Protocol; concrete sources live in
  :mod:`knowlet.core.ai.layers`
- :class:`EnvelopeContext` — bundle of vault / index / audit / config
  threaded through every source
- :class:`RoleConfig`      — declares which layers this role needs +
  role-specific system instruction / rules / examples
- :class:`Envelope`        — assembled bundle ready for an LLM call
- :func:`build_envelope`   — main entry point
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

# Canonical render order. ADR-0024 §3.1 documents these as the
# named tags an envelope may contain. ``task`` is special — it's
# rendered as a user message, not part of the system prompt, but
# we keep it in the order tuple so role configs can omit / include
# it uniformly.
LAYER_ORDER: tuple[str, ...] = (
    "knowlet-system",
    "user-profile",
    "wiki-schema",
    "vault-shape",
    "recent-activity",
    "task",
    "rules",
    "examples",
)


# ------------------------------------------------------------ Layer


@dataclass(frozen=True)
class Layer:
    """A single rendered envelope layer."""

    tag: str
    content: str
    src: str | None = None  # provenance hint (file path / "derived" / "role-config")

    def render(self) -> str:
        """Wrap content in the XML tag, with optional ``src`` attribute."""
        attr = f' src="{self.src}"' if self.src else ""
        return f"<{self.tag}{attr}>\n{self.content.strip()}\n</{self.tag}>"

    @property
    def byte_count(self) -> int:
        return len(self.render().encode("utf-8"))


# -------------------------------------------------- EnvelopeContext


@dataclass
class EnvelopeContext:
    """Shared context threaded through every :class:`LayerSource`.

    Most layers only need a subset of these. Sources that need a
    field missing here (e.g. ``audit_store=None``) should return
    ``None`` rather than raise — the framework drops missing layers
    silently. Test harnesses can pass ``EnvelopeContext()`` (all
    ``None``) and exercise role logic without a full vault.
    """

    vault: Any = None  # knowlet.core.vault.Vault | None
    index: Any = None  # knowlet.core.index.Index | None
    audit_store: Any = None  # knowlet.core.audit_log.AuditEventStore | None
    config: Any = None  # knowlet.config.KnowletConfig | None


# ---------------------------------------------------- LayerSource


@runtime_checkable
class LayerSource(Protocol):
    """Produces one envelope layer (or opts out).

    Implementations live in :mod:`knowlet.core.ai.layers` and self-
    register at import time via :func:`register_source`.
    """

    tag: str

    def render(
        self, ctx: EnvelopeContext, task: dict[str, Any]
    ) -> Layer | None:
        """Return a :class:`Layer`, or ``None`` to skip this layer."""
        ...


# ------------------------------------------------------ RoleConfig


@dataclass
class RoleConfig:
    """Declares which layers a role consumes and its role-specific text.

    ``system_instruction`` becomes the body of ``<knowlet-system>``;
    ``rules`` and ``examples`` become the bodies of ``<rules>`` and
    ``<examples>`` respectively. The remaining layers come from
    registered :class:`LayerSource` instances keyed by tag.
    """

    role: str
    layer_tags: tuple[str, ...]
    system_instruction: str
    rules: str = ""
    examples: str = ""


# -------------------------------------------------------- Envelope


@dataclass
class Envelope:
    """Assembled envelope ready for an LLM call.

    ``system_layers`` are concatenated (in canonical order) into one
    OpenAI ``system`` message. ``task_layer`` — when present — is
    rendered as the OpenAI ``user`` message (one-shot roles like
    editor advisor / capture extractor). Chat companion typically
    has no ``task_layer`` and passes the live user message + chat
    history through :meth:`to_chat_messages`.
    """

    role: str
    system_layers: list[Layer]
    task_layer: Layer | None

    def system_prompt(self) -> str:
        return "\n\n".join(layer.render() for layer in self.system_layers)

    def to_chat_messages(
        self,
        *,
        history: list[dict[str, Any]] | None = None,
        user_message: str | None = None,
    ) -> list[dict[str, Any]]:
        """OpenAI Chat Completions format.

        Behavior:

        - System message = concatenation of ``system_layers``.
        - If ``history`` is given, append it next (chat companion path).
        - Final user message comes from ``user_message`` if provided,
          else from ``task_layer.content``. If neither is set the
          returned list contains only the system message — callers
          handle that case (e.g., warmup pings).
        """
        msgs: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt()}
        ]
        if history:
            msgs.extend(history)
        if user_message is not None:
            msgs.append({"role": "user", "content": user_message})
        elif self.task_layer is not None:
            msgs.append({"role": "user", "content": self.task_layer.content})
        return msgs

    @property
    def total_bytes(self) -> int:
        n = sum(layer.byte_count for layer in self.system_layers)
        if self.task_layer:
            n += self.task_layer.byte_count
        return n


# -------------------------------------------------------- registry

_SOURCES: dict[str, LayerSource] = {}
_ROLES: dict[str, RoleConfig] = {}


def register_source(source: LayerSource) -> None:
    """Register a :class:`LayerSource` under its tag.

    Idempotent: re-registering the same tag overwrites the previous
    binding (useful for tests injecting fakes)."""
    _SOURCES[source.tag] = source


def register_role(cfg: RoleConfig) -> None:
    """Register (or overwrite) a role config."""
    _ROLES[cfg.role] = cfg


def get_role(role: str) -> RoleConfig:
    if role not in _ROLES:
        raise KeyError(
            f"unknown AI role {role!r}; register via register_role() "
            f"first. Known roles: {sorted(_ROLES)}"
        )
    return _ROLES[role]


def known_roles() -> list[str]:
    return sorted(_ROLES)


def known_tags() -> tuple[str, ...]:
    return LAYER_ORDER


# Tags handled inline by :func:`build_envelope` itself (their content
# comes from :class:`RoleConfig`, not from a registered source).
_ROLE_OWNED_TAGS: frozenset[str] = frozenset(
    {"knowlet-system", "rules", "examples"}
)


# ---------------------------------------------------- build_envelope


def build_envelope(
    role: str,
    task: dict[str, Any] | None,
    ctx: EnvelopeContext,
) -> Envelope:
    """Assemble a full envelope for ``role``.

    Layers are walked in :data:`LAYER_ORDER`. For each tag that the
    role's :class:`RoleConfig` declares:

    - ``knowlet-system`` / ``rules`` / ``examples`` come from the
      role config itself.
    - ``task`` is taken from the caller's ``task`` dict via the
      registered ``task`` source; it is split off into
      :attr:`Envelope.task_layer` (the user message) rather than the
      system prompt.
    - Other tags ask their registered :class:`LayerSource`. Sources
      that return ``None`` (missing data) cause the layer to be
      silently skipped.

    Unknown role → :class:`KeyError`. Roles without a registered
    source for a declared tag → that tag is silently skipped (lets
    tests register partial source sets).
    """
    cfg = get_role(role)
    task = task or {}

    system_layers: list[Layer] = []
    task_layer: Layer | None = None

    for tag in LAYER_ORDER:
        if tag not in cfg.layer_tags:
            continue

        if tag == "knowlet-system":
            system_layers.append(
                Layer(
                    tag="knowlet-system",
                    content=cfg.system_instruction,
                    src="role-config",
                )
            )
            continue
        if tag == "rules":
            if cfg.rules.strip():
                system_layers.append(
                    Layer(tag="rules", content=cfg.rules, src="role-config")
                )
            continue
        if tag == "examples":
            if cfg.examples.strip():
                system_layers.append(
                    Layer(
                        tag="examples",
                        content=cfg.examples,
                        src="role-config",
                    )
                )
            continue

        source = _SOURCES.get(tag)
        if source is None:
            # No registered source → silently skip (partial registration OK).
            continue
        rendered = source.render(ctx, task)
        if rendered is None:
            continue
        if tag == "task":
            task_layer = rendered
        else:
            system_layers.append(rendered)

    return Envelope(
        role=role,
        system_layers=system_layers,
        task_layer=task_layer,
    )
