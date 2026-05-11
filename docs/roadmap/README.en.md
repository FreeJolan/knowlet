# Roadmap

> **English** | [中文](./README.md)

Knowlet evolves in stages per the Wedge strategy. Capabilities share a common foundation; narrative tightens by stage. See [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.en.md) (and its 2026-05-04 amendment).

## ⚡ Current state (2026-05-11)

**Product phase** = development (per [ADR-0022](../decisions/0022-product-lifecycle-phases.en.md)). No external users; aggressive iteration allowed.

**Project status** = **Phase 1 ABCD ✅ + ADR-0027 sync (Slice 5.A-5.G + 2026-05-11 dogfood-pass closure of #113-#122 + three OAuth/push gaps) single-device closed-loop ✅**. Sync main line + key dogfood gaps closed; remaining sync polish = attachment delete-sync (orphan GC) + real-multi-device scenario validation + conflict UI visual cleanup (see [ADR-0027 § Status (2026-05-11)](../decisions/0027-sync-via-drive-api.md)).

**User product policy (2026-05-11)**: **Phase 3 AI rework is hard-gated on knowlet being a fully-capable note-taking app first**. Phase 2 D (Daily notes / Quick switcher / favorites) + Phase 2 E data durability (ADR-0018) + the sync polish above **must all** land before Phase 3 starts. Don't unilaterally jump to AI.

- **Frontend**: Alpine deprecated; switching to React 19 + Vite + TypeScript + shadcn/ui + Vercel AI SDK + CodeMirror 6 + react-arborist + Tanstack Query
- **Backend**: not rewritten; adding mypy strict + ruff + pre-commit + CI (per ADR-0020)
- **Order**: Phase 0 ✅ → Phase 1 ABC ✅ → Phase 1 D ✅ → ADR-0027 sync main line ✅ → **Phase 2 D ✅ → Phase 2 E data durability ✅ → Phase 3 AI rework (next) → Phase 3.5 desktop client → Phase 4 gray-release + v1.0.0 → Phase 5 mobile (read/review-centric)**
- **Estimated**: **12-17 weeks** to Phase 4 (gray entrance) — 2026-05-12 revision, added Phase 3.5 desktop 2-3 weeks

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
Phase 0   Decision lock + scaffold + backend hardening (parallel)  2-3 days  ✅ done
Phase 1   Knowledge-base baseline A + B + C (mandatory)            4-5 weeks ✅ done (m1c)
   A. File ops to Obsidian baseline: right-click menu / drag / rename / move / multi-select / Trash UI / folder-create UI / full-text search
   B. Editor to Bear baseline: CodeMirror 6 + Math (KaTeX) + Mermaid + templates + block references
   C. Knowledge connection: Wikilinks autocomplete + Backlinks + Graph view + Tag browser
Phase 1 D Obsidian-baseline UX gaps (added 2026-05-08 after dogfood)  2 weeks
          dogfood after Phase 1 ABC found 6 baseline UX gaps users hit daily
   D1. Multi-tab / multi-pane (largest item): tab strip above NoteView, h/v split, pin / close / reorder, state persistence
   D2. Full-text search panel: consume the existing FTS5 + vector backend; new "Search" rail tab or ⌘⇧F focus mode; query + results + snippet + click-jump + highlight
   D3. Properties UI: frontmatter form below title (aliases as chip strip / created-updated readonly / custom fields); user never has to touch YAML
   D4. Dark mode toggle: tokens already in place (Phase 0); add header sun/moon button + localStorage + system-preference fallback
   D5. Outline panel: 3rd right-rail tab (Backlinks / Graph / Outline); parse h1-h6 + click-jump
   D6. Hover preview for [[Title]]: hover popup with target's title + first paragraph
Phase 2   D + E (should-have, deferrable)                          1-2 weeks (deferable to Phase 4)
   D. Entry: Daily notes / Quick switcher / pinned
   E. Data durability: ADR-0018 / Note version / Import-Export
Phase 3   AI features re-done                                      3-4 weeks
   Chat (Vercel AI SDK) / capsule / Sediment / Quiz / Mining UI / Web search trace / Cards
   per ADR-0024 envelope: 7 AI roles / 7-layer prompt envelope / mech-hybrid-creative gate
Phase 4   Full dogfood + gray-release prep                         1-2 weeks
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

- 🟡 **Awaiting dogfood signal** (Phase 4+): citation back-refs / capsule cross-session draft tray / CLI `:quote` / `knowlet://` deep-link / per-session web search cap / Layer A on blank notes / drafts approve ambient / **retrieval quality v2 (RRF fusion / LLM rerank / query expansion / smart chunking; ~3-4 days, borrows qmd's 4 design points reimplemented in Python — ADR-0024 §"Out of scope")**
- 🔵 **Will be implemented during React rewrite (Phase 1-3)**: list_mining_tasks Web panel / fetch_url UI / knowledge-map sidebar / **graph view (Phase 1 C now)** / weekly digest / dark toggle UI (Phase 1) / cluster-scope quiz (Phase 3) / **`vault/.knowlet/wiki_schema.md` prompt injection + co-evolution + multi-level merging (ADR-0023 §2, Phase 3)** / **ingest source as first-class verb (ADR-0023 §4, Phase 3)** / **Lint LLM signals — cross-page contradictions / dangling concept / inferred-missing entity (ADR-0023 §5, Phase 3)** / **Pin chat turn to wiki (ADR-0023 §6, Phase 3)** / **Editor advisor (suggest folder location at new-note / draft-approval / ingest, ADR-0023 §8.1 + ADR-0024 §4, Phase 3)** / **Tidy advisor (M8.1 signal extension: scattered cluster / oversized folder / orphan / dangling concept; ambient proposals, ADR-0023 §8.2 + ADR-0024 §4, Phase 3)** / **Reorg planner (user-initiated tree reorg, 5 hard constraints, ADR-0023 §8.3 + ADR-0024 §4, post-Phase 3)** / **AI-assist envelope 7-layer architecture (per-action prompt template + static/derived/task layers + lazy loading + 7 AI roles, ADR-0024 §3-4, Phase 3)**
- 🟢 **Awaiting stage transition**: plugin system / native mobile / self-hosted sync / vault encryption / MCP server / Tauri / browser extension
- 🟣 **Data durability** (Phase 2 E, ADR-0018 pending): operational safety net (snapshot / restore / doctor integrity / Note schema_version) shipped at commit `40cfcd0`; full contract pending. Includes **`vault/.knowlet/log.md` + `vault.events` SQLite append-only stream** (per [ADR-0023 §3](../decisions/0023-llm-wiki-comparison-and-takeaways.en.md)) and **Note frontmatter `status` field — `active | stub | needs-update | deprecated`** (per [ADR-0023 §7](../decisions/0023-llm-wiki-comparison-and-takeaways.en.md))
- 🔴 **Forever**: team collab / discovery / Todo / AI-Chat-product feature copies / tag taxonomy / auto-merge / **auto-move / auto-archive (ADR-0024 §5 C)** / **LLM auto-IA-modify / "LLM owns the wiki" (ADR-0013 §1 / ADR-0023 §A)** / **AI-rewrites-Note-bodies "Note rewriter" (ADR-0024 §5 B)** / **AI-writes-Note-bodies ghostwriter toggle (ADR-0024 §5 A)** / **AI auto-writes frontmatter tag/alias (ADR-0024 §5 D)** / **frontmatter `confidence` / `source_count` LLM-attributed (ADR-0023 §D / §7 / ADR-0024 §5 E)** / **preset IA `entities/` `concepts/` `comparisons/` `maps/` (ADR-0023 §E / ADR-0024 §5 F)** / drafts image-video-PDF extraction / multi-URL paste / LLM PDF/video fetch / auto-save search results / multilingual search switch / **cross-vault wiki federation (ADR-0023)** / **LLM-driven schema auto-evolution — direct LLM editing of `wiki_schema.md` (ADR-0023; only "propose → user approves" co-evolution allowed)** / **direct integration of [`qmd`](https://github.com/tobi/qmd) (cross-language / 2GB models / mismatched architecture, ADR-0023 §G — but learn its 4 design points, see retrieval quality v2 above)** / integrating Marp / Obsidian Dataview / **8th AI role beyond ADR-0024 §4's locked 7 (high-bar ADR decision required)**

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
