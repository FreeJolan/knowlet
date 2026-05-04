# Roadmap

> **English** | [中文](./README.md)

Knowlet evolves in phases under the Wedge Strategy. Capabilities share source and reinforce each other; the narrative focuses by phase. See [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.en.md).

## Phase Overview

```
Stage 1 (MVP / V1):    AI long-term memory layer + lower-burden PKM
Stage 2 (V1 → V2):     User-demand-driven extensions
Stage 3 (V2 → V3):     Cross-AI-tool memory layer (MCP server)
Stage 4:               All-in-one form
```

## Stage 1 — MVP / V1

**Slogan:** A personal knowledge base that organizes itself. / 会自己整理的个人知识库

### Real Scenarios Served

See [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.en.md) Scenarios A / B / C. Briefly:

- **A. Research / paper reading** — Discuss in knowlet chat → AI draft → user reviews → save; later AI conversations auto-recall historical conclusions
- **B. Information stream subscription and organization** — User configures knowledge mining tasks → scheduled fetching + LLM organization → user reviews → save
- **C. Structured repeated memory + AI augmentation** — Foreign language vocabulary / domain concept distinction / writing assessment; SRS submodule + AI adjusts feedback by user context

### Core Features

- **Embedded chat**: LLM brought by user (see [ADR-0005](../decisions/0005-llm-integration-strategy.en.md))
- **LLM-driven retrieval**: LLM retrieves from the knowledge base on demand each turn
- **Knowledge mining tasks**: scheduled + Prompt + source constraints + transparent fetching
- **AI draft + human review**: default sedimentation mode
- **SRS submodule (FSRS)**: an "active review view" inside the knowledge base
- **Layered user context**: Markdown intent + JSON derived analytics + SQLite derived state
- **Desktop + mobile PWA**: covers fragment scenarios

### Explicitly Out of Scope

See [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.en.md) "Explicitly Out of Scope" section. Summary:

- Team collaboration / multi-user (never)
- Content recommendation / discovery / social
- Tasks / calendar / Todo management
- Replicating AI Chat product features
- knowlet's chat doesn't displace Claude / Cursor

> **2026-05-04 amendment**: the original line "Traditional PKM
> dedicated UI for backlinks / graphs (achieved indirectly via LLM
> agent + tools)" is **withdrawn**. Bilinks + graph view are core
> knowledge-software capabilities, not decorations. Wikilinks
> shipped in M7.0.4; graph view enters M8 (see ADR-0003 / 0011 /
> 0013 each with a 2026-05-04 amendment).

### Conditions for Entering Stage 2

- Three-scenario happy paths run stably
- AI draft + human review sedimentation loop is not annoying in real use
- LLM-driven retrieval hit rate reaches a usable threshold (specific number determined during prototyping)
- Cross-scenario context accumulation has observable effect (writing assessment uses historical mistake patterns / reading drives vocabulary queue, etc.)

## Stage 1 progress (2026-05-04 snapshot)

### ✅ Shipped

```
M6.0–M6.5  Obsidian-style UI shell + multi-session chat + polish
Phase B    concurrency / async lifespan / SSE module / 8 hardenings
M7.0       notes baseline (soft-delete / nesting / images / wikilinks / code highlight)
M7.1       Selection → chat capsule (ADR-0015)
M7.2       URL capture + sediment ambient (ADR-0016)
M7.3       Drafts polish (critical take + hover quote)
M7.4       Note quiz mode (ADR-0014: CLI + Web + history tab + Cards reflux)
M7.5       LLM web_search + fetch_url (ADR-0017, backend-agnostic)
M8.1       Structure signals backend (near-dup / clusters / orphan / aging)
ADR-0004 amendment fixes: web_search palette, manual Card creation UI
```

### ⏳ In flight / awaiting

- **Claude Design 2nd pass** (brief at [`../design/m7-m8-redesign-brief.md`](../design/m7-m8-redesign-brief.md)):
  covers 8 M7 surface audits + M8.2 knowledge-map sidebar / M8.2b graph view / M8.3 weekly digest / M8.4 dark token
- **Batched dogfood** (template at [`../dogfood/M7-M8.1-report-template.md`](../dogfood/M7-M8.1-report-template.md)), feedback feeds back to design + bug fixes

### 🔧 ADR-0004 amendment backlog (every AI capability needs a UI alt)

- ✅ `web_search` — palette command (commit `ee0998a`)
- ✅ `create_card` — Cards focus + palette + new-card modal (commit `483ed4c`)
- ⏳ `list_mining_tasks` — needs Web mining-config panel (awaiting design)
- ⏳ `fetch_url` — unify with M7.2 url-capture flow (awaiting design)

### 📋 After design lands (M8 second wave + dogfood polish)

```
M8.2  Knowledge-map sidebar (consumes M8.1 signals) + graph view (user-authored bilinks)
M8.3  Weekly digest (Sunday-newspaper, ADR-0013 Layer C)
M8.4  Dark mode toggle (localStorage + system preference)
M7.4.3-cluster  Cluster-scope quiz (route currently 501, wire-compatible, awaits Layer B)
```

## Knowledge-software core capability audit (2026-05-04)

knowlet is knowledge software, not an AI-Chat wrapper (per [ADR-0012](../decisions/0012-notes-first-ai-optional.en.md)). This section cuts across **the canonical capabilities of "knowledge software" as a category** and audits knowlet's coverage.

### A. Authoring

| Capability | Status |
|---|---|
| Markdown editing + preview | ✅ M6 |
| Image paste | ✅ M7.0.3 |
| Code syntax highlighting | ✅ M7.0.5 |
| Bilinks `[[Title]]` | ✅ M7.0.4 |
| **Block references `[[Note#Heading]]` / block-id** | ❌ **Not planned — Tier 1 gap** |
| **Math rendering (KaTeX)** | ❌ **Not planned — Tier 1 gap** (STEM essential) |
| **Mermaid / PlantUML diagrams** | ❌ **Not planned — Tier 1 gap** (technical notes) |
| **Templates** (book notes / meeting minutes / etc) | ❌ **Not planned — Tier 1 gap** |
| Outliner mode (Logseq-style block hierarchy) | ❌ Tier 2 — needs new ADR (changes IA) |
| General attachments (PDF / audio / video) | ❌ Currently images only |
| CodeMirror editor upgrade | ⏳ ADR-0011 §M7+ deferred |

### B. Organization & Retrieval

| Capability | Status |
|---|---|
| Folder hierarchy | ✅ M7.0.2 (recursive) |
| Tags (frontmatter) | ✅ M0 |
| Full-text search (FTS5) | ✅ M0 |
| Vector search + RRF hybrid | ✅ M0 |
| Backlinks panel | ✅ M7.0.4 |
| Note jumper palette (Cmd+P) | ✅ M6.2 |
| Graph view | ⏳ M8 (just amended in) |
| Knowledge-map sidebar (LLM signals) | ⏳ M8.2 |
| **Daily notes / journaling** (date-based auto-create) | ❌ **Not planned — Tier 1 gap** (Roam entry pattern) |
| **Bulk operations** (multi-select → tag / move / delete) | ❌ **Not planned — Tier 1 gap** |
| Tag tree explorer | ❌ Tier 2 |
| Saved searches / smart folders | ❌ Tier 2 |
| Typed properties (Obsidian properties) | ❌ Tier 2 |

### C. Capture

| Capability | Status |
|---|---|
| Manual new + sediment chat → note | ✅ M0 / M6 |
| URL → summary → capsule | ✅ M7.2 |
| Image paste | ✅ M7.0.3 |
| RSS / URL mining → drafts | ✅ M3 |
| Web mining-config panel | ⏳ ADR-0004 backlog |
| **Highlight → Card** (one-click from selection) | ❌ **Not planned — Tier 1 gap** (cousin to ADR-0014) |
| Watch folder (drop file → auto-import) | ❌ Tier 3 |
| Audio recording + transcription | ❌ Tier 3 |
| OCR images → text | ❌ Tier 3 |
| Browser extension / web clipper | ❌ M9+ (per ADR-0016 §"Out of scope") |

### D. Active Recall

| Capability | Status |
|---|---|
| Cards / FSRS | ✅ M0 |
| Quiz mode (scope-driven recall) | ✅ M7.4 |
| Wrong-answer → Card reflux | ✅ M7.4.2 |
| **Cloze deletions (`{{c1::}}`)** | ❌ **Not planned — Tier 2 gap** |
| Anki .apkg import | ❌ Tier 3 |

### E. AI Integration

| Capability | Status |
|---|---|
| Chat with vault (RAG) | ✅ M0 |
| Selection → chat capsule | ✅ M7.1 |
| URL → summary → capsule | ✅ M7.2 |
| Quiz generation + grading | ✅ M7.4 |
| Web search tool | ✅ M7.5 |
| Multi-session chat | ✅ M6.4 |
| **Inline editor AI** (Cmd+K → continue / refine / shorten) | ❌ **Not planned — Tier 2 gap** (Notion AI style) |
| **Smart linking** (typing-time AI suggests `[[...]]` candidates via vector index) | ❌ Tier 2 |
| Image understanding (paste image → ask AI) | ❌ Tier 3 |
| Voice / TTS / STT | ❌ Tier 3 |

### F. Lifecycle / Hygiene

| Capability | Status |
|---|---|
| Soft-delete + trash | ✅ M7.0.1 |
| Layer A ambient (sediment shows similar) | ✅ M7.2 |
| Layer B structure signals | ⏳ Backend ✅ M8.1 / UI awaits design |
| Layer C weekly digest | ⏳ M8.3 |
| Explicit archive (vs trash) | ❌ Tier 2 |
| Note freeze / pin | ❌ Tier 3 |
| Note version / diff history | ❌ Tier 3 (users fall back to git) |

### G. Sync & Export

| Capability | Status |
|---|---|
| Vault = plain folder (user brings Syncthing/iCloud) | ✅ M0 (per ADR-0006) |
| Export (PDF / HTML / Anki) | ❌ Tier 2 |
| Vault import (Obsidian / Notion / Roam) | ❌ Tier 2 |
| Self-built sync (CRDT / encrypted) | ⏳ Stage 2 |

### H. Extensibility

| Capability | Status |
|---|---|
| Plugin system | ⏳ Stage 2 |
| MCP server | ⏳ Stage 3 |

### I. Visual

| Capability | Status |
|---|---|
| Paper-light theme | ✅ M6.1.5 |
| Dark toggle | ⏳ M8.4 |

### Tier 1 gap summary (most identity-load-bearing for "knowledge software")

**M9 candidates** (priority order finalized after M8 dogfood):

1. **Block references + block-id anchors** — bilinks today reach note level; Roam/Obsidian/Logseq all reach block level. M7.0.4 wikilinks are the foundation; M9 adds `[[Note#Heading]]` and `[[Note^block-id]]` anchors.
2. **Daily notes / journaling** — Roam-style date-based auto-creation. Need to clarify boundary with ADR-0013 Layer C weekly digest (daily = capture entry; weekly = retrospective).
3. **Math (KaTeX) + Mermaid rendering** — STEM / engineering notes essential. marked has plugins; integration is cheap, just hasn't been queued.
4. **Templates** — `templates/` folder + new-note template picker.
5. **Highlight → Card one-click** — adjacent to M7.4 Cards reflux: select in note → floating button "make Card" → opens new-Card modal pre-filled. Strengthens active-recall capture.
6. **Bulk operations** — multi-select → change tag / move folder / delete. Will surface as a need late in dogfood as the vault grows.

### Tier 2 (middle priority)

7. Outliner mode (Logseq block hierarchy) — IA paradigm change, needs ADR
8. Cloze deletions (`{{c1::}}`) — Anki-style card faces
9. **Inline editor AI** (Cmd+K continue / refine / shorten) — Notion AI style; distinct entry from M7.1 capsule
10. Smart link suggestions (typing-time vector retrieval suggesting `[[...]]` candidates)
11. Explicit archive (vs trash)
12. Tag tree explorer / saved searches / typed properties
13. Export / import (Obsidian / Notion / Roam → knowlet)

### Tier 3 (deferred / low priority)

Attachments (PDF/audio/video) / watch folder / audio recording + transcription / OCR / image understanding / voice / browser extension / native mobile / plugin system (already Stage 2) / Anki .apkg import

---

## Stage 2 — V1 → V2: User-Demand-Driven Extensions

After stage 1 stabilizes, users naturally surface new needs. Possible directions (in expected priority):

- **Plugin ecosystem**: open interfaces for users / community to write custom tools, extending the atomic capability layer
- **Native mobile**: PWA isn't enough; audio / OCR / notification scenarios need native capabilities
- **Knowlet's own sync service**: when file-level sync's conflict experience falls short, add CRDT or encrypted sync paths
- **Full encryption path**: when high-privacy needs emerge (see [ADR-0006](../decisions/0006-storage-and-sync.en.md))
- **Fallback fetching backend**: support LLMs without native web_search (SearXNG / Brave / self-hosted)

> **2026-05-04 amendment**: the original "graph / backlink visualization" item in Stage 2 has **moved to Stage 1 / M8** (per ADR-0003 / 0011 / 0013 amendments). Bilinks are knowledge-software core, not a V2 extension.

Stage 2 is **pulled by user need**, not built first looking for need. Specific features must pass the priority criteria below before entering the roadmap.

## Stage 3 — V2 → V3: Cross-AI-Tool Memory Layer

Stage 1 atomic capabilities are designed to MCP standards (see [ADR-0004](../decisions/0004-ai-compose-code-execute.en.md)). Stage 3 formally opens MCP server form:

- Claude Desktop / Cursor / other MCP-compatible tools can directly invoke knowlet's capabilities
- Knowlet is no longer just a "standalone app" but the "private memory layer for all the user's AI tools"
- Fully consistent with ADR-0003's wedge narrative

## Stage 4 — Long-Term All-in-One Form

When the three core capabilities (consumption sedimentation / information mining / learning augmentation) reinforce each other in the MCP form:

```
Information mining → AI organizes candidates → user reviews and saves
              ↓
       LLM-driven retrieval recalls in all AI tools
              ↓
       Used knowledge becomes cards → SRS review
              ↓
       Mistakes feed back to notes and adjust mining task prompts
```

Stage 4 is no longer "stack new capabilities" but maxing out the feedback loops of existing capabilities.

## Feature Priority Criteria

Before any new feature enters the roadmap, run it through four questions:

1. **Does it serve the current stage's wedge?** No → backlog
2. **Does it harm the three core principles?** (AI optional / data sovereignty / plugin-ization) Yes → reject
3. **Can it be expressed with existing domain entities?** No → consider whether to add a new entity, not stuff into existing
4. **What's the cost of rejection?** If it's "lose some users not in current stage persona", that's acceptable

This avoids the "want to do everything" early trap; each candidate's verdict is recorded in corresponding ADR or design docs.
