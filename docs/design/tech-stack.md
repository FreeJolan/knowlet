# 技术选型与竞品参考

> [English](./tech-stack.en.md) | **中文**

> 活文档。具体实现选型会随原型推进调整,本文档仅记录当前倾向与理由。决策性内容见 [`../decisions/`](../decisions/)。

## 选型当前倾向

| 维度 | 倾向 | 理由 |
|---|---|---|
| **后端语言** | Python 或 Go(原型阶段评估) | Python 生态成熟(LLM SDK / embedding / FSRS 实现);Go 性能与单二进制分发友好 |
| **桌面端** | Tauri + Svelte / React | 比 Electron 轻;原生 Web 技术栈跨平台 |
| **移动端(阶段一)** | 响应式 PWA | 原生体验推到阶段二,详见 [`../roadmap/`](../roadmap/) |
| **向量库** | SQLite + sqlite-vec | 零外部依赖,与 ADR-0006 ".knowlet/ 派生数据"模式一致 |
| **LLM 接入** | OpenAI 兼容协议适配层 | 统一 API,详见 [ADR-0005](../decisions/0005-llm-integration-strategy.md) |
| **存储** | Markdown / JSON 按本质决定 | 详见 [ADR-0006](../decisions/0006-storage-and-sync.md) |
| **同步** | 用户自带管道(iCloud / Syncthing 等) | knowlet 阶段一不内置同步,详见 [ADR-0006](../decisions/0006-storage-and-sync.md) |
| **SRS 算法** | FSRS | 当前最先进,Anki 已默认,与"算法不是差异化"调性一致 |

后端语言尚未敲定,需在原型阶段评估两件事:

1. Python 单二进制分发(PyInstaller / Nuitka)对最终用户体验影响
2. Go 的 LLM 客户端 / embedding 生态成熟度,是否会成为应用层瓶颈

## 必须坚守的底线

不论具体选型怎样调整,以下底线由 [ADR-0002](../decisions/0002-core-principles.md) 与后续 ADR 锁定:

- 不引入私有数据格式(Markdown / JSON / SQLite 都开放)
- 不绑定单一云服务(同步管道用户自选)
- LLM 必须可换、可关([ADR-0005](../decisions/0005-llm-integration-strategy.md))
- 任何能力模块都可独立替换 / 禁用([ADR-0004](../decisions/0004-ai-compose-code-execute.md) 原子能力插件化)

## 竞品参考

| 产品 | 特点 | 可借鉴 / 区别 |
|---|---|---|
| **Obsidian + Smart Connections** | 知识库 + AI 插件 | 借鉴:插件生态。区别:knowlet 不要求用户手动整理,管理由 AI 承担 |
| **Reor** | 本地优先 + AI 笔记 | 借鉴:本地优先架构。区别:knowlet 强调 LLM-driven retrieval 与跨场景上下文 |
| **Khoj** | AI 搜索本地笔记 | 借鉴:RAG 实现。区别:knowlet 是嵌入式 chat + 知识挖掘任务,不只是搜索 |
| **RemNote** | 笔记 + SRS 一体化 | 借鉴:卡片与笔记统一模型。区别:knowlet 的 SRS 是子模块而非主形态 |
| **Anki / FSRS** | SRS 标杆 | 借鉴:SRS 算法直接采用 FSRS。区别:knowlet 不试图取代 Anki 的高级牌组功能 |
| **Notion AI / ChatGPT memory** | AI 助手内嵌记忆 | 区别:knowlet 是用户拥有的、跨工具的、本地优先的记忆层 |

## 差异化卖点

详见 [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.md)。三条组合(任意单条不够,组合在一起目前市面无成熟方案):

1. **AI 长期记忆层 + 减负型 PKM 的组合定位**
2. **跨场景上下文累积**(论文 / 信息流 / 学习场景共享同一份用户上下文)
3. **MCP server 形态(阶段三)**:跨 AI 工具暴露,不是孤立应用
