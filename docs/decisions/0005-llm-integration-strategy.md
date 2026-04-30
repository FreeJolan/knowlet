# 0005 — LLM 接入策略

> [English](./0005-llm-integration-strategy.en.md) | **中文**

- Status: Accepted
- Date: 2026-04-30

## Context

[ADR-0003](./0003-wedge-pivot-ai-memory-layer.md) 确立了"嵌入式 chat + AI 长期记忆层"的产品形态,[ADR-0004](./0004-ai-compose-code-execute.md) 确立了"AI 编排 + 原子执行"的工程边界。两份 ADR 都假定 knowlet 内部有可用的 LLM,但都没有定义 LLM 从哪里来、谁付费、怎么连接。

这个问题需要单独决策,因为它直接影响:

- 用户的配置门槛
- 数据流向(对话内容会经过谁的服务器)
- 工程复杂度(支持多少 provider)
- 与 [ADR-0002](./0002-core-principles.md) "AI 可选 + 数据主权"原则的对齐方式

## Decision

### 阶段一:LLM 完全由用户自带

knowlet 阶段一**不持有任何 LLM API key,不代理任何对话流量**。用户在 knowlet 中配置一个 LLM endpoint(URL + API key + 模型名),knowlet 直接调用。

支持的 provider 通过**统一的 OpenAI 兼容协议**接入:

- 官方 OpenAI / Anthropic / Google
- 兼容协议聚合服务(OpenRouter / Together / DeepInfra 等)
- 本地推理(Ollama / LM Studio / vLLM 等)
- 用户自托管的 LLM 服务

已经订阅 Claude / ChatGPT 等会员的用户,可以通过开源工具(如 `claude-code-router`)把订阅服务封装成 OpenAI 兼容 endpoint,接入 knowlet。knowlet 不为这种封装做官方背书,但兼容这种用法。

### 配置形态:阶段一就提供可视化 UI

LLM 配置是用户上手 knowlet 的第一步,不能依赖配置文件:

- **可视化设置面板**:endpoint URL / API key / 模型名 / 测试连接
- 配置文件作为**额外**的导出 / 备份机制,给希望版本化配置的用户使用

### 网页搜索优先使用 LLM provider 的原生 tool

挖掘任务(ADR-0003 场景 B)与对话中的实时联网,knowlet **优先使用 LLM provider 自身的原生 web search 能力**:

- Claude API 的 `web_search` server-side tool
- OpenAI Responses API 的 `web_search_preview` tool
- 类似 server-side search 能力的其他兼容 provider

含义:

- 用户不需要再配第二个搜索 API key
- 抓取由 LLM provider 后端完成,**用户 IP 不直接暴露给被抓站**
- knowlet 不需要自建搜索基础设施

对**不支持原生 web search 的 provider**(部分本地模型、部分小厂),阶段一**不提供 fallback**,而是在 UI 显式标注"当前 LLM 不支持网页搜索,挖掘任务不可用"。Fallback 路径(knowlet 内置搜索后端 / SearXNG / Brave API 等)推迟到有真实需求时再做。

### LLM 能力等级提示

knowlet 在 LLM 配置 UI 给出**推荐能力等级**:

- 推荐:支持 tool use + 长上下文 + 较强推理(Claude Opus / GPT-4 级别)
- 可用但能力下降:中等推理 + tool use(Claude Haiku / GPT-3.5 级别)
- 不推荐:无 tool use 或 tool use 不稳定的本地小模型

用户选弱模型时,UI 显式提示**"编排表现可能下降"**(对应 [ADR-0004](./0004-ai-compose-code-execute.md) 的"依赖模型能力下限"代价)。

### 架构层面:抽象层 vendor-agnostic + payment-agnostic

抽象层设计要求:

- **不假设"用户必然自带 LLM"** —— 即使阶段一只实现"自带"路径,接口要为后续可能的接入形态留干净的扩展点
- **不假设"LLM 一定免费 / 一定付费"** —— 计费 / 配额 / 限速等关切在抽象层有占位,即使阶段一不实现

这是工程预防,不是阶段一交付物。

## Consequences

### 好处

- **数据流向干净**:用户对话直接到用户选定的 provider,knowlet 不在中间
- **运营负担低(阶段一)**:knowlet 不持有 API key 不付 LLM 费用
- **完全 vendor-agnostic**:用户切换 LLM 不影响 knowlet 数据
- **网页搜索零额外配置**:对绝大多数主流用户(Claude / OpenAI / OpenRouter)开箱即用
- **与 ADR-0002 数据主权完全对齐**:用户对 LLM 选择拥有完全控制权

### 代价 / 约束

- **首次配置非零摩擦**:用户要找 API key 并填入,但目标用户(知识工作者 / 程序员)可接受
- **LLM provider 看得到对话**:用户与 provider 之间是直接连接,knowlet 不能加密代理
  - 缓解(用户侧):选支持 zero-retention 的 API tier(Anthropic / OpenAI 都有),或用本地 Ollama
  - knowlet 在文档中明确告知此事实,不掩盖
- **挖掘任务在不支持 web search 的 provider 上不可用**:阶段一不补 fallback
  - 用户 workaround:换支持 web search 的 provider 用于挖掘任务,日常对话仍可用本地模型
- **OpenAI 兼容协议的统一性有限**:不同 provider 在 tool calling / streaming / 错误处理上存在细节差异
  - 工程上需要 provider-specific 适配层,但保持对外 API 统一

### 后续扩展点(不在本 ADR 承诺时间表)

- knowlet 内置搜索后端作为 fallback
- 加密代理层
- LLM 计费抽象的实际填充

这些扩展点由实际需求驱动,届时由新 ADR 决策。
