# Architecture Decision Records (ADR)

> [English](./README.en.md) | **中文**

本目录记录 Knowlet 项目重要的架构与产品决策。每条 ADR 一旦合入即视为不可变,后续若被推翻,新增一篇并在新 ADR 中声明 `Supersedes: NNNN`。

## 目录

<!-- 新增 ADR 时同步更新此处索引 -->

- [0002 — 三条核心原则](./0002-core-principles.md)
- [0003 — Wedge 破局点修订:AI 长期记忆层 + 减负型 PKM](./0003-wedge-pivot-ai-memory-layer.md)
- [0004 — AI 编排 + 原子执行(AI compose, code execute)](./0004-ai-compose-code-execute.md)
- [0005 — LLM 接入策略](./0005-llm-integration-strategy.md)
- [0006 — 数据存储与同步策略](./0006-storage-and-sync.md)
- [0008 — CLI / UI 平价开发纪律](./0008-cli-parity-discipline.md)
- [0009 — Mining tasks 与 drafts](./0009-mining-tasks-and-drafts.md)
- [0010 — i18n 策略](./0010-i18n.md)
- [0011 — Web UI 重设计:笔记软件本位 + Focus Modes](./0011-web-ui-redesign.md)
- [0012 — 笔记本位 / AI 是可选增强](./0012-notes-first-ai-optional.md)
- [0013 — 知识管理契约 / 碎片化治理三层框架](./0013-knowledge-management-contract.md)
- [0014 — 笔记考试模式 / Scope-driven 主动召回](./0014-note-quiz-mode.md)

历史 / 已不代表当前方向的 ADR 见 [`archive/`](./archive/)。

## ADR 模板

```markdown
# NNNN — 标题

- Status: Accepted | Proposed | Superseded by NNNN
- Date: YYYY-MM-DD

## Context
做这个决策时面临的问题与背景。

## Decision
最终选择了什么。

## Consequences
带来的好处、代价与后续约束。
```
