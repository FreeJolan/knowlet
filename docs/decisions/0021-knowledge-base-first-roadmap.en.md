# 0021 — Knowledge-base-first implementation order (Phase 0-4)

> **English** | [中文](./0021-knowledge-base-first-roadmap.md)

- Status: Accepted
- Date: 2026-05-05

## Context

[ADR-0012](./0012-notes-first-ai-optional.en.md) pinned the identity as "knowledge software + AI is optional";
the [ADR-0003 amendment (2026-05-04)](./0003-wedge-pivot-ai-memory-layer.en.md#amendment-2026-05-04--user-course-correction) restored bilinks + graph view to "knowledge software core."

But the **implementation order** drifted seriously:

```
M6.0–M6.5  Obsidian-style UI shell + multi-session chat        (~3 weeks)
M7.0       Notes baseline 5 items (checklist done, UX un-polished) (1 week)
M7.1       Selection → chat capsule                             (3 days)
M7.2       URL → summary → capsule                              (3 days)
M7.3       Mining critical take + hover quote                   (1 day)
M7.4       Quiz mode                                            (1 week)
M7.5       LLM web_search                                       (3 days)
M8.1       Structure signals backend                            (1 day)
```

After M7.0 every phase was AI integration. **M7.0 notes baseline was treated as a checklist, not as "knowlet's signature"**.

The 2026-05-04 dogfood verified: the user rated file ops / chat / visual / interaction at F=1 across the board, total verdict "completely unwilling to use it again." [Full report](../dogfood/M7-M8.1-report-2026-05-04.md).

This ADR pins the **redo implementation order** so knowlet first becomes **usable as knowledge software**, then layers AI augmentation back on.

## Decision

### Five phases

```
🟢 Phase 0  Decision lock + scaffold + backend hardening (parallel)  2-3 days
🟢 Phase 1  Knowledge-base baseline A + B + C (mandatory)            4-5 weeks
🟢 Phase 2  Knowledge-base D + E (should-have, deferrable)           1-2 weeks
🟢 Phase 3  AI features re-built on the new stack                    3-4 weeks
🟢 Phase 4  Full dogfood + data durability + gray-release prep
```

Default product phase = **development** (per [ADR-0022](./0022-product-lifecycle-phases.en.md)); aggressive iteration allowed throughout, no compatibility burden.

### Phase 0 — Decision lock + scaffold + backend hardening

**Goal**: lock all "drift if not pinned" decisions, get scaffold up, kick off backend hardening. **No production code yet** — only foundations.

Checklist:
- [ ] ADR-0019 frontend stack written (this batch)
- [ ] ADR-0020 backend hardening written (this batch)
- [ ] ADR-0021 this ADR written (this batch)
- [ ] ADR-0022 product phases written (this batch)
- [ ] ADR-0011 §"Stack" amendment (this batch)
- [ ] Roadmap + memory updates (this batch)
- [ ] **Phase 0 implementation** (after agent restart):
  - [ ] `frontend/` directory; Vite + React + TS + Tailwind initialized; `bun install` + `bun dev` brings up a hello-world page
  - [ ] shadcn/ui installed; Tailwind config wired to existing paper-light + dark tokens
  - [ ] FastAPI proxies `/api/*` to `localhost:8000`; static `frontend/dist/` mount path decided
  - [ ] Backend: `mypy --strict` config + run + fix exposed type holes (estimated 50-100)
  - [ ] Backend: `ruff` strict config + fix lint
  - [ ] Backend: pre-commit hooks + docs
  - [ ] Backend: GitHub Actions CI

**Phase 0 done definition**:
- New React page boots, renders empty paper-light placeholder using applied tokens
- Backend `mypy --strict` + `ruff check` + `pytest` all green
- pre-commit + CI run; any failure blocks commit / push

**Phase 0 explicitly does NOT**: any actual feature.

### Phase 1 — Knowledge-base baseline A + B + C (mandatory)

**Goal**: knowlet earns the right to be used as knowledge software (a fresh Obsidian / Bear user opens it for the first time and within 5 minutes can create / rename / move / delete / restore / search / make-folder, **without touching the CLI**).

#### A. File ops to Obsidian / Bear / VS Code baseline (1-1.5 weeks)

- [ ] File tree: react-arborist + virtualization + multi-select (Cmd / Shift)
- [ ] Right-click menu: new note / new subfolder / rename / move / copy / delete / open in new tab / copy path
- [ ] Drag-to-move (notes / folders)
- [ ] F2 / double-click rename (inline edit)
- [ ] Bulk operations (multi-select → bulk move / delete / tag)
- [ ] **Trash UI** (focus mode pane / modal) — replaces CLI restore
- [ ] Vault full-text search (palette `Cmd+P` strengthened, on par with Obsidian quick switcher)
- [ ] **Folder creation UI** (replaces Finder)
- [ ] Sidebar favorites / recent (deferable to Phase 2 D)

**Acceptance**: project owner completes all file ops in the React UI without opening Finder / a terminal.

#### B. Editor to Bear / iA Writer baseline (2 weeks)

- [ ] CodeMirror 6 replaces textarea
- [ ] Markdown live preview / split / preview-only modes
- [ ] Image paste (backend exists; UI redo)
- [ ] **Math rendering** (KaTeX)
- [ ] **Mermaid diagrams**
- [ ] **Template system**: `templates/` directory + new-note template picker
- [ ] **Block references `[[Note#Heading]]`** + `[[Note^block-id]]` anchors
- [ ] Code syntax highlighting (CodeMirror built-in; drop highlight.js)
- [ ] In-editor shortcuts (Cmd+B/I/K basics; don't over-engineer)

**Acceptance**: project owner can write a Chinese note with math / code blocks / Mermaid / block references, **with experience no worse than Obsidian**.

#### C. Knowledge connection baseline (1 week)

- [ ] Wikilinks `[[Title]]` (existing; React redo + typing-time autocomplete)
- [ ] Backlinks panel (existing; React redo + sentence-level preview + filter)
- [ ] **Graph view** (per ADR-0003 amendment; node = note, edge = `[[…]]`, zoom + drag)
- [ ] **Tag browser** (tag tree / tag click → all notes carrying that tag)
- [ ] Tag autocomplete (typing → suggest existing vault tags)

**Acceptance**: project owner sees the vault overview in graph view, clicks any node to navigate; tag browser is as glanceable as Obsidian's.

#### Phase 1 done definition

- A + B + C complete checklist ✅
- After a week of dogfood, project owner is **willing to use knowlet as a daily notes app** (subjective)
- 0 P0 / P1 bugs

### Phase 2 — Knowledge-base D + E (should-have, deferrable)

#### D. Entry experience (0.5-1 week)

- [ ] **Daily notes** (date-based auto-create + jump; Roam entry pattern)
- [ ] Quick switcher strengthen (palette, fuzzy + recent)
- [ ] Pinned / favorite notes (top of left rail)

#### E. Data durability + sync (1 week, with ADR-0018)

- [ ] **ADR-0018 draft + implement**: schema_version on Card / Draft / MiningTask; migration scripts + fixture-based regression test suite
- [ ] Vault snapshot / restore UI (CLI exists; React adds a button)
- [ ] Note version history (lightweight, git-based or `.knowlet/backups/`)
- [ ] (Optional) Import: Obsidian / Notion / Roam → knowlet
- [ ] (Optional) Export: PDF / HTML / Anki

**Phase 2 is "should-have, deferrable"** — if Phase 1 dogfood says "go straight to AI," Phase 2 D / E can slip into Phase 4 integration time.

### Phase 3 — AI features re-done on the new stack (3-4 weeks)

**Key**: AI backend **already exists** (376 tests cover it). Phase 3 is **resurfacing** those features in React, while:
- Fixing the protocol layer (split user-facing message from LLM-facing prompt; eliminate "hidden prompt leaks into user bubble")
- Absorbing dogfood-exposed design issues (quiz scope picker / capsule dedup / URL ghost / sediment ambient inline; see [Claude Design 2nd pass bundle](../design/bundle-2026-05-04/))

Checklist:
- [ ] **Chat dock + chat focus mode**: Vercel AI SDK + useChat hook (SSE / streaming / persist / refresh-restore all bundled)
- [ ] **Selection → capsule** redo (dedup / wrap doesn't overflow input / popover smart avoidance / Cmd+Shift+A)
- [ ] **URL ghost capsule** (per Claude Design §3 — replaces banner)
- [ ] **Sediment + Layer A inline ambient**
- [ ] **Quiz focus mode** (per Claude Design §8 — 2-step scope picker / search-not-list / inline disagree)
- [ ] **Mining drafts UI**: critical take + hover quote redo, list + paginate + accept / reject
- [ ] **Web search trace display**: tool calls clearly visible in chat history
- [ ] **Cards full set**: Cards focus mode + new-card UI (existing)
- [ ] (Backfill) **UI peers for create_card / web_search / fetch_url / list_mining_tasks** (per ADR-0004 amendment)

**Acceptance**: every dogfood-report frustration cleared; top frustrations shift from "Chat completely unusable" to "I wish feature X were better."

### Phase 4 — Full dogfood + gray-release prep

- [ ] Full e2e tests (Playwright) — chat full-stack / file ops / quiz flow / etc
- [ ] Data durability ADR-0018 fully landed (if not in Phase 2)
- [ ] Documentation complete (README / install / use guide / contribute)
- [ ] Gray-release entry criteria evaluated (per ADR-0022)
- [ ] Gray-release distribution mechanism (brew formula / installer / invite flow)

### After Phase 4 = enter gray release (per ADR-0022)

## Consequences

### Positive

- **Order is right**: knowledge software first, AI second; consistent with the ADR-0012 identity contract
- **Each phase has a quantifiable acceptance bar**: no "thought it was done"
- **Tight dogfood feedback loop**: a dogfood after Phase 1, another after Phase 3; cadence
- **Gray-release entry path is clear**: Phase 4 entry criteria locked

### Negative

- **8-10 weeks of no new AI features** (project owner has expressed willingness to be patient)
- **Some existing AI features (quiz / mining / web_search) exist as "raw API + curl" until Phase 3**: barely usable, no UI
  - Mitigation: Phase 3 isn't a delay; getting the order right matters more

### Out of scope

- Anything after gray release (per ADR-0022, ADR before entering)
- M9 stage (this ADR folds the previous M9 candidates — block refs / Daily / Math / templates etc — into Phase 1 B/D)

## References

- [ADR-0012](./0012-notes-first-ai-optional.en.md) — Notes-first / AI optional (this ADR is the implementation tier)
- [ADR-0003 amendment (2026-05-04)](./0003-wedge-pivot-ai-memory-layer.en.md#amendment-2026-05-04--user-course-correction) — bilinks + graph are core (Phase 1 C)
- [ADR-0004 amendment (2026-05-04)](./0004-ai-compose-code-execute.en.md#amendment-2026-05-04--user-clarification-ai--sole-entry-point) — every AI capability needs a UI alternative (Phase 3 cashes this in)
- [ADR-0019 frontend stack](./0019-frontend-stack.en.md) / [ADR-0020 backend hardening](./0020-backend-python-discipline.en.md) — engineering foundations
- [ADR-0022 product phases](./0022-product-lifecycle-phases.en.md) — currently development phase, aggressive iteration allowed
- [Dogfood report 2026-05-04](../dogfood/M7-M8.1-report-2026-05-04.md) — the original signal triggering this ADR
- [Claude Design 2nd pass bundle](../design/bundle-2026-05-04/) — Phase 1/3 visual + interaction reference
