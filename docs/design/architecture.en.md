# Architecture Design

> **English** | [中文](./architecture.md)

> Living doc. Describes Knowlet's current architectural intent and evolves with implementation. Decision sources are in [`../decisions/`](../decisions/); this document is their architectural unfolding.

## 1. Four-Layer Structure

Knowlet stacks four layers, single-direction dependency:

| Layer | Responsibility | Notes |
|---|---|---|
| **Storage** | Vault entities (Markdown / JSON) + `.knowlet/` derived data | See [ADR-0006](../decisions/0006-storage-and-sync.en.md) |
| **Domain** | Note / Card / Mistake / Source — four core entities | See below |
| **Capability** | Ingest / Distill / Recall / Quiz | All implemented as atomic capabilities + LLM orchestration; see [ADR-0004](../decisions/0004-ai-compose-code-execute.en.md) |
| **Interaction** | Embedded chat / settings UI / mobile PWA / future MCP server | See [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.en.md), [ADR-0005](../decisions/0005-llm-integration-strategy.en.md) |

Capability-layer modules don't depend on each other directly; they collaborate through entities exposed by the domain layer.

## 2. Four Domain Entities

```
Note (note)             Markdown document    User-led editing
Card (card)             JSON record          UI-led editing; SRS state in non-frontmatter fields
Mistake                 JSON record          Machine-maintained
Source (info source)    JSON record          Mostly machine, optional user description
```

Relationships:

- Note is the destination of knowledge; card review / mistake diagnosis / intelligence sedimentation all flow into Notes
- Card is derived from Notes or independently created, with its own SRS state
- Mistake is produced by failed Card reviews, reverse-weights Cards and tags Notes
- Source is external input; products first become candidate Notes / Cards, accepted into the library after review

Storage formats and directory layout: see [ADR-0006](../decisions/0006-storage-and-sync.en.md) "Entity Storage Format" section.

## 3. Produce-Consume Loop

Four core Paths, **Path 0 is the main line** (corresponding to the ADR-0003 wedge):

```
                ┌──────────────────────────────────┐
                │      Knowledge Base (Vault)      │
                │   notes / cards / mistakes /     │
                │   sources / users                │
                └──────────────────────────────────┘
                  ▲          ▲          ▲          │
        Path 1    │  Path 2  │  Path 3  │      Path 0 (main)
   Active write   │ OCR/import│ Knowledge│  Consumption-driven
                  │          │ mining   │     production
                  │          │  task    │
                  │          │          │          ▼
                  │          │          │   ┌──────────────┐
                  │          │          │   │    Cards     │
                  │          │          │   └──────────────┘
                  │          │          │          │
                  │          │          │          ▼
                  │          │          │      Review
                  │          │          │          │
                  │          │          │          ▼
                  │          │          │   ┌──────────────┐
                  └──────────┴──────────┴───│   Mistakes   │
                          Path 4 feedback   └──────────────┘
```

### Path 0 — Consumption-Driven Production (main line)

Any question / reading / discussion content gets sedimented automatically. Sub-flow:

```
User asks in knowlet chat
   │
   ▼
LLM-driven retrieval (LLM auto-fetches from vault)
   │
   ├─ Hit → Answer based on local content + general knowledge
   │           └─ AI draft sedimentation candidate (optional) → user review → Note saved
   │
   └─ Miss + needs external info → LLM provider's native web_search
                                    ↓
                                  Answer based on external + local
                                    └─ AI draft candidate → user review → Note saved
```

**Key point**: the LLM **automatically** invokes the knowledge-base retrieval tool before each answer, rather than waiting for the user to actively search. This is the concrete embodiment of [ADR-0004](../decisions/0004-ai-compose-code-execute.en.md) "atomic capability + LLM orchestration" — retrieval is a tool, the LLM decides when to call it.

### Path 1 — Active Write

User directly writes a Note or Card in knowlet. The most basic input path; doesn't depend on AI.

### Path 2 — OCR / Import

Scanning books / screenshots / clipping / Markdown bulk import — produces Note or Card candidates, processed via AI draft and saved.

### Path 3 — Knowledge Mining Tasks

User configures a scheduled task (frequency + Prompt + source constraints). At the scheduled time:

```
Trigger (scheduled / manual)
   ▼
LLM executes via tool-call:
   - LLM provider's native web_search
   - Fetching is transparent and traceable (sites visited, search terms used)
   ▼
LLM organizes → multiple atomic Notes + index Note
   ▼
Enters "pending review"
   ▼
User reviews (skim, prune, accept) → saved
```

See [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.en.md) Scenario B and [ADR-0005](../decisions/0005-llm-integration-strategy.en.md).

### Path 4 — Mistake Feedback

Mistakes are first-class citizens:

```yaml
# Core fields of a Mistake entity
linked_card: cards/01HYYY.json
linked_note: notes/01HXXX-...md
error_type: factual | conceptual | confusion | forgotten
frequency: 7
last_failed_at: 2026-04-29T10:23:00Z
ai_diagnosis: |
  User repeatedly errors on closed-interval loop conditions...
```

Mistakes drive three things:

1. **Weighted question generation**: SRS algorithm overlays mistake weights (FSRS difficulty / stability fine-tuning)
2. **Blind-spot map**: visualizes "weakest areas"; data aggregated from `.knowlet/profile/<domain>_analytics.json`
3. **Feedback to knowledge base**: a Card repeatedly missed → notes are not well-written → auto-tag Note for improvement

## 4. Cross-Scenario Context Accumulation

One of ADR-0003's differentiators: multiple use scenarios **share one user context**, with AI accumulating understanding across them.

```
                ┌──────────────────────────────────────┐
                │  User context (users/me.md + .knowlet/) │
                │  Goals / preferences / mistake patterns │
                │  Vocabulary mastery                     │
                └──────────────────────────────────────┘
                 ▲          ▲          ▲          │
                 │          │          │          ▼
          Scenario A  Scenario B  Scenario C  Injected to all
          Paper      Information  Learning    AI interactions
          reading    flow mining  scenario
          (no SRS)   (no SRS)     (SRS-led)
```

Cross-scenario signal flow (minimum set in stage 1):

| Source | Flow | Effect |
|---|---|---|
| Repeated mistakes on a card type | User context "frequent errors" | Auto-checked during writing assessment |
| Vocabulary encountered in reading / discussion | Promoted to vocabulary SRS | Enters review queue |
| Writing reveals weak expressions | Recommend related vocabulary / sentence patterns | Added to learning targets |

More complex accumulation (mastery levels reverse-influence assessment judgments) deferred to stage 2.

## 5. AI Compose + Code Execute

[ADR-0004](../decisions/0004-ai-compose-code-execute.en.md) is the engineering foundation of this architecture. All cross-feature workflows are orchestrated by the LLM via tool-calls; code only exposes atomic capabilities.

Expected core atomic capabilities in stage 1 (non-exhaustive):

```
search_notes(query, top_k)         Retrieve from Vault
get_note(id)                       Read a Note
create_note(content, metadata)     Create a Note
update_note(id, patch)             Modify a Note
link_notes(a, b, relation)         Establish a link
delete_note(id)                    Delete (via second gate)
create_card(front, back, ...)      Create a card
review_card(id, rating)            Submit review rating
get_user_profile()                 Read user context
update_user_profile(patch)         Update user context
run_mining_task(task_id)           Execute knowledge mining task
fetch_url(url)                     Fetch URL (via LLM provider's native search)
...
```

Each tool satisfies the four constraints of ADR-0004: reversible / second gate / one-sentence granularity / structured returns.

## 6. Knowledge Aging Mechanism

Path 3 fetched content can expire (especially technical docs / framework articles). Need **TTL + revalidation**:

- Source entity tags expiration in `revalidate_after`
- On expiration, trigger re-fetch and diff
- Conflicting / outdated content highlighted in UI to avoid "zombie knowledge"

## 7. Dual-Loop Self-Evolution

- **Inner loop (high frequency)**: review → mistakes → SRS weighting → Note tagged for improvement
- **Outer loop (low frequency)**: periodic vault scans identifying contradictions / outdated / orphaned notes, pushed to user (triggered by user or AI orchestration)

## 8. Key Extension Points

- **MD / JSON foundation** → stage 2 graph visualization built on Frontmatter / link fields
- **Atomic capabilities = MCP tool schema** → stage 2 naturally becomes an MCP server, exposed across AI tools
- **Clear domain entity boundaries** → new capabilities (e.g., new Source types) don't crowd existing entities
- **`.knowlet/` is purely derived** → rebuild mechanism guarantees zero mental overhead about derived data

## TODO

- Upgrade ASCII diagrams to Mermaid (better cross-renderer display)
- Migrate the two whiteboards from the Lark draft (overall loop, Path 0 sub-graph) to in-repo visualizations
