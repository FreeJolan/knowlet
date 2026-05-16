"""Phase 3 — AI 子系统模块。

每个 AI role 一个模块(per ADR-0024 §4),后续切片逐步填充:
- ``envelope``    — 7 层 prompt envelope 组装器(P3.1,未来切片)
- ``role/*``      — 7 个 role 各自的实现(P3.2 起,未来切片)

当前 sub-package 为空 —— P3.0 阶段一度引入过 tier 分类(`tiers.py`),
2026-05-16 review 后删除(per ADR-0028 §1 amendment: knowlet 不评估
模型、不分类、不基于模型 gate feature)。
"""

from __future__ import annotations
