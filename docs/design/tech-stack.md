# 技术选型与竞品参考

> 活文档。具体实现选型会随原型推进调整,本文档仅记录当前倾向与理由。

## 选型建议

| 维度 | 选型 | 理由 |
|---|---|---|
| **后端** | Python 或 Go | Python 生态最好(langchain / llamaindex 等);Go 性能好,可单二进制分发 |
| **前端(桌面)** | Tauri + Svelte / React | 比 Electron 轻,体积与内存友好 |
| **向量库** | SQLite + sqlite-vec | 零外部依赖,对开源社区与用户都友好 |
| **LLM 抽象** | 统一适配器 | 至少支持 OpenAI / Anthropic / 本地 Ollama,符合"AI 可选"原则 |
| **存储** | 纯 MD + Frontmatter + Git | 数据主权、可版本化、可迁移 |

后端语言尚未最终敲定,需要在原型阶段评估两件事:

1. Python 单二进制分发可行性(PyInstaller / Nuitka)对最终用户体验影响
2. Go 的 LLM 客户端生态成熟度,是否会成为应用层瓶颈

## 必须坚守的底线

不论具体选型怎样调整,以下底线由 [ADR-0002](../decisions/0002-core-principles.md) 锁定:

- 不引入私有数据格式
- 不绑定单一云服务
- LLM 必须可换、可关
- 任何能力模块都可独立替换/禁用

## 竞品参考

| 产品 | 特点 | 可借鉴 |
|---|---|---|
| **Obsidian + Smart Connections** | 知识库 + AI 插件 | 插件生态、双链 |
| **Reor** | 本地优先 + AI 笔记 | 本地优先架构 |
| **Khoj** | AI 搜索自己的笔记 | RAG 实现 |
| **RemNote** | 笔记 + SRS 一体化 | 卡片与笔记统一模型 |
| **Anki** | SRS 标杆 | SM-2 算法、记忆曲线 |

## 差异化卖点

Knowlet 相对上述竞品的差异化是**三条组合**(任意单条都不构成壁垒,组合在一起目前市面无成熟方案):

1. **生产-消费闭环 + 错题驱动** —— 详见 [`architecture.md`](./architecture.md)
2. **语音优先的移动端 OCR / TTS 体验** —— 详见 [`voice.md`](./voice.md)
3. **纯文本底座 + AI 可插拔** —— 详见 [ADR-0002](../decisions/0002-core-principles.md)
