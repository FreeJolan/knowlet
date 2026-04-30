# Knowlet 设计文档

> [English](./README.en.md) | **中文**

本目录记录 Knowlet 项目的设计讨论结果与规划,作为飞书初稿之后的正式落地文档。

## 目录结构

- [`decisions/`](./decisions/) — ADR 风格的决策记录,每个文件一条决策。**不可变**,只新增不改写;若决策被推翻,新增一篇标记 supersedes 旧 ADR。
- [`design/`](./design/) — 活文档(living docs),记录架构分层、领域模型、闭环图等。会随项目演进持续更新。
- [`roadmap/`](./roadmap/) — 阶段路线图、特性优先级、里程碑。

## 写作约定

- 所有文档使用 Markdown,优先纯文本与轻量表达
- 图示使用 Mermaid / ASCII / 外链图床,避免引入二进制
- 决策文档(ADR)使用 `NNNN-kebab-case-title.md` 命名,从 0001 开始递增
- 每篇文档头部带一句话摘要,便于在索引中扫读
