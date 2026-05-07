# 0023 — LLM Wiki comparison + restating the human/machine contract

> **English** | [中文](./0023-llm-wiki-comparison-and-takeaways.md)

- Status: Proposed
- Date: 2026-05-07

## Context

In 2026-04, Karpathy published [`llm-wiki.md`](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f), proposing a widely circulated "LLM Wiki" pattern for personal knowledge bases. It overlaps heavily with knowlet's domain (PKB + LLM augmentation) but takes the opposite side on several root design choices.

This ADR exists to:

1. **Clarify the differences** as a positioning anchor — knowlet's README uses this comparison to make the "user owns / LLM proposes" root principle concrete.
2. **Adopt 5 non-conflicting features** into the roadmap (`wiki_schema.md` / `log.md` / Ingest verb / Lint / Pin to wiki).
3. **Explicitly reject** the parts of Karpathy's pattern that conflict with knowlet's core contract, so future discussions don't drift back toward "let the LLM run the vault."

## Karpathy LLM Wiki summary (so this ADR is self-contained)

**Three layers:**

- `sources/` — user's raw materials, immutable, LLM read-only
- The wiki (markdown directory) — **LLM-owned**, LLM writes, user reads
- `CLAUDE.md` / `AGENTS.md` — schema telling the LLM how to maintain the wiki

**Three operations:** Ingest (drop a source → LLM reads + writes summary + updates 10-15 related pages + appends log) / Query (LLM searches wiki, synthesizes answer, can file good answers back as new pages) / Lint (periodic health check: contradictions, stale claims, orphans, missing concept pages).

**Two navigation files:** `index.md` (content-oriented) + `log.md` (chronological, append-only).

**Key quotes:** "You never (or rarely) write the wiki yourself" / "Obsidian is the IDE; the LLM is the programmer; the wiki is the codebase" / "the tedious part of maintaining a knowledge base is not the reading or thinking — it's the bookkeeping."

**Form factor:** an idea file — not software / app / UI / toolchain, but a brief you copy-paste to your LLM agent. The actual user environment is Claude Code + Obsidian **side-by-side in two windows**.

## Decision

### 1. Restate the root principle — "user owns, LLM proposes"

[ADR-0013 §1](./0013-knowledge-management-contract.en.md) already mandates "no auto-merge / no auto-archive / no LLM-driven IA changes." This ADR elevates the rule to **knowlet's first-line positioning identity**.

The most precise way to state the difference is **who writes which layer**:

| Layer | Karpathy LLM Wiki | knowlet |
|---|---|---|
| **Content** (note bodies) | **LLM writes** (compiles `raw/` → wiki pages) | **User writes** |
| **Navigation / catalog** | **LLM writes** (`index.md` is an LLM-maintained markdown catalog: one line per page with summary + source count, grouped by entities / concepts / sources) | **No dedicated catalog file** (file tree + auto-backlinks instead; **code maintains backlinks, no need for the LLM to periodically rewrite a catalog**) |
| **Search index** (BM25 + vector) | Optional later: [qmd](https://github.com/tobi/qmd) (kicks in around 100+ pages) | **Code-maintained** (SQLite FTS5 + sqlite-vec, present from day 1) |

knowlet is **lighter than Karpathy's setup**: no LLM-maintained catalog, no scale-triggered search engine install. **The LLM writes nothing in the vault's persistent layer.**

Consequences:

- ✅ knowlet: user owns notes; LLM produces **candidates** (drafts / summaries / link suggestions / IA proposals); everything that enters the vault flows through a review pipeline
- ❌ Karpathy LLM Wiki: LLM **fully owns** the wiki (both content and catalog are LLM-compiled); user is reader + director only

These aren't ranked good vs bad — they make different assumptions about **trust in knowledge sediment**:

- Karpathy's pattern assumes single user + single topic + strong schema constraints + short-to-medium-term focus, where LLM maintenance is a net positive.
- knowlet's pattern assumes multi-year / multi-domain / multi-LLM-backend usage, where **the user's need for per-note explainability, trustworthiness, and controllability outweighs maintenance-cost savings**.

#### 1.1 Comparison via Tiago Forte's CODE framework

CODE = Capture / Organize / Distill / Express (*Building a Second Brain*, 2022). The two patterns differ sharply in AI participation across the four stages:

| Stage | "LLM runs your wiki" pattern | knowlet |
|---|---|---|
| Capture | user + AI (Web Clipper / scraping) | user + AI (URL capture / mining tasks) |
| **Organize** | **LLM auto-decides IA** (preset entities/concepts/comparisons/...) | **User-owned**; AI proposes only on user-initiated trigger ([ADR-0024](./0024-ai-assist-envelope.en.md) Editor advisor / Tidy advisor) |
| **Distill** | **LLM auto-writes note bodies** (synthesizes multiple sources → wiki page) | **AI produces candidates only → review queue → user approves** |
| Express | user (queries / generates slides) | user (writes notes / runs Quiz / sediments) |

**knowlet's essential differentiator = no auto-Organize; Distill always flows through the review queue**. This is more precise than the bumper-sticker "user owns, LLM proposes" — and it's the wording the README's positioning section uses.

### 2. Adopted feature 1 — `vault/.knowlet/wiki_schema.md`

**Problem**: Karpathy uses `CLAUDE.md` / `AGENTS.md` as "wiki maintenance rules" that co-evolve with the domain. knowlet today has user_profile (identity) and ADRs (project decisions), but **lacks a "vault-personal conventions" layer**.

**Adoption**: add a vault-level file `vault/.knowlet/wiki_schema.md` (user-readable, user-writable). Examples of what users might write:

- "I prefer H2 for chapter sections in my notes."
- "Use singular form for `[[Title]]` links."
- "Never let the LLM auto-merge synonyms."
- "New concepts get their own page; aliases live only in the main page's frontmatter `aliases` field."

**Injection points**:

- Chat system prompt (appended after user_profile)
- Mining draft prompt (so the LLM knows the vault's writing/linking conventions)
- Ingest source prompt (same, see §4)

**Non-conflict**: profile is "who I am"; schema is "how this vault is written." Two orthogonal layers.

#### Co-evolution mechanism (active prompts to evolve schema)

A secondary expansion of Karpathy's idea (in commentary writing) emphasizes: "start with 5-10 sources; revisit the schema every 10-20 ingests, encoding patterns you discover." knowlet makes this **active** rather than passive:

- Backend triggers an ambient suggestion in the review queue / weekly digest when:
  - mining draft approvals reach N (default 12), OR
  - sediments reach M (default 8), OR
  - ingests reach K (default 6)
- Example prompt: "You've approved 12 drafts recently; 8 of them landed in `concepts/`. Want to add 'new concepts go to concepts/' as a rule in wiki_schema?"
- Accept → auto-append to `wiki_schema.md` (visible diff, user-editable)
- Reject → suppress; next threshold doubles before re-suggesting

**Borrows Claude Code's Rule + Why pattern**: the wiki_schema.md template requires a `**Why:**` line per rule (with example values from the user's conversation history). This makes schema not "rules the AI decided for me" but "rules the AI helped me write down — and I can read why."

**Multi-level merging** (borrows Claude Code's CLAUDE.md tree inheritance):

- `~/.knowlet/wiki_schema.md` — cross-vault personal preferences (optional)
- `vault/.knowlet/wiki_schema.md` — per-vault (primary)
- `vault/<folder>/.knowlet/wiki_schema.md` — per-folder override (opt-in, default off)

**Phase**: Phase 3 (when chat/mining/ingest prompts get redone, as the static-schema layer in [ADR-0024](./0024-ai-assist-envelope.en.md) §3 envelope). Backend prompt-injection logic can ship earlier.

### 3. Adopted feature 2 — `vault/.knowlet/log.md` event log

**Problem**: knowlet has chat history (per session) + mining drafts (per-task review trail), but **no vault-level append-only timeline**.

**Adoption**: add `vault/.knowlet/log.md` (rendered view), backed by a SQLite event stream (`vault.events` table, append-only).

**Recorded events**:

- `note.created` / `note.updated` / `note.deleted` / `note.restored`
- `draft.proposed` / `draft.approved` / `draft.rejected`
- `chat.sediment_committed`
- `source.ingested` (§4)
- `lint.run` (§5)
- `quiz.session.completed`

**Uses**: growth curves / rollback localization / audit / motivational feedback ("you added 7 notes this week").

**Land alongside [ADR-0018 (data durability, pending)](#references)**: the event stream is a natural oracle for schema migration and vault-fixture testing — every schema change should be traceable through the event log.

**Phase**: Same as ADR-0018 (Phase 2 E).

### 4. Adopted feature 3 — Ingest source as a first-class verb

**Problem**: knowlet's URL capture ([ADR-0016](./0016-url-capture.en.md)) is **chat-bound**; the flow is chat → discuss → sediment. But a high-frequency real scenario is **"file first, read later"** — the user sees a great article / paper, drops it into sources, and lets the LLM produce a summary draft.

**Adoption**: add a first-class action `ingest source`. Flow:

```
User drags URL / file / clipping into vault
   → backend runs url_capture / file parsing → lands in vault/sources/<date>-<slug>/
   → LLM auto-generates a summary draft (same pipeline as mining drafts)
   → enters review queue
   → user approves → +1 Note (optionally linked back to the source)
```

**Reuses existing pipeline**:

- url_capture (M7.2 / [ADR-0016](./0016-url-capture.en.md)) for content extraction
- mining drafts ([ADR-0009](./0009-mining-tasks-and-drafts.en.md)) review queue
- [ADR-0013 §1](./0013-knowledge-management-contract.en.md) "user owns" contract auto-satisfied (review queue, no direct write)

**Coexists with the chat path**: the chat-side URL → discuss → sediment flow stays. Two paths complement each other:

- chat path = "I want to read while discussing"
- ingest path = "file it now, deal with it later"

**Phase**: Phase 3 (alongside the review queue UI redo).

### 5. Adopted feature 4 — Lint (LLM cross-page contradictions)

**Problem**: M8.1 structure signals already compute near-duplicates / clusters / orphans / aging. Karpathy's Lint adds a layer M8.1 doesn't: **LLM-driven cross-page contradiction detection** + finding "concepts referenced but with no page of their own."

**Adoption**: extend M8.1 + add a user-triggered `knowlet lint` (CLI) / "Run lint" UI button:

| Signal type | Source | Computation | Surface |
|---|---|---|---|
| near-duplicates / clusters / orphans / aging | M8.1 | embedding cosine + static rules | knowledge-map sidebar |
| **cross-page contradictions** | this ADR | LLM batch pass (sample 50 note pairs per run) | same surface |
| **dangling concept** (`[[Concept]]` link with no target Note) | this ADR | static scan of wikilinks vs notes/ | same surface |
| **inferred missing entity / concept** | this ADR | LLM scans N main notes → extracts entities mentioned ≥ K times | same surface |

**[ADR-0013 §1](./0013-knowledge-management-contract.en.md) still binds**: lint **surfaces information only** — no "auto-fix" / "auto-merge" / "auto-create page" buttons.

**Phase**: Phase 3 (alongside knowledge-map sidebar). The three LLM-driven signals (contradictions / dangling / inferred-missing) ship after the static ambient lands.

### 6. Adopted feature 5 — "Pin good chat answer back to wiki"

**Problem**: Comparison tables / syntheses produced inside chat currently sink into history; you can only retrieve them via whole-session sediment.

**Adoption**: add a turn-level "📌 Pin to vault" action in the chat UI:

- Click → file this assistant turn's content as a mining draft candidate (review queue)
- Reuses the mining draft pipeline; [ADR-0013 §1](./0013-knowledge-management-contract.en.md) auto-satisfied
- Pinned turns get a visual marker in chat history to avoid double-pinning

**Phase**: Phase 3 (chat UI redo).

### 7. Adopted feature 6 — Note frontmatter `status` field

**Problem**: Karpathy's frontmatter design has two fields: `confidence: high/medium/low` (based on cross-validation source count) and `status: active | stub | needs-update | deprecated`. The first **only makes sense when the LLM is the note's author** — knowlet's user-written notes can't take that semantic. The second **maps cleanly onto knowlet's "user-owns" model**.

**Adopt: `status` field** (into Note frontmatter v2 schema):

```yaml
---
title: "RAG vs LLM Wiki"
created: 2026-05-04
status: active   # active | stub | needs-update | deprecated
---
```

**Assignment rules**:

| Value | How it gets set |
|---|---|
| `active` | default; set when user finishes writing / approves draft |
| `stub` | auto-detected: body < 100 chars + no wikilinks. Surfaced in lint as "needs filling" |
| `needs-update` | Linter ([ADR-0023 §5](#5-adopted-feature-4--lint-llm-cross-page-contradictions)) sets this when newer source contradicts the page; **only marks, never edits the body** (per [ADR-0024 §5 B](./0024-ai-assist-envelope.en.md)) |
| `deprecated` | user-set; replaces "delete" in dedupe / refresh flows |

**Explicitly rejected fields**:

- ❌ `confidence: high/medium/low` (LLM-attributed): knowlet notes are **user-written**; the LLM can't assign "how confident I am in this conclusion." If the user wants to mark subjective certainty, use other custom frontmatter — but **no LLM-driven confidence is introduced**.
- ❌ `source_count` (LLM-attributed): same reasoning — in Karpathy's model, source count is an attribute of an LLM compilation product; for knowlet's **user-written** notes, the field is semantically meaningless.

**Phase**: same as [ADR-0018 data durability](#references) (Phase 2 E). Note `schema_version` already shipped at commit `40cfcd0`; `status` is an incremental addition in schema v2.

### 8. Adopted feature 7 — IA recommendation triplet (Editor / Tidy / Reorg advisor)

**Problem**: Karpathy's pattern lets the LLM auto-decide IA (preset entities/concepts/comparisons/maps/...). knowlet can't copy that, but **can** offer "AI proposals" at the file-tree-as-navigation layer.

**Adoption**: three AI roles (full definitions in [ADR-0024 §4](./0024-ai-assist-envelope.en.md)), from finest to coarsest grain:

#### 8.1 Editor advisor — Suggest location for a new note

**Trigger**: at the final step of three entry points — Cmd+N for new note / mining draft approval / ingest source landing as draft.

**Mechanism**: compute embedding from title + first N chars; cosine match against existing notes; take top-K notes' parent folders as candidates.

**UX**:

- Default = the user's currently selected folder in the file tree (matches Obsidian / Bear muscle memory)
- Suggestion appears as a **small chip**: `💡 Suggest papers/llm/ (3 similar notes there)` — click to apply, ignore to keep default
- **No modal dialog**

**Phase**: Phase 3 (alongside chat / mining / ingest UI redo).

#### 8.2 Tidy advisor — Small targeted local IA suggestions

**Trigger**: M8.1 structure signals fire; surface ambient in the knowledge-map sidebar.

**Mechanism**: extend M8.1's signal set:

| Signal | Trigger condition | Proposal | Granularity |
|---|---|---|---|
| **Scattered semantic cluster** | M8.1 detects N notes with cosine > 0.85 across ≥3 folders | "These 5 notes are topically close but scattered across 3 folders. Want to colocate them in a new folder `<suggested name>`?" | ≤7 notes per item |
| **Oversized folder** | single folder note count > 50 | "`papers/` now has 73 notes; want to split by sub-topic? Here are 3 candidate splits" | user picks 1 of 2-3 candidates |
| **Orphan note** | no inbound links + last-edited > 90d + semantically distant from current folder's other notes | "`<note>` looks out of place in `<folder>` (semantic outlier); move it?" | single note per item |
| **Dangling concept** | `[[Foo]]` link with no target Note | "You linked to `[[Foo]]` 5 times but never created the page. Want to create it? Choose location: ..." | creates one new note |

**Constraints**:

- Each proposal item ≤ 7 notes
- All surfaced as info / chips; never proactively modal
- Always through review queue; **never an "Apply all" button**

**Phase**: Phase 3 (alongside knowledge-map sidebar).

#### 8.3 Reorg planner — User-initiated whole-tree reorg

**Trigger**: explicit user command `knowlet reorg <scope>` (CLI) / "Tidy this folder" UI button. **Rare operation** (analogous to `git rebase -i`), not a daily feature.

**Typical scenarios**:

- Migrating from Bear / Notion exports — dumped into knowlet without structure
- After 1-2 years of use, wanting to switch organization style (from by-date to by-topic)
- vault > 200 notes still flat; wants hierarchy

**5 hard constraints** (any missing ⇒ don't ship):

1. **Always plan-then-apply** — proposal is a **preview** (diff view: original tree on left, proposed on right), zero file moves yet. In preview state, user: accept-all / reject-all / toggle individual items
2. **Auto-snapshot before applying** — one-command rollback via `knowlet vault restore-snapshot pre-tree-reorg`
3. **Reverse manifest** — every move records its source location to `reorg-<ts>.json`, so even after the snapshot is gone, `knowlet reorg undo <id>` reverses it
4. **MUST read wiki_schema.md** — if the schema says "I prefer flat" or "organize by project not topic," the AI MUST honor it
5. **Default scope = subfolder, not whole vault** — "reorg this folder" is much safer than "reorg whole vault"; whole-vault is an explicit opt-in

**Phase**: post-Phase 3 (after Phase 1/2 knowledge base baseline + data durability stabilize).

## What we explicitly do NOT adopt

### A. ❌ "LLM fully owns the wiki"

**Conflict**: violates [ADR-0013 §1](./0013-knowledge-management-contract.en.md) "user owns; LLM doesn't modify vault IA on its own."

knowlet's whole reason to exist is that this pattern produces "AI sediment" the user gradually loses trust in — when a user looks at a note and can't tell whether they wrote it or the LLM did, why it's organized that way, or what the LLM changed in the last maintenance pass, the knowledge base's credibility collapses.

### B. ❌ "Two windows side-by-side (Claude Code + Obsidian)"

**Conflict**: violates [ADR-0008](./0008-cli-parity-discipline.en.md) + [ADR-0021](./0021-knowledge-base-first-roadmap.en.md) "integrated experience is core value."

knowlet chose React over staying CLI-only specifically because PKM users expect an "install-and-use" integrated app. Splitting chat / editing / browsing / mining across two windows betrays that judgment.

### C. ❌ "Pattern, not product"

**Conflict**: Karpathy's gist targets users who can vibe-code; knowlet targets PKM users at the Bear / Obsidian level. Our value proposition is a working product, not an agent-facing brief.

### D. ❌ frontmatter `confidence: high/medium/low` (LLM-attributed)

See §7. The LLM cannot assign a "confidence" semantic to a user-written note.

### E. ❌ Preset IA (`entities/` / `concepts/` / `comparisons/` / `maps/`)

knowlet's AI roles only use folders the user already has, may suggest creating one new folder (with approval), but **never recommend such preset structures**. See [ADR-0024 §5 F](./0024-ai-assist-envelope.en.md).

### F. ❌ AI auto-rewrites Note bodies / auto-move / auto-archive / auto-merge

See [ADR-0024 §5 A-C](./0024-ai-assist-envelope.en.md). Even when the Linter detects a newer source contradicting a note, it can only mark `status: needs-update` (§7) — **never edit the body**.

### G. ❌ Direct integration of [qmd](https://github.com/tobi/qmd)

**Reasons** (precise replacement for the previous vague "we already have FTS + vec" wording):

1. **Cross-language**: qmd is Node.js, knowlet is Python; adds IPC latency and failure surface
2. **Forced ~2GB local models**: knowlet lets the user **configure** the embedding backend (dummy / BGE / OpenAI / local Ollama); install footprint stays flexible
3. **Architecture direction mismatch**: qmd is a standalone search engine; knowlet is a PKM app where search is a feature; integration direction doesn't compose cleanly
4. **No "scale-up path" equivalent**: qmd in Karpathy's pattern is "the optional upgrade once index.md isn't enough"; knowlet has FTS + vec from day 1

**But adopt its design**: RRF fusion / LLM rerank / query expansion / smart chunking — 4 design points reimplemented in our Python stack as Phase 2 backend polish ("retrieval quality v2"). Triggered by dogfood signal that retrieval quality is the bottleneck. See [ADR-0024 §"Out of scope"](./0024-ai-assist-envelope.en.md).

## Consequences

### Positive

- 7 actionable additions to the roadmap (none conflict with existing ADRs; §8's three advisors are concrete instantiations of [ADR-0024](./0024-ai-assist-envelope.en.md))
- Sharpened positioning language — README uses the CODE-framework comparison to make the root principle concrete (§1.1)
- Forecloses future discussions drifting back to "let the LLM manage the vault" (technically possible, but a step backward as a product)
- The 7 features are spread across Phase 2 E / Phase 3 / post-Phase 3, so they don't block the Phase 1 critical path

### Negative

- ~3-4 weeks of total work, spread across Phase 2 E / Phase 3
- Three new concepts (`wiki_schema.md` / `log.md` / `status` frontmatter) add some doc surface area
- §8's three advisors depend on [ADR-0024](./0024-ai-assist-envelope.en.md)'s envelope architecture landing first

### Mitigations

- `wiki_schema.md` defaults to empty; users who don't write one still get a working app (graceful degradation)
- `log.md` is auto-generated by the backend; no user action required
- `status` defaults to `active`; old notes auto-migrate

### Out of scope

- **LLM-driven schema auto-evolution** (LLM directly editing `wiki_schema.md`): this ADR adopts the "propose → user approves" co-evolution mechanism only (§2); no door for "AI auto-edits schema files"
- **Cross-vault wiki federation**: violates ADR-0003's "single user, single vault" assumption — never
- **Direct integration of qmd**: see §G; but adopt its 4 design points (retrieval quality v2, Phase 2 candidate)
- **Generating Marp slides / Obsidian Dataview compatibility**: out of product scope
- **frontmatter `confidence` / `source_count`** (LLM-attributed): see §D / §7
- **Whole-tree reorg as LLM-initiated action**: see §F; only user-initiated Reorg planner (§8.3) is in scope

## References

- [Karpathy LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — the comparison subject
- [ADR-0008](./0008-cli-parity-discipline.en.md) — Integrated experience / single source
- [ADR-0009](./0009-mining-tasks-and-drafts.en.md) — Mining drafts review queue (reused by §4 / §6 / §8)
- [ADR-0013](./0013-knowledge-management-contract.en.md) — "User owns, LLM proposes" contract
- [ADR-0014](./0014-note-quiz-mode.en.md) — Active recall (knowlet-specific, not in Karpathy's scope)
- [ADR-0016](./0016-url-capture.en.md) — URL capture (§4 extends it)
- [ADR-0021](./0021-knowledge-base-first-roadmap.en.md) — Phase plan
- [ADR-0024](./0024-ai-assist-envelope.en.md) — AI-assist envelope + system prompt architecture (§8's three advisors are its concrete instantiations)
- ADR-0018 data durability (pending) — `log.md` event stream + `status` field fall in its scope
- Feishu wiki article *"Karpathy's LLM Knowledge Base: Compile Your Personal Wiki with an LLM"* (2026-04) — the expansion material referenced in §1.1 / §2 co-evolution / §7 frontmatter / §8 / §G qmd
