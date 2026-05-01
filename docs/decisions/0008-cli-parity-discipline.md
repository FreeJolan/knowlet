# 0008 — CLI / UI 平价开发纪律

> [English](./0008-cli-parity-discipline.en.md) | **中文**

- Status: Accepted
- Date: 2026-05-01

## Context

[ADR-0007](./0007-mvp-slice.md) 把 MVP 接入形态定为 CLI,并指出"开放外部用户前需补 UI"。M0 完成后用户进一步明确了两件事:

1. **GUI 是产品 viability 的硬约束**(见 project memory `project_knowlet_gui_priority`),不是"可选扩展"。绝大多数知识工作者不会在 CLI 里做沉淀类任务,CLI 只在"先自用"阶段成立。
2. **knowlet 99% 由 agent 写代码**(见全局 CLAUDE.md §Collaboration principles 与 project memory `feedback_no_hidden_debt`)。在这种工作模式下,debug / 维护成本远高于写代码成本,**自动化测试覆盖率最大化**是关键约束 —— 人工 UI 回归测试在长期不可持续。

加上 [ADR-0004](./0004-ai-compose-code-execute.md) 里"代码只暴露原子能力 + LLM 编排"的哲学,以及 [ADR-0007](./0007-mvp-slice.md) 里"后端按 daemon 模式设计,为后续 UI 复用"的指导,自然推导出一条工程纪律:**所有功能性的 UI 操作必须有 CLI 镜像,所有业务逻辑只在后端模块实现一次**。

如果不显式写下这条纪律,新贡献者(包括未来的 agent)很容易写出"UI 直接读 frontmatter / 直接调 sqlite / 自己在前端实现 reindex"这类把后端逻辑泄漏到 UI 层的代码,导致:

- 同样的逻辑在 CLI 与 UI 各实现一次,长期分叉;
- UI 端的 bug 必须靠人工点击复现;
- 测试覆盖率被"分母"稀释 —— 后端测得再好也保不住整个产品的正确性。

## Decision

### 总原则

`knowlet/core/*` 与 `knowlet/chat/*` 是 knowlet 业务逻辑的**唯一事实来源**。`knowlet/cli/*` 与未来的 `knowlet/web/*` 是**薄壳**:接 CLI / HTTP / WebSocket 协议,翻译成对后端模块的调用,然后把结果序列化回去。**任何业务逻辑出现在薄壳里都视为设计缺陷**。

### 五条硬规则

#### 1. 后端先,壳层后

一个新的功能性能力,必须先在 `core/` 或 `chat/` 落函数(且带测试),然后才考虑 CLI / UI 接入。允许的演化顺序:

```
backend function (+ test) → CLI 入口 → UI 入口
```

不允许:

```
UI button → 在 frontend 现写一段逻辑 → (永远没补) backend 函数
```

#### 2. 每个功能性 UI 操作必须有 CLI 入口

CLI 入口形态可以是:显式子命令(`knowlet user edit`)、slash 命令(`:user edit`)、`config set <key> <value>` 之类的通用入口、或 stdin / 文件参数驱动的批处理形态。**形式不限,可触达即可**。

例外只允许"纯视觉 / 纯 UX"操作:面板布局、动画、暗色模式色值、拖放手感、字体调整、快捷键提示。这些不影响产品**正确性**,只影响**舒适度**。

#### 3. 流式响应以"结构化事件流"为底层

任何流式输出(LLM tokens、tool call trace、知识挖掘任务进度、长查询的中间结果)必须以"事件 generator"形式从后端产出。每个事件是一个结构化对象(dataclass / TypedDict),包含 `type` 字段与负载。

- UI 层订阅事件,按 type 分发到不同组件渲染;
- CLI 层把事件序列化成行打印(`json.dumps(event)` 一行一条);
- 测试直接断言事件序列(顺序、type、关键字段)。

后端的"事件 generator"只写一次,UI 与 CLI 通过相同的接口消费。**禁止** UI 端持有自己的流逻辑(比如自己累加 partial token、自己维护 tool call 状态)。

#### 4. 测试主要打 backend 函数

测试金字塔:

```
              ┌──────────────────────┐
              │ UI smoke (人工 / 极少自动)│      只测 UI 独有部分
              ├──────────────────────┤
              │  CLI integration     │       少量,跑通 = 集成层 OK
              ├──────────────────────┤
              │  Backend unit + integ│       大量,核心覆盖
              └──────────────────────┘
```

- **后端单元 + 集成测试**是大头:覆盖搜索、索引、沉淀、retrieval、tool dispatch、用户上下文注入等业务逻辑。
- **CLI 集成 smoke**:覆盖 CLI 与后端的 wiring(参数解析、错误码、stdout 格式)。每个 CLI 入口至少一条 smoke。
- **UI 测试**只测 UI 自身的事:渲染、键鼠 / 触摸事件、状态机、SSE / WebSocket 连接管理。**绝不**重测搜索 / 索引 / 沉淀这些 backend 已覆盖的逻辑。

#### 5. 完成判定的硬条件

一个 feature 在"完成"前必须满足:

- ✅ Backend 函数 + 至少一条覆盖正常路径的测试 + 覆盖典型错误路径的测试;
- ✅ 至少一个 CLI 触达入口(命令 / slash / 通用入口);
- ✅ (UI 时代)对应 UI 入口 + 一次 manual UI smoke 走通。

任意一项缺失即视为未完成。**禁止**用"先合进去,UI/test 后补"的方式临时绕过。

### 关于 daemon 化的隐含意义

[ADR-0007](./0007-mvp-slice.md) 已经把后端定为 daemon-style 设计。在本 ADR 的纪律下,daemon 化的具体形态变得明确:

- 当 web UI(M2)上线,daemon 起一个本地 HTTP / WebSocket server,暴露后端能力。
- CLI 在 daemon 起来之后转为"CLI 与 daemon 通信"模式(类似 `gh` / `stripe` 的本地客户端形态),不再每次重新 import torch / sentence-transformers。
- HTTP API 成为 backend 与所有壳的唯一接口契约。**HTTP API 测试**届时取代"backend 单元测试"作为大头。

但这个演化是 M2 阶段的事,在那之前,CLI 直接 import 后端模块仍然成立。本 ADR 的核心五条规则,在哪种形态下都要求生效。

## Consequences

### 好处

- **自动化测试覆盖率显著提升**。后端测试 + CLI 集成 smoke 几乎覆盖所有功能性回归。UI 上线后,人工 QA 只需要测视觉与交互手感,**不再点击数十个按钮去验证逻辑正确性**。
- **架构防腐**。 UI 永远不能"偷"后端的事,被结构钉死。三个月后另一个 agent 来改某块逻辑,只需要看 `core/` 的对应模块,不需要在 `cli/` `web/` 里到处找。
- **CLI 自然成为高级用户与脚本接口**。每个能力都有 CLI 入口,意味着用户可以用 shell 脚本编排 knowlet,这跟"AI 长期记忆层、跨工具可用"的破局点(ADR-0003)自然契合。
- **daemon 化路径清晰**。M2 落地时只需替换"CLI 直 import"为"CLI HTTP 调用",backend 不动。

### 代价 / 约束

- **每个 feature 多 5-10% 工作量**(CLI 入口 + 测试)。在 agent 写代码成本接近零的前提下,这点开销远低于后续 debug 节省。
- **流式接口设计成本**。一次性把流式 API 设计成结构化事件流比"先随便流出去"贵,但分叉一旦发生就不可逆。
- **拒绝"快速绕过"的诱惑需要持续自律**。新贡献者(尤其外部贡献者)可能会提交"先在 UI 里实现一遍,后续再抽"的 PR,需要在 review 时坚定要求按本 ADR 走。

### 与现有 ADR 的关系

- 从属于 [ADR-0002](./0002-core-principles.md):本 ADR 不引入新原则,只是其"能力插件化"原则的工程支撑。
- 协同 [ADR-0004](./0004-ai-compose-code-execute.md):atomic capability 的 tool schema 与 backend 函数边界完全重合;LLM 通过 tool 编排 = UI 通过函数调用编排 = CLI 通过命令编排,三层共享同一组原子能力。
- 强化 [ADR-0007](./0007-mvp-slice.md):"后端按 daemon 模式设计"的承诺被本 ADR 落到具体规则。
- 不影响 [ADR-0005](./0005-llm-integration-strategy.md) / [ADR-0006](./0006-storage-and-sync.md):那些是关于外部接口与数据,本 ADR 是关于内部分层。
