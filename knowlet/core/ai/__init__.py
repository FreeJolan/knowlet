"""Phase 3 — AI 子系统模块。

每个 AI role 一个模块(per ADR-0024 §4):
- ``tiers``       — 模型档位映射(ADR-0028 §1)
- ``envelope``    — 7 层 prompt envelope 组装器(P3.1,未来切片)
- ``role/*``      — 7 个 role 各自的实现(P3.2 起,未来切片)

本 sub-package 在 Phase 3 内逐步填充。当前仅 ``tiers``。
"""

from __future__ import annotations
