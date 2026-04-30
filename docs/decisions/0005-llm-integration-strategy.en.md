# 0005 — LLM Integration Strategy

> **English** | [中文](./0005-llm-integration-strategy.md)

- Status: Accepted
- Date: 2026-04-30

## Context

[ADR-0003](./0003-wedge-pivot-ai-memory-layer.en.md) establishes "embedded chat + AI long-term memory layer" as the product form, and [ADR-0004](./0004-ai-compose-code-execute.en.md) establishes "AI compose, code execute" as the engineering boundary. Both ADRs assume an LLM is available inside knowlet, but neither defines where the LLM comes from, who pays, or how to connect.

This needs its own decision because it directly affects:

- User configuration friction
- Data flow (whose servers see conversation content)
- Engineering complexity (how many providers to support)
- Alignment with [ADR-0002](./0002-core-principles.en.md)'s "AI optional + data sovereignty" principles

## Decision

### Stage 1: LLM Entirely Brought by the User

Knowlet in stage 1 **holds no LLM API keys and proxies no conversation traffic**. The user configures an LLM endpoint (URL + API key + model name) in knowlet, and knowlet calls it directly.

Supported providers connect via a **unified OpenAI-compatible protocol**:

- Official OpenAI / Anthropic / Google
- Aggregator services compatible with the protocol (OpenRouter / Together / DeepInfra, etc.)
- Local inference (Ollama / LM Studio / vLLM, etc.)
- User-self-hosted LLM services

Users who already subscribe to Claude / ChatGPT can use open-source tools (e.g., `claude-code-router`) to wrap their subscription as an OpenAI-compatible endpoint and connect it to knowlet. Knowlet does not officially endorse such wrapping but is compatible with it.

### Configuration Form: Visualized UI in Stage 1

LLM configuration is the user's first step with knowlet; it cannot depend on a config file:

- **Visualized settings panel**: endpoint URL / API key / model name / test connection
- Config files serve as an **additional** export / backup mechanism for users who want to version their configuration

### Web Search Prefers the LLM Provider's Native Tool

For mining tasks (ADR-0003 Scenario B) and real-time web access during conversation, knowlet **prefers the LLM provider's own native web search capability**:

- Claude API's `web_search` server-side tool
- OpenAI Responses API's `web_search_preview` tool
- Other compatible providers with similar server-side search capability

Implications:

- User does not need to configure a second search API key
- Fetching is done by the LLM provider's backend; **the user's IP is not exposed to the fetched site**
- No need for knowlet to build search infrastructure

For **providers without native web search** (some local models, some smaller vendors), stage 1 **does not provide a fallback**, but explicitly indicates in the UI: "Current LLM does not support web search; mining tasks unavailable." Fallback paths (knowlet's own search backend / SearXNG / Brave API, etc.) are deferred until a real need arises.

### LLM Capability Tier Hint

Knowlet shows a **recommended capability tier** in LLM config UI:

- Recommended: supports tool use + long context + strong reasoning (Claude Opus / GPT-4 class)
- Usable but reduced quality: medium reasoning + tool use (Claude Haiku / GPT-3.5 class)
- Not recommended: no tool use or unstable tool use (small local models)

When users pick a weak model, the UI explicitly warns **"orchestration quality may degrade"** (corresponding to [ADR-0004](./0004-ai-compose-code-execute.en.md)'s "depends on model capability floor" cost).

### Architectural: Vendor-Agnostic + Payment-Agnostic Abstraction

Abstraction layer requirements:

- **Do not assume "users will always bring their own LLM"** — even though stage 1 only implements the bring-your-own path, the interface must leave clean extension points for possible future integration forms
- **Do not assume "LLM is always free / always paid"** — billing / quota / rate limits must have placeholders in the abstraction layer, even if not implemented in stage 1

This is engineering preparation, not a stage 1 deliverable.

## Consequences

### Benefits

- **Clean data flow**: user conversations go directly to the user-chosen provider; knowlet is not in the middle
- **Low operational burden (stage 1)**: knowlet holds no API keys and pays no LLM fees
- **Fully vendor-agnostic**: switching LLMs does not affect knowlet data
- **Web search zero extra config**: works out of the box for the vast majority of mainstream users (Claude / OpenAI / OpenRouter)
- **Fully aligned with ADR-0002 data sovereignty**: user has full control over LLM choice

### Costs / Constraints

- **First-time configuration has nonzero friction**: user has to find an API key and enter it; acceptable for target users (knowledge workers / programmers)
- **LLM provider sees the conversation**: user-provider connection is direct; knowlet cannot encrypt-proxy
  - User-side mitigation: choose a zero-retention API tier (Anthropic / OpenAI both offer); or use local Ollama
  - Knowlet documentation explicitly states this fact, no concealment
- **Mining tasks unavailable on providers without web search**: stage 1 has no fallback
  - Workaround: switch to a provider with web search for mining tasks; daily chat can still use local models
- **OpenAI-compatible protocol's uniformity is limited**: providers differ in tool calling / streaming / error handling details
  - Engineering needs provider-specific adapter layers but maintains a unified external API

### Future Extensions (No Schedule Committed in This ADR)

- Knowlet's own search backend as fallback
- Encryption proxy layer
- Actual filling of the LLM billing abstraction

These extensions are driven by real demand and will be decided by future ADRs.
