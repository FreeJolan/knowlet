# Architecture diagrams

> **English** | [中文](./architecture-diagrams.md)

> Living document. Both diagrams reflect the 2026-05-02 shape (M6 + ADR-0013/0014). The technical diagram describes code / modules / data flow; the product diagram describes user-facing lanes / concepts / surfaces. Read them side by side.

---

## 1. Technical architecture

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                                  USER INTERFACES                                  │
│  ┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐  │
│  │  CLI (terminal)     │    │  Web SPA            │    │  Future: Tauri      │  │
│  │  Typer · Rich       │    │  Alpine · Tailwind  │    │  desktop shell      │  │
│  │  REPL chat (`:`)    │    │  Split.js · marked  │    │  (M9+, same         │  │
│  │                     │    │                     │    │  web/static)        │  │
│  └──────────┬──────────┘    └──────────┬──────────┘    └─────────────────────┘  │
└─────────────┼──────────────────────────┼──────────────────────────────────────────┘
              │ direct import             │ HTTP / SSE
              ▼                           ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│              ADAPTERS (thin shells · ADR-0008 parity)                              │
│                                                                                    │
│  ┌──────────────────────────┐    ┌──────────────────────────────────────────┐    │
│  │  knowlet/cli/             │    │  knowlet/web/server.py (FastAPI)         │    │
│  │  · main.py (302 lines)    │    │  /api/health · /notes · /chat/turn       │    │
│  │  · vault, config, user,   │    │  /chat/stream · /chat/sessions/* (M6.4)  │    │
│  │    cards, mining, drafts  │    │  /chat/ask-once · /system/reindex        │    │
│  │  · chat_repl              │    │  /system/doctor · /drafts · /cards       │    │
│  │  · _common · _doctor      │    │  /mining · /profile                      │    │
│  └────────────┬──────────────┘    └────────────┬─────────────────────────────┘    │
└───────────────┼─────────────────────────────────┼────────────────────────────────┘
                │                                 │
                └──────────────┬──────────────────┘
                               ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│              ORCHESTRATION  (knowlet/chat/)                                        │
│                                                                                    │
│   bootstrap.py  →  ChatRuntime                                                     │
│                    ├─ vault, config, backend, index                                │
│                    ├─ llm, registry, ctx                                           │
│                    ├─ session: ChatSession (history, user_turn_stream)             │
│                    ├─ conversations: ConversationStore   (M6.4)                    │
│                    └─ active_conversation: Conversation                            │
│                                                                                    │
│   session.py        ChatSession.user_turn / user_turn_stream → tool loop           │
│   prompts.py        CHAT_SYSTEM_PROMPT / SEDIMENT_PROMPT                           │
│   sediment.py       conversation history → Note draft (JSON)                       │
│   conversation_     CRUD over <vault>/.knowlet/conversations/                      │
│     store.py                                                                       │
└──────────────────────────────────┬─────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│              CORE  (knowlet/core/  ·  single source of truth · no UI code)         │
│                                                                                    │
│   ┌───────────────────────┐  ┌────────────────────────┐  ┌────────────────────┐  │
│   │  ENTITIES             │  │  STORAGE / PERSISTENCE │  │  EXTERNAL          │  │
│   │  note.py              │  │  vault.py              │  │  llm.py            │  │
│   │  card.py              │  │   atomic write +       │  │   OpenAI-compat    │  │
│   │  drafts.py (Draft)    │  │   backups              │  │   client           │  │
│   │  user_profile.py      │  │  card_store.py         │  │  embedding.py      │  │
│   │  mining/task.py       │  │  drafts.py (Store +    │  │   sentence-trans   │  │
│   │   (MiningTask,        │  │    archive)            │  │   formers / dummy  │  │
│   │    SourceSpec)        │  │  mining/task_store.py  │  │                    │  │
│   │                       │  │  index.py              │  │                    │  │
│   │                       │  │   SQLite + FTS5 +      │  │                    │  │
│   │                       │  │   sqlite-vec           │  │                    │  │
│   │                       │  │   (per-thread conn)    │  │                    │  │
│   └───────────────────────┘  └────────────────────────┘  └────────────────────┘  │
│                                                                                    │
│   ┌──────────────────────────────────────────────────────────────────────────┐    │
│   │  TOOLS  (LLM tool-calling, OpenAI shape; ADR-0004 future MCP adapter)    │    │
│   │  _registry.py  +                                                         │    │
│   │  search_notes · get_note · list_recent_notes · create_card ·             │    │
│   │  list_due_cards · get_card · review_card · list_mining_tasks ·           │    │
│   │  run_mining_task · list_drafts · get_draft · approve_draft ·             │    │
│   │  reject_draft · get_user_profile                                         │    │
│   └──────────────────────────────────────────────────────────────────────────┘    │
│                                                                                    │
│   ┌──────────────────────────────────────────────────────────────────────────┐    │
│   │  MINING PIPELINE                                                          │    │
│   │  scheduler (APScheduler) → fetch (RSS / URL) → extractor (LLM) →         │    │
│   │  drafts/ → user reviews → notes/ + index                                  │    │
│   │  + max_items_per_run (B2) + max_keep archive (M6.5)                      │    │
│   └──────────────────────────────────────────────────────────────────────────┘    │
│                                                                                    │
│   ┌──────────────────────────────────────────────────────────────────────────┐    │
│   │  CROSS-CUTTING                                                            │    │
│   │  i18n (contextvars · EN/ZH catalogs) · _logging (rotating file handler) ·│    │
│   │  events · splitter · fsrs_wrap                                           │    │
│   └──────────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────┬─────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│              ON-DISK VAULT  (user-owned files · ADR-0006)                          │
│                                                                                    │
│   <vault>/                                                                         │
│     ├── notes/<ulid>.md           ← B3: ULID-only filename · iCloud-safe          │
│     ├── drafts/<id>-<slug>.md     ← AI-extracted, pending review                  │
│     │     └── .archive/            ← M6.5 max_keep soft-archive                   │
│     ├── cards/<ulid>.md            ← FSRS state in frontmatter                    │
│     ├── tasks/<id>-<slug>.md       ← mining task config                           │
│     ├── users/me.md                ← user profile                                 │
│     └── .knowlet/                                                                  │
│         ├── config.toml            ← LLM endpoint, embedding, language            │
│         ├── index.sqlite           ← FTS5 + sqlite-vec, derived (rebuildable)     │
│         ├── conversations/         ← M6.4 multi-session chat                      │
│         ├── quizzes/               ← ADR-0014 future, M7.4                        │
│         ├── mining/                ← seen-set per task                            │
│         ├── backups/               ← pre-overwrite copies                         │
│         └── knowlet.log            ← rotating log                                 │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### Key constraints

| Dimension | Constraint |
|---|---|
| Single source of truth | `core/` is the only home for business logic; cli / web / future desktop are thin shells (ADR-0008) |
| Streaming | `ChatSession.user_turn_stream` is the single source of streaming events; web SSE and CLI REPL both consume the same event stream (ADR-0008) |
| Tool shape | OpenAI function-calling shape today; MCP via a future external adapter (ADR-0004 revised) |
| Data sovereignty | All user content is Markdown / JSON on the filesystem; `.knowlet/` derived data is rebuildable (ADR-0006) |
| Concurrency | Per-thread SQLite connection · WAL · busy_timeout 5s (B1) |
| AI optional | When api_key is empty, the backend still starts / Note CRUD works / chat-class entries are hidden (ADR-0012) |

---

## 2. Product architecture

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                                    USER                                           │
└──────────────────────────────────┬─────────────────────────────────────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────────┐
        │                          │                              │
        ▼                          ▼                              ▼
   ┌────────────┐            ┌────────────┐                ┌────────────┐
   │  Lane A    │            │  Lane B    │                │  Lane C    │
   │  KNOWLEDGE │            │  AI CHAT   │                │  INGEST    │
   └────────────┘            └────────────┘                └────────────┘

┌──────────────────────────────────────────────────────────────────────────────────┐
│  Lane A — KNOWLEDGE  (notes-app identity · ADR-0012)                               │
│  ─────────────────────────────────────────                                         │
│  Concepts   Note · Tag · Folder (M7.0) · Backlink (M7.0)                          │
│  Capability create / read / edit / delete (M7.0) / search / tabs / outline /     │
│             preview                                                                │
│  Surfaces   Left file tree · Center editor · Right Outline · Cmd+P quick switch  │
│  Storage    <vault>/notes/<ulid>.md (frontmatter + Markdown, B3 ULID-only)        │
│                                                                                    │
│  Lane B — AI CONVERSATION  (wedge differentiator · ADR-0003 / 0012)                │
│  ─────────────────────────────────────────────────                                 │
│  Concepts   Conversation · Session · Tool call · Reference · Sediment draft       │
│  Capability multi-turn chat with vault tools · scope toggle (note/vault/none) ·   │
│             multi-session (M6.4) · auto-title · sediment chat → Note ·            │
│             one-shot ask-AI (palette `>`)                                          │
│  Surfaces   Right AI dock · Chat focus (`Cmd+Shift+C`) · Cmd+K palette            │
│  Storage    <vault>/.knowlet/conversations/<ulid>.json                             │
│                                                                                    │
│  Lane C — AI INGESTION  (subscriptions / mining)                                   │
│  ───────────────────────────────────────────                                       │
│  Concepts   Mining task · Source · Item · Draft · Inbox                           │
│  Capability scheduled RSS / URL fetch · LLM extraction · max_items_per_run (B2) ·│
│             max_keep soft-archive (M6.5) · user review (approve/reject/skip)      │
│  Surfaces   Footer Drafts icon · Drafts focus (`Cmd+Shift+D`) ·                   │
│             CLI `mining add/list/run/reset` · palette `Fetch all feeds now`       │
│  Storage    <vault>/drafts/, tasks/, .knowlet/mining/seen                         │
└──────────────────────────────────────────────────────────────────────────────────┘

      ┌──────────────────────────────────────┐
      │  Lane D                               │
      │  ACTIVE RECALL                        │
      └──────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────────┐
│  Lane D — ACTIVE RECALL  (Cards / Quiz · ADR-0014)                                 │
│  ──────────────────────────────────────────                                        │
│  Concepts   Card · Due/Review · Quiz session (M7.4) · Reflux                      │
│  Capability FSRS scheduling · self-rate (1-4) · scope-driven quiz (M7.4) ·        │
│             quiz-miss reflux to Cards                                              │
│  Surfaces   Footer Cards icon · Cards focus (`Cmd+Shift+R`) ·                     │
│             Quiz focus (`Cmd+Shift+Q`, M7.4) · palette `Review` / `Quiz me`       │
│  Storage    <vault>/cards/<ulid>.md (FSRS state) ·                                │
│             <vault>/.knowlet/quizzes/<ulid>.json (M7.4)                            │
└──────────────────────────────────────────────────────────────────────────────────┘

           ┌───────────────────────────────────────────────────────┐
           │  Cross-lane                                            │
           │  KNOWLEDGE GOVERNANCE                                  │
           └───────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────────────────────┐
│  Cross-lane — KNOWLEDGE GOVERNANCE  (fragmentation · ADR-0013 · M7-M8)             │
│  ────────────────────────────────────────────────────────────                      │
│  Concepts   Similarity · Cluster · Near-duplicate · Aging · Digest                │
│  Layer A — entry-point ambient (M7) — show top-3 similar Notes on new-Note        │
│            creation; default action stays "create new"                             │
│  Layer B — passive structuring (M8) — background compute of clusters /            │
│            near-duplicates / orphans / aging; compute, don't act                   │
│  Layer C — periodic digest (M8) — Sunday-newspaper tone; cadence is               │
│            user-configurable; no unread badge                                      │
│                                                                                    │
│  Contract  AI does not silently change the IA — any action that mutates           │
│            vault structure (directories / content / tags) requires an              │
│            explicit user click; no defaults, no background tasks (ADR-0013 §1)    │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### Lane × Surface matrix

|  | Left | Center | Right | Footer | Cmd+K | Focus | Modal |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Lane A Knowledge | ✓ tree | ✓ editor | ✓ Outline / Backlinks (M7.0) | — | ✓ jump | — | — |
| Lane B AI Chat | — | — | ✓ AI dock | — | ✓ `>` ask-once | ✓ chat | ✓ sediment |
| Lane C Ingest | — | — | — | ✓ Drafts icon | ✓ feed cmd | ✓ drafts | — |
| Lane D Recall | — | — | — | ✓ Cards icon | ✓ cards cmd | ✓ cards / quiz (M7.4) | — |
| Cross-lane Governance | — | (Layer A entry) | (Layer B Map) | — | — | (TBD M8) | — |

### ADR map

| Constraint / design | ADR |
|---|---|
| Three core principles (data sovereignty / AI optional / pluginization) | [ADR-0002](../decisions/0002-core-principles.en.md) |
| Wedge: AI long-term memory layer | [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.en.md) |
| AI compose + atomic execute + future MCP adapter | [ADR-0004](../decisions/0004-ai-compose-code-execute.en.md) |
| LLM integration strategy (OpenAI-compat) | [ADR-0005](../decisions/0005-llm-integration-strategy.en.md) |
| Storage / sync / rebuild mechanism | [ADR-0006](../decisions/0006-storage-and-sync.en.md) |
| CLI / UI parity discipline + UI test extension | [ADR-0008](../decisions/0008-cli-parity-discipline.en.md) |
| Mining tasks + drafts + scheduler | [ADR-0009](../decisions/0009-mining-tasks-and-drafts.en.md) |
| i18n (English default, EN+ZH) | [ADR-0010](../decisions/0010-i18n.en.md) |
| Web UI redesign: 3-column + focus modes + Cmd+K | [ADR-0011](../decisions/0011-web-ui-redesign.en.md) |
| Notes-first / AI as optional augmentation | [ADR-0012](../decisions/0012-notes-first-ai-optional.en.md) |
| Knowledge-management contract / 3-layer governance | [ADR-0013](../decisions/0013-knowledge-management-contract.en.md) |
| Note-quiz mode / scope-driven active recall | [ADR-0014](../decisions/0014-note-quiz-mode.en.md) |
