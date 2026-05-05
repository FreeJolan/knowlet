# Roadmap

> **English** | [中文](./README.md)

Knowlet evolves in stages per the Wedge strategy. Capabilities share a common foundation; narrative tightens by stage. See [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.en.md) (and its 2026-05-04 amendment).

## ⚡ Current state (2026-05-05)

**Product phase** = development (per [ADR-0022](../decisions/0022-product-lifecycle-phases.en.md)). No external users; aggressive iteration allowed.

**Project status** = **rewrite in progress**. The 2026-05-04 dogfood verified the frontend was basically unusable, triggering these decisions (see ADR-0019 / 0020 / 0021):

- **Frontend**: Alpine deprecated; switching to React 19 + Vite + TypeScript + shadcn/ui + Vercel AI SDK + CodeMirror 6 + react-arborist + Tanstack Query
- **Backend**: not rewritten; adding mypy strict + ruff + pre-commit + CI (per ADR-0020)
- **Order**: Phase 0 (scaffold + backend hardening) → Phase 1 (knowledge-base baseline) → Phase 2 (should-have, deferrable) → Phase 3 (AI features re-done) → Phase 4 (gray-release prep)
- **Estimated**: 8-12 weeks to Phase 4 (gray entrance)

```
🟢 Already shipped backend, **kept** (zero change, reused as-is)
   notes / cards / drafts / mining tasks CRUD + index (FTS + vec)
   chat multi-session + sediment + LLM-driven retrieval
   capsule backend (M7.1) + URL capture (M7.2) + critical take + hover quote (M7.3)
   quiz mode (M7.4) + web_search + fetch_url (M7.5)
   structure signals (M8.1)
   vault snapshot / doctor integrity / Note schema_version

❌ Already shipped frontend, **will be deleted**
   knowlet/web/static/* (Alpine + custom SSE + custom palette)
   ~2000 lines app.js + ~1100 lines index.html + ~743 lines app.css
   Almost everything except token CSS variables is discarded

⏳ Awaiting rewrite
   All frontend surfaces (per ADR-0021 §"Phase 1/2/3")
```

## Phase plan after rewrite

See [ADR-0021](../decisions/0021-knowledge-base-first-roadmap.en.md). Summary:

```
Phase 0  Decision lock + scaffold + backend hardening (parallel)  2-3 days
Phase 1  Knowledge-base baseline A + B + C (mandatory)            4-5 weeks
   A. File ops to Obsidian baseline: right-click menu / drag / rename / move / multi-select / Trash UI / folder-create UI / full-text search
   B. Editor to Bear baseline: CodeMirror 6 + Math (KaTeX) + Mermaid + templates + block references
   C. Knowledge connection: Wikilinks autocomplete + Backlinks + Graph view + Tag browser
Phase 2  D + E (should-have, deferrable)                          1-2 weeks (deferable to Phase 4)
   D. Entry: Daily notes / Quick switcher / pinned
   E. Data durability: ADR-0018 / Note version / Import-Export
Phase 3  AI features re-done                                      3-4 weeks
   Chat (Vercel AI SDK) / capsule / Sediment / Quiz / Mining UI / Web search trace / Cards
Phase 4  Full dogfood + gray-release prep                         1-2 weeks
   Playwright e2e tests / docs / gray entry preparation
```

**After Phase 4** = enter gray release (per [ADR-0022](../decisions/0022-product-lifecycle-phases.en.md)).

## Stage 1 (MVP / V1) — Strategic layer

> Phases 0-4 are the implementation slices within V1. This section is the strategic "what V1 is overall," independent of specific phases.

**Slogan:** *A personal knowledge base that organizes itself.*

### Real scenarios served (from ADR-0003)

- **A — Research / paper reading**: discuss in chat → AI draft → user review → sediment; later AI conversations auto-recall historical conclusions
- **B — Information stream subscription + organization**: configure mining task → scheduled fetch + LLM organize → user review → ingest
- **C — Structured spaced repetition + AI augmentation**: vocab / professional concept disambiguation / writing review; SRS submodule scheduling + AI adjusting feedback in context

### Core features (strategic)

- **Embedded chat**: user brings their own LLM ([ADR-0005](../decisions/0005-llm-integration-strategy.en.md))
- **LLM-driven retrieval**: LLM retrieves from vault on-demand each turn
- **Knowledge mining tasks**: schedule + prompt + source constraint + transparent fetching
- **AI draft + human review**: default sedimentation pattern
- **SRS submodule (FSRS)**: as the vault's "active review view"
- **Layered user context**: Markdown intent + JSON derived analysis + SQLite derived state
- **Desktop + mobile PWA**: covers fragment scenarios
- **Bilinks + graph view** (2026-05-04 amendment): user-authored connections are core IA

### Explicitly out of scope

See [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.en.md) "Explicitly Out of Scope" (with 2026-05-04 amendment). Summary:

- Team collaboration / multi-user (forever)
- Content recommendation / discovery / social
- Tasks / calendar / Todo
- Replicating AI Chat product features
- knowlet's chat doesn't displace Claude / Cursor

## Stage 2 (V1 → V2)

User-demand-driven extensions (after gray and production):

- Plugin ecosystem; native mobile; self-hosted sync (CRDT / encrypted); full encryption path; fallback fetching backend (partially shipped via ADR-0017)

## Stage 3 (V2 → V3)

knowlet's atomic capabilities open as MCP server: Claude Desktop / Cursor / other MCP-compatible tools call knowlet directly. Memory layer across all AI tools.

## Stage 4 (long-term)

Three main capabilities (consume / mine / learn) reinforce each other in MCP form. Feedback loops fully closed; no new capabilities to add, just polish.

## 📦 Cross-ADR deferred-items registry (2026-05-05 reorg)

> Single-source-of-truth registry of every §"Out of scope" / §"Defer" / §"Future extension" across all ADRs. **For full content, see [Chinese version](./README.md#-跨-adr-延期事项总账2026-05-05-重整).** Summary by category:

- 🟡 **Awaiting dogfood signal** (Phase 4+): citation back-refs / capsule cross-session draft tray / CLI `:quote` / `knowlet://` deep-link / per-session web search cap / Layer A on blank notes / drafts approve ambient
- 🔵 **Will be implemented during React rewrite (Phase 1-3)**: list_mining_tasks Web panel / fetch_url UI / knowledge-map sidebar / **graph view (Phase 1 C now)** / weekly digest / dark toggle UI (Phase 1) / cluster-scope quiz (Phase 3)
- 🟢 **Awaiting stage transition**: plugin system / native mobile / self-hosted sync / vault encryption / MCP server / Tauri / browser extension
- 🟣 **Data durability** (Phase 2 E, ADR-0018 pending): operational safety net (snapshot / restore / doctor integrity / Note schema_version) shipped at commit `40cfcd0`; full contract pending
- 🔴 **Forever**: team collab / discovery / Todo / AI-Chat-product feature copies / tag taxonomy / auto-merge / LLM auto-IA-modify / drafts image-video-PDF extraction / multi-URL paste / LLM PDF/video fetch / auto-save search results / multilingual search switch

### Maintenance rule

> Every new / amended ADR with §"Out of scope" must register here.

## Deprecated as of 2026-05-05

- ❌ "M8.2 knowledge map sidebar as Alpine implementation" — now React (Phase 3)
- ❌ "M8.4 dark toggle in Alpine UI" — tokens kept, toggle UI in Phase 1 React
- ❌ "Batch 2 / Batch 3 of Claude Design 2nd pass on Alpine" — discarded; design intent maps to React
- ❌ "Polish file ops on Alpine UI" — discarded; full Phase 1 A redo

## Feature priority criteria

Every new feature must answer:

1. Does it serve the current stage's wedge? Otherwise → backlog
2. Does it harm the three core principles (AI optional / data sovereignty / pluggable)? Yes → reject
3. Can it be expressed with existing domain entities? No → think before adding entities
4. What's the cost of refusing it? If "lose some users not in our current stage profile," accept the cost
