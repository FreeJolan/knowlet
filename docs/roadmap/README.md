# 路线图

> [English](./README.en.md) | **中文**

Knowlet 按 Wedge 战略分阶段演进。能力同源、相互增强;叙事按阶段聚焦。详见 [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.md)(及其 2026-05-04 amendment)。

## ⚡ 当前状态(2026-05-05)

**产品阶段** = 开发期(per [ADR-0022](../decisions/0022-product-lifecycle-phases.md))。无外部用户,允许激进迭代。

**项目状态** = **重写中**。2026-05-04 dogfood 验证前端基本不可用,触发以下决策(详见 ADR-0019 / 0020 / 0021):

- **前端**:Alpine 弃用,改 React 19 + Vite + TypeScript + shadcn/ui + AI SDK + CodeMirror 6 + react-arborist + Tanstack Query
- **后端**:不重写,加 mypy strict + ruff + pre-commit + CI(per ADR-0020)
- **顺序**:Phase 0 (脚手架 + 后端硬化) → Phase 1 (知识库基线) → Phase 2 (该有但可推) → Phase 3 (AI 能力重做) → Phase 4 (灰度准备)
- **预估时间**:8-12 周到 Phase 4(灰度入口前)

```
🟢 已 ship 但**待重做** 的后端能力(0 改动,直接复用)
   notes / cards / drafts / mining tasks 的 CRUD + 索引(FTS + vec)
   chat 多会话 + sediment + LLM-driven retrieval
   capsule 后端 (M7.1) + URL capture (M7.2) + critical take + hover quote (M7.3)
   quiz 模式 (M7.4) + web_search + fetch_url (M7.5)
   structure signals (M8.1)
   vault snapshot / doctor 完整性 / Note schema_version

❌ 已 ship 但**会被删除** 的前端
   knowlet/web/static/* (Alpine + 自写 SSE + 自写 palette)
   ~2000 行 app.js + ~1100 行 index.html + ~743 行 app.css
   除 token CSS variables 外几乎全部废弃

⏳ 等待重写
   全部前端 surface(per ADR-0021 §"Phase 1/2/3")
```

## 重写后的 Phase 计划

详见 [ADR-0021](../decisions/0021-knowledge-base-first-roadmap.md)。摘要:

```
Phase 0  决策锁定 + 脚手架 + 后端硬化(并行)            2-3 天
Phase 1  知识库基线 A + B + C(必备)                   4-5 周
   A. File ops 跟齐 Obsidian:右键菜单 / 拖拽 / 重命名 / 移动 / 多选 / Trash UI / 文件夹创建 UI / 全文搜索
   B. 编辑器跟齐 Bear:CodeMirror 6 + Math (KaTeX) + Mermaid + 模板 + 块引用
   C. 知识连接:Wikilinks autocomplete + Backlinks + Graph view + Tag 浏览器
Phase 2  D + E(该有可推)                              1-2 周(可推到 Phase 4)
   D. 入口:Daily notes / Quick switcher 强化 / 收藏
   E. 数据耐久:ADR-0018 落地 / Note version / Import-Export
Phase 3  AI 能力重做                                   3-4 周
   Chat (Vercel AI SDK) / 胶囊 / Sediment / Quiz / Mining UI / Web search trace / Cards
Phase 4  整体 dogfood + 灰度准备                        1-2 周
   Playwright e2e 测试 / 文档 / 灰度入口准备
```

**Phase 4 之后** = 进入灰度期(per [ADR-0022](../decisions/0022-product-lifecycle-phases.md))。

## 阶段一(MVP / V1)— 战略层

> Phase 0-4 是 V1 内部的实施切片。本节是战略层"V1 整体在干什么",跟具体 Phase 不绑。

**Slogan:** 会自己整理的个人知识库 / *A personal knowledge base that organizes itself.*

### 服务的真实场景

详见 [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.md) 场景 A / B / C。简要:

- **场景 A — 研究 / 论文阅读**:在 knowlet chat 讨论 → AI 草稿 → 用户审查 → 沉淀;后续 AI 对话自动召回历史结论
- **场景 B — 信息流订阅与整理**:配置知识挖掘任务 → 定时抓取 + LLM 整理 → 用户审查 → 入库
- **场景 C — 结构化重复记忆 + AI 增强**:外语词汇 / 专业概念辨析 / 写作批改类场景,SRS 子模块调度 + AI 在交互中按用户上下文调整反馈

### 核心特性(战略层)

- **嵌入式 chat**:LLM 由用户自带([ADR-0005](../decisions/0005-llm-integration-strategy.md))
- **LLM-driven retrieval**:LLM 在每次对话中按需从知识库检索
- **知识挖掘任务**:定时 + Prompt + 来源约束 + 抓取过程透明
- **AI 草稿 + 人工审查**:默认沉淀模式
- **SRS 子模块(FSRS)**:作为知识库的"主动复习视图"
- **分层用户上下文**:Markdown 意图 + JSON 派生分析 + SQLite 派生状态
- **桌面端 + 移动 PWA**:碎片场景兜底
- **双链 + 图谱**(2026-05-04 amendment):用户认可的连接关系是核心 IA

### 显式不做

详见 [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.md) "阶段一明确不做"小节(含 2026-05-04 amendment)。摘要:

- 团队协作 / 多用户(终生不做)
- 内容推荐 / 信息发现 / 社交
- 任务 / 日历 / Todo 管理
- AI Chat 产品的功能复刻
- knowlet chat 不抢 Claude / Cursor 的位置

## 阶段二 — V1 → V2:用户需求驱动的扩展

阶段二是**被用户需求推着走**(灰度期 + 上线期之后)。可能演进的方向(预期优先级):

- **Plugin 生态**:开放接口让用户/社区写自定义 tool,扩展原子能力层
- **移动端原生**:PWA 不够,音频 / OCR / 通知等场景需要原生能力
- **knowlet 自建同步**:文件级同步的冲突体验不佳时,补 CRDT 或加密同步路径
- **完整加密路径**:高隐私需求出现时(参见 [ADR-0006](../decisions/0006-storage-and-sync.md))
- **Fallback 抓取后端**:支持不带原生 web_search 的 LLM(部分已 ship 在 ADR-0017)

## 阶段三 — V2 → V3:跨 AI 工具的记忆层

knowlet 阶段一的原子能力按 MCP 标准设计([ADR-0004](../decisions/0004-ai-compose-code-execute.md))。阶段三正式开放 MCP server 形态:

- Claude Desktop / Cursor / 其他 MCP-compatible 工具直接调 knowlet 的能力
- knowlet 不再只是"打开就用的应用",而是"用户所有 AI 工具的私人记忆层"

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

## 📦 跨 ADR 延期事项总账(2026-05-05 重整)

> **目的**:每条 ADR / design doc 都有 §"Out of scope" / §"Defer" / §"未来扩展点"。本节按出处编录所有这些事项,作为防遗忘的 single source of truth。
>
> **维护规则**:每写一条新 ADR / 修订现有 ADR 时,§"Out of scope" 必须同步登记到这里。

### 🟡 等 dogfood 信号定优先级(Phase 4 之后再排)

| 项 | 出处 | 触发条件 |
|---|---|---|
| **ADR-0015b citation back-references**(LLM 回答里 `[1] [2]` 跳回原文) | ADR-0015 §3 | 灰度期 dogfood 显示需要 |
| **胶囊跨 session 草稿夹**(M7.1 capsule 持久化超过单条 message) | ADR-0015 §"Out of scope" | 用户主动要求 |
| **CLI `:quote <note_id> <line_range>` REPL 子命令** | ADR-0015 §"Out of scope" | 优先级低,GUI 替代 |
| **`knowlet://note/<id>?line=42` deep-link 协议** | ADR-0015 §"Out of scope" | 桌面 / 移动阶段才需要 |
| **Per-session web search 累计上限 + UI 用量 monitor** | ADR-0017 §"Out of scope" | dogfood 数据显示需要 |
| **Sediment 模态 Layer A 在 "+ 新建空 Note" 时也触发** | ADR-0016 §"Mitigations" | 用户写到一定篇幅后是否需要 |
| **Drafts approve 时显示 Layer A ambient** | ADR-0016 §"Out of scope" | 后续 |

### 🔵 在新 React 重写时一并实施(Phase 1-3)

| 项 | 出处 | 在哪 phase |
|---|---|---|
| `list_mining_tasks` Web 配置面板 | ADR-0004 amendment §"Backlog" | Phase 3 |
| `fetch_url` UI 入口(跟 url-capture 流统一) | ADR-0004 amendment §"Backlog" | Phase 3 |
| **知识地图侧栏**(消费 M8.1 LLM 推断信号) | ADR-0013 §3 Layer B | Phase 3 |
| **Graph view**(用户认可的 `[[Title]]` 链接可视化) | ADR-0003/0011/0013 amendment | **Phase 1 C**(已重新归位) |
| **周报**(Sunday-newspaper 调性) | ADR-0013 §3 Layer C | Phase 3 或 Phase 4 |
| **暗色 toggle** | 设计 brief §11 | Phase 1 起就有(token 已就位)/ toggle UI 在 Phase 1 |
| **M7.4.3 cluster scope quiz** | ADR-0014 §8 | Phase 3(在 quiz 重做时一并)|
| **`vault/.knowlet/wiki_schema.md`**(vault 写作约定 → 注入 chat / mining / ingest prompt) | ADR-0023 §2 | Phase 3(随 chat/mining prompt 重做) |
| **Ingest source 一等动作**(URL/文件 → sources/ → mining draft → review queue) | ADR-0023 §4 | Phase 3(随 review queue UI) |
| **Lint LLM 信号** —— 跨页 contradictions / dangling concept / 缺页 entity 推断 | ADR-0023 §5 | Phase 3(随知识地图侧栏)|
| **Pin chat turn 到 wiki**(turn 级 📌 → mining draft 候选) | ADR-0023 §6 | Phase 3(随 chat UI 重做)|

### 🟢 等阶段切换(灰度 / 上线 / 阶段二 / 三)

| 项 | 阶段 | 出处 |
|---|---|---|
| Plugin 系统 | 阶段二 | ADR-0003 §"阶段二" |
| 移动端原生 | 阶段二 | ADR-0003 §"阶段二" |
| knowlet 自建同步(CRDT / 加密) | 阶段二 | ADR-0006 §"阶段二" |
| Vault 加密(`git-crypt` / `age` / 自研) | 阶段二 | ADR-0006 §127 |
| MCP server | 阶段三 | ADR-0003 §"阶段三" |
| Tauri 桌面壳(M9+) | M9+ | ADR-0011 §"Schedule" |
| 浏览器扩展 / share-target | M9+ Tauri 阶段 | ADR-0016 §"Out of scope" |

### 🟣 数据耐久性(Phase 2 E,ADR-0018 待起草)

`knowlet vault snapshot` / `restore-snapshot` / `list-snapshots` + `knowlet doctor` 数据完整性检查 + Note `schema_version` 已在 commit `40cfcd0` ship,作为 dogfood 期的运营安全垫。下一步 ADR-0018 把契约钉死:

- Schema 演进规则(只能加字段不能删字段;1 major version backward compat 强制)
- Vault fixtures 测试套件(M0/M3/M7 vault snapshot,跑回归测试 "新代码能读旧 vault")
- 半显式 versioning(讨论 `v0.1.0` 是否就是灰度入口版)
- `.knowlet/backups/` 真正用起来(per ADR-0006 §3)
- Card / Draft / MiningTask 也加 `schema_version`(目前只 Note 加了)
- **`vault/.knowlet/log.md` + 底层 `vault.events` SQLite append-only 流**(per [ADR-0023 §3](../decisions/0023-llm-wiki-comparison-and-takeaways.md)):note/draft/sediment/ingest/lint/quiz 事件统一时间线,作为 schema migration / vault fixture 测试的天然 oracle

### 🔴 显式永不做

| 项 | 出处 |
|---|---|
| 团队协作 / 多用户 | ADR-0003 §"阶段一明确不做"(终生不做)|
| 内容推荐 / 信息发现 / 社交 | ADR-0003 §"阶段一明确不做" |
| 任务 / 日历 / Todo 管理 | ADR-0003 §"阶段一明确不做" |
| AI Chat 产品功能复刻(模型选择 / 长上下文 / 图像生成) | ADR-0003 §"阶段一明确不做" |
| Tag taxonomy(top-down 强制分类) | ADR-0013 §3 Layer B |
| Auto-archive / auto-merge | ADR-0013 §1 契约 |
| LLM 主动改 vault IA / "LLM 全权拥有 wiki" | ADR-0013 §1 / ADR-0023 §A |
| Drafts 提取的 image / video / PDF 内容(只处理文字) | ADR-0016 §"Out of scope" |
| 多 URL 一次粘贴抓取 | ADR-0016 §"Out of scope" |
| LLM 抓取 PDF / video(trafilatura 不处理) | ADR-0017 §"Out of scope" |
| 自动备 search 结果到 vault | ADR-0017 §"Out of scope" |
| 多语言 search query 切换 | ADR-0017 §"Out of scope" |
| 跨 vault wiki 联邦(把多个 vault 串起来) | ADR-0023 §"Out of scope" |
| LLM-driven schema 自动演化(让 LLM 改 `wiki_schema.md`) | ADR-0023 §"Out of scope" |
| 集成 [`qmd`](https://github.com/tobi/qmd) / Marp / Obsidian Dataview 等外部工具 | ADR-0023 §"Out of scope" |

## 已废弃(2026-05-05)

以下事项之前在路线图,**因 ADR-0019 / 0021 重写决策而失效**:

- ❌ "M8.2 知识地图侧栏作为 Alpine 实现" — 改在 React 重做(Phase 3)
- ❌ "M8.4 暗色 toggle 在 Alpine UI 实现" — token 已就位,UI 在 Phase 1 React 实现
- ❌ "Batch 2 / Batch 3 of Claude Design 2nd pass(在 Alpine 上)" — 弃。Design 决定全部映射到 React 实现
- ❌ "在 Alpine UI 上 polish file ops" — 弃。Phase 1 A 整体重做

## 特性优先级原则

每条新特性进入路线图前,先过四个问题:

1. **服务于当前阶段的破局点吗?** 否 → backlog
2. **会损害三条核心原则吗?**(AI 可选 / 数据主权 / 插件化)是 → 拒绝
3. **能用现有领域实体表达吗?** 否 → 思考是否需要新增实体
4. **拒绝它的代价是什么?** 如果代价是"失去某类用户但他们不在当前阶段画像里",可以接受
