# 0024 — AI 协助边界 + 系统 prompt 分层架构

> [English](./0024-ai-assist-envelope.en.md) | **中文**

- Status: Proposed
- Date: 2026-05-07

## Context

[ADR-0013 §1](./0013-knowledge-management-contract.md) 锁定了"用户拥有,LLM 提案"的根原则,但没有具体回答两件事:

1. **AI 该协助 KB 维护的哪些环节?** 把人手维护知识库的 13 件事按工作类型分类后,哪些 AI 可以替代,哪些只能提案,哪些根本不该碰?
2. **每个 AI 任务的系统 prompt 该怎么组装?** 当前 `CHAT_SYSTEM_PROMPT_BASE` + user_profile 两层不够 —— 不同任务(chat / mining / lint / reorg)需要看到不同上下文,但分层应该统一。

本 ADR 给这两件事一个**总览框架**,作为后续所有 AI 功能开发的**入闸标准**:

- 任何新 AI 功能开发前,必须能在 §1 工作类型表 + §2 维护任务表上找到位置
- 任何新 AI 任务的 prompt 必须按 §3 envelope 结构组装
- §4 七个 AI role 划清了职责边界;不在表里的 role 不能引入

[ADR-0023](./0023-llm-wiki-comparison-and-takeaways.md) 里的多个吸纳特性(wiki_schema 注入 / Lint / Editor advisor / Tidy advisor / Reorg planner)都是本 ADR 框架的**实例化**;本 ADR 是它们共同的架构基础。

## Decision

### 1. 工作类型分类(决定 AI 该不该碰)

每件 KB 维护工作分到三类之一,**类别决定 AI 的角色**:

| 类别 | 含义 | AI 角色 | 错代价 |
|---|---|---|---|
| **mech**(机械)| 可程序化 / 重复 / 无创造性判断 | **替代**(自动做,留 audit trail)| 低,可重做 |
| **hybrid**(辅助)| 需要判断但有标准答案集 | **提案**(候选 → review queue → 用户审批)| 中,有 review 兜底 |
| **creative**(创造)| 用户的智力产物 / 表达 | **不碰**(或仅在用户显式调用"替我写"模式)| 极高,损用户认知所有权 |

**根原则**:`creative` 类工作 AI **永远不主动做**。`mech` 类自动做但留 audit trail(per [ADR-0023 §3](./0023-llm-wiki-comparison-and-takeaways.md) `vault.events`)。`hybrid` 类走现有 review queue([ADR-0009](./0009-mining-tasks-and-drafts.md))。

### 2. 13 项 KB 维护工作的现状映射

按周期梳理用户视角的全部 KB 维护工作:

```
日常(每天)
  1. Capture     抓内容(URL / 想法 / 剪报)
  2. Write       写笔记 ← 用户的核心创造
  3. Lookup      查旧笔记
处理 inbox(周/月)
  4. Triage      处理"抓了但没处理"的素材
  5. Tidy        移走"放错地方"的笔记
  6. Dedupe      合并重复 / 同义概念
  7. Refresh     新信息进来时更新旧笔记 ← 创造,只能提议
  8. Discover    发现"老引用 X 但从没写"的概念
  9. Resolve     标矛盾(新旧来源打架)
  10. Trim       deprecate / 清理死木
项目级(年/重大节点)
  11. Reorg      整树重排
  12. Migrate    跨工具迁移
  13. Archive    归档
```

按工作类别打标 + 映射到 knowlet 现状:

| # | 工作 | 类别 | knowlet 现状 | 缺什么 / 由哪条 ADR 兜 |
|---|---|---|---|---|
| 1 | Capture | mech | URL capture(M7.2) | + ingest 一等动作([ADR-0023 §4](./0023-llm-wiki-comparison-and-takeaways.md)) |
| 2 | **Write** | **creative** | CodeMirror 编辑器 | **AI 不参与正文写作** |
| 3 | Lookup | mech | FTS + vec 索引 | + 检索质量 v2(RRF / 重排 / query 扩展 / 智能分块,见 §"Out of scope") |
| 4 | Triage | hybrid | mining drafts queue([ADR-0009](./0009-mining-tasks-and-drafts.md)) | + ingest 落 draft 后接同款管线 |
| 5 | Tidy | hybrid | — | Editor advisor + Tidy advisor([ADR-0023 §8](./0023-llm-wiki-comparison-and-takeaways.md)) |
| 6 | Dedupe | hybrid | M8.1 near-duplicates(后端) | UI 侧栏接出来(Phase 3) |
| 7 | **Refresh** | **creative** | — | **不替写**;只 lint 标"newer source 推翻此页"([ADR-0023 §5](./0023-llm-wiki-comparison-and-takeaways.md)) |
| 8 | Discover | hybrid | — | dangling concept + missing entity([ADR-0023 §5](./0023-llm-wiki-comparison-and-takeaways.md)) |
| 9 | Resolve | hybrid | — | cross-page contradictions([ADR-0023 §5](./0023-llm-wiki-comparison-and-takeaways.md)) |
| 10 | Trim | hybrid | aging signal(M8.1) | UI 接 + 提议 deprecate(不删除) |
| 11 | Reorg | hybrid | — | Reorg planner([ADR-0023 §8](./0023-llm-wiki-comparison-and-takeaways.md),用户主动触发,5 条硬约束)|
| 12 | Migrate | mech | vault import 工具(部分) | Phase 2 E([ADR-0018](./0018-data-durability.md) 待起草) |
| 13 | Archive | mech | trash + soft delete | OK |

**这张表是入闸标准**:任何新 AI 功能 RFC 必须先在这里找到行,确认类别没错;`creative` 行的功能直接拒。

### 3. 系统 prompt 分层架构(借鉴 Claude Code)

Claude Code 的 prompt 工程是当前最成熟的实现之一。**knowlet 直接借鉴它的设计模式,不重新发明**。

#### 3.1 Envelope 7 层结构

```
<knowlet-system>
  任务级 base instructions(代码里的 per-action 模板:chat / mining / ingest / lint / editor-advisor / tidy-advisor / reorg-planner)
</knowlet-system>

<user-profile src="vault/.knowlet/user_profile.md">
  "我是谁"(身份层,per ADR-0013)
</user-profile>

<wiki-schema src="vault/.knowlet/wiki_schema.md">
  "这个 vault 怎么写"(约定层,per ADR-0023 §2)
</wiki-schema>

<vault-shape>
  total_notes: 247
  top_folders: [{name: papers/, count: 73}, ...]
  depth: 3
</vault-shape>

<recent-activity window="7d" src="vault.events">
  - 2026-05-06 note.created "RAG vs LLM Wiki"
  - 2026-05-05 draft.approved "Karpathy LLM Wiki"
  ...
</recent-activity>

<task type="editor-advisor" action="suggest_location">
  input: {title: "Mintlify virtual filesystem", body_first_200_chars: "..."}
  similar_notes: [...]
  candidate_folders: [...]
</task>

<rules>
  - Always default to the user's currently selected folder.
  - Output MUST be JSON: {"recommended_folder": "...", "reason": "...", "confidence": 0.0-1.0}
  - If confidence < 0.5, return null (don't show suggestion).
</rules>

<examples>
  ... 1-2 个具体输出范例 ...
</examples>
```

#### 3.2 三类层(决定来源 + 是否动态)

| 类型 | 来源 | 动态? | 谁负责组装 |
|---|---|---|---|
| **静态层** | `user_profile.md` / `wiki_schema.md` | 用户编辑 | vault load 时缓存 |
| **派生层** | `vault_shape` / `recent_activity` | 自动派生 | 后端从 `vault.events` + index 算 |
| **任务层** | `<task>` / `<payload>` / `<rules>` / `<examples>` | per-call | 调用方组装 |

#### 3.3 按需载入(lazy)

不是每个 AI 任务都需要全部 7 层。明确每个 role 的"必需 / 可选 / 跳过":

| Role | system | profile | schema | shape | activity | task | rules | examples |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| Chat companion | ✅ | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ |
| Capture extractor | ✅ | — | ✅ | — | — | ✅ | ✅ | ✅ |
| Editor advisor | ✅ | — | ✅ | ✅ | — | ✅ | ✅ | ✅ |
| Search booster | ✅ | — | — | — | — | ✅ | ✅ | — |
| Linter | ✅ | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Tidy advisor | ✅ | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Reorg planner | ✅ | — | ✅ | ✅ | — | ✅ | ✅ | ✅ |

`profile` 仅 chat 需要(影响对话语气);`activity` 主要 lint/tidy 用(看用户最近关注什么)。

#### 3.4 借鉴 Claude Code 的 8 个具体设计

| 设计 | Claude Code 怎么做 | knowlet 落地 |
|---|---|---|
| **Tag 切片 + 稳定 anchor** | `<system-reminder>` / `<example>` 等显式 tag | §3.1 的 7 层 envelope 全用显式 tag |
| **多层级 schema 合并** | `~/.claude/CLAUDE.md` + `./CLAUDE.md` + 子目录 | `~/.knowlet/wiki_schema.md`(跨 vault)+ `vault/.knowlet/wiki_schema.md`(per-vault),三层用得上时启用 |
| **Rule + Why 模式** | 每条 CLAUDE.md 规则带"为什么这样做" | wiki_schema.md 模板硬约定:每条规则必须带 `**Why:**` 行 |
| **Lazy tool loading** | `ToolSearch` 按需载入工具 schema | knowlet vault tools(create_card / start_quiz / list_drafts / ...)按当前 role 注入 |
| **System reminder 周期注入** | 状态 nudge | review queue 进入时注入"你有 12 条 pending drafts";lint 时注入"上次 lint 14 天前" |
| **`<example>` 一两条具体范例** | 关键 behavior 都附 example | 结构化输出场景(editor / linter / tidy / reorg)必须配 1-2 个 example |
| **Slash command 路由** | `/loop` `/init` `/review` 各自带专门 prompt | knowlet chat REPL `:user` `:lint` `:quiz` 等;每个 slash 触发一个 role,**自动按该 role 组装 envelope** |
| **行为规则用绝对句** | "ALWAYS X" / "NEVER Y" | knowlet ADR-0013 §1 翻译进 prompt 用强语气 |

**特别一条**(借鉴 Claude Code 的 norm,不是 prompt 里的 rule):**操作前先用一句话说明判断依据**。Editor advisor 输出推荐位置前先说"基于 5 篇 RAG 相关笔记都在 `concepts/rag/`,建议放那";reorg planner 输出 plan 前先说"检测到 23 篇散在 4 个文件夹,共同主题是 X"。**让用户能直接和理由对话**,这是把 trust-building 做进 prompt 的核心。

### 4. 七个 AI Role

knowlet 的 AI 拆成 7 个互不重叠的 role。每个 role 有明确的输入 / 输出 / 调用入口 / 工作类别:

| Role | 工作类别 | 输入 | 输出 | 调用入口 | 状态 |
|---|---|---|---|---|---|
| **Chat companion** | hybrid | 用户消息 + chat history | 回答 + tool call trace | chat focus mode / chat REPL | 现有,Phase 3 重做 |
| **Capture extractor** | mech | URL / 文件 / 剪报 | source 摘要 → drafts queue | URL 粘贴 / drag-drop / `:capture` | M7.2 部分有,ingest 升级见 [ADR-0023 §4](./0023-llm-wiki-comparison-and-takeaways.md) |
| **Editor advisor** | hybrid | 标题 + 前 N 字 + vault context | 文件夹 / tag / title 候选(JSON,带 confidence) | 新建 note / 通过 draft 时 chip | **新**,Phase 3 |
| **Search booster** | mech | query + top-K 候选 | 重排 + 综合答 | chat-time vault 检索 | 现有(简单版),retrieval v2 见 §"Out of scope" |
| **Linter** | hybrid | 全 vault 扫描 | contradictions / dangling concept / missing entity 报告 | `knowlet lint` / 周报 | **新**,[ADR-0023 §5](./0023-llm-wiki-comparison-and-takeaways.md),Phase 3 |
| **Tidy advisor** | hybrid | M8.1 信号 + vault shape | 小颗粒 IA 建议(≤7 note 单条)| 知识地图侧栏 ambient | **新**,[ADR-0023 §8](./0023-llm-wiki-comparison-and-takeaways.md),Phase 3 |
| **Reorg planner** | hybrid | 用户主动触发 + scope | 整子树 reorg plan(必预览 + 必快照 + 必 manifest) | `knowlet reorg <scope>` 显式命令 | **新**,[ADR-0023 §8](./0023-llm-wiki-comparison-and-takeaways.md),Phase 3 之后 |

**七个 role 是边界**。新 AI 能力提议 → 必须能映射到现有 role,或者证明需要建第 8 个 role(高门槛 ADR 决策)。

## §5 不允许的部分(显式划清 AI 不该做的事)

`creative` 类工作 AI 永远不主动做。具体禁止清单:

### A. ❌ Note ghostwriter — AI 替用户写正文

**冲突**:违反 [ADR-0013 §1](./0013-knowledge-management-contract.md) "用户拥有"。Note 正文是用户的**智力产物**,AI 不替写。

**例外**:用户在 chat 里显式说"帮我把这个 idea 整理成 note 草稿" → AI 输出**草稿**进 review queue,审批后才进 vault。这是 hybrid 路径,不是 creative 替代。

### B. ❌ Note rewriter — AI 自动改老笔记内容

**冲突**:违反 [ADR-0013 §1](./0013-knowledge-management-contract.md)。哪怕 AI 检测到"newer source 推翻此页",**只能 lint 标记**(`status: needs-update`),不能直接改正文。

**正确路径**:Linter 给出报告 → 用户决定是否打开 note 自己改 → 改完 commit。

### C. ❌ Auto-move / Auto-archive / Auto-merge 文件

**冲突**:违反 [ADR-0013 §1](./0013-knowledge-management-contract.md)。任何文件级操作(move / archive / merge / delete)**必须经过 review queue 或用户主动触发的 plan 预览**。

**没有这种 toggle**:不要做"自动模式开关"让用户在 settings 里开启 auto-move。这等同于把 IA 拱手交给 LLM。

### D. ❌ Auto-tag / Auto-alias

**冲突**:tag / alias 是**用户的语义判断**。AI 可以 suggest tag,但不能直接写到 frontmatter。

**正确路径**:Editor advisor 给候选 → 用户在 chip 里点接受 → 才写。

### E. ❌ frontmatter `confidence` 字段(LLM-attributed 版本)

[ADR-0023 §7](./0023-llm-wiki-comparison-and-takeaways.md) 已显式拒绝 Karpathy 模式的 `confidence: high/medium/low` 字段(基于 LLM 综合的来源数)。原因:knowlet 用户**自己写**的 Note,confidence 不是 LLM 能赋值的属性。

**保留**:如果用户**自己**想标"我对这条结论有多确信",可以用 [ADR-0023 §7 status](./0023-llm-wiki-comparison-and-takeaways.md) 的扩展或自定义 frontmatter,**但不引入 LLM-driven confidence**。

### F. ❌ 预设 IA(`entities/` / `concepts/` / `comparisons/` / `maps/`)

**冲突**:Karpathy 模式预设的目录结构是 LLM 在做 IA 决策。knowlet 的所有 AI role **只用用户已有文件夹**,必要时建议建一个新文件夹(经审批),**不会建议"你应该有 entities 目录"这种预设结构**。

## Consequences

### Positive

- **入闸标准统一**:新 AI 功能不能再 ad-hoc 加;必须先在 §1 / §2 表里定位
- **Prompt 架构统一**:不再每个新 AI 任务自己拼 prompt;7 层 envelope 是单一组装路径
- **AI role 边界清晰**:7 个 role 互不重叠,实施时不会越界
- **借鉴 Claude Code**:不重新发明 prompt 工程的成熟模式

### Negative

- 实施工作量大:7 个 role × 7 层 envelope × per-role 的 prompt template + lazy loader = ~3-5 周后端工作
- 引入新概念(envelope / role / 层),文档负担增

### Mitigations

- 实施分阶段:Phase 0/1 已经是 chat companion + capture extractor + search booster 的简单版本;Phase 3 重做时按本架构重写
- 文档负担:本 ADR 是**入闸 reference**,不要求每个 PR 都重读;只要求新 AI 功能 RFC 时引用

### Out of scope

- **Retrieval quality v2**(RRF 融合 / LLM 重排 / query 扩展 / 智能分块)
  借鉴 [qmd](https://github.com/tobi/qmd) 的 4 个设计点,在 Python 栈里重做。**不直接用 qmd**(跨语言 / 2GB 模型 / 架构方向反向)。工作量约 3-4 天,Phase 2 backend polish 候选,触发条件 = dogfood 期发现检索质量是瓶颈。
- **第 8 个 AI role**:本 ADR 锁定 7 个 role。新 role 提议必须是高门槛 ADR 决策,而不是 ad-hoc 加
- **Per-folder wiki_schema.md** 子目录覆盖:Claude Code 支持目录树合并,knowlet 默认只支持 global + vault 两层,per-folder 等用户主动要才做
- **AI 替写 Note 正文 toggle**:即便 settings 里开启也不允许;`creative` 类工作不开后门

## References

- [Karpathy LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — 本 ADR 间接引用(对比对象在 ADR-0023)
- [ADR-0009](./0009-mining-tasks-and-drafts.md) — Mining drafts review queue(§1 hybrid 类的 mechanism)
- [ADR-0013](./0013-knowledge-management-contract.md) — "用户拥有,LLM 提案" 根原则
- [ADR-0023](./0023-llm-wiki-comparison-and-takeaways.md) — LLM Wiki 对比,本 ADR 是它的架构基础
- ADR-0018 数据耐久性(待起草)— `vault.events` 流是 §3 派生层的来源
- Claude Code prompt 工程(借鉴对象;无单一公开规范文档,从行为观察得出)
