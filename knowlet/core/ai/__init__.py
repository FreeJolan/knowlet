"""Phase 3 — AI 子系统模块。

每个 AI role 一个模块(per ADR-0024 §4),按 Phase 3 stages 推进:

- ``envelope`` + ``layers`` — Stage 1 ✅ — 7 层 prompt envelope 框架
  (ADR-0024 §3.1) + 7 个 ADR-0024 role 的 placeholder 配置。
- ``retrieval/*``           — Stage 1(retrieval v2: query expansion /
  LLM rerank / smart chunking)。
- ``role/*``                — Stages 3-6,逐个 role 填充真 prompt
  templates + 输入输出 schemas。

Import side effect: importing this package registers the 7 roles and
5 layer sources in the envelope registry (see ``layers.py``).
"""

from __future__ import annotations

# Importing ``layers`` registers all sources + roles. Without this
# explicit re-export, ``from knowlet.core.ai import envelope`` would
# leave the registry empty. We keep ``layers`` private to the module
# itself — callers use ``build_envelope`` / ``known_roles`` etc.
from knowlet.core.ai import layers  # noqa: F401 — registers on import
from knowlet.core.ai.envelope import (
    Envelope,
    EnvelopeContext,
    Layer,
    LayerSource,
    RoleConfig,
    build_envelope,
    known_roles,
    known_tags,
    register_role,
    register_source,
)

__all__ = [
    "Envelope",
    "EnvelopeContext",
    "Layer",
    "LayerSource",
    "RoleConfig",
    "build_envelope",
    "known_roles",
    "known_tags",
    "register_role",
    "register_source",
]
