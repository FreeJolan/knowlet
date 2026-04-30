# 路线图

> [English](./README.en.md) | **中文**

Knowlet 按 Wedge 战略分阶段演进。能力同源、相互增强;叙事按阶段聚焦。详见 [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.md)。

## 阶段总览

```
阶段一 (MVP / V1):    AI 长期记忆层 + 减负型 PKM
阶段二 (V1 → V2):     用户需求驱动的扩展
阶段三 (V2 → V3):     跨 AI 工具的记忆层(MCP server)
阶段四:               全能形态
```

## 阶段一 — MVP / V1

**Slogan:** 会自己整理的个人知识库 / *A personal knowledge base that organizes itself.*

### 服务的真实场景

详见 [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.md) 场景 A / B / C。简要:

- **场景 A — 研究 / 论文阅读**:在 knowlet chat 讨论 → AI 草稿 → 用户审查 → 沉淀;后续 AI 对话自动召回历史结论
- **场景 B — 信息流订阅与整理**:配置知识挖掘任务 → 定时抓取 + LLM 整理 → 用户审查 → 入库
- **场景 C — 结构化重复记忆 + AI 增强**:外语词汇 / 专业概念辨析 / 写作批改类场景,SRS 子模块调度 + AI 在交互中按用户上下文调整反馈

### 核心特性

- **嵌入式 chat**:LLM 由用户自带([ADR-0005](../decisions/0005-llm-integration-strategy.md))
- **LLM-driven retrieval**:LLM 在每次对话中按需从知识库检索
- **知识挖掘任务**:定时 + Prompt + 来源约束 + 抓取过程透明
- **AI 草稿 + 人工审查**:默认沉淀模式
- **SRS 子模块(FSRS)**:作为知识库的"主动复习视图"
- **分层用户上下文**:Markdown 意图 + JSON 派生分析 + SQLite 派生状态
- **桌面端 + 移动 PWA**:碎片场景兜底

### 显式不做

详见 [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.md) "阶段一明确不做"小节。摘要:

- 团队协作 / 多用户(终生不做)
- 内容推荐 / 信息发现 / 社交
- 任务 / 日历 / Todo 管理
- 传统 PKM 的双链 / 图谱专门 UI(由 LLM agent + tools 间接达成)
- AI Chat 产品的功能复刻
- knowlet chat 不抢 Claude / Cursor 的位置

### 衡量是否可进入阶段二

- 三个真实场景的 happy path 能稳定跑通
- AI 草稿 + 人工审查的沉淀循环在用户实际使用中不令人烦躁
- LLM-driven retrieval 命中率达可用阈值(具体数值在原型阶段定)
- 跨场景上下文累积有可观察的效果(写作批改用上历史错误模式 / 阅读促进词汇队列等)

## 阶段二 — V1 → V2:用户需求驱动的扩展

阶段一稳定后,用户自然会浮出新需求。可能演进的方向(按预期优先级):

- **图谱 / 双链可视化**:用户开始想看"我的知识全貌",通过 LLM agent + tools 已可达成,但需要直观 UI
- **plugin 生态**:开放接口让用户/社区写自定义 tool,扩展原子能力层
- **移动端原生**:PWA 不够,音频 / OCR / 通知等场景需要原生能力
- **knowlet 自建同步**:文件级同步的冲突体验不佳时,补 CRDT 或加密同步路径
- **完整加密路径**:高隐私需求出现时(参见 [ADR-0006](../decisions/0006-storage-and-sync.md))
- **fallback 抓取后端**:支持不带原生 web_search 的 LLM(SearXNG / Brave / 自托管)

阶段二是**被用户需求推着走**,而不是先做出来再找需求。具体特性进入路线图前需通过特性优先级原则(下方)。

## 阶段三 — V2 → V3:跨 AI 工具的记忆层

knowlet 阶段一的原子能力按 MCP 标准设计([ADR-0004](../decisions/0004-ai-compose-code-execute.md))。阶段三正式开放 MCP server 形态:

- Claude Desktop / Cursor / 其他 MCP-compatible 工具直接调 knowlet 的能力
- knowlet 不再只是"打开就用的应用",而是"用户所有 AI 工具的私人记忆层"
- 这与 ADR-0003 的破局点叙事完全自洽

## 阶段四 — 长远全能形态

当三条主能力(消费沉淀 / 信息挖掘 / 学习增强)在 MCP 形态下相互强化:

```
信息挖掘 → AI 整理候选 → 用户审查入库
              ↓
       LLM-driven retrieval 在所有 AI 工具中召回
              ↓
       使用过的知识形成卡片 → SRS 复习
              ↓
       错题反哺笔记与挖掘任务的 prompt 调整
```

阶段四不再是"叠加新能力",而是把已有能力的反馈环路打满。

## 特性优先级原则

每条新特性进入路线图前,先过四个问题:

1. **服务于当前阶段的破局点吗?** 否 → backlog
2. **会损害三条核心原则吗?**(AI 可选 / 数据主权 / 插件化) 是 → 拒绝
3. **能用现有领域实体表达吗?** 否 → 思考是否需要新增实体,而不是塞进现有实体里
4. **拒绝它的代价是什么?** 如果代价是"失去某类用户但他们不在当前阶段画像里",可以接受

这套原则避免"什么都想做"的早期陷阱,具体每条候选特性的判断结果会在 ADR 或 design 文档里记录。
