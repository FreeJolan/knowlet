# 0028 — AI 输出质量机制契约

> **中文**(English to follow if needed)

- Status: Accepted
- Date: 2026-05-14

## Context

ADR-0024 钉了 AI 能力的 envelope 结构(7 层 prompt)+ 7 个 role + 工作类别约束(mech / hybrid / creative)。它解决了"AI 该做什么、不该做什么、怎么分层组装上下文"。

但**它没回答"我们怎么保证 AI 输出的质量稳定 + 可信"**。Phase 3 启动前必须把这层契约钉死,否则会出现以下任意一种翻车:

- Chat retrieve 0 篇笔记但给了煞有介事的答案 → 用户信了 → 笔记体系被错误前提污染
- Editor advisor 推荐一个明显不相干的 folder → 用户 accept → vault IA 渐渐熵增
- Linter 标了一个根本不矛盾的"矛盾" → 用户去改原本对的笔记 → 数据被 AI 污染
- 用户配了一个低端模型,UI 没提示,体验全面崩溃,用户骂街然后流失

**根原则**(用户 2026-05-14 reframe):**质量不是事后用 eval 测出来的,是事前用产品机制约束出来的。** 本 ADR 是 Phase 3 所有 AI role 在动手前必须满足的机制清单。Eval 框架是后续兜底(防 prompt regression),不是替代机制设计。

## 用户故事(三角色)

**小张(power user · 偶尔自己调 prompt)**
- 他知道 LLM 会幻觉、会编引用、会被低端模型拖累。他要的是:**每条 AI 输出都能溯源**(基于哪几篇笔记 / 哪段对话 / 哪个 tool 调用结果),并且**所有动作可 audit + 可 undo**。
- 失败路径: 他换了个便宜模型测,UI 应该明确告诉他"这是降级模式,以下高质量 role 会被 disable"。

**小红(casual · 信任 knowlet 的默认)**
- 她不懂"幻觉"是什么,但能感受到"AI 这次说得不对"。要的是:**AI 不说没把握的话** —— 没找到笔记就明确说没找到,不在 confidence 低时硬装。
- 失败路径: AI 偶尔出错时,她要能一键反馈"这次答得不好",knowlet 默默记下来,不打扰她。

**完全新用户(刚装,什么都没配)**
- 他第一次打开 chat 没配 LLM,要的是:**清晰的引导**(去哪配 / 推荐什么 / 为什么) —— 不是一个 "LLM not configured" error。
- 失败路径: 他配错了 base URL,UI 要在第一次调用失败时清晰说"是 LLM 配置的锅",不是默默 spinner 转半分钟。

三个故事都通,做。

## Decision

### §1 模型档位策略(用户带,我们画线)

knowlet 不内嵌 LLM、不替用户付费。**用户自带 API key / OAuth 凭证。** 但我们要承担"质量底线声明"责任:

**推荐清单(default = 我们调试时的目标模型)**:

| Tier | 模型示例 | knowlet 行为 |
|---|---|---|
| **A. 推荐** | Claude Opus 4.7 / Sonnet 4.6 / GPT-5 / Gemini 2.5 Pro | 全部 7 个 AI role 正常工作 |
| **B. 可用** | Claude Haiku 4.5 / GPT-4o-mini / Gemini 2.5 Flash | Chat / Capture 可用;Editor advisor / Linter 在 UI 显式标"降级模式,准确率可能下降" |
| **C. 不推荐** | GPT-3.5 / 本地小模型 / 任何 < 8K context window | 大多数 hybrid role 直接 disable,UI 提示"请升级模型以解锁";只保留最基本的 chat fallback |

**配置入口**:Settings → LLM → 模型推荐列表(直接选)+ 自定义 base URL / model name(高级用户)。**默认配置 = 本机 cliproxyapi(OAuth Claude)**,因为用户多数已经有 Claude 订阅。

**质量降级是显式的,不是 silent**:用户选 B/C 档,knowlet UI 永远明确告知当前能力边界,不假装"什么都能做"。

### §2 8 条机制约束(每个 AI role 必须满足)

Phase 3 每个 role slice 在 review 前,必须证明这 8 条都满足:

1. **走统一 envelope** — per ADR-0024 §3。**不允许**任何 role 自己拼 prompt 字符串。所有 prompt 经过 `knowlet/core/ai/envelope.py` 组装,7 层结构强约束。
2. **审计 trail** — 每次 LLM 调用 → `events.sqlite` 写入 `ai.call` 事件,包含:role / model / envelope hash / tool calls / output / latency / cost(token 数)。任意一次 AI 输出**可 replay**。
3. **结构化输出 + JSON schema 校验** — hybrid / mech 类 role 的输出**必须**有 JSON schema。解析失败 → retry 1 次 → 仍失败 → surface error,不向用户展示破损输出。
4. **Confidence threshold + abstain 路径** — 任何"推荐"类输出(editor advisor / linter / tidy)必须带 `confidence: 0.0-1.0`。**低于阈值不显示,不假装有答案**。阈值在 envelope 的 `<rules>` 层硬约定,默认 0.5。
5. **Destination 结构化,不是用户输入文件名** — AI 产物落点必须是约定的结构位(`drafts/` / 推荐 folder / inbox)。不允许 AI 在 prompt 里"决定"文件名 — 文件名永远是 `<note.id>.md` 由 vault 层生成。
6. **First-class tool 调用** — 笔记领域操作(create_card / start_quiz / list_drafts / suggest_folder)走真正的 tool call,不通过 prompt 字符串"假设你能..."。tool catalog 集中维护,lazy 注入(per ADR-0024 §3.4)。
7. **Why / citation 必带** — 任何 AI 输出展示给用户时,必须能回答"为什么":
   - **Chat 答案** → 引到具体笔记片段(grounded);**未引到任何笔记时不显示 citation 区,但答案本身不加 "通用知识" 标(per 2026-05-14 用户决策)**
   - **Editor advisor** → "基于 5 篇 RAG 相关笔记都在 `concepts/rag/`,建议放那"
   - **Linter** → 每条问题指向具体笔记片段
   - **Reorg planner** → 必须输出 manifest + diff 预览
8. **可中断 + 可撤销** — 长链 AI 任务(mining run / reorg / lint)用户**随时可停**(取消按钮),已落地的写动作**可 undo**(走 `.knowlet/backups/` + `vault.events` rewind)。

### §3 参考架构:Claude Code(后端工程)+ Cursor(集成 UX),默认照抄,例外才发明

per 项目 memory `project_ai_design_borrow_from_claude_code`:knowlet AI 的工程模式默认 = 两个成熟产品的实践。Claude Code 教**怎么把 LLM 调出好结果**;Cursor 教**怎么把 AI 顺滑嵌进用户在编辑笔记的工作面板**。两者解决不同问题,knowlet 都需要。

**从 Claude Code 直接照抄(后端 / prompt 层)**:
- 7 层 prompt envelope 结构(ADR-0024 §3 已落)
- `<system-reminder>` / `<example>` / `<task>` / `<rules>` 等 anchor tag
- 多层级 memory(`~/.knowlet/wiki_schema.md` + `vault/.knowlet/wiki_schema.md`,跟 Claude Code 的 `~/.claude/CLAUDE.md` + 项目 CLAUDE.md 同构)
- `Rule + Why` 强约定(memory 里每条规则必须带"为什么")
- Slash command → per-role 专属 envelope 路由
- Lazy tool loading(per ADR-0024 §3.4 提到的 ToolSearch 模式)
- 行为规则用绝对句("ALWAYS X" / "NEVER Y")
- 操作前先一句话说明判断依据(trust-building 进 prompt)

**参考方式**:直接观察我们当前 Claude Code 运行环境(我们就在它里面跑),不是去抓网上泄漏版本。开发期通过 `~/.claude/`、`~/.claude/projects/<proj>/memory/`、当前 system prompt + tool catalog 直接观察 + 模仿。

**从 Cursor 直接照抄(集成 UX 层)**:
- **选中文本 → 召唤 AI 自动带 context**(笔记里选一段 → 快捷键 → chat 已知道这段)
- **`@-mention` 在 chat 里精准拉对象进 context**(@ 笔记 / @ folder / @ tag,比纯 retrieve 更可控)
- **Suggestion → Preview diff → Apply 流**(对应 knowlet 的 drafts queue;UI 必须做 diff 视图,不是只展示 final)
- **`.cursorrules` 项目级规则文件存在**(对应我们 `wiki_schema.md`)
- **整 codebase / vault index 给 AI 用**(我们已有 FTS + vec)
- **显式隐私模式开关在 Settings 显眼位置**

**Cursor 慎抄 / 不抄的部分**:
- ⚠️ ⌘K 内联 AI 重写:必须走 diff preview + accept,绝不 silent overwrite;且 ⌘K 在 knowlet 已被 quick switcher 占,要换键
- ⚠️ Tab autocomplete:需要 fine-tuned 小快模型,Phase 3 不做
- ⚠️ Composer / Agent mode:跟 ADR-0024 §C 冲突,knowlet 等价是 mining task / linter / reorg planner(用户主动触发,不暴露"agent 自由行动")
- ❌ Cursor 的 **autonomously-triggered AI authorship**(typing-time Tab autocomplete / 主动浮 suggest):跟 ADR-0024 §A "AI 必须用户显式调用才写" + ADR-0024 §"AI 替写 toggle 不开后门" + 新增 [ADR-0029 §4 原则 5 "AI 不主动浮"](./0029-cognitive-contract.md) 冲突。 
  knowlet **允许 AI 写大量正文**,**前提是用户显式调用**(在 chat 里说"帮我起草这篇")**且必须走 drafts queue 让用户做最终入库决策**(per ADR-0013 + [ADR-0029 §4 原则 1](./0029-cognitive-contract.md))

**两个参考都没有 + knowlet 必须自己设计**:
- 笔记 tool catalog(create_card / start_quiz / list_drafts / suggest_folder / lint_note / find_dangling_concepts / 等)
- Drafts review queue 工作流 — knowlet 独有的 hybrid 落地路径
- 跨笔记 semantic 工具(near-duplicates / cross-page contradictions / dangling concepts)
- `wiki_schema.md` 笔记 IA 约定层

### §4 Grounding + Citation 政策

**chat 路径默认 = vault-grounded mode**:
- 每次用户提问 → retrieve 相关笔记 → AI 答案 prefer grounded 到 retrieved notes
- UI 在答案区下方展示 "Sources" 区:列被引用的笔记(标题 + 跳转链接),per ADR-0013 §"用户拥有"

**当 retrieve 命中 0 / 极低相关度时**:
- AI 仍可回答(模型自带通用知识能力,我们不强禁)
- **UI 上没有 Sources 区**(因为没有可引用的笔记)
- **不强加 "基于通用知识" 标签** —— 用户从"有没有 Sources 区"自己判断答案的依据(per 2026-05-14 用户决策:有笔记就显示来源,没笔记就只显示答案,信号已足)

**反向**:knowlet 不主动把 chat 包装成 "通用 AI 助手",chat 入口提示语始终强调 "问关于你 vault 的问题"。fallback 是 emergent 行为,不是 first-class feature。

### §5 隐私 / 成本 / 延迟基线

**隐私**:
- 默认 envelope 不注入 `sync_credentials.json` / `.knowlet/sync_state.sqlite` 等敏感文件
- `user_profile.md` 仅 chat companion role 注入(per ADR-0024 §3.3 表),其它 role 不需要
- 用户可在 Settings → Privacy 显式 opt-out 某类层(如"不要发送 recent_activity 到 LLM")
- **本地零 LLM 模式**作为终极兜底:所有 AI feature disable,knowlet 退化为纯笔记软件继续工作(ADR-0013 §"用户拥有"硬要求)

**成本**:
- 每个 role 有默认 token 上限(envelope + completion 总和):chat 16K / capture 8K / editor advisor 4K / linter 32K(全 vault 扫)/ ...
- Settings → LLM → 显示当前月 token 用量(从 `vault.events` 聚合,不靠第三方)
- 不内置 cost dashboard 高级功能;但用户能 export `vault.events` 自己算

**延迟**:
- Chat first-token P50 ≤ 2s / P95 ≤ 5s(基于 Sonnet 4.6 在 cliproxyapi 上的实测基线)
- Editor advisor 总响应 P95 ≤ 1.5s(debounce 1-2s + LLM ≤ 1.5s,用户感知 ≤ 3s)
- Linter 全 vault 扫 P95 ≤ 30s for 1000 notes;期间必须有 progress bar

### §6 失败模式契约

每种失败必须有明确的 UI 表现 + 用户可恢复路径:

| 失败 | UI 表现 | 用户可做的 |
|---|---|---|
| LLM 未配置 | Chat 入口空状态显式提示 + Settings 直达按钮 | 配置 / disable AI |
| LLM 凭证失效 | 第一次调用失败时弹明确 toast + Settings 提醒 | 重新配置 |
| LLM 超时 | "AI 响应超时,要重试吗?" + 重试按钮 | 重试 / 取消 |
| LLM 限流 | "上游限流,请稍后重试" + 暂停 60s 自动重试 | 等待 / 切模型 |
| JSON parse fail | retry 一次,仍失败 → "AI 输出格式异常,本次未应用" | 无需操作,UI 不展示破损 |
| Confidence < threshold | **不显示**该建议 | 不知情 = 正确行为 |
| Tool call 失败 | trace UI 显示哪个 tool 失败 + 错误信息 | 看 trace / 反馈 |
| Retrieve 0 命中 | 答案区正常,Sources 区不显示 | 自己判断 |
| 用户主动取消 long task | 立即停;已写部分保留,未写部分不写 | 后续可重跑 |

### §7 验证(eval 是 Phase 3 后置,不是前置)

本 ADR **不要求 Phase 3 立即建 eval 框架**。机制约束本身就是质量的第一层保障。

**Phase 3 期间**:
- 每个 role slice 通过手动 dogfood 验证 §2 八条机制都实现了
- 用户反馈作为唯一的"质量信号" — 用户撞到的 bug 进 GitHub issue → 修

**Phase 3 之后(灰度前 / Phase 4 内)**:
- 落地 `knowlet/core/ai/eval/` —— fixture vault + query 集 + metric 计算
- 跑 baseline,得每 role 的 precision / recall / hit rate
- 后续 prompt 改动 → CI 跑 eval set → catch silent regression

**为什么不前置**:用户原话(2026-05-14):"我觉得没必要一开始做那么复杂,甚至考虑做什么 eval 决策,即使要做也是后续的事情了。" 机制做对了,初期手动 dogfood 已足;eval 是规模化质量保障工具,Phase 3 单人开发期收益低、成本高。

### §9 对话上下文管理 + LLM API 调用机制

LLM API(OpenAI Chat Completions / Anthropic Messages / Vercel AI SDK 底层)**全部无状态**。每次调用都是独立的,SDK 不替我们维护对话历史。这是 LLM 应用开发的基础事实,所有设计建立在它上面。

#### 9.1 历史维护是 knowlet 的责任

每次 chat 调用,knowlet 都必须组装并发送**完整 message 数组**(system + 所有历史 turn + 当前 user 消息)。没有任何 SDK 替我们做这件事(Vercel AI SDK 的 `useChat` 仅前端 React state 缓存,底层调用仍发完整数组)。

knowlet 历史持久化位置: `vault/.knowlet/conversations/<chat_id>/messages.jsonl`(per ADR-0023 §"events log" 的同构 store)。Drive sync 把它跟笔记一起同步(per ADR-0027)。

#### 9.2 上下文增长 → 三层策略组合

20 轮对话后,单次调用输入轻松超过 10K tokens(history + 检索片段 + envelope)。**成本 + 延迟随对话长度线性增长**。Knowlet chat 用以下组合控制:

| 策略 | 触发 | 行为 |
|---|---|---|
| **滑动窗口** | 默认,所有对话 | 保留最近 N 轮 raw(默认 N=20) |
| **摘要压缩** | 超过窗口 | 把超出窗口的老 turn 喂另一次 LLM 调用压成 1 段摘要,挂在 system 后、history 前 |
| **用户主动重置** | 始终可用 | "新建对话" 按钮 → 归档当前 chat 到 `conversations/`,开新会话 |

**Phase 3 起步只做滑动窗口**;摘要压缩 / 自动重置等到 dogfood 撞到长对话痛点再加。

#### 9.3 Envelope 顺序必须 cache-friendly

Anthropic prompt caching:**5 分钟内同一 stable prefix 的后续调用收 1/10 价**。envelope 7 层组装必须按"稳定度从高到低"排序,把变动小的层放前面:

```
[system static]                ← 长期稳定(每个 role 一份),缓存命中
[user_profile.md]              ← 用户编辑才变,缓存命中
[wiki_schema.md]               ← 用户编辑才变,缓存命中
[vault_shape]                  ← 派生,5min 内大概率不变,缓存命中
[recent_activity]              ← 每次新调用就变,不缓存
[message history]              ← 增长部分,跟当前对话绑定
[<task> / <rules> / <examples>] ← per-call
[当前 user message]            ← 永远新
```

这条顺序在 `knowlet/core/ai/envelope.py` 的组装函数里**硬编**,所有 role 共用。

#### 9.4 Retrieved notes 在历史里的保留策略

Chat 第一轮做了 retrieve 返回 5 篇笔记片段(2-3K tokens),第二轮历史里要保留这些片段吗?

- **保留(默认)**: 上下文连贯,模型能基于第一轮检索结果回答 follow-up。代价 = 每轮都拖着这些 tokens
- **每轮重新检索**: token 省,但 follow-up 可能漂移到新检索结果上 → 答案不连续

**knowlet 默认 = 保留,但裁剪**:只在 history 里保留每篇笔记的 title + 关键片段(~200 tokens/note),不带全文。全文只在该 turn 的 prompt 里出现一次。

#### 9.5 cliproxyapi 路径专项

用户(包括我们 dogfood)很可能通过 cliproxyapi 走 OAuth Claude 路径,而不是直连 Anthropic API。这条路径有几个区别要 knowlet 在设计上对齐:

| 维度 | 直连 Anthropic API | cliproxyapi → `claude -p` |
|---|---|---|
| 凭证 | API key | OAuth Claude 订阅配额 |
| 状态 | 服务端无状态(API 真)| `-p` 进程无状态(进程真),knowlet 仍发完整 history |
| 用户配置漏入 | 无 | **`~/.claude/CLAUDE.md` + 项目 CLAUDE.md + skill 会注入**,可能污染 knowlet 输出 |
| Claude 内置 tool | knowlet 不允许 LLM 直接动 vault | 同左 —— cliproxyapi 必须运行在禁 tool 模式;**knowlet 不依赖 LLM 内置 tool** |
| Prompt cache | 完整支持(传 `cache_control`)| 取决于 cliproxyapi 是否透传 cache 字段;**有则赚,无则正常** |
| 启动延迟 | 网络往返 | + 几百 ms 进程 spawn 开销 |
| 模型固定 | API 调用方指定 | 只能用当前登录的 Claude 模型 |

**knowlet 的 design 必须同时兼容两条路径**:
- 默认配置 = cliproxyapi(per global CLAUDE.md 上的 Settings 引导),零摩擦
- Settings 允许配置直连 API(高级用户 / 不想要配置污染 / 要更稳的延迟)
- envelope 设计 cache-friendly + 不依赖 Claude 内置 tool —— 两条路径都能跑

**配置污染兜底**:Phase 3 内 dogfood 阶段接受 `~/.claude/CLAUDE.md` 漏入(成本低、影响小);灰度前(Phase 4)必须实测 + 文档化此风险,或要求 cliproxyapi 增强为"isolated context 模式"。

#### 9.6 关键设计纪律:LLM = 决策大脑,knowlet = 动手手脚

**任何对 vault 的实际写操作(create file / move / delete / update),永远不通过 LLM tool call 执行**。LLM 的输出永远是**结构化 JSON 决策**(JSON schema 校验后),knowlet 自己的代码读 JSON 后执行实际动作。

例:Editor advisor 输出 `{"recommended_folder": "concepts/rag/", "confidence": 0.8, "reason": "..."}`,knowlet UI 弹气泡让用户 accept,**用户点 accept 后 knowlet 自己做 `vault.move_note()`**。LLM 永远不直接动文件。

这条是 ADR-0024 §C "auto-move 禁止" + ADR-0028 §2 第 6 条 "first-class tool 调用" 的合并表达。也是 cliproxyapi 路径下的硬保险 —— 即使 Claude 内置 tool 没禁,knowlet 也不会被它影响。

### §8 不做的事(显式划清)

- ❌ **AI 替用户做笔记入库的最终决策** — per ADR-0024 §5 A + ADR-0029 §4 原则 1。**关键澄清**:AI **允许写大量正文**,前提是用户**显式调用** AND 走 review 流让**用户做最终入库决策**。本条 anti-goal 锁的是"决策权"而非"AI 写多少字数"
- ❌ **Auto-tag / Auto-alias / Auto-move / Auto-merge** 等任何未经用户显式触发就改 vault 状态的行为 — per ADR-0024 §5 C/D
- ❌ **frontmatter `confidence` LLM-attributed 字段** — per ADR-0024 §5 E
- ❌ **预设 IA(`entities/` / `concepts/` / 等强制文件夹)** — per ADR-0024 §5 F
- ❌ **AI fallback 到通用问答时强加 "通用知识" 标签** — per §4
- ❌ **Phase 3 内做完整 eval 框架** — per §7,后置到灰度前

## Consequences

**Positive**

- Phase 3 每个 role slice 在动手前有明确"完成标准" = §2 八条机制约束 + §1 模型档位 + §4 grounding 政策 + §6 失败契约。质量从"靠记忆 / 当下灵感"变成 30 秒查表。
- 用户对 AI 输出有可解释性(citation / why / trace / replay) —— trust building 进产品骨架
- 模型档位策略避免"用户用便宜模型 → 体验崩 → 怪 knowlet" 这条 churn 链
- 借鉴 Claude Code 而不是发明新东西 —— 开发成本 -50%,质量底线 +∞

**Negative / Risks**

- §2 第 3 条(JSON schema)强制后,某些自然语言场景(chat 答案)模型可能受约束更僵硬。**Mitigation**:chat 答案不要求 JSON schema,只对结构化 hybrid role 强制
- §1 B/C 档显式 degrade 提示可能让低端模型用户觉得 knowlet "嫌弃"他们。**Mitigation**:措辞中性("以下功能在你当前模型上效果不可靠,推荐升级到 X 享用完整体验"),不嘲讽
- §4 不强标 "通用知识" 答案 → 用户可能误以为所有答案都基于笔记 → 引用错误前提。**Mitigation**:dogfood 中持续观察;如果出现问题,这条决策可以反悔
- §6 失败 UI 矩阵在初期可能不完整(只覆盖最常见路径)。**Mitigation**:dogfood 撞到再补,本 ADR 是 baseline 不是穷举

## Alternatives considered

- **方案 A:Phase 3 前置做完整 eval 框架** — 工程量大,Phase 3 单人开发期没数据可对比,主要会拖延所有 role 落地。**用户 2026-05-14 显式否决。** 推到 Phase 4 之前再做。
- **方案 B:knowlet 内嵌 LLM(自带 Opus / 自带本地模型)** — 数据主权 ✅ 但商业模式重(替用户付 API 费 / 自训模型成本爆炸)。**否。** 用户带 = 数据主权 + 成本透明 + 用户选择权。
- **方案 C:不区分模型档位,任何模型都暴露全部 AI feature** — silent failure 风险大,小红 / 新用户体验差。**否。** §1 显式画线 + 显式 degrade 提示是必须的。
- **方案 D:发明 knowlet 自己的 prompt envelope / tag schema / memory 层级** — 重复造轮子,质量不一定更好。**否,per 项目 memory `project_ai_design_borrow_from_claude_code`**。

## References

- [ADR-0024 — AI assist envelope + 7 roles + "creative 工作 AI 不主动,仅在用户显式调用时输出草稿走 review queue"](./0024-ai-assist-envelope.md)
- [ADR-0013 — 知识管理契约(用户拥有)](./0013-knowledge-management-contract.md)
- [ADR-0023 §3 — events log(audit trail 基础)](./0023-llm-wiki-comparison-and-takeaways.md)
- [ADR-0023 §5 — Linter 规约](./0023-llm-wiki-comparison-and-takeaways.md)
- [ADR-0023 §8 — Editor / Tidy / Reorg advisor 规约](./0023-llm-wiki-comparison-and-takeaways.md)
- 项目 memory:
  - `project_knowlet_ai_value_is_curated_workflow.md`(差异化论点)
  - `project_ai_design_borrow_from_claude_code.md`(借鉴策略)
  - `feedback_knowlet_not_manual_authoring_centric.md`(用户场景定位)
  - `project_ai_rework_gated_on_kb_complete.md`(Phase 3 启动前置)

## 实施位置

- `knowlet/core/ai/envelope.py` — §2 第 1 条(P3.1 落地)
- `knowlet/core/ai/role/{chat,capture,editor_advisor,linter}.py` — 每个 role 一个文件,内嵌 prompt + tool + JSON schema(P3.2-P3.6 各 slice)
- `knowlet/core/ai/tools/` — 笔记领域 tool catalog(P3.2 起按需扩)
- `knowlet/core/events.py` — `ai.call` event 类型(扩 ADR-0023 §3 的 schema)
- `frontend/src/components/Chat/`, `Capture/`, `Lint/`, ...(各 Phase 3 slice 的 UI)
- Settings → LLM panel + Privacy panel + 用量展示(P3.2 起逐步落)
- `tests/fixtures/ai/` — Phase 4 内的 eval fixture 起点(本 Phase 不做)
