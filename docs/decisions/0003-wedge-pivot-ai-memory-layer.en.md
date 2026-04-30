# 0003 — Wedge Pivot: AI Long-Term Memory Layer + Lower-Burden PKM

> **English** | [中文](./0003-wedge-pivot-ai-memory-layer.md)

- Status: Accepted
- Date: 2026-04-30
- Supersedes: [0001](./0001-wedge-learning-first.en.md)

## Context

[ADR-0001](./0001-wedge-learning-first.en.md) chose "learning-first" as the wedge, described concretely as OCR + cards + SRS + AI question generation + mistake feedback, with acquisition aimed at exam / language-learning communities.

In subsequent product-form discussion, ADR-0001's "learning-first" framing was found to actually mix two product forms that pull against each other:

| Form | Description | Typical user |
|---|---|---|
| **A** | Exam / language-style SRS tool: heavy review cadence, heavy cards, heavy mobile | Exam / language-learning communities |
| **B** | Active learning memory for knowledge workers: heavy RAG, heavy note sedimentation, cards as a side feature | Programmers / researchers / knowledge workers |

ADR-0001's description leans toward A, but [ADR-0002](./0002-core-principles.en.md)'s open source tone / data sovereignty / capability plugin-ization principles point more toward B. Running both in parallel causes architectural wobble and unclear mindshare.

In addition, during repositioning, a deeper product proposition surfaced:

> The real obstacle to a personal knowledge base isn't "AI not strong enough", it's **management cost being too high**. The high abandonment rate of Obsidian / Notion / Roam mainly comes from: the mental burden of summarizing / classifying / sedimenting; the migration cost of learning a tool's rules; and the frustration of "I spent time organizing but never used it".
>
> The real product value of LLMs is **swallowing this low-ROI, mechanical organization work**, leaving user attention focused on thinking, asking, judging — the high-ROI parts AI cannot replace. AI is not just a "cost absorber"; it is also a "value multiplier" — old notes get auto-connected, actively recalled, accumulated across scenarios.

Based on these two judgments, ADR-0001's wedge narrative needs to be replaced.

## Decision

### Wedge Position

Pivot the wedge to form B, with positioning tightened to:

> **Personal knowledge base + AI long-term memory layer.** AI takes over mechanical organization (summarizing, classifying, sedimenting, retrieving); the user retains intent, thinking, judgment. Simultaneously, any AI tool (Claude / Cursor / others) can actively retrieve from this knowledge base during conversation — visible not just inside knowlet but across all the user's AI workflows.

### Slogan

- Chinese: **"会自己整理的个人知识库"**
- English: **"A personal knowledge base that organizes itself."**

### Naming Tone

The repository name **knowlet** = `know + -let` (analogous to *booklet* / *droplet*), meaning *a small unit of knowing*.

Implicit tone: **modest, atomic, cumulative**. Documentation and product copy should not claim "second brain", "AI knowledge engine", "revolutionary" or other grand terms; instead, lead from "accumulation of small knowings".

### Real Use Cases Served in Stage 1

#### Scenario A — Research / paper reading
User actively finds a paper → discusses in knowlet's embedded chat → AI writes a Note draft → user reviews and saves → sediments. In any subsequent AI conversation, the LLM actively retrieves this Note and answers with historical context.

#### Scenario B — Information stream subscription and organization
User configures a "knowledge mining task" (frequency + source constraints + Prompt) → executes on schedule → fetching is transparent and traceable → generates multiple atomic Notes + an index Note → user reviews and accepts.

#### Scenario C — Structured repeated memory + AI augmentation
Covers content needing long-term memorization and repeated practice (foreign language vocabulary, technical concept disambiguation, writing assessment, etc.). The SRS submodule handles scheduling; AI provides on-demand sentence generation / explanation / synonym distinction during review, and adjusts feedback depth and style based on "user context" during assessment-style tasks.

The three scenarios share **one user context** (goals / preferences / mistake patterns / vocabulary mastery); AI accumulates understanding across them.

### Stage 1 Core Features

- **Embedded chat**: LLM is brought by the user (OpenAI-compatible protocol), knowlet does not proxy conversation traffic
- **LLM-driven retrieval**: LLM pulls relevant content from the private knowledge base on demand during each conversation
- **Knowledge mining tasks**: scheduled + Prompt + source constraints + transparent fetching
- **AI draft + human review** as the default sedimentation mode
- **SRS submodule (FSRS)**: an "active review view" inside the knowledge base, not a standalone product
- **Layered user context**: Markdown intent layer + JSON derived analytics layer + SQLite derived state layer
- **Desktop primary + mobile PWA** for fragment scenarios

### Explicitly Out of Scope in Stage 1

- Team collaboration / multi-user (never)
- Content recommendation / discovery / social
- Tasks / calendar / Todo management
- Traditional PKM dedicated UI for backlinks / graphs (achieved indirectly via LLM agent + tools)
- Cross-user content sharing / knowledge pack publishing
- AI autonomous decision-making (user is always the decision-maker, AI is the executor)
- Replicating AI Chat product features (model selection optimization / long context / code generation / image generation)
- Content moderation / safety filtering
- Built-in Wikipedia / public knowledge bases
- OT / CRDT real-time multi-device editing
- knowlet's chat does not displace Claude / Cursor: only enters the picture when "work meets sedimentation"

### Stage Evolution Anchors

See [`../roadmap/`](../roadmap/) for details. Briefly:

- **Stage 1 (MVP / V1)**: above core features
- **Stage 2**: extensions driven by natural user demand (graph visualization / plugin ecosystem / native mobile experience)
- **Stage 3 / long-term**: knowlet's atomic capabilities exposed as an MCP server, accessible across AI tools — echoing the "AI long-term memory layer" wedge

### Relationship with Other ADRs

- **Supersedes** [ADR-0001](./0001-wedge-learning-first.en.md)'s wedge narrative (Slogan / core features / acquisition / stage order), but preserves its "Wedge Strategy" methodology — the basic judgment that "capabilities share source, narrative is narrow"
- **Subordinate to** [ADR-0002](./0002-core-principles.en.md)'s three core principles
- **Complementary to** ADR-0004 (AI compose, code execute) / ADR-0005 (LLM integration strategy) / ADR-0006 (storage and sync)

## Consequences

### Benefits

- **Focused narrative**: target users are clear (knowledge workers / programmers / researchers / continuous learners)
- **Fully aligned with ADR-0002 tone**: data sovereignty / AI optional / plugin-ization promises naturally hold; no more tension as in ADR-0001
- **Directly addresses PKM high abandonment pain**: "management cost" becomes AI's primary service target, frustration source eliminated
- **Cross-scenario context accumulation forms natural differentiation**: Anki / Claude / Duolingo / Notion AI cannot do this (they're isolated from each other)
- **Stage 2 expansion is pulled by user need**, not arbitrary feature padding

### Costs / Constraints

- Abandons the strong SRS narrative for exam scenarios (a core selling point of original ADR-0001)
- OCR + cards descend to the SRS submodule level, no longer the main stage 1 battleground
- Users must bring their own LLM (OpenAI / Anthropic / Ollama, etc.); first-time configuration has nonzero friction, but acceptable for target users
- Sync pipeline brought by the user (iCloud / Dropbox / Syncthing, etc.); knowlet does not implement sync logic in stage 1
- LLM provider sees user conversations + RAG-hit fragments; knowlet does not proxy or filter; privacy is determined by the user's LLM choice
- "Rebuild mechanism" (rebuilding derived data from Markdown / JSON) has visible delay on large vaults at first launch — acceptable
