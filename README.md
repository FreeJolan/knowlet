# Knowlet

> [English](./README.en.md) | **中文**

> **会自己整理的个人知识库。**
> *A personal knowledge base that organizes itself.*

Knowlet 是一个先自用、后开源的 AI 长期记忆层 + 减负型 PKM。AI 替你承担总结、分类、沉淀、检索这些低 ROI 的整理工作,你保留意图、思考、判断;同时,任何 AI 工具(Claude / Cursor / 其他)在跟你对话时,都可以从这个知识库主动检索你的私人累积知识 —— 不仅在 knowlet 内可见,也在你所有的 AI 工作流中可见。

> Knowlet 当前处于设计阶段,代码尚未开始实现。本仓库目前仅维护设计文档与路线图。

## 核心理念

- **AI 是可选增强,不是必需品** —— 无 AI 时仍是可用的笔记库
- **数据主权在用户** —— 本地优先,Markdown / JSON,可随时打包带走
- **能力插件化 + AI 编排 + 原子执行** —— 代码只暴露原子能力,LLM 编排工作流

详见 [ADR-0002 — 三条核心原则](./docs/decisions/0002-core-principles.md) 与 [ADR-0004 — AI 编排 + 原子执行](./docs/decisions/0004-ai-compose-code-execute.md)。

## 阶段一服务的真实场景

详见 [ADR-0003](./docs/decisions/0003-wedge-pivot-ai-memory-layer.md):

- **A. 研究 / 论文阅读** — 嵌入式 chat 讨论 → AI 草稿 → 用户审查 → 沉淀;后续 AI 对话自动召回
- **B. 信息流订阅与整理** — 用户配置知识挖掘任务 → 定时抓取 + LLM 整理 → 用户审查 → 入库
- **C. 结构化重复记忆 + AI 增强** — 外语词汇 / 专业概念辨析 / 写作批改;SRS 子模块 + AI 按用户上下文调整反馈

三个场景共享同一份用户上下文(目标 / 偏好 / 错误模式 / 词汇掌握),AI 在跨场景间累积理解。

## 文档索引

- [`docs/`](./docs/) — 设计文档总入口
  - [`decisions/`](./docs/decisions/) — 架构决策记录(ADR)
  - [`design/`](./docs/design/) — 活文档:架构 / 用户 / 组织策略 / 技术栈 / 语音
  - [`roadmap/`](./docs/roadmap/) — 阶段路线图

## License

[MIT](./LICENSE)
