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

[ADR-0013 §1](./0013-knowledge-management-contract.md) 已规定 "no auto-merge / no auto-archive / LLM 不主动改 vault IA"。本 ADR 把这条规则升级为 **knowlet 对外定位的第一身份**:

- ✅ knowlet:用户拥有笔记,LLM 生产**候选**(草稿 / 摘要 / 链接建议),所有进入 vault 的内容**过审批管线**
- ❌ Karpathy LLM Wiki:LLM **全权拥有** wiki,用户只读 + 引导

两条路线不是优劣比较,而是**对"知识沉积物的可信度"做了不同假设**:

- Karpathy 模式假设单一用户 + 单一专题 + 强 schema 约束 + 短中期专注下,LLM 维护是净正收益
- knowlet 模式假设跨多年 / 跨多场景 / 多 LLM 后端切换的长期使用下,**用户对每条笔记的可解释性 / 可信度 / 可控性的需求高于维护成本节省**

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

**Phase**:Phase 3(随 chat/mining/ingest prompt 重做)。Backend prompt 注入逻辑可以早做。

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

## 不引入的部分(明确划清)

### A. ❌ "LLM 全权拥有 wiki"

**冲突**:违反 [ADR-0013 §1](./0013-knowledge-management-contract.md) "用户拥有,LLM 不主动改 vault IA"。

knowlet 整个产品的存在理由就是这个模式产生的"AI 沉积物"会让用户逐渐失去信任 —— 当用户看到一条笔记记不清"是我写的还是 AI 写的、为什么这样组织、上次 LLM 维护改了什么"时,知识库的可信度就崩了。

### B. ❌ "两个窗口并排(Claude Code + Obsidian)"

**冲突**:违反 [ADR-0008](./0008-cli-parity-discipline.md) + [ADR-0021](./0021-knowledge-base-first-roadmap.md) 的"集成体验是核心价值"决策。

knowlet 选 React 而不是继续 CLI-only,就是因为 PKM 用户期望的是"装好就能用"的集成应用。把 chat / 编辑 / 浏览 / mining 拆到两个窗口违背这个判断。

### C. ❌ "Pattern, not product"

**冲突**:Karpathy gist 的目标受众是能 vibe-code 的技术用户;knowlet 目标受众是 Bear / Obsidian 量级的 PKM 用户。我们的价值是落地的产品,不是给 agent 的 brief。

## Consequences

### Positive

- 5 条 actionable 改进进 roadmap(都不和现有 ADR 冲突)
- 定位语言锐化 —— README 利用这条对比把根原则讲清楚
- 避免后续讨论里滑回"让 LLM 替你管 vault"的诱惑(技术上做得到,但是产品上是回头路)

### Negative

- 5 条特性总工作量约 2-3 周,分摊到 Phase 2 E / Phase 3
- 增加了 `wiki_schema.md` / `log.md` 两个新概念,文档负担略增

### Mitigations

- `wiki_schema.md` 默认空文件,用户不写也能用(优雅降级)
- `log.md` 由后端自动生成,不增加用户操作成本

### Out of scope

- **LLM-driven schema 自动演化**(让 LLM 在你 ingest 30 条 source 后建议改 wiki_schema):放 §B 不引入,等 dogfood 信号
- **跨 vault wiki 联邦**(把多个 vault 的 wiki 串起来):违反 ADR-0003 "单用户单 vault" 假设,不做
- **Karpathy 提的 [`qmd`](https://github.com/tobi/qmd) 本地搜索引擎集成**:knowlet 已有 FTS + 向量索引(`core/index/`),不再加新依赖
- **生成 Marp 幻灯片 / Obsidian Dataview 兼容**:不在产品定位内

## References

- [Karpathy LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — 本 ADR 比较的对象
- [ADR-0008](./0008-cli-parity-discipline.md) — 集成体验 / 单一来源
- [ADR-0009](./0009-mining-tasks-and-drafts.md) — Mining drafts review queue(§4 / §6 复用)
- [ADR-0013](./0013-knowledge-management-contract.md) — "用户拥有,LLM 提案" 契约
- [ADR-0014](./0014-note-quiz-mode.md) — 主动召回(knowlet 独有维度,Karpathy 不涉及)
- [ADR-0016](./0016-url-capture.md) — URL 捕获(本 ADR §4 在它基础上扩展)
- [ADR-0021](./0021-knowledge-base-first-roadmap.md) — Phase 计划
- ADR-0018 数据耐久性(待起草)— `log.md` event stream 在它范围内
