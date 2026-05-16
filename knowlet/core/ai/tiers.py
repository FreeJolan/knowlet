"""ADR-0028 §1 — 模型档位策略。

把已知 model id 映射到 Tier A/B/C,并描述每档对 knowlet AI role 的影响。
不调用任何 LLM API;纯静态查表。

档位含义(per ADR-0028 §1):
- **Tier A**: 推荐基线(Opus 4.7 / Sonnet 4.6 / GPT-5 / Gemini 2.5 Pro 等)。
  全部 7 个 AI role 正常工作。是我们调试 + dogfood 的基准。
- **Tier B**: 可用但有限(Haiku 4.5 / GPT-4o-mini / Gemini 2.5 Flash 等)。
  Chat / Capture 仍 work;复杂结构化推理(Editor advisor / Linter 等)
  在 UI 显式标 "降级模式"。
- **Tier C**: 不推荐(GPT-3.5 / 本地小模型 / context < 8K)。
  绝大多数 hybrid role 直接 disable,只保留最基本 chat fallback。
- **unknown**: 用户配了我们没识别的模型 id。**保守对待 = Tier C**(让
  用户主动覆盖),并在 UI 提示"未识别的模型,按 Tier C 处理;如果你
  确认它是 A 档可在 settings 里 override"。

新增 / 重命名模型时,更新 ``KNOWN_MODELS`` 并跑 tier mapping 测试。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Tier = Literal["A", "B", "C", "unknown"]


# 顺序约定: 同档位内按发布日期由新到旧 / 由主流到 niche 排序,UI 直接按
# 这个顺序显示推荐列表(无需前端再排)。
#
# 维护原则:
# - 只列**我们实际验证过 / 信心打的**型号,不列网上文档里看到但没测过的
# - 模型 id 用各 provider 的官方 stable 名(避免 "claude-3-opus-latest"
#   这种 alias —— alias 会随时间漂移)
# - 一个模型按"主流 provider id"列;同模型不同 provider(如 OpenRouter
#   转发的 Claude)默认走 unknown 路径,需要用户 explicit 选档
KNOWN_MODELS: dict[str, Tier] = {
    # ---------- Anthropic Tier A ----------
    "claude-opus-4-7": "A",
    "claude-opus-4-7-20250929": "A",
    "claude-sonnet-4-6": "A",
    "claude-sonnet-4-6-20250929": "A",
    # ---------- Anthropic Tier B ----------
    "claude-haiku-4-5": "B",
    "claude-haiku-4-5-20251001": "B",
    # ---------- OpenAI Tier A ----------
    "gpt-5": "A",
    "gpt-5-pro": "A",
    # ---------- OpenAI Tier B ----------
    "gpt-4o-mini": "B",
    "gpt-5-mini": "B",
    # ---------- OpenAI Tier C ----------
    "gpt-3.5-turbo": "C",
    # ---------- Google Tier A ----------
    "gemini-2.5-pro": "A",
    "gemini-2.5-pro-latest": "A",
    # ---------- Google Tier B ----------
    "gemini-2.5-flash": "B",
    "gemini-2.5-flash-latest": "B",
}


# 每个 AI role 对所需档位的最低要求(per ADR-0028 §1 + Phase 3 slicing
# 设计).在 Tier B 上,某些 role 的输出质量明显下降但仍 work;在 Tier C
# 上,这些 role 应当 disable(避免给用户"AI 在乱说" 的体验).
#
# Key = role id; value = 该 role 在哪些档位上 enabled.
ROLE_TIER_REQUIREMENTS: dict[str, set[Tier]] = {
    "chat_companion": {"A", "B", "C"},      # 任何能跑就能 chat
    "capture_extractor": {"A", "B"},        # 需要结构化抽取 → C 不可靠
    "editor_advisor": {"A"},                # 跨笔记语义 → 只 A 档稳
    "search_booster": {"A", "B"},           # 重排 → A/B 可
    "linter": {"A"},                        # 跨页 reasoning → 只 A 档
    "tidy_advisor": {"A"},                  # 同 linter
    "reorg_planner": {"A"},                 # 高风险 → 只 A 档
}


# 友好的 role label(中文,UI 直接渲染).中英文 i18n 表在前端,此处保
# 留中文 fallback 字符串避免后端要持有 i18n state.
ROLE_DISPLAY_LABELS: dict[str, str] = {
    "chat_companion": "Chat",
    "capture_extractor": "捕获 / 抓取",
    "editor_advisor": "编辑建议",
    "search_booster": "搜索增强",
    "linter": "Lint 扫描",
    "tidy_advisor": "整理建议",
    "reorg_planner": "重组规划",
}


@dataclass(frozen=True)
class TierProfile:
    """Tier + degraded role 列表的可序列化视图,给 HTTP 层用."""

    tier: Tier
    label: str
    description: str
    enabled_roles: list[str]
    degraded_roles: list[str]


def classify_model(model_id: str) -> Tier:
    """Look up the tier for a given model id. Returns ``"unknown"`` if
    the id isn't in ``KNOWN_MODELS``.

    Matching is exact, not fuzzy. Aliases (e.g.,
    ``claude-opus-4-7-latest``) should be added to ``KNOWN_MODELS``
    explicitly if we want them recognized — we don't try to guess.
    """
    if not model_id:
        return "unknown"
    return KNOWN_MODELS.get(model_id, "unknown")


def profile_for_tier(tier: Tier) -> TierProfile:
    """Return a serializable view of which knowlet roles are enabled
    on a given tier."""
    label = {
        "A": "推荐",
        "B": "可用(部分降级)",
        "C": "不推荐",
        "unknown": "未识别(按 C 处理)",
    }[tier]
    description = {
        "A": "所有 AI 能力正常工作。这是我们调试的基线。",
        "B": "Chat / 抓取等基础能力可用;Editor advisor / Linter / Tidy / Reorg 等需要跨笔记语义推理的能力在该档位上 disable,避免给出不可靠输出。",
        "C": "仅保留最基本的 chat fallback;大多数 hybrid AI role 在此档上 disable。建议升级到 Tier A 解锁完整体验。",
        "unknown": "knowlet 没识别这个模型 id,保守按 Tier C 处理(只 chat fallback)。如果你确认它实际是 A 档,可以在 advanced settings 里手动 override。",
    }[tier]
    enabled = []
    degraded = []
    for role, supported in ROLE_TIER_REQUIREMENTS.items():
        # Treat "unknown" as "C" for enabling purposes (保守).
        effective_tier: Tier = "C" if tier == "unknown" else tier
        if effective_tier in supported:
            enabled.append(role)
        else:
            degraded.append(role)
    return TierProfile(
        tier=tier,
        label=label,
        description=description,
        enabled_roles=enabled,
        degraded_roles=degraded,
    )


def is_role_enabled(model_id: str, role: str) -> bool:
    """Helper for runtime gating: should ``role`` run on the user's
    current ``model_id``? Defaults to safe (disabled) for unknown
    roles."""
    tier = classify_model(model_id)
    supported = ROLE_TIER_REQUIREMENTS.get(role)
    if supported is None:
        return False
    effective_tier: Tier = "C" if tier == "unknown" else tier
    return effective_tier in supported


# ----------------------------------------------------- recommended list


@dataclass(frozen=True)
class RecommendedModel:
    """One row in the per-provider recommendation list. UI renders these
    as picker options, grouped by provider and tier-sorted."""

    provider: str
    model_id: str
    display_name: str
    tier: Tier
    base_url_hint: str | None = None


# Curated picker list — what we tell users to consider. Order within
# each provider = recommended-first.
RECOMMENDED_MODELS: list[RecommendedModel] = [
    # Anthropic via cliproxyapi (default for our dogfood setup).
    RecommendedModel(
        provider="cliproxyapi",
        model_id="claude-opus-4-7",
        display_name="Claude Opus 4.7 (via cliproxyapi)",
        tier="A",
        base_url_hint="http://127.0.0.1:8317/v1",
    ),
    RecommendedModel(
        provider="cliproxyapi",
        model_id="claude-sonnet-4-6",
        display_name="Claude Sonnet 4.6 (via cliproxyapi)",
        tier="A",
        base_url_hint="http://127.0.0.1:8317/v1",
    ),
    RecommendedModel(
        provider="cliproxyapi",
        model_id="claude-haiku-4-5",
        display_name="Claude Haiku 4.5 (via cliproxyapi)",
        tier="B",
        base_url_hint="http://127.0.0.1:8317/v1",
    ),
    # Anthropic direct API.
    RecommendedModel(
        provider="anthropic",
        model_id="claude-opus-4-7",
        display_name="Claude Opus 4.7 (direct API)",
        tier="A",
        base_url_hint="https://api.anthropic.com/v1",
    ),
    RecommendedModel(
        provider="anthropic",
        model_id="claude-sonnet-4-6",
        display_name="Claude Sonnet 4.6 (direct API)",
        tier="A",
        base_url_hint="https://api.anthropic.com/v1",
    ),
    # OpenAI.
    RecommendedModel(
        provider="openai",
        model_id="gpt-5",
        display_name="GPT-5",
        tier="A",
        base_url_hint="https://api.openai.com/v1",
    ),
    RecommendedModel(
        provider="openai",
        model_id="gpt-5-mini",
        display_name="GPT-5 mini",
        tier="B",
        base_url_hint="https://api.openai.com/v1",
    ),
    # Google.
    RecommendedModel(
        provider="google",
        model_id="gemini-2.5-pro",
        display_name="Gemini 2.5 Pro",
        tier="A",
        base_url_hint="https://generativelanguage.googleapis.com/v1beta/openai",
    ),
    RecommendedModel(
        provider="google",
        model_id="gemini-2.5-flash",
        display_name="Gemini 2.5 Flash",
        tier="B",
        base_url_hint="https://generativelanguage.googleapis.com/v1beta/openai",
    ),
]


def recommended_for_provider(provider: str) -> list[RecommendedModel]:
    return [m for m in RECOMMENDED_MODELS if m.provider == provider]
