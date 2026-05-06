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

[ADR-0013 §1](./0013-knowledge-management-contract.en.md) already mandates "no auto-merge / no auto-archive / no LLM-driven IA changes." This ADR elevates the rule to **knowlet's first-line positioning identity**:

- ✅ knowlet: user owns notes; LLM produces **candidates** (drafts / summaries / link suggestions); everything that enters the vault flows through a review pipeline
- ❌ Karpathy LLM Wiki: LLM **fully owns** the wiki; user is reader + director only

These aren't ranked good vs bad — they make different assumptions about **trust in knowledge sediment**:

- Karpathy's pattern assumes single user + single topic + strong schema constraints + short-to-medium-term focus, where LLM maintenance is a net positive.
- knowlet's pattern assumes multi-year / multi-domain / multi-LLM-backend usage, where **the user's need for per-note explainability, trustworthiness, and controllability outweighs maintenance-cost savings**.

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

**Phase**: Phase 3 (when chat/mining/ingest prompts get redone). Backend prompt-injection logic can ship earlier.

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

## What we explicitly do NOT adopt

### A. ❌ "LLM fully owns the wiki"

**Conflict**: violates [ADR-0013 §1](./0013-knowledge-management-contract.en.md) "user owns; LLM doesn't modify vault IA on its own."

knowlet's whole reason to exist is that this pattern produces "AI sediment" the user gradually loses trust in — when a user looks at a note and can't tell whether they wrote it or the LLM did, why it's organized that way, or what the LLM changed in the last maintenance pass, the knowledge base's credibility collapses.

### B. ❌ "Two windows side-by-side (Claude Code + Obsidian)"

**Conflict**: violates [ADR-0008](./0008-cli-parity-discipline.en.md) + [ADR-0021](./0021-knowledge-base-first-roadmap.en.md) "integrated experience is core value."

knowlet chose React over staying CLI-only specifically because PKM users expect an "install-and-use" integrated app. Splitting chat / editing / browsing / mining across two windows betrays that judgment.

### C. ❌ "Pattern, not product"

**Conflict**: Karpathy's gist targets users who can vibe-code; knowlet targets PKM users at the Bear / Obsidian level. Our value proposition is a working product, not an agent-facing brief.

## Consequences

### Positive

- 5 actionable additions to the roadmap (none conflict with existing ADRs)
- Sharpened positioning language — README uses this comparison to make the root principle concrete
- Forecloses future discussions drifting back to "let the LLM manage the vault" (technically possible, but a step backward as a product)

### Negative

- ~2-3 weeks of total work, spread across Phase 2 E / Phase 3
- Two new concepts (`wiki_schema.md` / `log.md`) add some doc surface area

### Mitigations

- `wiki_schema.md` defaults to empty; users who don't write one still get a working app (graceful degradation)
- `log.md` is auto-generated by the backend; no user action required

### Out of scope

- **LLM-driven schema auto-evolution** (the LLM proposing edits to `wiki_schema.md` after you've ingested 30 sources): goes into §B not-adopted, pending dogfood signal
- **Cross-vault wiki federation** (linking multiple vaults' wikis): violates ADR-0003's "single user, single vault" assumption — never
- **Integrating Karpathy's recommended [`qmd`](https://github.com/tobi/qmd) local search engine**: knowlet already has FTS + vector index (`core/index/`); no new dep
- **Generating Marp slides / Obsidian Dataview compatibility**: out of product scope

## References

- [Karpathy LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — the comparison subject
- [ADR-0008](./0008-cli-parity-discipline.en.md) — Integrated experience / single source
- [ADR-0009](./0009-mining-tasks-and-drafts.en.md) — Mining drafts review queue (reused by §4 / §6)
- [ADR-0013](./0013-knowledge-management-contract.en.md) — "User owns, LLM proposes" contract
- [ADR-0014](./0014-note-quiz-mode.en.md) — Active recall (knowlet-specific, not in Karpathy's scope)
- [ADR-0016](./0016-url-capture.en.md) — URL capture (§4 extends it)
- [ADR-0021](./0021-knowledge-base-first-roadmap.en.md) — Phase plan
- ADR-0018 data durability (pending) — `log.md` event stream falls in its scope
