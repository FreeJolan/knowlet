# 0004 — AI 编排 + 原子执行(AI compose, code execute)

> [English](./0004-ai-compose-code-execute.en.md) | **中文**

- Status: Accepted
- Date: 2026-04-30

## Context

knowlet 在 [ADR-0003](./0003-wedge-pivot-ai-memory-layer.md) 中确立的破局点是"AI 长期记忆层 + 减负型 PKM",其核心承诺包括:

- AI 替用户承担机械整理(草稿 + 人工审查)
- 工具栈持续变薄(吃掉用户原本被迫使用的工具)
- 零迁移成本与零强制学习曲线
- AI 行为透明 + 可定向

这些承诺如果用传统的"代码内置每条工作流 + UI 暴露每个动作"实现,会陷入两个问题:

1. **每加一个能力就要新增 UI / 工作流 / onboarding 步骤**,工程量与维护成本同步膨胀
2. **用户需要为每个新能力学习新的 UI 模式**,跟"零强制学习曲线"承诺直接冲突

观察当前 LLM(Claude Opus 4.x / GPT 4.x / Gemini 2.x 等)的能力,已经具备:

- 理解自然语言意图
- 拆解多步任务
- 基于反馈调整执行
- 通过 tool-call 完成具体动作

也就是说,**LLM 本身已经能担任工作流的编排者**。代码可以只暴露原子能力,跨能力的工作流让 LLM 通过 tool-call 编排。

LLM 的输出存在概率性,这意味着编排会有失败可能。但当模型足够强,失败率低到可以通过设计兜底(可逆操作 / 二次门 / 透明审计)消化时,**用编排成本换 UI 与维护成本的减少**整体是划算的。

这个判断需要被显式记录,因为它影响 knowlet 几乎每一个产品与工程决策。

## Decision

### 总原则

knowlet 在代码中**只实现"原子能力层"**:输入输出明确、有限副作用、尽可能可逆、单一职责的一组 tools。**所有跨特性的工作流逻辑都让 LLM 通过 tool-call 编排**,不在代码中写专门的 UI 或工作流路径。

```
┌─────────────────────────────────────────────┐
│  AI 编排层(概率性)                          │
│  理解意图 / 拆步骤 / 决定调用哪些 tool        │
└─────────────────────────────────────────────┘
                    ↓ tool calls
┌─────────────────────────────────────────────┐
│  原子能力层(确定性)                         │
│  输入输出明确 / 有限副作用 / 可测试 / 可回滚   │
└─────────────────────────────────────────────┘
```

### 四条执行约束

为了让"概率尾部"的代价可控,原子能力层必须遵守:

#### 1. 可逆 / 幂等优先

- LLM 调错 `delete_note(x)`,用户能 `undo`
- 重复调用 `tag_note(x, "ai")` 不产生副作用
- 把"概率失败"的代价从"数据损坏"降到"多按一次撤销"

#### 2. 破坏性操作走二次门

- `delete_note` / `move_note` / `merge_notes` 等不可逆 tool 不直接执行
- 先返回"待确认"状态,LLM 把意图用自然语言复述给用户,用户拍板才执行
- 这是给概率尾部的安全网,也是 ADR-0003 中"AI 草稿 + 人工审查"在 tool 层的延伸

#### 3. 颗粒度对应"一句话动作"

- 太碎(20 个 CRUD):LLM 容易迷路、token 浪费
- 太大(god-tool):编排灵活性失效
- 经验法则:每个原子能力 ≈ **用户能用一句话描述的动作**("把这条 Note 标为重要"、"把这两条关联起来")

#### 4. 返回结构化数据,不返自然语言

- LLM 要基于结果继续编排;自然语言需再 parse 一次,徒增不确定性
- 错误信息要带"建议修复方式",让 LLM 自动恢复

### 与 [ADR-0002](./0002-core-principles.md) / [ADR-0003](./0003-wedge-pivot-ai-memory-layer.md) 的关系

本 ADR 是上述 ADR 在**工程边界**上的支撑,而非新原则:

| 上层原则 | 本 ADR 的支撑 |
|---|---|
| AI 是可选增强(ADR-0002) | 原子能力层是确定性的,关掉 AI 仍然可用(只是失去编排) |
| 数据主权(ADR-0002) | 原子能力的输入输出都在用户的 vault 内,LLM 编排不增加数据外泄面 |
| 能力插件化(ADR-0002) | 原子能力天然就是插件单元,新增插件 = 新增 tool |
| AI 草稿 + 人工审查(ADR-0003) | "审查"是概率尾部的人工兜底机制 |
| 零强制学习曲线(ADR-0003) | 用户用自然语言说话,不需要学 UI 模式 |
| 透明 + 可定向(ADR-0003) | tool call 天然可日志化 / 可审计 |

### 与 MCP 的关系(2026-05-02 修订)

**原版本写过头了**:之前这一段说"原子能力层 = MCP tools"、"knowlet 天然就是 MCP server"、"原子能力的 tool schema 一开始就按 MCP 标准设计"。但**当前 `core/tools/_registry.py` 实际上是 OpenAI function-calling 形态**(扁平 dict 输入 / sync handler / 每 vault 的 ToolContext closure),没有 MCP 的 resources / prompts / JSON-RPC 框架 / 能力协商。继续宣称"天然 MCP"是 ADR 与代码不符。

**修订后的实际定位**:

- 原子能力的 schema **不**直接对应 MCP 协议;它对应的是 LLM tool-calling 的 OpenAI/Anthropic 通用形态
- 跨 AI 工具暴露能力**不是免费副产品**,需要一层 **MCP adapter** —— 它把 knowlet 的 registry 翻译成 MCP server(URI-keyed resources for notes, JSON-RPC framing, prompts capability)
- 这层 adapter 是**未来工作**(M5+ / 视用户需求),不是阶段一架构必须满足的硬约束
- 设计 registry 时**保留**"将来桥到 MCP"的可能性(handler 输入输出尽量 JSON-serializable;avoid bake-in tight coupling to OpenAI shape),但**不为 MCP 现在就让步任何当下设计**

**这一节的意义不变**:knowlet 仍然定位为"跨 AI 工具可用的能力层",这是 [ADR-0003](./0003-wedge-pivot-ai-memory-layer.md) wedge 的延展。但跨工具可用是通过**未来的 adapter** 实现的,不是 schema 在阶段一就要满足 MCP。

> **触发**:2026-05-02 第二轮独立工程审视 critique #2(MCP claim 与代码不符)。把"天然 MCP"从架构承诺**下调**为"未来 adapter 的可达目标"。

## Consequences

### 好处

- **工程量大幅降低**:不再为每个跨特性工作流写 UI / 代码路径
- **能力随 LLM 进步自动增强**:同样的原子能力,模型更强时编排能力更强,knowlet 不需要追赶
- **新能力上线只需新增 tool**:开发节奏变快,且与"插件化"原则一致
- **用户学习成本接近 0**:会说话就能用,不用学 UI 模式或快捷键
- **跨 AI 工具暴露能力**:通过未来的 MCP adapter 可达(不是免费副产品,见上 §"与 MCP 的关系")

### 代价 / 约束

- **可发现性下降**:用户不知道"我可以让 AI 把两条 Note 合并"
  - 缓解:首次启动 AI 主动介绍能力清单 + 提供 `/help` 列出所有 tool 的人话描述
- **性能与成本**:每个动作走 LLM = token 成本 + 延迟
  - 缓解:为最高频几个操作保留显式快捷键(类比 Claude Code 的 `/fast` `/clear`)
  - 这是"快捷键级"补充,**不是**工作流 UI 复刻
- **调试困难**:出错时用户不知道是 prompt / tool / 模型哪层的问题
  - 缓解:UI 提供"展开看 AI 调了哪些 tool、参数、结果"(透明度承诺的延伸)
- **概率失败**:LLM 偶尔编排错误
  - 缓解:四条执行约束(可逆 / 二次门 / 颗粒度 / 结构化返回)
- **依赖模型能力下限**:在弱模型(本地小模型 / 旧 GPT-3.5)上,编排质量可能不达可用阈值
  - 缓解:knowlet 在 LLM 配置 UI 给出推荐能力等级;用户选弱模型时显式提示"编排表现可能下降"

## Amendment(2026-05-04 用户澄清:AI ≠ 唯一入口)

原版本反复强调"代码只实现原子能力层 + LLM 通过 tool-call 编排" —— 这本身没问题,
但**容易被误读为"用户只能通过 AI 调用原子能力"**。这次澄清把以下原则**升级为硬性
约束**(原版本只是隐含):

### 第 5 条执行约束:每个 AI 功能点必须有 UI 替代路径

**任何能由 LLM tool-call 触发的 AI 功能点,必须存在一条 UI 操作组合可以达到等价结果。**

具体含义:

| 正面例子(允许) | 反面例子(禁止) |
|---|---|
| `search_notes` 既能让 LLM 调,也能在左栏 / 命令面板里手动搜 | `search_notes` 只暴露给 LLM,UI 上没有搜索入口 |
| `create_card` 既是 chat 工具,也是 quiz summary 的"做成 Card"按钮 | `create_card` 只在跟 AI 说话时能触发 |
| `web_search` (M7.5) 是 LLM 工具;同时 UI 上提供搜索框入口(**待补**;M7.5 当前只有 LLM 路径,要补 UI)| `web_search` 永远只能由 LLM 自己决定要不要调 |

理由:

1. **AI ≠ 唯一通路**:用户在 AI 不熟练 / token 配额吃紧 / 想要快速精确操作 / 不想跟
   AI 解释意图时,必须能直接抵达结果。
2. **避免"不会用 AI 的用户失去整套能力"**:如果某能力只走 AI 路径,等同于把 AI 推荐
   能力当成准入门槛,跟 ADR-0002 "AI 是可选增强" + ADR-0012 "AI 是可选能力" 矛盾。
3. **可达性**:UI 操作的代价是 N 次点击 + 学一次模式;LLM 调用的代价是写一句话 +
   等响应 + 看 tool trace。两者各自适用场景,不该有 capability gap。

### 落地清单(需要补 UI 入口的现有能力)

审视当前 16 个 tools(M7.5 之后):

| Tool | 现有 UI 入口 | 补丁状态 |
|---|---|---|
| `search_notes` | 左栏搜索框 / palette `Cmd+P` 笔记跳转 | ✅ 已有 |
| `get_note` | 点笔记打开 | ✅ 已有 |
| `list_recent_notes` | 左栏笔记列表(updated_at 排序) | ✅ 已有 |
| `get_user_profile` | 个人资料模态(profile)| ✅ 已有 |
| `create_card` | quiz summary "做成 Card" + drafts 通过流(部分)| ⚠ 补:Cards focus mode 的"+ 新建 Card"按钮 |
| `list_due_cards` | Cards focus mode | ✅ 已有 |
| `get_card` | 同上 | ✅ 已有 |
| `review_card` | Cards focus mode 1/2/3/4 评分 | ✅ 已有 |
| `list_mining_tasks` | CLI `knowlet mining ls`(Web TBD) | ⚠ 补:Web 上 mining 配置面板 |
| `run_mining_task` | CLI `knowlet mining run-all` + palette `mining-run-all` | ✅ 已有 |
| `list_drafts` | drafts focus mode | ✅ 已有 |
| `get_draft` | 同上 | ✅ 已有 |
| `approve_draft` | drafts focus mode A 键 | ✅ 已有 |
| `reject_draft` | drafts focus mode X 键 | ✅ 已有 |
| `web_search` (M7.5)| **缺**:目前只有 LLM 路径 | ❗ 需补:palette 命令 / 左栏搜索框附加 |
| `fetch_url` (M7.5)| **缺**:目前只有 LLM 路径 | ❗ 需补:跟 M7.2 url-capture 流统一 |

带 ⚠ / ❗ 的项进 M8 dogfood 后 polish 列表,不再放任。

### 跟 ADR-0011 §"显式不做" 的协调

ADR-0011 §6 把 graph view 列为"显式不做"(此次连同 ADR-0003 一起 amend);
但 ADR-0011 §3 主三栏布局 + palette + focus mode 的 UI 框架本来就是为了让
**每一类原子能力都有 first-class UI 入口**。本 amendment 把这层意图明文写进 ADR-0004,
作为后续每个新 tool 的接收准入条件:**新 tool 注册时必须同时声明它的 UI 入口在哪**,
否则视为不完整。
