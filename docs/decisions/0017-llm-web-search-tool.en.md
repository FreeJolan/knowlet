# 0017 — LLM Web Search Tool (backend-agnostic)

> **English** | [中文](./0017-llm-web-search-tool.md)

- Status: Proposed
- Date: 2026-05-03

## Context

[ADR-0016 §7](./0016-url-capture.en.md) left a placeholder note:

> If we later want "the LLM searches the web on its own," the path is **a local `web_search` tool** (like the existing vault tools), called via LLM function calling, decoupled from the OpenAI-compat backend.

A dogfood side-question:

> Does an OpenAI-compat LLM not have web search?

**Answer**: OpenAI Chat Completions itself has **no native web search**; Claude via OpenAI-compat proxy **typically isn't piped through** either (server tools have no protocol mapping). That means knowlet's chat flows (M0 CLI / M2 web / M7.1 capsules / M7.2 URL discuss / M7.4 quiz) all hit a wall when asked about real-time information — the LLM only knows what was true at training cutoff.

This ADR adds the backend-agnostic path: a local `web_search` tool, registered via LLM function-calling. Any OpenAI-compat backend gets search ability for free. Aligned with [feedback_backend_agnostic](memory) and [ADR-0008](./0008-cli-parity-discipline.en.md).

## Decision

### 1. Implementation — local function-calling tool

**Don't depend on** vendor-specific server tools (Claude `web_search_20250305`, OpenAI `gpt-4o-search-preview`, etc.). Reasons:

- knowlet's LLM backend is a user-configured OpenAI-compat endpoint (default `claude-opus-4-7` via cliproxyapi). Server tools aren't visible at the protocol layer.
- Aligned with [feedback_backend_agnostic](memory) — no per-backend integrations.
- LLM function-calling is **mandatory** in the OpenAI-compat protocol; every backend supports it.

Register a local `web_search(query)` tool in the existing `core/tools/_registry.py`, peer to vault tools.

### 2. Backend choice — Provider Protocol + progressive defaults

**Architecturally not bound to any specific backend.** `SearchProvider` Protocol + multiple implementations. Auto-fallback to the zero-setup DuckDuckGo; if a key is configured, automatically upgrades to Brave/Tavily; data-sovereignty-sensitive users can switch to Searx.

**Provider priority (auto)**:

```
1. brave_api_key set        → BraveSearch (high quality, 2k/mo free)
2. tavily_api_key set       → TavilySearch (LLM-native, scored)
3. searx_url set            → SearxSearch (self-hosted; data sovereignty)
4. otherwise                → DDGInstantAnswer (no key, sparse coverage)
```

The user can also explicitly pin `provider = "brave"`.

**Config schema** (added to `KnowletConfig.web_search`):

```toml
[web_search]
# Default = "" → auto-pick (brave > tavily > searx > ddg)
provider = ""
brave_api_key = ""
tavily_api_key = ""
searx_url = ""             # e.g. "https://searx.example.com"
max_per_turn = 3
```

**Explicit rejects**:

- ❌ DuckDuckGo HTML scrape (ToS gray area, fragile)
- ❌ Google Custom Search (complex setup, 100/day free limit)
- ❌ SerpAPI (per-call billing, $0.003+ per query)

### 3. When the LLM searches — automatic function-calling

Register `web_search(query: string, top_k: int = 5)` in the tool registry → the LLM **calls it on its own** when it detects a knowledge gap (function-calling protocol guarantees this).

**No mandatory prefix** (`>>search` etc.): breaks conversation flow, contradicts ADR-0012's "AI is a tool, not a ritual."

**Controllability backstops**:

- Max 3 calls per turn (§4)
- Web UI shows tool-call traces (the existing chat_stream tool_call event includes them)
- The user can write "answer with what you know, don't search" in chat → the LLM follows it

### 4. Per-turn call cap — 3

`config.web_search.max_per_turn = 3` (default). Reasons:

- 1 is too rigid (LLMs often need "original query → rewrite → verify" three hops)
- 3 is enough + caps runaway behavior
- Over the cap → tool raises, the LLM sees the error and naturally stops

Per-session running cap is configurable but **defaults to unlimited** (heavy users on a single session shouldn't be interrupted; we'll add max_per_session if it actually bites).

### 5. Result format — two-stage (search → fetch)

**Two cooperating tools**, reusing M7.2's trafilatura fetch:

#### 5.1 `web_search(query, top_k=5)` → list

Returns top_k SearchResults, **without full bodies**:

```json
{
  "results": [
    {"title": "...", "url": "...", "snippet": "...", "rank": 0},
    ...
  ]
}
```

~200-char snippet each. The LLM scans these and decides which to deep-read.

#### 5.2 `fetch_url(url)` → article body

Reuses `core/url_capture.fetch_and_extract(url)` (M7.2), returns the trafilatura-extracted body (capped at 5000 chars). The LLM gets the full text and answers from it.

#### 5.3 Why two stages?

- **Token efficiency**: 5 full bodies = ~25k tokens; fetching pages we don't need is waste
- **LLM judgment**: title+snippet is enough for the model to pick the most relevant 1-2 — fetch only those
- **Code reuse**: `core/url_capture.py`'s fetch_and_extract is already dogfood-validated; no parallel implementation
- **Error isolation**: if one URL fails (JS-heavy / paywall) only that one fails; the rest of the search results are still there

### 6. Safety / privacy / cost

#### 6.1 Data flow

| Provider | Where the user query goes |
|---|---|
| Brave  | brave.com → receives query for results |
| Tavily | tavily.com → receives query |
| Searx  | user's own Searx instance → user controls the data flow |
| DDG IA | duckduckgo.com → receives query |

**All providers send the query out** (obvious). But **don't send note content** — the LLM only passes the query string to the tool, not the surrounding context.

#### 6.2 API key storage

Inherits [ADR-0006](./0006-storage-and-sync.en.md): keys live in `KnowletConfig` (user-home or vault-adjacent config) → **don't enter the vault** → **won't be synced** (same handling as the LLM api_key).

#### 6.3 Cost

- Brave: 2k/mo free; max 3 calls/turn → ~22 turns/day before hitting the ceiling. Heavy users can pay ($3 / 1k queries).
- Tavily: 1k/mo free.
- Searx: $0 for the API (host costs are separate).
- DDG IA: $0 + sparse.

A "this month: X/Y" UI counter would be nice, but not in M7.5 scope (monitoring is later polish).

### 7. CLI parity

[ADR-0008](./0008-cli-parity-discipline.en.md) requires features to reach every interface. Tool registry is a backend capability, **automatically** available across all chat entries:

- ✅ Web right-rail AI dock + chat focus mode
- ✅ M7.1 capsule chat / M7.2 URL discuss (both go through chat session)
- ❌ M7.4 quiz **not wired** (quiz uses a separate generation/grading prompt; quizzes don't need web search)
- ✅ CLI `knowlet chat` REPL — auto-gets capability (zero extra work)
- ❌ Cmd+K palette `>` ask-once **not wired** — ask-once is ephemeral one-shot; adding search would slow it and conflict with "quick question" intent

### 8. UI display

Tool calls already flow through the existing `tool_call` SSE event; the frontend chat history naturally shows a trace line:

```
· web_search(query="...")
· fetch_url(url="...")
```

**No dedicated "searching..." animation** — the tool-call trace is informative enough; extra UI is redundant.

### 9. Phase plan

```
M7.5.0  ADR-0017 drafted + user approval                (this commit)
M7.5.1  Backend  KnowletConfig.web_search + core/web_search.py (Provider Protocol + 4 implementations)
M7.5.2  Tool registration + max_per_turn enforcement + tests
M7.5.3  CLI smoke + dogfood docs (README + config docs)
                                                        tag → m7.5
```

## Consequences

### Positive

- knowlet can finally answer real-time questions ("latest LLM eval methods?" / "current transformers library version?")
- Backend-agnostic — every OpenAI-compat LLM gets the capability
- Progressive defaults: zero-setup works (DDG fallback), better quality is one Brave key away
- Two-stage search → fetch reuses M7.2 url_capture, no parallel implementation
- Auto function-calling doesn't break conversation flow; tool traces let users see what the AI is doing

### Negative

- User queries **leave the machine** to a third-party search engine (Brave/Tavily/DDG). Searx self-host is the data-sovereignty escape valve, but has setup cost.
- Default DDG fallback is sparse → users may **try once, see nothing, conclude the feature is broken**. Docs must explain "upgrade to Brave key for real quality."
- Per-turn 3-call cap + token cost adds to chat session bill (LLM context grows by ~5k extra tokens)
- LLM **may search when not necessary** (over-reliance on tools is a common function-calling failure mode). Mitigation in §3: user can prepend "only answer from what you know" in system prompt.

### Mitigations

- README + docs/web-search.md explains the 4 provider trade-offs + Brave key signup steps
- max_per_turn=3 + tool raises beyond → LLM naturally stops
- Add a system-prompt line "Only use web_search when you genuinely need real-time or post-training information" (M7.5.2)

### Out of scope

- Per-session running cap + UI usage monitor → later polish, after dogfood data
- Auto-saving search results into the vault → not done (overlaps with M7.2 URL capture; users who want to keep something can use that flow)
- Multilingual query switching → let the LLM decide (Claude already does context-aware language)
- LLM auto-fetching binaries (PDF / video) → trafilatura doesn't handle them; fetch_url rejects non-HTML

## References

- [ADR-0006](./0006-storage-and-sync.en.md) — Storage / sync (API key doesn't enter vault)
- [ADR-0008](./0008-cli-parity-discipline.en.md) — CLI parity discipline (§7 satisfied automatically)
- [ADR-0012](./0012-notes-first-ai-optional.en.md) — Notes-first / AI is optional (search is a tool, not unprompted)
- [ADR-0016 §7](./0016-url-capture.en.md) — Web search placeholder (this ADR delivers on it)
- [feedback_backend_agnostic](memory) — knowlet doesn't bind to a specific LLM backend; search backend is the same Protocol pattern
