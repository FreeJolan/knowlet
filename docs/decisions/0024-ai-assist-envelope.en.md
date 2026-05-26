# 0024 — AI-assist envelope + system prompt layered architecture

> **English** | [中文](./0024-ai-assist-envelope.md)

- Status: Proposed
- Date: 2026-05-07

## Context

[ADR-0013 §1](./0013-knowledge-management-contract.en.md) locked in the "user owns, LLM proposes" root principle, but it doesn't concretely answer two things:

1. **Which knowledge-base maintenance tasks should AI help with?** When you decompose a human-maintained vault into ~13 categories of work, which can AI replace, which can AI only propose, and which should AI not touch at all?
2. **How should the system prompt for each AI task be assembled?** The current `CHAT_SYSTEM_PROMPT_BASE` + user_profile (two layers) isn't enough — different tasks (chat / mining / lint / reorg) need different context, but the layering should be unified.

This ADR provides a **framing** for both questions, to be used as a **gate criterion** for all future AI-feature development:

- Any new AI-feature proposal must locate itself on the §1 work-category table + §2 maintenance-task table
- Any new AI task's prompt must be assembled per the §3 envelope structure
- §4 lists 7 AI roles with clear boundaries; new roles require a high-bar ADR decision

The features adopted in [ADR-0023](./0023-llm-wiki-comparison-and-takeaways.en.md) (wiki_schema injection / Lint / Editor advisor / Tidy advisor / Reorg planner) are **instantiations** of this framework; this ADR is their shared architectural foundation.

## Decision

### 1. Work-category lens (decides whether AI touches it)

Every KB-maintenance task fits into one of three categories. **Category determines the AI's role**:

| Category | Meaning | AI role | Cost if wrong |
|---|---|---|---|
| **mech** | programmable / repetitive / no creative judgment | **replace** (auto, with audit trail) | low, redo-able |
| **hybrid** | requires judgment but has a standard answer set | **propose** (candidate → review queue → user approves) | medium, review queue catches errors |
| **creative** | user's intellectual product / expression | **don't touch** (or only when user explicitly invokes "write for me" mode) | very high, breaks user's cognitive ownership |

**Root rule**: AI **never autonomously performs** `creative` work. `mech` work is auto-done with audit trail (per [ADR-0023 §3](./0023-llm-wiki-comparison-and-takeaways.en.md) `vault.events`). `hybrid` work flows through the existing review queue ([ADR-0009](./0009-mining-tasks-and-drafts.en.md)).

### 2. 13 maintenance tasks mapped to current state

A user-perspective inventory of all KB-maintenance work:

```
Daily
  1. Capture     grab content (URL / thought / clipping)
  2. Write       write notes ← user's core creative act
  3. Lookup      query old notes
Inbox processing (weekly / monthly)
  4. Triage      process "captured but not yet processed"
  5. Tidy        relocate misplaced notes
  6. Dedupe      merge duplicates / synonymous concepts
  7. Refresh     update old notes when new info arrives ← creative; only suggest
  8. Discover    notice "I keep referencing X but never wrote it"
  9. Resolve     flag contradictions (newer source vs older note)
  10. Trim       deprecate / clear deadwood
Project-level (yearly / major transitions)
  11. Reorg      bulk tree reorganization
  12. Migrate    cross-tool migration
  13. Archive    archive
```

Tagged by category + mapped to knowlet:

| # | Task | Category | knowlet status | What's missing / which ADR covers |
|---|---|---|---|---|
| 1 | Capture | mech | URL capture (M7.2) | + ingest as first-class verb ([ADR-0023 §4](./0023-llm-wiki-comparison-and-takeaways.en.md)) |
| 2 | **Write** | **creative** | CodeMirror editor | **AI doesn't author note bodies** |
| 3 | Lookup | mech | FTS + vec index | + retrieval-quality v2 (RRF / rerank / query expansion / smart chunking, see §"Out of scope") |
| 4 | Triage | hybrid | mining drafts queue ([ADR-0009](./0009-mining-tasks-and-drafts.en.md)) | + ingest pipeline routes drafts here too |
| 5 | Tidy | hybrid | — | Editor advisor + Tidy advisor ([ADR-0023 §8](./0023-llm-wiki-comparison-and-takeaways.en.md)) |
| 6 | Dedupe | hybrid | M8.1 near-duplicates (backend) | UI sidebar surface (Phase 3) |
| 7 | **Refresh** | **creative** | — | **Don't rewrite**; lint marks `status: needs-update` only ([ADR-0023 §5](./0023-llm-wiki-comparison-and-takeaways.en.md)) |
| 8 | Discover | hybrid | — | dangling concept + missing entity ([ADR-0023 §5](./0023-llm-wiki-comparison-and-takeaways.en.md)) |
| 9 | Resolve | hybrid | — | cross-page contradictions ([ADR-0023 §5](./0023-llm-wiki-comparison-and-takeaways.en.md)) |
| 10 | Trim | hybrid | aging signal (M8.1) | UI surface + suggest deprecate (don't delete) |
| 11 | Reorg | hybrid | — | Reorg planner ([ADR-0023 §8](./0023-llm-wiki-comparison-and-takeaways.en.md), user-initiated, 5 hard constraints) |
| 12 | Migrate | mech | partial vault import | Phase 2 E ([ADR-0018](./0018-data-durability.en.md), pending) |
| 13 | Archive | mech | trash + soft delete | OK |

**This table is the gate**: every new AI-feature RFC must locate itself on a row and confirm the category. `creative` rows are auto-rejected.

### 3. System prompt layered architecture (borrowing mature agents)

Mature agents such as Codex and Claude Code have validated a set of stable prompt-engineering patterns. **knowlet borrows those design patterns directly rather than reinventing them**; the runtime default is no longer tied to Claude.

#### 3.1 Envelope: 7-layer structure

```
<knowlet-system>
  Per-action base instructions (templates in code: chat / mining / ingest / lint / editor-advisor / tidy-advisor / reorg-planner)
</knowlet-system>

<user-profile src="vault/.knowlet/user_profile.md">
  "Who I am" (identity layer, per ADR-0013)
</user-profile>

<wiki-schema src="vault/.knowlet/wiki_schema.md">
  "How this vault is written" (conventions layer, per ADR-0023 §2)
</wiki-schema>

<vault-shape>
  total_notes: 247
  top_folders: [{name: papers/, count: 73}, ...]
  depth: 3
</vault-shape>

<recent-activity window="7d" src="vault.events">
  - 2026-05-06 note.created "RAG vs LLM Wiki"
  - 2026-05-05 draft.approved "Karpathy LLM Wiki"
  ...
</recent-activity>

<task type="editor-advisor" action="suggest_location">
  input: {title: "Mintlify virtual filesystem", body_first_200_chars: "..."}
  similar_notes: [...]
  candidate_folders: [...]
</task>

<rules>
  - Always default to the user's currently selected folder.
  - Output MUST be JSON: {"recommended_folder": "...", "reason": "...", "confidence": 0.0-1.0}
  - If confidence < 0.5, return null (don't show suggestion).
</rules>

<examples>
  ... 1-2 concrete output examples ...
</examples>
```

#### 3.2 Three layer types

| Type | Source | Dynamic? | Who assembles |
|---|---|---|---|
| **Static layers** | `user_profile.md` / `wiki_schema.md` | edited by user | cached on vault load |
| **Derived layers** | `vault_shape` / `recent_activity` | auto-derived | backend, from `vault.events` + index |
| **Task layers** | `<task>` / `<payload>` / `<rules>` / `<examples>` | per-call | caller |

#### 3.3 Lazy loading

Not every AI task needs all 7 layers. Per-role required / optional / skip mapping:

| Role | system | profile | schema | shape | activity | task | rules | examples |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| Chat companion | ✅ | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ |
| Capture extractor | ✅ | — | ✅ | — | — | ✅ | ✅ | ✅ |
| Editor advisor | ✅ | — | ✅ | ✅ | — | ✅ | ✅ | ✅ |
| Search booster | ✅ | — | — | — | — | ✅ | ✅ | — |
| Linter | ✅ | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Tidy advisor | ✅ | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Reorg planner | ✅ | — | ✅ | ✅ | — | ✅ | ✅ | ✅ |

`profile` is mostly chat-only (affects conversational tone); `activity` is mostly lint/tidy (knows what user's been focused on).

#### 3.4 Eight specific mature-agent design patterns to adopt

| Pattern | How mature agents do it | knowlet adoption |
|---|---|---|
| **Tagged section delimiters** | `<system-reminder>` / `<example>` etc. with stable anchors | All 7 envelope layers use explicit tags |
| **Multi-level schema merging** | global agent rules + project `AGENTS.md` + per-folder rules | `~/.knowlet/wiki_schema.md` (cross-vault) + `vault/.knowlet/wiki_schema.md` (per-vault); 3rd level optional |
| **Rule + Why pattern** | Each agent rule includes "why this is so" | `wiki_schema.md` template requires `**Why:**` line per rule |
| **Lazy tool loading** | `ToolSearch` loads tool schemas on demand | knowlet vault tools (create_card / start_quiz / list_drafts / ...) injected per active role |
| **Periodic system reminders** | State nudges | "you have 12 pending drafts" injected when entering review queue; "last lint 14 days ago" when entering lint |
| **`<example>` blocks** | Critical behaviors include 1-2 examples | Structured-output roles (editor / linter / tidy / reorg) MUST include 1-2 examples |
| **Slash command routing** | `/loop` `/init` `/review` each carry a tailored prompt | knowlet chat REPL `:user` `:lint` `:quiz` etc.; each slash triggers a role and **auto-assembles its envelope** |
| **Absolute language for rules** | "ALWAYS X" / "NEVER Y" | knowlet ADR-0013 §1 reads as strong language in prompts |

**Special norm** (borrowed from mature agent behavior, not a prompt rule): **state your reasoning in one sentence before acting**. Editor advisor announces "based on 5 RAG-related notes already in `concepts/rag/`, suggest there"; reorg planner says "detected 23 notes scattered across 4 folders sharing topic X." **This lets the user dialogue with the reasoning** — that's how trust-building gets built into the prompt.

### 4. Seven AI roles

knowlet's AI splits into 7 non-overlapping roles. Each has well-defined inputs / outputs / invocation point / work category:

| Role | Category | Input | Output | Invoked from | Status |
|---|---|---|---|---|---|
| **Chat companion** | hybrid | user message + chat history | answer + tool-call trace | chat focus mode / chat REPL | exists, Phase 3 redo |
| **Capture extractor** | mech | URL / file / clipping | source summary → drafts queue | URL paste / drag-drop / `:capture` | partial via M7.2; ingest upgrade per [ADR-0023 §4](./0023-llm-wiki-comparison-and-takeaways.en.md) |
| **Editor advisor** | hybrid | title + first N chars + vault context | folder / tag / title candidates (JSON, with confidence) | new note / draft approval chip | **new**, Phase 3 |
| **Search booster** | mech | query + top-K candidates | rerank + synthesis | chat-time vault retrieval | exists (basic); v2 see §"Out of scope" |
| **Linter** | hybrid | full vault scan | contradictions / dangling concept / missing entity report | `knowlet lint` / weekly digest | **new**, [ADR-0023 §5](./0023-llm-wiki-comparison-and-takeaways.en.md), Phase 3 |
| **Tidy advisor** | hybrid | M8.1 signals + vault shape | small targeted IA suggestions (≤7 notes per item) | knowledge-map sidebar ambient | **new**, [ADR-0023 §8](./0023-llm-wiki-comparison-and-takeaways.en.md), Phase 3 |
| **Reorg planner** | hybrid | user-initiated + scope | sub-tree reorg plan (mandatory preview + snapshot + manifest) | `knowlet reorg <scope>` explicit command | **new**, [ADR-0023 §8](./0023-llm-wiki-comparison-and-takeaways.en.md), post-Phase 3 |

**Seven roles is the boundary**. New AI-capability proposals must map to an existing role, or argue for an 8th (high-bar ADR), not be added ad-hoc.

## §5 Forbidden — what AI must NOT do

`creative` work is never autonomously performed by AI. Concrete blacklist:

### A. ❌ Note ghostwriter — AI writes note bodies for the user

**Conflict**: violates [ADR-0013 §1](./0013-knowledge-management-contract.en.md) "user owns." Note bodies are the user's **intellectual product**; AI doesn't ghostwrite.

**Exception**: in chat the user explicitly says "draft this idea as a note" → AI outputs a **draft** into the review queue; only after approval does it land in the vault. That's a hybrid path, not a creative replacement.

### B. ❌ Note rewriter — AI auto-edits existing note content

**Conflict**: violates [ADR-0013 §1](./0013-knowledge-management-contract.en.md). Even if AI detects "newer source contradicts this page," it can **only mark via lint** (`status: needs-update`), never edit the body.

**Correct path**: Linter produces a report → user opens and decides to edit themselves → user commits.

### C. ❌ Auto-move / Auto-archive / Auto-merge files

**Conflict**: violates [ADR-0013 §1](./0013-knowledge-management-contract.en.md). Any file-level operation (move / archive / merge / delete) **must go through review queue or user-initiated plan-preview**.

**No such toggle exists**: don't ship a "auto mode" setting that lets users opt into auto-move. That's handing IA control to the LLM.

### D. ❌ Auto-tag / Auto-alias

**Conflict**: tags / aliases are **user semantic judgments**. AI can suggest tags, but cannot write to frontmatter directly.

**Correct path**: Editor advisor proposes candidates → user clicks chip to accept → only then written.

### E. ❌ frontmatter `confidence` field (LLM-attributed version)

[ADR-0023 §7](./0023-llm-wiki-comparison-and-takeaways.en.md) explicitly rejects Karpathy's `confidence: high/medium/low` field (based on LLM-synthesized source count). Reason: knowlet notes are **user-written**; confidence isn't an attribute the LLM can assign.

**Reserved**: if the user **themselves** wants to mark "how confident I am in this conclusion," they can extend [ADR-0023 §7 status](./0023-llm-wiki-comparison-and-takeaways.en.md) or use custom frontmatter, **but no LLM-driven confidence is introduced**.

### F. ❌ Preset IA (`entities/` / `concepts/` / `comparisons/` / `maps/`)

**Conflict**: Karpathy's preset directory structure is the LLM making IA decisions. All knowlet AI roles **only use folders the user already has**, and may suggest creating one new folder (with approval) — **never recommend "you should have an entities/ directory"** or similar preset structure.

## Consequences

### Positive

- **Unified gate criterion**: new AI features can no longer be added ad-hoc; must locate themselves on §1 / §2 tables
- **Unified prompt architecture**: no more per-task prompt assembly hacks; the 7-layer envelope is the single assembly path
- **Clear AI role boundaries**: 7 roles don't overlap; implementation can't accidentally cross
- **Borrowed from mature agents**: don't reinvent prompt engineering's mature patterns

### Negative

- Implementation effort is high: 7 roles × 7 envelope layers × per-role prompt templates + lazy loader = ~3-5 weeks of backend work
- New concepts (envelope / role / layer) add documentation surface

### Mitigations

- Phased rollout: Phase 0/1 already cover Chat companion + Capture extractor + Search booster (basic versions); Phase 3 redo is the rewrite per this architecture
- Doc burden: this ADR is a **gate reference**, not required reading for every PR; only required when proposing new AI features

### Out of scope

- **Retrieval quality v2** (RRF fusion / LLM rerank / query expansion / smart chunking)
  Borrows the 4 design points from [qmd](https://github.com/tobi/qmd), reimplemented in our Python stack. **Don't adopt qmd directly** (cross-language / forced 2GB models / architecture mismatch). Workload ~3-4 days, Phase 2 backend polish candidate, gated on dogfood signal that retrieval quality is a bottleneck.
- **An 8th AI role**: this ADR locks 7 roles. New role proposals must be high-bar ADR decisions, not ad-hoc additions
- **Per-folder `wiki_schema.md` overrides**: mature agents support directory-tree rule merging; knowlet defaults to global + vault (2 levels); per-folder is opt-in only when user actively requests it
- **AI-rewrite-Note-bodies toggle**: even with a settings opt-in, this is forbidden; `creative` work has no back doors

## References

- [Karpathy LLM Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) — referenced indirectly (the comparison subject is in ADR-0023)
- [ADR-0009](./0009-mining-tasks-and-drafts.en.md) — Mining drafts review queue (the mechanism for §1 hybrid category)
- [ADR-0013](./0013-knowledge-management-contract.en.md) — "User owns, LLM proposes" root principle
- [ADR-0023](./0023-llm-wiki-comparison-and-takeaways.en.md) — LLM Wiki comparison; this ADR is its architectural foundation
- ADR-0018 data durability (pending) — `vault.events` stream is the source of §3 derived layers
- Mature agent prompt engineering (the borrowed reference; no single public spec doc, derived from Codex / Claude Code behavior)
