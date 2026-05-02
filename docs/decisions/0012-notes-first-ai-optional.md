# 0012 — 笔记本位 / AI 是可选增强

> [English](./0012-notes-first-ai-optional.en.md) | **中文**

- Status: Accepted
- Date: 2026-05-02

## Context

2026-05-02 第二轮独立工程审视(`Agent` 工具 fresh-eyes)指出一处**真实内在矛盾**:
- ADR-0003 把产品命名为"AI 长期记忆层(wedge)"
- ADR-0011 在 6 天后强制"笔记软件本位"的 IA 重做
- 但**依赖栈是 agent 平台栈**(openai / sqlite-vec / sentence-transformers / FSRS / SSE / APScheduler / trafilatura / feedparser);**笔记软件标配的两件**(真编辑器 / wikilink+backlink)被 defer;**只有 AI 工具才有的东西**(mining / chat / sediment / cards)全 ship 了

每一次 UX 决策都在两极之间摇摆;ADR-0011 之后下一个 ADR 大概率是 "0013 — re-pivot"。**必须先回答"knowlet 是什么"。**

## Decision

**knowlet 在产品定位上是一款笔记软件 / 个人知识库。AI 是可选的增强能力,而非核心。**

具体含义,落到一条**可验证**的硬约束:

> **没有配置 AI 能力的用户,knowlet 仍然可用。**

这不是 marketing 话术,是工程契约。下面是它在**每一个**子系统上的具体形态:

| 子系统 | AI 配置 = 0 时 | AI 配置 = 1 时 |
|---|---|---|
| **Note CRUD**(创建 / 编辑 / 删除 / 重命名) | ✅ 完整功能 | ✅ 完整功能 |
| **File tree 导航 / Cmd+P 跳转** | ✅ 完整 | ✅ 完整 |
| **检索**(FTS5 trigram 通路) | ✅ 完整 | ✅ + 向量通路 + RRF 融合 |
| **Cards / FSRS 复习**(算法层) | ✅ 完整,卡片由用户手写 | ✅ + AI 协助生成卡片 |
| **Cmd+K 命令面板** | ✅ 跳转 / 命令 | ✅ + `>` ask AI / 部分命令 |
| **Mining 订阅** | ⚠️ **降级**:抓取 RSS / URL → 存原始 item;**不做 AI 摘要**;Inbox 显示 raw 内容,用户自己决定怎么处理 | ✅ 完整 + AI 抽取 + 起标题 + 打标签 |
| **Sediment(对话沉淀为笔记)** | ❌ 隐藏入口(没有对话可沉淀) | ✅ 完整 |
| **Chat dock / Chat focus** | ❌ 隐藏入口 + UI 不渲染 | ✅ 完整 |

注意"❌ 隐藏入口"**不是显示"配置 AI 才能用"的 CTA**。配置 AI 是用户主动加能力,不是产品向用户讨要 token —— 入口悄悄隐藏即可。

## Operational rule(强约束,新功能必须满足)

> **每个新功能落地前,必须回答:"AI 没配置时,这个功能是什么?"**
>
> 三种合法答案:
> 1. **完整工作**(笔记 CRUD / 检索 / Cards / Cmd+K 跳转)—— 跟 AI 完全无关
> 2. **降级工作**(Mining 抓取但不抽取)—— 给出更弱但可用的形态
> 3. **隐藏**(Chat / Sediment / Ask AI)—— UI 入口直接不渲染,不留 disabled 灰按钮

**没有第四种答案。**"等用户自己去 settings 配 AI 才能用"不是答案 —— 那等于把"笔记软件"降级为"AI 工具,顺便能写笔记"。

## 为什么这是 ADR-0003 的延续而不是反转

ADR-0003 的真正承诺是"**AI 长期记忆层**"作为 **wedge 差异化**(对比 Bear / Obsidian / Notion 多了什么),不是产品**身份**。身份始终是"个人知识库 / 笔记软件",AI 是身份之上的差异化层。

之前的混淆来自 ADR-0003 §"产品形态"对 wedge 的描述太浓,读起来像身份。本 ADR 把它显式为身份 + 差异化的两层结构:

```
┌─────────────────────────────────────────┐
│  knowlet 身份 = 个人知识库 / 笔记软件      │  ← AI 没配置时仍然成立
├─────────────────────────────────────────┤
│  knowlet 差异化 = AI 长期记忆层            │  ← 配置 AI 后解锁
└─────────────────────────────────────────┘
```

## Consequences

### 立即触发的 backlog 项

- **`knowlet doctor` 必须区分 LLM 配置缺失 / embedding 配置缺失 / 全无**,并且**只在其中两种情况告警**(全无是合法状态,不是错误)
- **首次启动空 vault 不强制 AI setup wizard**(ADR-0011 §8 已经写对,确认)
- **Mining 在 LLM 缺失时降级**:`run_task` 应该检测 LLM 不可用 → 跳过抽取阶段,把 raw item 直接成 draft
- **UI 入口动态隐藏**:`/api/health` 返回 `ai_available: bool`(基于 LLM 配置 + 启动时 healthcheck);前端根据这个 flag 渲染 Chat / Sediment / `>` ask AI 入口
- **Cards 创建路径**:除了"AI 从 chat 生成卡片",还要保留"用户手动 new card"流程(目前 CLI 有,UI 没有)

### 跟现有 ADR 的关系

- **ADR-0003** 应该追加注释指向本 ADR,把"AI 长期记忆层"明确定位为 wedge 差异化而非身份
- **ADR-0011** 落实(§"产品定位字面成立")—— 但当时只解决 UI 的 chat-first 问题,没把"AI 可选"这条结构性原则提炼出来,本 ADR 补上
- **`feedback_no_hidden_debt` §6**(2026-05-02 加的"基础设施决策不能推到以后")—— 本 ADR 是它的应用:AI-optional 不能"等以后再补",每个新功能落地都得过这关

### 跟产品方向的关系

之后所有产品级思考(碎片化治理 ADR-0012-候选 → 现在改 ADR-0013、笔记考试模式、被动结构化、周报)都在本 ADR 的契约下展开:
- **AI 出题 / AI 评分**:身份允许("AI 是 advisory"),但用户必须能不用 AI 直接 review notes
- **被动结构化(cluster / 近重复)**:AI 计算可选;没有 embedding 时 fallback 到关键词去重
- **周报**:可以有 AI 摘要版,也可以有"上周新增 N 条"纯统计版

## 决策溯源

- 用户原话(2026-05-02):"我始终在强调,'人才是主体,AI 是辅助',所以当然,我们在做一款笔记软件(本质是知识库),这一点体现在,就算用户没有配置 AI 能力,照样能使用 knowlet。"
- 触发于 2026-05-02 第二轮独立工程审视的 critique #6(产品定位内在矛盾)
- 跟用户多轮 feedback 一致:`feedback_no_hidden_debt`(AI 是工具不是主体)、`project_knowlet_fragmentation_thinking` §"永不自动改 IA"契约(同源原则)
