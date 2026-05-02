# 0016 — URL → Note Capture Flow + Layer A Ingest-side Ambient

> **English** | [中文](./0016-url-capture.md)

- Status: Proposed
- Date: 2026-05-02

## Context

[M7.1 / ADR-0015](./0015-quote-references.en.md) bridged **"existing note → AI conversation"** with fine-grained capsules. The dual is still missing:

> **External content (URL / article) → I want to take notes after reading**

dogfood feedback (2026-05-01):

> Sometimes I jump from a draft to the page link to read; afterwards I might want to record what I learned, but there's no clean entry point. I might even want to brainstorm with the AI then turn that into a note.

knowlet today:

- User reads URL → wants to record → **must hand-paste content into the chat input box** (brute, loses traceability)
- Or leave knowlet entirely → **leaves the "AI present" collaboration context**

[ADR-0013](./0013-knowledge-management-contract.en.md) §3 also calls **Layer A — ingest-side ambient information** an M7 candidate: every time the user is about to create a new Note, show top-3 similar Notes, with **no preset action, no "suggest merge" prompts** — pure information, the user judges.

This ADR **lands two things at once** (their implementation paths overlap heavily; splitting the ADRs would fragment them):

1. **URL capture flow**: paste URL → summarize → capsule → AI discussion → sediment to Note
2. **Layer A ambient**: top-3 similar Notes shown when the sediment modal opens (pure information, no preset action)

## Decision

### 1. Primary URL entry — paste detection + Cmd+K dual rail

**Primary: chat-input paste detection**

- User pastes text into the chat input (right-rail dock or chat focus)
- Frontend checks if the pasted content matches a "single URL" (`^https?://\S+$` after trim)
- If so → intercept default paste, float a small hint below the input: `[Fetch & discuss this page]`
- Click → enter the capture flow
- User keeps typing (ignores the hint) → it auto-dismisses

**Secondary: Cmd+K palette**

- New command `url-capture` — paste / type URL in palette → "fetch & discuss"
- Keyboard fallback; covers cases where paste detection wouldn't fire (already typing other text)

**Explicitly not done**:

- ❌ Header "+ from URL" button — entry redundancy with paste detection
- ❌ "Discuss then save" button in drafts modal — drafts already have source URL; punted to a follow-up
- ❌ Browser extension / share-target — large engineering, defer to M9+ Tauri phase

### 2. How captured content enters the chat — reuse the M7.1 capsule mechanism

**Add a new capsule source: `source = "url"`** (M7.1's default is `source = "note"`)

- Data model: `QuoteRef` gains `source: str = "note"` + `source_url: str = ""`
- Wire payload (`QuoteRefPayload`) mirrors the same two fields
- Render branching:
  - `source = "note"` → `《Note title》quote_text…` (M7.1 status quo)
  - `source = "url"` → `[web] {title} · {hostname}`, click opens URL
- LLM context branching:
  - `source = "note"`: `extract_enclosing_section` finds the enclosing heading (M7.1 status quo)
  - `source = "url"`: **use quote_text (the summary) directly, no vault lookup**

Maximizes reuse of M7.1's send pipeline + capsule strip + Cmd+Shift+A shortcut (URL capsules can also use the shortcut, but their creation path is paste / palette, not selection).

### 3. Content granularity — independent LLM summary + URL link

**Capture pipeline**:

```
1. User pastes URL → trafilatura.extract pulls main content (mining/sources.py reuse)
2. Independent LLM call produces a ~300-char neutral summary
3. Capsule renders as [web] {title} · {hostname} + summary + clickable URL
4. Sent to chat, the LLM sees:
   "I want to ask about this article (from 《{title}》· {url}):
    > {summary}
    ———————————————
    {user's question}"
```

**Key choices**:

- **Full text never enters chat context** — only the summary does. Token budget tightens from M7.1's 1500 chars to ~500 chars per capsule.
- Summary prompt is **fixed, neutral**:
  ```
  Produce a ~300-character neutral summary of the following webpage body,
  extracting the thesis + key arguments + conclusion. No personal commentary,
  no expansion beyond the source.
  ```
- Summary call **reuses the configured LLMClient** (any OpenAI-compat backend); does NOT go through the chat session (avoids polluting the conversation history)
- Sync, not streaming; ~3-6s wait gets a streaming hint

**Failure fallback**:

- trafilatura can't extract (JS-heavy / paywall) → fetch failure toast, no capsule path
- LLM summary call fails → capsule reads "(summary failed; original {N} chars)" placeholder; user can still attach + ask. The chat-side LLM gets empty `quote_text` and uses url + title as the reference.

### 4. Ingest-side Layer A ambient — top-3 similar shown in sediment modal

**Trigger (M7.2 scope)**: **only when sediment modal opens**.

**Explicitly not in M7.2**:

- Manual "+ new blank note" doesn't trigger (blank has no content to search)
- Drafts approve flow doesn't trigger (M7.x follow-up; drafts come from mining, different context from active user action)

**Implementation**:

- New endpoint `GET /api/notes/similar?q=<text>&top_k=3`
- Reuses `core/index.py`'s `search(query, top_k)` — existing RRF hybrid (FTS + vec)
- Sediment modal queries with the draft body when opening; fetches top-3
- UI: a collapsible "Possibly related" panel **above** or **right of** the title field
  - Default collapsed; collapsed shows count ("3 related")
  - Expanded: each row = title + ≤80-char preview + click → opens the Note in a new tab
  - **No verbs, no buttons** ("merge into this" / "merge into existing Note" forbidden)
- Strict adherence to [ADR-0013 §1](./0013-knowledge-management-contract.en.md): AI gives information, the human decides; **default action is always "create new"**

**Score threshold**: none. Just take top_k=3. Even low-relevance triplets are reasonable "peripheral vision."

### 5. Save = direct to Note (sediment status quo)

The URL flow's last step = **identical path to existing sediment**:

- User finishes discussing → clicks sediment in right-rail dock or chat focus
- Sediment modal opens → §4 ambient fires
- User edits title / tags / body → commit → `notes/<ulid>.md`

**Explicitly not done**:

- ❌ URL capture has its own "auto draft" path — drafts queue is mining's; user-initiated action goes straight to sediment
- ❌ Sediment modal grows a "save as Note / save as draft" toggle — adds decision overhead; M6.5 settled on "sediment goes straight to Note"

### 6. CLI parity not enforced

CLI `knowlet chat` has no notion of "paste detection." CLI users can use `:capture <url>` REPL syntax later (not in M7.2) or keep manual-paste-the-full-text.

[ADR-0008](./0008-cli-parity-discipline.en.md) governs "feature must reach every interface," not "every interface must have the same input model" — same logic as ADR-0015 §7.2 (GUI has paste interception; terminal doesn't).

### 7. Web search not in this ADR

During dogfood the user asked: does an OpenAI-compat backend have native web search?

**Answer**: OpenAI Chat Completions protocol itself does **not**; Claude via OpenAI-compat proxy usually **doesn't pipe through** either (server tools have no protocol mapping).

**For knowlet**:

- M7.2's URL capture is **user-supplied URL**, not LLM-initiated search
- Future "LLM searches the web" path = **write a local `web_search` tool** (like existing vault tools), via LLM function calling — backend-agnostic per [feedback_backend_agnostic](memory)
- That's a separate feature → its own ADR-0017, not in M7.2

### 8. Phase plan

```
M7.2.0  ADR-0016 + user approval                       (this commit)
M7.2.1  Backend  /api/url/capture + QuoteRef.source=url + Layer A search endpoint
M7.2.2  Frontend paste detection + URL capsule rendering branch
M7.2.3  Frontend sediment modal ambient panel
M7.2.4  Cmd+K palette `url-capture` command
M7.2.5  i18n + docs
                                                       tag → m7.2
```

Each phase: separate commit + push. m7.2 tag once §8 is fully ✅.

## Consequences

### Positive

- The dogfood gap between knowlet and external content finally closes
- URL summarization runs as a separate LLM call → **doesn't pollute the chat session history**; chat sees a clean quote+context
- Layer A ambient lands in one place (sediment) and reaches every user-initiated Note creation path
- Capsule rendering branches (note vs url) reuse the same M7.1 pipeline — no parallel implementation
- Strictly adheres to ADR-0013 §1: Layer A is pure information, no preset action

### Negative

- Two-hop latency (fetch → summarize → capsule appears) ~3-6s; user feels "waiting"
- Summary LLM call burns tokens / API quota; the cost of frequent URL pasting is visible
- trafilatura can't pull JS-heavy / paywall pages; those URLs fall back to "fetch failed; try manual paste"
- Layer A in sediment alone doesn't cover "+ new blank note" path (blank has no content to search) — design trim, not a defect

### Mitigations

- Two-hop latency: streaming hint ("Fetching... summarizing...") so users don't stare at nothing
- Summary token cost: prompt limits output to ~300 chars + truncates input at 5000 chars → ~2k tokens per call
- trafilatura failure: clear error toast + manual-paste fallback; the flow doesn't dead-lock
- Blank-note Layer A miss: future follow-up — when content reaches a threshold, fire ambient (not in M7.2)

### Out of scope

- LLM-initiated web search (→ separate ADR-0017)
- Drafts approve ambient (→ M7.x follow-up)
- Browser extension / share-target (→ M9+ Tauri)
- Image / video / PDF content from URLs (text only)
- Multi-URL paste in one shot (single URL only; multi → "one at a time" hint)

## References

- [ADR-0008](./0008-cli-parity-discipline.en.md) — CLI parity discipline (§6 explains why this isn't a violation)
- [ADR-0011](./0011-web-ui-redesign.en.md) — Web UI redesign (sediment modal structure + right-rail AI dock)
- [ADR-0012](./0012-notes-first-ai-optional.en.md) — Notes-first / AI is optional (URL capture is user-initiated; AI is the tool)
- [ADR-0013](./0013-knowledge-management-contract.en.md) §1 + §3 — AI doesn't auto-modify IA + Layer A ingest-side ambient (this ADR §4 is the implementation)
- [ADR-0015](./0015-quote-references.en.md) — Selection → chat capsule (this ADR reuses the capsule mechanism)
