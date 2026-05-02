# 0012 — Notes-first / AI as optional capability

> **English** | [中文](./0012-notes-first-ai-optional.md)

- Status: Accepted
- Date: 2026-05-02

## Context

A 2026-05-02 second-opinion engineering review (`Agent` tool, fresh-eyes) flagged a real internal contradiction:

- ADR-0003 names the product an "AI long-term memory layer (wedge)."
- ADR-0011, six days later, mandates a "notes-first" IA redesign.
- But **the dependency stack is an agent-platform stack** (openai / sqlite-vec / sentence-transformers / FSRS / SSE / APScheduler / trafilatura / feedparser); **the two things every notes app has** (a real editor / wikilink + backlink) are deferred; **the things only AI tools have** (mining / chat / sediment / cards) are all shipped.

Every UX decision oscillates between the two poles. The next ADR was likely going to be "0013 — re-pivot." We have to answer **what knowlet is** before continuing.

## Decision

**knowlet is, in product positioning, a notes app / personal knowledge base. AI is an optional augmentation, not the core.**

Concretely, the following is a **verifiable** hard constraint:

> **A user with no AI capability configured can still use knowlet.**

This is not marketing language; it's an engineering contract. Here is what it means for each subsystem:

| Subsystem | AI configured = 0 | AI configured = 1 |
|---|---|---|
| **Note CRUD** (create / edit / delete / rename) | ✅ Full | ✅ Full |
| **File tree nav / Cmd+P jump** | ✅ Full | ✅ Full |
| **Search** (FTS5 trigram path) | ✅ Full | ✅ + vector path + RRF |
| **Cards / FSRS review** (algorithm layer) | ✅ Full; user hand-writes cards | ✅ + AI-assisted card generation |
| **Cmd+K palette** | ✅ Jump / commands | ✅ + `>` ask AI / additional commands |
| **Mining feeds** | ⚠️ **Degraded**: fetch RSS / URL → store raw items; **no AI summarization**; inbox shows raw content; user decides what to do | ✅ Full + AI extraction + auto-title + tagging |
| **Sediment (chat → note)** | ❌ Hidden entry (no chat to sediment) | ✅ Full |
| **Chat dock / Chat focus** | ❌ Hidden entry, UI not rendered | ✅ Full |

Note: "❌ Hidden entry" **does not mean a "configure AI to enable" CTA.** Configuring AI is the user opting into a capability, not the product begging for tokens — entries silently disappear.

## Operational rule (hard constraint, every new feature must satisfy)

> **Before any new feature ships, answer: "What is this feature when AI isn't configured?"**
>
> Three legal answers:
> 1. **Works fully** (note CRUD / search / cards / Cmd+K jump) — independent of AI
> 2. **Works in degraded mode** (mining fetches but doesn't extract) — a weaker but usable form
> 3. **Hidden** (chat / sediment / ask AI) — UI entry simply not rendered, no greyed-out disabled buttons

**There is no fourth answer.** "User has to go into Settings and configure AI to use this" is not an answer — that demotes "notes app" to "AI tool that incidentally lets you write notes."

## Why this is a continuation of ADR-0003, not a reversal

ADR-0003's actual promise is "**AI long-term memory layer**" as the **wedge differentiator** (what knowlet has that Bear / Obsidian / Notion don't), not the product's **identity**. The identity has always been "personal knowledge base / notes app"; AI is a differentiation layer on top of that identity.

Earlier confusion came from ADR-0003 §"Product form" describing the wedge in heavy enough strokes that it read as identity. This ADR makes the two-layer structure explicit:

```
┌─────────────────────────────────────────────┐
│  knowlet identity = personal KB / notes app │  ← still true with no AI
├─────────────────────────────────────────────┤
│  knowlet wedge = AI long-term memory layer  │  ← unlocked when AI configured
└─────────────────────────────────────────────┘
```

## Consequences

### Backlog items this immediately triggers

- **`knowlet doctor` must distinguish**: missing LLM config / missing embedding config / both missing — and **only the first two are warnings** (both missing is a legal state, not an error).
- **First-launch empty vault must not force an AI setup wizard** (ADR-0011 §8 already gets this right; confirmed.)
- **Mining must degrade when LLM is missing**: `run_task` should detect LLM unavailable → skip the extraction phase and turn raw items directly into drafts.
- **UI entries dynamically hidden**: `/api/health` returns `ai_available: bool` (based on LLM config + startup healthcheck); the frontend renders Chat / Sediment / `>` ask AI entries based on this flag.
- **Card creation paths**: in addition to "AI generates cards from chat," preserve the "user manually creates a new card" flow (CLI has it; UI doesn't yet).

### Relation to existing ADRs

- **ADR-0003** should append a note pointing to this ADR, locating "AI long-term memory layer" as the wedge differentiator rather than the identity.
- **ADR-0011** delivers on this (§"Product positioning becomes literal"), but its scope was the chat-first → notes-first UI flip; the structural "AI optional" principle wasn't extracted until now. This ADR fills that gap.
- **`feedback_no_hidden_debt` §6** (the 2026-05-02 "infrastructure decisions can't be deferred" rule) — this ADR is its application: AI-optional cannot be "we'll fix it later." Every new feature must satisfy the operational rule above on landing.

### Relation to product direction

All future product-level work (the fragmentation-governance ADR-0012-candidate → renumber ADR-0013, note-quiz mode, passive structuring, weekly digest) operates under this contract:
- **AI quizzing / AI grading**: identity allows it ("AI is advisory"), but users must be able to review notes without AI present.
- **Passive structuring (clustering / near-duplicates)**: AI computation is optional; without embeddings, fall back to keyword-based deduplication.
- **Weekly digest**: there can be both an AI-summary version and a "N items added this week" pure-stats version.

## Decision provenance

- User's exact words (2026-05-02): "I keep emphasizing — humans are the subject, AI is the assistant. So of course we're building a notes app (fundamentally a knowledge base). The proof is: even without AI configured, knowlet should still be usable."
- Triggered by critique #6 in the 2026-05-02 second-opinion engineering review (product-positioning internal contradiction).
- Consistent with prior user feedback: `feedback_no_hidden_debt` (AI is a tool, not the subject), `project_knowlet_fragmentation_thinking` §"never let AI silently change the IA" (same root principle).
