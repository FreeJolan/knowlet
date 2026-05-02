# 0017 — LLM Web Search Tool(backend-agnostic)

> [English](./0017-llm-web-search-tool.en.md) | **中文**

- Status: Proposed
- Date: 2026-05-03

## Context

[ADR-0016 §7](./0016-url-capture.md) 占位提过一句:

> 如果未来要做"LLM 主动搜索网页",路径是**写本地 `web_search` tool**(类似已有 vault tools),走 LLM function calling,跟 OpenAI-compat 后端解耦。

dogfood 期间用户原 side-ask:

> 现在通过 OpenAI 格式对接的 LLM,是不具备 web search 能力的吗

**答**:OpenAI Chat Completions 协议本身**没有原生 web search**;Claude 经 OpenAI-compat 代理**通常也没接**(server tools 没有协议映射)。这意味着 knowlet 的所有 chat 流(M0 CLI / M2 web / M7.1 capsule / M7.2 URL discuss / M7.4 quiz)在**询问实时信息**时都会撞墙 —— LLM 只能基于训练截止前的知识答。

本 ADR **加一条 backend-agnostic 路径**:写本地 `web_search` tool,走 LLM function-calling 注册,任何 OpenAI-compat 后端都自动获得搜索能力。跟 [feedback_backend_agnostic](memory) + [ADR-0008](./0008-cli-parity-discipline.md) 的精神一致。

## Decision

### 1. 实现路径 — 本地 function-calling tool

**不依赖** LLM 厂商的 server tool(Claude `web_search_20250305` / OpenAI `gpt-4o-search-preview` / 等等)。原因:

- knowlet 的 LLM 后端是用户配置的 OpenAI-compat endpoint(默认 `claude-opus-4-7` 经 cliproxyapi);server tools 在协议层不可见
- 跟 [feedback_backend_agnostic](memory) 一致:不写 per-backend 集成
- LLM function-calling 是 OpenAI-compat 协议的**必有**部分,任何后端都支持

注册一个本地 `web_search(query)` tool 进现有 `core/tools/_registry.py`,跟 vault tools 同位。

### 2. 后端选择 — Provider Protocol + 渐进式默认

**架构上不绑任何具体搜索后端。** `SearchProvider` Protocol + 多个 implementation,默认 fallback 到零 setup 的 DuckDuckGo,有 key 自动升级到 Brave/Tavily,数据主权敏感的人切 Searx。

**Provider 优先级(auto 模式)**:

```
1. config 里有 brave_api_key       → BraveSearch(质量高,2000/月免费)
2. config 里有 tavily_api_key      → TavilySearch(LLM-原生,带 score)
3. config 里 searx_url 非空        → SearxSearch(用户自托管,数据主权最强)
4. 都没配                          → DDGInstantAnswer(免 key,但质量一般)
```

用户也可以显式指定 `provider = "brave"` 强制使用某个。

**配置 schema**(进 `KnowletConfig.web_search`):

```toml
[web_search]
# 默认 = "" → auto-pick(brave > tavily > searx > ddg)
provider = ""
brave_api_key = ""
tavily_api_key = ""
searx_url = ""             # e.g. "https://searx.example.com"
max_per_turn = 3
```

**显式拒绝**:

- ❌ DuckDuckGo HTML scrape(ToS 灰区 + 不稳定)
- ❌ Google Custom Search(setup 复杂 + 100/day 免费配额)
- ❌ SerpAPI(按调用付费,$0.01-$0.003/query 起)

### 3. LLM 何时调用搜索 — 自动 function-calling

注册 `web_search(query: string, top_k: int = 5)` 进 tool registry → LLM 看到知识空缺时**自动调用**(function-calling 协议保证)。

**不做强制前缀**(`>>search` 等):打断对话流,跟 ADR-0012 "AI 是工具,不是仪式"基调矛盾。

**可控性兜底**:

- 单 turn 最多 3 次调用(§4)
- Web UI 显示 tool call 痕迹(已有的 chat_stream tool_call event 自动包含)
- 用户可在 chat 里加 "不要搜索,只用你已知的回答" → LLM 会遵守

### 4. 单 turn 调用上限 — 3 次

`config.web_search.max_per_turn = 3`(默认值),理由:

- 1 次太死板(LLM 经常需要 "原 query → 改写 → 验证" 三跳)
- 3 次封顶足够 + 防 LLM 失控
- 超过上限 → tool 直接 raise,LLM 看到 error 后自然停手

session 级累计上限放配置但**默认无限**(用户重度用一个会话不应被打断;真出问题加 max_per_session)。

### 5. 结果格式 — 二段式(search → fetch)

**两个 tool 协同**,沿用 M7.2 已有的 trafilatura 抓取:

#### 5.1 `web_search(query, top_k=5)` → 列表结果

返回前 top_k 条 SearchResult,**不含正文全文**:

```json
{
  "results": [
    {"title": "...", "url": "...", "snippet": "...", "rank": 0},
    ...
  ]
}
```

每条 ~200 字符 snippet。LLM 看完决定哪条值得深读。

#### 5.2 `fetch_url(url)` → 抓单页正文

复用 `core/url_capture.fetch_and_extract(url)`(M7.2 已实现),返回 trafilatura 抽出的正文(限 5000 字符)。LLM 拿到全文后基于此回答。

#### 5.3 为什么二段式?

- **token 效率**:5 条全文 = ~25k token,搜不必要的页面浪费
- **LLM 决策权**:title+snippet 已经能让模型判断哪条是最相关的,只 fetch 1-2 条值得读的
- **复用已有代码**:`core/url_capture.py` 的 fetch_and_extract 已经经过 dogfood 验证,不重复造轮子
- **错误隔离**:某条 URL 抓不动(JS-heavy / paywall)时只该条失败,其他 search 结果还在

### 6. 安全 / 隐私 / 成本

#### 6.1 数据流

| Provider | 用户 query 流向 |
|---|---|
| Brave  | brave.com → 接收 query 用于返回结果 |
| Tavily | tavily.com → 接收 query |
| Searx  | 用户自己的 Searx 实例 → 用户对数据流自有控制 |
| DDG IA | duckduckgo.com → 接收 query |

**所有 provider 都把 query 发出去**(显然)。但**不发笔记内容**(LLM 只把 query 字符串交给 tool,不会把上下文也发)。

#### 6.2 API key 存储

继承 [ADR-0006](./0006-storage-and-sync.md):key 存在 `KnowletConfig`(用户 home 或 vault 同位 config 文件)→ **不进 vault** → **不会被同步出去**(跟 LLM api_key 同处理)。

#### 6.3 成本控制

- Brave 免费 2000/月,每 turn 上限 3 → 每天 ~22 个 chat turn 全用上才到顶。重度用户可考虑付费档($3/1000 queries)。
- Tavily 免费 1000/月。
- Searx 自托管 = $0(但 host 成本另算)。
- DDG IA = $0 + 不稳定。

UI 可以加个"本月已用 X/Y"读数,但不在 M7.5 范围内(monitoring 是后续 polish)。

### 7. CLI parity

[ADR-0008](./0008-cli-parity-discipline.md) 硬要求 feature 跨 interface 不缺失。Tool registry 是 backend 能力,**自动**对所有 chat 入口可用:

- ✅ Web 右栏 AI dock + chat focus mode
- ✅ M7.1 capsule chat / M7.2 URL discuss(都走 chat session)
- ✅ M7.4 quiz 不接(quiz 是单独的 generation/grading prompt,跟 chat session 解耦;quiz 内不需要搜索)
- ✅ CLI `knowlet chat` REPL 自动获得能力(0 额外工作)
- ❌ Cmd+K palette `>` ask-once **不接** —— ask-once 是 ephemeral one-shot,加搜索语义会拖慢 + 跟"快速问一下"的设计意图相悖

### 8. UI 显示

Tool call 已经走现有的 `tool_call` SSE event,前端 chat history 会自然显示一行 trace:

```
· web_search(query="...")
· fetch_url(url="...")
```

**不加专属"正在搜索"动画** —— tool call trace 已经够 informative,加额外 UI 反而冗余。

### 9. Phase plan

```
M7.5.0  ADR-0017 起草 + 用户拍板                (本 commit)
M7.5.1  Backend  KnowletConfig.web_search 加配置 + core/web_search.py(Provider Protocol + 4 implementation)
M7.5.2  Tool registration + max_per_turn 防失控 + tests
M7.5.3  CLI smoke + dogfood 文档(README + config docs)
                                                tag → m7.5
```

## Consequences

### Positive

- knowlet 终于能回答实时问题("今年最新的 LLM 评估方法?", "transformers 库最新版本?")
- backend-agnostic — 任何 OpenAI-compat LLM 都自动获得能力
- 渐进式默认:零 setup 也能用(DDG fallback),想要质量去注册 Brave key
- 二段式 search → fetch 复用 M7.2 url_capture 模块,无平行实现
- 自动 function-calling 不打断用户的对话流;tool trace 让用户看清楚 AI 在做什么

### Negative

- 用户 query **会发到第三方搜索引擎**(Brave/Tavily/DDG)。Searx 自托管是数据主权的回避路径,但有 host 启动成本
- 默认 DDG fallback 质量一般 → 用户可能**第一次试觉得不行**就以为整个 web_search feature 是废的;docs 必须把 "升级到 Brave key 拿好质量" 写清楚
- 单 turn 3 次调用 + token 耗费会增加 chat session 成本(LLM context 多塞 ~5k token)
- LLM **可能在不必要时调用**搜索(过度依赖 tool 是 function-calling 的常见失败模式)。Mitigation 在 §3:用户可在 system prompt 加 "只用你已知的回答" 来抑制

### Mitigations

- README + docs/web-search.md 写清楚 4 个 provider 的对比 + Brave key 注册步骤
- max_per_turn=3 + tool 在超出时 raise → LLM 看到 error 自然停手
- 在 chat system prompt 里加一行 "Only use web_search when you genuinely need real-time or post-training information"(M7.5.2 实施)

### Out of scope

- per-session 累计上限 + UI 用量 monitor → 后续 polish,等 dogfood 数据
- 自动备 search 结果到 vault → 不做(等同 M7.2 URL capture 的语义,如果用户想留就走 capture 流)
- 多语言 search 切换 → 让 LLM 自己决定 query 语言(Claude 已经会根据上下文自动切)
- LLM 主动 fetch 大文件(PDF / video) → trafilatura 不处理,fetch_url 拒绝非 HTML

## References

- [ADR-0006](./0006-storage-and-sync.md) — Storage / sync(API key 不进 vault)
- [ADR-0008](./0008-cli-parity-discipline.md) — CLI parity discipline(§7 自动 satisfy)
- [ADR-0012](./0012-notes-first-ai-optional.md) — Notes-first / AI is optional(搜索是工具,不主动)
- [ADR-0016 §7](./0016-url-capture.md) — Web search 占位(本 ADR 兑现)
- [feedback_backend_agnostic](memory) — knowlet 不绑特定 LLM 后端;搜索后端同样 Provider 化
