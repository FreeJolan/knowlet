# 0006 — Storage and Sync Strategy

> **English** | [中文](./0006-storage-and-sync.md)

- Status: Accepted
- Date: 2026-04-30

## Context

[ADR-0002](./0002-core-principles.en.md) and [ADR-0003](./0003-wedge-pivot-ai-memory-layer.en.md) commit at the principle level:

- Data sovereignty: user can pack up and take all data at any time
- Local-first: usable without network
- Derived data is rebuildable, not confused with ground truth
- Privacy boundaries are explicit

These commitments need to land on concrete directory layout, file formats, sync pipelines, and privacy tiers. This ADR settles all of that.

## Decision

### Three-Layer Storage Model

```
<vault>/                          ← user-chosen directory
├── notes/                        Markdown documents (user notes)
├── cards/                        JSON records (SRS cards)
├── mistakes/                     JSON records (mistakes)
├── sources/                      JSON records (information source metadata)
├── users/
│   └── me.md                     Markdown user intent (goals / preferences / style)
└── .knowlet/                     Derived data + private cache (default not synced)
    ├── index.sqlite              SRS scheduling + full-text indexes
    ├── vectors.sqlite            Vector indexes
    ├── profile/                  AI-derived analytics (JSON)
    ├── conversations/            Conversation raw payload (30-day retention)
    └── backups/                  Backups of critical state files
```

| Layer | Content | Synced? | Lossable? |
|---|---|---|---|
| **Vault entities** | notes / cards / mistakes / sources / users | ✅ | ❌ ground truth |
| **AI-derived analytics** | `.knowlet/profile/*.json` (mistake patterns, mastery vectors, learning behavior profile) | ❌ | ✅ rebuildable from vault |
| **System indexes** | `.knowlet/index.sqlite` / `vectors.sqlite` | ❌ | ✅ rebuildable from vault |
| **Conversation cache** | `.knowlet/conversations/` | ❌ (never synced) | ✅ auto-expires after 30 days |

Decision rule: **"Does losing this data mean losing the real information the user gave us?"** — yes → vault entity (must sync); no (can be rebuilt from other data) → `.knowlet/` (default no sync).

### Entity Storage Format: By Nature

| Entity | Format | Filename | Primary editor |
|---|---|---|---|
| Note | Markdown + YAML frontmatter | `notes/<id>-<slug>.md` | User (UI + occasional external editor) |
| Card | JSON | `cards/<id>.json` | UI (user rarely opens raw file) |
| Mistake | JSON | `mistakes/<id>.json` | Machine (user does not edit directly) |
| Source | JSON | `sources/<id>.json` | Mostly machine (user occasionally edits description) |
| User profile | Markdown + YAML frontmatter | `users/me.md` | User (free editing) |

Decision rule: **documents** (user-led editing, possibly viewed in external editors) → Markdown; **records** (machine/UI-led editing, UI is the norm) → JSON.

Card's `front` / `back` and other content fields **may contain Markdown strings**, rendered as Markdown by the UI.

IDs use [ULID](https://github.com/ulid/spec): 26 characters, lexicographic order = time order, no conflicts across devices.

### Write Constraints

Apply to all vault files:

1. **Atomic writes**: write to `.tmp` then `rename`, preventing half-files from power loss / crashes
2. **Strict schema validation + graceful fallback**: parse failure → UI shows "fix this file"; missing fields / type errors → fill with defaults + log warning
3. **Critical state file backups**: written to `.knowlet/backups/<entity>/<id>.<ts>.json`, keeping last N versions, recoverable by user/tools
4. **UI deletion of an entity** cleans up corresponding files (avoid orphans)

### Sync Strategy

Stage 1: **Knowlet has no built-in sync logic**. The vault is just a folder; the user picks the sync pipeline:

- iCloud Drive
- OneDrive / Dropbox / Google Drive
- Syncthing (open source, recommended)
- Any other file-level sync service

Knowlet only does:

- File IO + file watcher monitoring external changes → auto reload
- Detecting conflict files (e.g., `xxx (conflict).md`) and prompting the user in UI

Implication: **Knowlet needs no account system**. Vault = a directory; whoever opens it is the user. This further aligns with [ADR-0002](./0002-core-principles.en.md) data sovereignty — data isn't even "uploaded to knowlet".

Stage 2 / future: knowlet may build its own lightweight sync service (CRDT- or encryption-based) as an advanced option, coexisting with file-level sync. To be decided by a future ADR.

### Rebuild Mechanism

After a new device pulls the vault from its sync pipeline, first launch:

```
1. Scan notes/*.md
   Chunk + call embedding model
   → .knowlet/vectors.sqlite

2. Scan cards/*.json
   Read srs fields
   → .knowlet/index.sqlite (SRS schedule)

3. Scan mistakes/*.json
   Aggregate by error_type / pattern
   → .knowlet/profile/<domain>_analytics.json

4. Scan cards' review_history
   Compute mastery vectors
   → .knowlet/profile/<domain>_analytics.json
```

Time estimates (rough, actual numbers depend on implementation):

- Few hundred Notes / Cards → < 10 seconds
- Few thousand → 30 seconds ~ 1 minute
- Few tens of thousands → a few minutes

UI is immediately usable; vector indexes fill in the background, with RAG hit rate climbing gradually during that period.

**Ground truth is always the vault entities; deleting `.knowlet/` only triggers rebuild — data does not get lost.**

### Encryption Strategy

Stage 1 **default no encryption**, with **encryption as an optional advanced option** (specific tech such as git-crypt / age decided by future ADR).

Reasons:

- Most target users (programmers / knowledge workers) have already made a "trust decision" when picking iCloud / private GitHub repo / Dropbox
- High-privacy users (healthcare / legal) can enable encryption with one click
- Stage 1 doesn't implement the encryption path; deferred until real demand emerges

### Privacy Boundary Statements (with [ADR-0005](./0005-llm-integration-strategy.en.md))

Knowlet documentation must clearly inform users:

- **The LLM provider sees the user's conversation + RAG-hit Note fragments**. Direct connection; knowlet does not proxy or filter. Privacy is determined by the user's LLM choice. For complete privacy → use local Ollama; for low-risk online use → choose a zero-retention API tier.
- **Stage 1 uses LLM provider's native web_search**: fetching is done by the provider's backend, **user IP is not exposed to fetched sites**.
- **Stage 2 fallback fetching backend** (if implemented): requests originate from user's local machine, **user IP is exposed to fetched sites** (same as visiting in a browser). UI prompts explicitly when this is enabled.
- **Conversation raw payload is local-cache-only, auto-cleared after 30 days, never synced**.

## Consequences

### Benefits

- **User can pack up and take all data anytime**: copy the entire vault away; everything is in open formats (Markdown / JSON)
- **Knowlet doesn't participate in sync → low engineering + naturally cross-platform**: macOS / Linux / Windows / mobile PWA share the same file IO
- **No account system needed**: simplifies product boundary, consistent with "never multi-user" (ADR-0003)
- **Ground truth concept is simple and clear**: vault entities are truth, `.knowlet/` is cache
- **Rebuild mechanism makes derived data loss non-fatal**: users have no anxiety about clearing `.knowlet/`

### Costs / Constraints

- **Sync quality depends on user's chosen service**: conflict handling, reliability, cross-platform consistency are not in knowlet's control
- **Large vault first-launch has visible delay**: rebuilding indexes / vectors takes time (acceptable, with progress indicator)
- **JSON entities can't be edited in rich-text editors**: viewing experience for cards / mistakes / sources raw files is worse than Markdown, but target users mostly interact via UI — acceptable
- **Encryption path deferred**: high-privacy users have no full solution in stage 1; can only rely on choosing zero-retention LLM + private sync pipeline
- **LLM provider visibility cannot be solved by knowlet**: only stated in docs; user decides at LLM-choice time

### Future Extensions (No Schedule Committed in This ADR)

- Knowlet's own sync service (CRDT or encrypted sync)
- Full encryption path (git-crypt / age, etc.)
- Additional private fetching backend for LLM provider limitations

These extensions are driven by real demand and will be decided by future ADRs.
