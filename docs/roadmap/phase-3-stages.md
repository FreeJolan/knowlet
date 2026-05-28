> ⚠️ **已被取代(2026-05-24)** — 本 7-Stage 计划已被 [`ai-modes-roadmap.md`](./ai-modes-roadmap.md) 取代。
> 经 2026-05-24 与用户的重定向讨论,这套 envelope 全家桶 / linter 全库扫 / reorg planner / tidy advisor /
> vault health dashboard / 知识·资料二分 / anti-drift 队列 大部分被判为**伪需求或早产**(建立在发明的
> persona 上,而非用户真实需求)。新方向 = need-driven 的 **modes**(Cursor-for-notes:grounded 对谈 +
> stance + diff-accept)。**请按 `ai-modes-roadmap.md` 推进;截至 2026-05-28,F0 AI 底层能力重构已达到当前门槛,下一步是阶段 E/Quiz。** 本文件仅作历史参考。
> 另注意:`AGENTS.md` 的 Phase A/B/C/D/E 是协作流程,不是本 repo 的产品 roadmap 阶段;不要用本文件里的旧 stage/slice 名称推断下一步。

# Phase 3 — 7 Stage 推进计划(2026-05-16 重打包)

> **状态**: 临时活文档,供按 stage 推进 + TuTu 任务跟踪。整个 Phase 3 完成后可与 `phase-3-slicing.md` 合并或归档。
>
> **为什么重打包**: 之前 `phase-3-slicing.md` 把 4 项 AI 能力推到 Phase 4(Eval / Reorg planner / Tidy advisor / Retrieval v2)。本计划把它们全部拉回 Phase 3,**让 Phase 4 纯粹做 hardening + 灰度准备**,不再承担新 AI feature 引入。
>
> **取代关系**: 本文件取代 `phase-3-slicing.md` 中"slice 概览"那张表;原文件里各 slice 的详细描述(用户故事 / ADR 检测)仍是有效参考。

---

## 总览(7 Stage)

| # | TuTu 短名 | 包含 | 工期 | 累计 |
|---|---|---|---|---|
| 0 | LLM 设置 | P3.0 LLM Settings | ✅ done | — |
| 1 | **AI 底盘** | Envelope framework + Retrieval v2 + ai.call audit | 6-8 天 | 6-8 天 |
| 2 | **结构基底** | 知识/资料 type chip + wiki_schema/user_profile 注入 | 5-7 天 | 11-15 天 |
| 3 | **采集闭环** | Drafts queue 重做 + Capture extractor | 9-11 天 | 20-26 天 |
| 4 | **对话重做** | Chat companion v2(@-mention / Sources / Vercel AI SDK) | 5-7 天 | 25-33 天 |
| 5 | **随写助手** | Editor advisor + Tidy advisor | 6-8 天 | 31-41 天 |
| 6 | **巡检重组** | Linter + Mining tasks UI + Reorg planner | 11-14 天 | 42-55 天 |
| 7 | **总收口** | Vault Health Dashboard + Eval framework + 全 phase dogfood | 7-9 天 | 49-64 天 |

**Phase 3 总工期**: 49-64 工作日 = **10-13 周**单人开发(比原 5-7 周长,因为收了 4 项推后能力)。

---

## Stage 1 — AI 底盘

**TuTu 名**: `AI 底盘`

**范围**:
- **Envelope assembly framework**(原 P3.1)— 所有 AI role 走统一 `knowlet/core/ai/envelope.py` 组装 prompt;按 ADR-0024 §3.1 的 7 层结构按需 lazy load;为后续每个 role 提供共用基础设施
- **Retrieval quality v2**(原 Phase 4 backlog)— RRF 融合 / LLM 重排 / Query 扩展 / 智能分块。借鉴 qmd 的 4 个设计点用 Python 重做(per ADR-0024 §"Out of scope")
- **ai.call audit log** — 每次 LLM 调用写 `events.sqlite`,Settings → Advanced 可看最近 N 次 trace

**用户感知**: 普通用户感知不到。但 Search booster 召回质量肉眼可见地提升,Chat 答案更准。Power user 可看 audit log。

**满足 ADR**:
- ADR-0028 §2 第 1 条(统一 envelope)+ 第 2 条(audit trail)
- ADR-0028 §9(对话上下文 + cliproxyapi 路径)
- ADR-0024 Search booster role 升级

**工期**: 6-8 天

---

## Stage 2 — 结构基底

**TuTu 名**: `结构基底`

**范围**:
- **知识/资料 type chip + per-source 默认**(原 P3.8)— frontmatter 加 `kind: knowledge | reference` 字段;`<KindChip>` 组件落 4 个 surface(文件树 / note header / drafts / quick switcher);⌘⇧K 切换;**升级即时,降级需 popover 二次确认**(per ADR-0029 §4.5 anti-drift)
- **wiki_schema 多层级 merge**(原 P3.A 的一部分)— `~/.knowlet/wiki_schema.md`(global) + `vault/.knowlet/wiki_schema.md`(per-vault),global 先 per-vault 追加在后
- **wiki_schema 模板 + onboarding 文案** — vault init 时写 starter 模板,含 Rule + **Why:** 行示例(per ADR-0024 §3.4)

注: `user_profile.md` / `wiki_schema.md` **注入 envelope** 的部分已在 Stage 1 落地(`knowlet/core/ai/layers.py` 的 `UserProfileSource` / `WikiSchemaSource`)。本 stage 只补 multi-level merge + onboarding。

**用户故事(三角色)**(已与 ADR-0029 §4.5 默认分类表对齐):
- **小张**: 手动 ⌘N 新建 → 默认 **知识**(主动写 = 主动思考);看完一份资料想转 ⌘⇧K → popover 提示"资料 → 知识 即时生效";偶尔写偏了想降级 → 同键 → popover 警告"知识 → 资料 需二次确认"防误降
- **小红**: 文件树每行 / note header / quick switcher 都看见 📘 知识 / 📄 资料 的小 chip,hover 出 tooltip 解释("知识 = 你要内化的内容,会进 review queue / 资料 = 备查内容,直接存");随时一眼知道每篇是哪类
- **新用户**: 第一次进 vault 看到 chip 跟解释 → 不读文档就理解结构;空 vault 的 starter `wiki_schema.md` 模板演示了 Rule + Why 写法

**满足 ADR**:
- ADR-0029 §4.5 知识/资料 asymmetric distinction(完整兑现:per-source 默认表 + 升降级不对称 + structure-visible meta 原则 + permanent learnability hover)
- ADR-0023 §2 wiki_schema(multi-level merge + co-evolution 主动机制)
- ADR-0024 §3.4 借鉴成熟 agent 的 Rule + Why 模式(模板硬约定)

**工期**: 5-7 天

---

## Stage 3 — 采集闭环(2026-05-21: §3.7 deferred to Stage 4)

**TuTu 名**: `采集闭环`

> 实施记录(2026-05-21): §3.1–§3.6 + §3.8 全部 ship;§3.7 chat URL inline review 合并到 Stage 4(对话重做)— chat 输入面本来要重写,inline review 和 chat input 重写合做一次更自然。⌘⇧V + CaptureBox 已经覆盖了小红从 chat 外的 capture 路径。



**范围**:
- **Drafts queue 重做**(原 P3.9)— capture-time inline review;age tickling;auto-archive;anti-drift 四种 safety net(per ADR-0029 §4 原则 7 + ADR-0009 amendment 2026-05-16)
- **Capture extractor**(原 P3.3)— URL paste / drag-drop PDF / Capture box;⌘⇧V 全局快捷键;接 drafts queue 流;支持 知识/资料 默认分类入口

**用户故事(三角色)**:
- 小张: ⌘⇧V 粘贴 URL → AI 提 source 摘要 → inline 三按钮(📚 资料 / 💡 知识 / 跳过)→ 一秒进 vault,不打断当前思路
- 小红: 偶尔丢 URL 进 chat → AI inline 显示三按钮 → 她点 [📚 资料] → 一秒完成
- 新用户: 看到 capture box 大字标"先随便扔,以后再整理" → 安心扔

**满足 ADR**:
- ADR-0029 §4 原则 7(capture-time default + anti-drift 四套)
- ADR-0009 amendment 2026-05-16(drafts queue 全闭环)
- ADR-0023 §4(ingest source 一等动作)
- ADR-0024 Capture extractor role

**工期**: 9-11 天(这是整个 phase 最重的 stage)

---

## Stage 4 — 对话重做

**TuTu 名**: `对话重做`

**范围**:
- **Chat companion v2**(原 P3.2)— 前端 chat focus mode;Vercel AI SDK 化替代自写 SSE;走 Stage 1 的 envelope;`@-mention` 拉 note 进 context(借鉴 Cursor);Sources 区永远比 answer 显眼

**用户故事(三角色)**:
- 小张: chat 里 `@projects/foo` → note 进 context;回答下方 Sources 列出引用,点击跳源文 → 不再担心 AI 幻觉,知道答案哪儿来
- 小红: 问问题,得到回答 + Sources;她看 Sources 比看回答先,因为知道这是自己 vault 里有的东西
- 新用户: 进 chat 看到一个例子提示("试试问'我最近在想什么?'"),敲一下,看 AI 从她仅有的 3 篇 note 里给出回答

**满足 ADR**:
- ADR-0024 Chat companion role 重做
- ADR-0023 §6(pin chat turn 到 wiki) — 顺便落地
- ADR-0015 §3(citation Layer)

**工期**: 5-7 天

---

## Stage 5 — 随写助手

**TuTu 名**: `随写助手`

**范围**:
- **Editor advisor**(原 P3.4)— 新建 note / 通过 draft 时 chip 显示文件夹 / tag / title 候选(JSON + confidence)
- **Tidy advisor**(原本 ADR-0024 Phase 3,但 phase-3-slicing.md 漏了)— 基于 vault shape 给小颗粒 IA 建议(≤7 note 单条),入口在知识地图侧栏 ambient

**用户故事(三角色)**:
- 小张: 新建 note 输完标题前 50 字,右上角 chip 给三个文件夹候选(带 confidence)→ 一键采纳;侧栏偶尔 ambient 提示"这几篇关于 X 的笔记可以合并/重命名/挪到 Y"
- 小红: 不主动看 chip 也不影响她写;偶尔扫到 ambient 提示觉得"哦原来可以这样整理",点采纳
- 新用户: 第一篇笔记新建时 chip 给的三个候选都是空文件夹建议 → 引导她建立组织习惯

**满足 ADR**:
- ADR-0024 Editor advisor role + Tidy advisor role
- ADR-0023 §8(IA 小颗粒建议)
- ADR-0029 §4 原则 5(不主动浮 = Tidy 只在侧栏 ambient,不弹窗)

**工期**: 6-8 天

---

## Stage 6 — 巡检重组

**TuTu 名**: `巡检重组`

**范围**:
- **Linter**(原 P3.6)— 用户主动触发(`knowlet lint` / Settings 按钮 / `:lint` slash);全 vault 扫 contradictions / dangling concept / missing entity / drift signals;不自动运行(per ADR-0029 §5b)
- **Mining tasks UI**(原 P3.5)— 定期 background AI 工作的配置 / 触发 / 结果审查面板
- **Reorg planner**(原 Phase 4)— 整子树重组(`knowlet reorg <scope>` 显式命令);必预览 + 必快照 + 必 manifest

**用户故事(三角色)**:
- 小张: 周末点一下 lint,看 vault 里的矛盾报告 / 缺页 entity / 待挂连接;mining tasks 配了"每日扫我订阅源进 drafts";偶尔用 reorg 把一坨 essays/ 重组到 essays/by-topic/
- 小红: 不主动用这些,但偶尔在 Dashboard 看到 lint 报"你 5 篇笔记可能在说同一件事"会点进去看
- 新用户: 不接触;这些是熟手才用的工具,UI 不挡她

**满足 ADR**:
- ADR-0024 Linter role + Reorg planner role + Mining tasks
- ADR-0029 §5b(Linter 仅用户触发,backlog 不自动 nag)
- ADR-0009(mining tasks 完整闭环)

**工期**: 11-14 天(三个 role,reorg planner 本身偏复杂)

---

## Stage 7 — 总收口

**TuTu 名**: `总收口`

**范围**:
- **Vault Health Dashboard**(原 P3.7)— 一个屏幕看 vault 全貌:总 note 数 / kind 分布 / drafts 积压 / lint 信号 / capture 节奏。**Discovery surface,不是 AI role**
- **Eval framework**(原 Phase 4)— AI role 输出质量评测;离线跑;录回归 case;不进生产路径
- **全 Phase 3 dogfood + 修复** — 串起前 6 个 stage 真用一遍,发现的小坑全部修

**用户故事(三角色)**:
- 小张: Dashboard 是他的"周日早晨页面",一眼知道 vault 是否健康;Eval 不直接用(那是开发者工具),但他知道 AI 输出在被持续监控
- 小红: 偶尔点开 Dashboard 看一眼,知道自己上周写了多少
- 新用户: 进 Dashboard 看到"你目前有 0 篇笔记,从这里开始" → 友好引导

**满足 ADR**:
- ADR-0024 Dashboard(非 role)+ Eval framework
- ADR-0028 §7(Eval framework 落地)
- ADR-0029 §4 原则 8(dashboard discovery 机制)

**工期**: 7-9 天

---

## 依赖关系(给"能不能跳着做"用)

```
Stage 0 (P3.0) ✅
   ↓
Stage 1 (底盘) ──→ Stage 2 (结构) ──→ Stage 3 (采集) ──→ Stage 6 (巡检重组)
                                         ↓                  ↓
                       Stage 4 (对话) ←───┼  ←──── 大致可并行   ↓
                       Stage 5 (随写) ←───┘                     ↓
                                                                ↓
                                                      Stage 7 (收口)
```

**强依赖**(必须按顺序):
- Stage 1 → 所有后续(没 envelope 都不行)
- Stage 2 → Stage 3, 5(类型分类是 capture 默认值的前提)
- Stage 3 → Stage 6 Mining(mining 写 drafts queue)
- Stage 6 → Stage 7(Dashboard 要展示 lint 结果)

**可并行**(只要 Stage 1+2 都好了):
- Stage 4 (对话) 独立于 Stage 5 (随写) 独立于 Stage 6 (巡检)

**推荐顺序**(单人最朴素): 1 → 2 → 3 → 4 → 5 → 6 → 7。即 TuTu 里 1-7 顺序往下勾。

---

## Phase 4 现在是什么样

把 4 项 AI 能力收进 Phase 3 后,Phase 4 就**纯 hardening + 灰度**:

- 全栈 e2e 测试(Playwright)
- 文档完整(install / use guide / CONTRIBUTING)
- 灰度发布机制(brew formula / installer / 邀请流程)
- 灰度期 entry criteria 评估(per ADR-0022)
- (历史延期项里仍剩"等 dogfood 信号"那一栏,不在 Phase 4 必做范围)

预估仍是 **1-2 周**。

---

## 全局时间表(2026-05-16 修订)

```
Stage 0 LLM 设置        ✅ done
Stage 1 AI 底盘         6-8 天
Stage 2 结构基底        5-7 天
Stage 3 采集闭环        9-11 天
Stage 4 对话重做        5-7 天
Stage 5 随写助手        6-8 天
Stage 6 巡检重组        11-14 天
Stage 7 总收口          7-9 天   ← Phase 3 完
Phase 3.5 桌面端        2-3 周
Phase 4 hardening      1-2 周   ← 灰度入口
v1.0.0 灰度
Phase 5 移动端          ?       ← 灰度有反馈后启动
```

到 v1.0.0 灰度入口前: **Phase 3 (10-13 周) + Phase 3.5 (2-3 周) + Phase 4 (1-2 周) = 13-18 周**。
