# 0023 — LLM Wiki 模式对比 + 知识库人机契约重申

> [English](./0023-llm-wiki-comparison-and-takeaways.en.md) | **中文**

- Status: Proposed
- Date: 2026-05-07

## Context

2026-04 Karpathy 发了一篇 gist [`llm-wiki.md`](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f),提出了一个被业界广泛传播的"LLM Wiki"知识库模式。它和 knowlet 的目标领域(personal knowledge base + LLM 增强)高度重叠,但在几条根本设计选择上和 knowlet 走了相反方向。

本 ADR 的作用是:

1. **梳理两者差异**作为定位锚点 —— knowlet README 借这条对比把"用户拥有 / LLM 提案"根原则讲清楚
2. **吸收 5 个不冲突的小特性**进 roadmap(`wiki_schema.md` / `log.md` / Ingest verb / Lint / Pin to wiki)
3. **明确不引入** Karpathy 模式里和 knowlet 核心契约冲突的部分,避免后续讨论里滑回 LLM-owns-the-wiki 的老路

## Karpathy LLM Wiki 摘要(便于本 ADR 自包含)

**三层架构:**

- `sources/` — 用户原始材料,immutable,LLM 只读
- wiki(markdown 目录)— **LLM 全权拥有**,LLM 写 / 用户读
- `CLAUDE.md` / `AGENTS.md` — schema,告诉 LLM 怎么维护这个 wiki

**三个动作:** Ingest(扔进新 source → LLM 读 + 写 summary + 更新 10-15 个相关页 + append log)/ Query(LLM 查 wiki,合并答,可反向归档为新页)/ Lint(周期性 health check:contradictions / 过时声明 / orphans / 缺页 concept)。

**两个 navigation 文件:** `index.md`(内容向)+ `log.md`(时间向 append-only)。

**关键引语:** "你 never (or rarely) write the wiki yourself" / "Obsidian 是 IDE,LLM 是 programmer,wiki 是 codebase" / "维护知识库枯燥的不是阅读和思考,而是 bookkeeping"。

**形态:** idea file —— 不是软件 / app / UI / 工具链,而是一段可复制粘贴给 LLM agent 的 brief。用户实际工作环境是 Claude Code + Obsidian **两个窗口并排**。

## Decision

### 1. 重申根原则 — "用户拥有,LLM 提案"

[ADR-0013 §1](./0013-knowledge-management-contract.md) 已规定 "no auto-merge / no auto-archive / LLM 不主动改 vault IA"。本 ADR 把这条规则升级为 **knowlet 对外定位的第一身份**。

最精确的差异是**谁来写哪一层**:

| 维度 | Karpathy LLM Wiki | knowlet |
|---|---|---|
| **内容**(笔记主体)| **LLM 写**(从 `raw/` 编译出 wiki 页面)| **用户写** |
| **导航 / catalog** | **LLM 写**(`index.md` 是 LLM 维护的 markdown 目录,每页一行摘要 + 来源数,按 entities / concepts / sources 分类)| **不存在专门 catalog 文件**(用 file tree + 自动 backlinks 替代;**代码维护反向链接,不需要 LLM 周期性写 catalog**)|
| **搜索引擎索引**(BM25 + 向量)| 后期接 [qmd](https://github.com/tobi/qmd)(可选,~100 页之后)| **代码自动维护**(SQLite FTS5 + sqlite-vec,从 day 1 就有)|

knowlet 体系**比 Karpathy 更轻**:不需要 LLM 周期性维护 catalog,也不需要等规模长大再装搜索引擎。**LLM 不写 vault 的任何持久层**。

后果:

- ✅ knowlet:用户拥有笔记,LLM 生产**候选**(草稿 / 摘要 / 链接建议 / IA 提案),所有进入 vault 的内容**过审批管线**
- ❌ Karpathy LLM Wiki:LLM **全权拥有** wiki(内容 + catalog 都是 LLM 编译产物),用户只读 + 引导

两条路线不是优劣比较,而是**对"知识沉积物的可信度"做了不同假设**:

- Karpathy 模式假设单一用户 + 单一专题 + 强 schema 约束 + 短中期专注下,LLM 维护是净正收益
- knowlet 模式假设跨多年 / 跨多场景 / 多 LLM 后端切换的长期使用下,**用户对每条笔记的可解释性 / 可信度 / 可控性的需求高于维护成本节省**

#### 1.1 用 Tiago Forte 的 CODE 框架对比

CODE = Capture / Organize / Distill / Express(《Building a Second Brain》2022)。两条路线在 4 个阶段的 AI 参与度截然不同:

| 阶段 | "LLM 替你管 wiki" 模式 | knowlet |
|---|---|---|
| Capture(收集)| 用户 + AI(Web Clipper / 抓取)| 用户 + AI(URL 捕获 / Mining 任务) |
| **Organize**(组织)| **LLM 自动决定 IA**(预设 entities/concepts/comparisons/...)| **用户拥有**;AI 仅在用户主动触发时给候选([ADR-0024](./0024-ai-assist-envelope.md) Editor advisor / Tidy advisor) |
| **Distill**(提炼)| **LLM 自动写笔记主体**(LLM 综合多 source → wiki 页)| **AI 只产候选 → review queue → 用户审批** |
| Express(表达)| 用户(查询 / 生成 slides)| 用户(写 / 用 Quiz / Sediment)|

**knowlet 的差异本质 = 不自动化 Organize;Distill 永远走审批管线**。这条比"用户拥有,LLM 提案"更精确,作为 README 定位段的核心表述。

### 2. 吸收特性 1 — `vault/.knowlet/wiki_schema.md`

**问题**:Karpathy gist 用 `CLAUDE.md` / `AGENTS.md` 作为"wiki 维护规则",和领域共同演化。knowlet 当前有 user_profile(身份)和 ADR(项目决策),**缺一层"vault 个性化约定"**。

**采纳**:加一个 vault 级文件 `vault/.knowlet/wiki_schema.md`(用户可读可写),内容例子:

- "我的笔记偏好用 H2 分章节"
- "[[Title]] 链接优先用单数形式"
- "永远不要让 LLM 自动合并同义词"
- "新概念要建独立页;术语别名只在主页 frontmatter `aliases` 字段列"

**注入点**:

- chat system prompt(在 user_profile 之后追加)
- mining draft prompt(让 LLM 知道当前 vault 的写作 / 链接惯例)
- ingest source prompt(同上,§4)

**不冲突**:profile 是"我是谁",schema 是"这个 vault 怎么写"。两层正交。

#### Co-evolution 机制(主动促 schema 演化)

文档(Karpathy 体系的二次扩展材料)强调:"从 5-10 来源开始,每 10-20 次摄入回顾一次 schema,把发现的模式编码进去"。knowlet 把这条**做成主动机制**而非被动文件:

- 后端在 mining draft approve 累计达 N 次(默认 12)/ sediment 累计 M 次(默认 8)/ ingest 累计 K 次(默认 6)时,在 review queue / 周报里弹一条 ambient:
  > "你最近批准了 12 条 draft;有 8 条都把笔记放进了 `concepts/` 目录。要不要把'新概念优先放 concepts/' 这条规则加到 wiki_schema?"
- 用户接受 → 自动追加到 `wiki_schema.md`(用户可见 diff,可以编辑)
- 用户拒绝 → 记录抑制,下次累计阈值翻倍才再提

**借鉴 Claude Code 的 Rule + Why 模式**:wiki_schema.md 模板硬约定每条规则带 `**Why:**` 行(示例值取自用户对话历史),让 schema 不是"AI 替我决定的规则",而是"AI 帮我写下来 + 我能读懂为什么"。

**多层级合并**(借鉴 Claude Code 的 CLAUDE.md 树型继承):

- `~/.knowlet/wiki_schema.md` — 跨 vault 的我的偏好(可选)
- `vault/.knowlet/wiki_schema.md` — per-vault(主)
- `vault/<folder>/.knowlet/wiki_schema.md` — per-folder 覆盖(opt-in,默认不启用)

**Phase**:Phase 3(随 chat/mining/ingest prompt 重做,在 [ADR-0024](./0024-ai-assist-envelope.md) §3 envelope 架构里作为静态 schema 层)。Backend prompt 注入逻辑可以早做。

### 3. 吸收特性 2 — `vault/.knowlet/log.md` 事件日志

**问题**:knowlet 当前有 chat history(per-session)+ mining drafts(per-task review trail),但**没有 vault 视角的 append-only 时间线**。

**采纳**:增加 `vault/.knowlet/log.md`(渲染),底层 SQLite event stream(`vault.events` 表,append-only)。

**记录的事件**:

- `note.created` / `note.updated` / `note.deleted` / `note.restored`
- `draft.proposed` / `draft.approved` / `draft.rejected`
- `chat.sediment_committed`
- `source.ingested`(§4)
- `lint.run`(§5)
- `quiz.session.completed`

**用途**:增长曲线 / 回滚定位 / 审计 / 激励反馈("本周你新增 7 条笔记")。

**和 [ADR-0018(数据耐久性,待起草)](#references) 合并落地**:event stream 是 schema migration / vault fixture 测试的天然 oracle —— 任何 schema 变更都应能在 event log 里溯源。

**Phase**:和 ADR-0018 同期(Phase 2 E)。

### 4. 吸收特性 3 — Ingest source 升级一等动作

**问题**:knowlet 当前的 URL 捕获([ADR-0016](./0016-url-capture.md))**绑定在 chat 里**,流向是 chat → 讨论 → 沉淀。但用户高频场景是**"先归档再读"** —— 看到一篇好文 / 一篇 paper,直接放进 sources,让 LLM 出 summary draft。

**采纳**:加一个一等动作 `ingest source`,流程:

```
用户拖一个 URL / 文件 / 剪报进 vault
   → 后端走 url_capture / 文件解析 → 落到 vault/sources/<date>-<slug>/
   → LLM 自动生成 summary draft(走 mining draft 同款管线)
   → 进 review queue
   → 用户审批 → +1 Note(可选 link 回 source)
```

**复用现有管线**:

- url_capture(M7.2 / [ADR-0016](./0016-url-capture.md))抓正文
- mining drafts([ADR-0009](./0009-mining-tasks-and-drafts.md))review queue
- [ADR-0013 §1](./0013-knowledge-management-contract.md) "用户拥有" 契约自动满足(进 review queue,不直接落库)

**和 chat 路径并存**:chat 里 URL → 讨论 → 沉淀仍然保留。两条路径互不替代:

- chat 路径 = "我想边读边讨论"
- ingest 路径 = "我先存,稍后再说"

**Phase**:Phase 3(随 review queue UI 重做)。

### 5. 吸收特性 4 — Lint 操作(LLM 跨页 contradictions)

**问题**:M8.1 structure signals 已经在算 near-duplicates / clusters / orphans / aging。Karpathy Lint 加了一层 M8.1 没有的:**用 LLM 跨页找 contradictions** + 找"被引用过但没建页的 concept"。

**采纳**:扩展 M8.1 + 加一个用户主动触发的 `knowlet lint`(CLI)/ "Run lint" UI 按钮:

| 信号类型 | 来源 | 计算方式 | 呈现 |
|---|---|---|---|
| near-duplicates / clusters / orphans / aging | M8.1 | 嵌入余弦 + 静态规则 | 知识地图侧栏 |
| **跨页 contradictions** | 本 ADR 新增 | LLM batch pass(每次 50 个 note pair 抽样) | 同位 |
| **dangling concept**(`[[Concept]]` 链接但无目标 Note) | 本 ADR 新增 | 静态扫描 wikilinks vs notes/ | 同位 |
| **缺页的 entity / concept**(LLM 推断) | 本 ADR 新增 | LLM scan 选 N 篇主 note → 提取出现频次 ≥ K 的 entity | 同位 |

**[ADR-0013 §1](./0013-knowledge-management-contract.md) 仍然成立**:lint 只**呈现信息**,不提供 "auto-fix" / "auto-merge" / "auto-create page" 按钮。

**Phase**:Phase 3(随知识地图侧栏)。LLM 信号(contradictions / dangling / missing-entity)三条作为后续候选,等 ambient 落地再开。

### 6. 吸收特性 5 — "Pin good chat answer back to wiki"

**问题**:对比表 / 综述这种 chat 中产生的中间产物目前会沉到 history 里,只能整个 session sediment 时一起捞。

**采纳**:在 chat UI 加 turn 级"📌 钉到知识库"动作:

- 单击 → 把这条 assistant turn 的内容作为 mining draft 候选(走 review queue)
- 复用 mining drafts 管线;[ADR-0013 §1](./0013-knowledge-management-contract.md) 自动满足
- 钉过的 turn 在 chat history 里有视觉标记,避免重复钉

**Phase**:Phase 3(chat UI 重做时一并)。

### 7. 吸收特性 6 — Note frontmatter `status` 字段

**问题**:Karpathy 体系的 frontmatter 设计里有两个字段:`confidence: high/medium/low`(基于 cross-validation 来源数)和 `status: active | stub | needs-update | deprecated`。前者**只在 LLM 是 Note 作者时合理** —— knowlet 用户写的 Note 套不上;后者**和 knowlet 的"用户拥有"模型完全兼容**。

**采纳:`status` 字段**(进 Note frontmatter v2 schema):

```yaml
---
title: "RAG vs LLM Wiki"
created: 2026-05-04
status: active   # active | stub | needs-update | deprecated
---
```

**判定规则**:

| 值 | 触发方式 |
|---|---|
| `active` | 默认值;用户写完 / 通过 draft 时打 |
| `stub` | 自动判定:正文 < 100 字 + 无 wikilinks。可作为 lint 报告的"待补完" |
| `needs-update` | Linter([ADR-0023 §5](#5-吸收特性-4--lint-操作llm-跨页-contradictions))检测到 newer source 推翻此页时打;**只标记,不改正文**(per [ADR-0024 §5 B](./0024-ai-assist-envelope.md)) |
| `deprecated` | 用户主动标;在 dedupe / refresh 流程里替代"删除" |

**显式拒绝的字段**:

- ❌ `confidence: high/medium/low`(LLM-attributed):knowlet 用户**自己写**的 Note,LLM 不能赋值"我对这条多确信"。如果用户**自己**想标主观把握,用其它自定义 frontmatter,但**不引入 LLM-driven confidence**。
- ❌ `source_count`(LLM-attributed):同理 —— 在 Karpathy 体系里来源数是 LLM 编译产物的属性;在 knowlet 里**用户写的 Note** 不是从 sources 编译的,这个字段语义不存在。

**Phase**:与 [ADR-0018 数据耐久性](#references) 同期(Phase 2 E)。Note schema_version 已经在 commit `40cfcd0` ship,`status` 是 schema v2 的增量字段。

### 8. 吸收特性 7 — IA 推荐三件套(Editor / Tidy / Reorg advisor)

**问题**:Karpathy 模式让 LLM 自动决定 IA(预设 entities/concepts/comparisons/maps/...)。knowlet 不能学这种,但**可以**在 file tree 这个本身就是导航的层做"AI 提案"。

**采纳**:三个 AI role(详细定义见 [ADR-0024 §4](./0024-ai-assist-envelope.md)),从粒度小到大:

#### 8.1 Editor advisor — 新建笔记时推荐位置

**触发**:用户 Cmd+N 起新笔记 / mining draft 通过 / ingest source 落 draft 三个入口的最后一步。

**机制**:用 title + 前 N 字算 embedding,和现有 Note 做 cosine,取 top-K Note → 取它们所在文件夹做候选。

**UX**:

- 默认值 = 当前 file tree 选中的文件夹(符合 Obsidian / Bear 的 muscle memory)
- 推荐以**小 chip** 形式出现:`💡 建议放到 papers/llm/(3 篇相似笔记在那里)`,点击应用,不点击就用默认
- **不能弹模态框**

**Phase**:Phase 3(随 chat / mining / ingest UI 重做)。

#### 8.2 Tidy advisor — 小颗粒局部 IA 建议

**触发**:M8.1 structure signals 检测出"信号"时,在知识地图侧栏 ambient 显示。

**机制**:扩展 M8.1 信号集:

| 信号 | 触发条件 | 提案动作 | 提案颗粒 |
|---|---|---|---|
| **散落的语义簇** | M8.1 检出 cosine > 0.85 的 N 个 note,但分布在 ≥3 个文件夹 | "这 5 篇笔记主题相近但散在 3 个文件夹,要不要放进同一个新文件夹 `<建议名>` ?" | ≤ 7 个 note,单次建议 |
| **超大文件夹** | 单文件夹笔记数 > 50 | "`papers/` 现在 73 篇,要不要按子主题拆?这是 3 个备选拆法" | 用户在 2-3 个备选里挑 |
| **孤儿 note** | 无入链 + last-edited > 90d + 距离当前文件夹其他笔记语义远 | "`<note>` 看起来不属于 `<folder>`(语义离群),要移走吗?" | 单 note,单建议 |
| **dangling concept** | `[[Foo]]` 链接无目标 Note | "你 5 处链接到 `[[Foo]]` 但没建,要建吗?选位置:..." | 建一个新 note |

**约束**:

- 每条提案颗粒 ≤ 7 个 note
- 全部走信息呈现 / chip,不主动弹 modal
- 走 review queue,任何一个 move 都是单独决定,**永远不存在"一键应用全部"按钮**

**Phase**:Phase 3(随知识地图侧栏)。

#### 8.3 Reorg planner — 用户主动触发的整树重排

**触发**:用户显式命令 `knowlet reorg <scope>`(CLI)/ "整理这个文件夹" UI 按钮。**罕见操作**(类比 `git rebase -i`),不是日常功能。

**典型场景**:

- 从 Bear / Notion 导出迁过来,扔进 knowlet 没结构
- 用了 1-2 年后想换组织方式(从按日期改按主题)
- vault > 200 篇但还是平铺,想分层

**5 条硬约束**(任一缺失就别做):

1. **永远先 plan 后 apply** — 提案是个**预览**(diff 视图,左原树右新树),零文件移动。用户在预览态:全接 / 全拒 / 单条 toggle
2. **执行前自动 snapshot** — 一键回滚靠 `knowlet vault restore-snapshot pre-tree-reorg`
3. **逆向 manifest** — 每个 move 记录"原位置",写进 `reorg-<ts>.json`,即便快照清了也能用 `knowlet reorg undo <id>` 一键反向
4. **必读 wiki_schema.md** — schema 里写了"我喜欢 flat" / "按项目分而非按主题分",AI 必须遵守
5. **scope 默认是子文件夹,不是整 vault** — "reorg this folder" 比 "reorg whole vault" 安全得多;整 vault 是显式开关

**Phase**:Phase 3 之后(等 Phase 1/2 知识库基线和数据耐久性都稳了再做)。

## 不引入的部分(明确划清)

### A. ❌ "LLM 全权拥有 wiki"

**冲突**:违反 [ADR-0013 §1](./0013-knowledge-management-contract.md) "用户拥有,LLM 不主动改 vault IA"。

knowlet 整个产品的存在理由就是这个模式产生的"AI 沉积物"会让用户逐渐失去信任 —— 当用户看到一条笔记记不清"是我写的还是 AI 写的、为什么这样组织、上次 LLM 维护改了什么"时,知识库的可信度就崩了。

### B. ❌ "两个窗口并排(Claude Code + Obsidian)"

**冲突**:违反 [ADR-0008](./0008-cli-parity-discipline.md) + [ADR-0021](./0021-knowledge-base-first-roadmap.md) 的"集成体验是核心价值"决策。

knowlet 选 React 而不是继续 CLI-only,就是因为 PKM 用户期望的是"装好就能用"的集成应用。把 chat / 编辑 / 浏览 / mining 拆到两个窗口违背这个判断。

### C. ❌ "Pattern, not product"

**冲突**:Karpathy gist 的目标受众是能 vibe-code 的技术用户;knowlet 目标受众是 Bear / Obsidian 量级的 PKM 用户。我们的价值是落地的产品,不是给 agent 的 brief。

### D. ❌ frontmatter `confidence: high/medium/low`(LLM-attributed 版本)

详见 §7。LLM 不能为用户写的 Note 赋值"可信度"语义。

### E. ❌ 预设 IA(`entities/` / `concepts/` / `comparisons/` / `maps/`)

knowlet 的 AI role 只用用户已有文件夹,必要时建议**建一个新文件夹**(经审批),**永远不会预设这种结构**。详见 [ADR-0024 §5 F](./0024-ai-assist-envelope.md)。

### F. ❌ AI 自动改 Note 正文 / auto-move / auto-archive / auto-merge

详见 [ADR-0024 §5 A-C](./0024-ai-assist-envelope.md)。即便 Linter 检测到 newer source 推翻此页,也只能标 `status: needs-update`(§7),**绝不修改正文**。

### G. ❌ 直接集成 [qmd](https://github.com/tobi/qmd)

**理由**(精确版,替代之前模糊的"已有 FTS + vec"措辞):

1. **跨语言**:qmd 是 Node.js,knowlet 是 Python;增 IPC 延迟和故障面
2. **强制 ~2GB 本地模型**:knowlet 让用户**配** embedding backend(dummy / BGE / OpenAI / 本地 ollama),装机灵活
3. **架构方向反向**:qmd 是独立搜索引擎,knowlet 是 PKM 应用;集成方向不顺
4. **没有"升级路径"对应物**:qmd 是 Karpathy 体系里"index.md 不够用时的可选升级",knowlet 从 day 1 就有 FTS + vec

**但学习它的设计**:RRF 融合 / LLM 重排 / Query 扩展 / 智能分块 4 个设计点在 knowlet Python 栈里重做,作为 Phase 2 backend polish("retrieval quality v2"),触发条件 = dogfood 期发现检索质量是瓶颈。详见 [ADR-0024 §"Out of scope"](./0024-ai-assist-envelope.md)。

## Consequences

### Positive

- 7 条 actionable 改进进 roadmap(都不和现有 ADR 冲突;§8 三件套是 [ADR-0024](./0024-ai-assist-envelope.md) 的具体实例)
- 定位语言锐化 —— README 利用 CODE 框架对比把根原则讲清楚(§1.1)
- 避免后续讨论里滑回"让 LLM 替你管 vault"的诱惑(技术上做得到,但是产品上是回头路)
- 7 条特性的工作量分散到 Phase 2 E / Phase 3 / Phase 3 之后,不阻塞 Phase 1 关键路径

### Negative

- 7 条特性总工作量约 3-4 周,分摊到 Phase 2 E / Phase 3
- 增加了 `wiki_schema.md` / `log.md` / `status` frontmatter 三个新概念,文档负担略增
- §8 三件套依赖 [ADR-0024](./0024-ai-assist-envelope.md) 的 envelope 架构落地

### Mitigations

- `wiki_schema.md` 默认空文件,用户不写也能用(优雅降级)
- `log.md` 由后端自动生成,不增加用户操作成本
- `status` 字段默认 `active`,旧 Note 自动迁移

### Out of scope

- **LLM-driven schema 自动演化**(让 LLM 直接改 `wiki_schema.md`):本 ADR 只采纳"提议 → 用户审批"的 co-evolution 机制(§2),不开"AI 自动改 schema 文件"的口子
- **跨 vault wiki 联邦**(把多个 vault 的 wiki 串起来):违反 ADR-0003 "单用户单 vault" 假设,不做
- **直接集成 qmd**:见 §G;但学其 4 个设计点(retrieval quality v2,Phase 2 候选)
- **生成 Marp 幻灯片 / Obsidian Dataview 兼容**:不在产品定位内
- **frontmatter `confidence` / `source_count`**(LLM-attributed):见 §D / §7
- **整树重排作为 LLM 主动行为**:见 §F;只有用户主动触发的 Reorg planner(§8.3)合规

## References

- [Karpathy LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — 本 ADR 比较的对象
- [ADR-0008](./0008-cli-parity-discipline.md) — 集成体验 / 单一来源
- [ADR-0009](./0009-mining-tasks-and-drafts.md) — Mining drafts review queue(§4 / §6 / §8 复用)
- [ADR-0013](./0013-knowledge-management-contract.md) — "用户拥有,LLM 提案" 契约
- [ADR-0014](./0014-note-quiz-mode.md) — 主动召回(knowlet 独有维度,Karpathy 不涉及)
- [ADR-0016](./0016-url-capture.md) — URL 捕获(本 ADR §4 在它基础上扩展)
- [ADR-0021](./0021-knowledge-base-first-roadmap.md) — Phase 计划
- [ADR-0024](./0024-ai-assist-envelope.md) — AI 协助边界 + 系统 prompt 架构(§8 三件套是它的具体实例)
- ADR-0018 数据耐久性(待起草)— `log.md` event stream + `status` 字段 在它范围内
- 飞书 wiki 文档《Karpathy 的 LLM 知识库:用大模型编译你的个人 Wiki》(2026-04)— 本 ADR §1.1 / §2 co-evolution / §7 frontmatter / §8 / §G qmd 对比的扩展材料
