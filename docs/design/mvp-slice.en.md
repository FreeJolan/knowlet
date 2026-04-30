# MVP Slice Implementation Plan

> **English** | [中文](./mvp-slice.md)

> Living doc. The engineering unfolding of [ADR-0007](../decisions/0007-mvp-slice.en.md), updated as MVP implementation progresses.

## Scope at a Glance

Only the end-to-end minimum usable version of **Scenario A (research / paper reading)**. See [ADR-0007 — MVP Scope](../decisions/0007-mvp-slice.en.md#mvp-scope).

## Library Choices

Reuse mature libraries + write the architectural layer ourselves (per the "no wheel reinvention" boundary):

| Purpose | Library | Reuse / Build | Reason |
|---|---|---|---|
| LLM calls | `openai` official SDK | Reuse | OpenAI-compatible protocol, hits Anthropic / OpenRouter / Ollama directly |
| Embedding (local) | `sentence-transformers` or `fastembed` | Reuse | Local inference, zero extra config |
| Vector library | `sqlite-vec` Python bindings | Reuse | Aligned with ADR-0006, zero external deps |
| Full-text index | SQLite built-in FTS5 | Reuse | Zero deps, required for RAG hybrid retrieval |
| Markdown parsing | `mistune` | Reuse | High performance, simple API |
| Frontmatter | `python-frontmatter` | Reuse | Standard implementation |
| File watcher | `watchdog` | Reuse | Industry standard |
| Schema validation | `pydantic` v2 | Reuse | Used for both LLM tool schema and entity schema |
| ULID | `python-ulid` | Reuse | Simple, no conflicts across devices |
| CLI framework | `typer` + `rich` | Reuse | Declarative + pretty output |
| Config | `pydantic-settings` + TOML | Reuse | Type-safe |
| HTTP client | `httpx` | Reuse | Modern, native async |
| MCP | Official `mcp` Python SDK | Reuse | Reserved for the eventual MCP server form |
| **Text splitter** | Self-written (~30 lines, sliding window + overlap) | **Build** | Cleaner than pulling in LangChain |
| **RAG main flow** | Self-written (~80 lines) | **Build** | Tightly coupled with atomic-capability + LLM-compose philosophy; no off-the-shelf framework fits |
| **Atomic-capability tool implementations** | Self-written, MCP schema | **Build** | Architecture core; nothing existing |
| **AI draft + human review flow** | Self-written | **Build** | Business logic; nothing existing |

## Module Layout (initial)

```
knowlet/                    Python package
├── core/
│   ├── vault.py            Vault read / write, file watcher
│   ├── note.py             Note entity + frontmatter handling
│   ├── embedding.py        Embedding interface (default: sentence-transformers)
│   ├── retrieval.py        Hybrid full-text + vector retrieval
│   ├── splitter.py         Self-written text splitter
│   ├── llm.py              OpenAI-compatible client wrapper
│   └── tools/              Atomic capabilities (MCP-style schema)
│       ├── _registry.py    Tool registration and dispatch
│       ├── search_notes.py
│       ├── get_note.py
│       ├── create_note.py
│       └── ...
├── chat/
│   ├── session.py          Chat session state machine + tool dispatch
│   └── sediment.py         AI draft + human review flow
├── cli/
│   └── main.py             Typer entry
├── config.py               Config loading (pydantic-settings)
└── __main__.py             python -m knowlet entry
```

## Data Layout (within MVP scope)

```
<vault>/                          User-chosen directory, placed inside iCloud / Syncthing
├── notes/<id>-<slug>.md          The only entity type in MVP
└── .knowlet/
    ├── index.sqlite              FTS5 + sqlite-vec share one DB
    ├── conversations/            Conversation raw payload (30-day retention; see ADR-0006)
    ├── backups/                  Critical-file backups
    └── config.toml               LLM endpoint / vault path / embedding model choice
```

MVP does not create `cards/` `mistakes/` `sources/` `users/`; those directories appear in subsequent stage-1 slices.

## First Milestone (M0)

Concretely verifiable behaviors (from the user's perspective):

```
1. knowlet config init
   → Guides user to fill in LLM endpoint URL + API key + model name; generates .knowlet/config.toml

2. knowlet vault init <path>
   → Creates the vault structure (notes/ + .knowlet/) at the given path
   → Initializes SQLite + sqlite-vec tables

3. knowlet chat
   → Launches chat REPL (Rich-rendered)
   → User asks → LLM auto-invokes search_notes tool
     - Hit: answer fuses local Notes + general knowledge
     - Miss: answer based on general knowledge, prompts "no relevant local content found"

4. In chat, type :save command
   → LLM generates a Note draft of the current conversation (title + summary + key Q&A + tags)
   → Shows diff to user: y (accept) / n (discard) / e (open in $EDITOR)
   → On accept, Note lands in notes/<ulid>-<slug>.md, triggers incremental indexing

5. knowlet ls [--recent]
   → Lists Notes in the vault (default: descending by created_at)

6. After exiting chat, run knowlet chat again, new session
   → User asks a related question → LLM recalls the previously sedimented Note via search_notes → answer carries historical conclusions

7. After self-use for about a week, subjective judgment "not annoying to use"
```

Completing these 7 steps → MVP works (corresponding to ADR-0007 validation criteria 1-5).

## Key Prompt (initial draft)

LLM-driven retrieval system prompt design principles:

- Clearly tell the LLM which tools are available
- Encourage **proactive retrieval before answering** (default behavior)
- Guide it on **when not to retrieve** (clearly chitchat or general knowledge)
- Instruct it to **annotate sources** when citing local Notes (in line with ADR-0003 transparency commitment)

Specific first-version prompt determined during implementation; iterate during prototype stage.

## Error Handling and Logging

- LLM tool call failure → tool returns structured error + suggested fix (ADR-0004 constraint #4); LLM auto-recovers
- File IO failure → friendly error message + suggestion (check permissions / disk space)
- LLM API failure (network / auth / rate limit) → retry once; on failure, prompt user to check config
- Log levels: default INFO; `--verbose` switches to DEBUG (shows all tool calls)
- Transparency: UI always allows seeing "which tools the LLM called, with what params, what results" (ADR-0009 transparency commitment, CLI implementation — note: ADR-0009 to be defined)

## Details Yet to Lock (Decided During Prototyping)

- Specific embedding model (`all-MiniLM-L6-v2` vs `multilingual-e5-small` vs others) — Chinese-English mixed scenarios need testing
- Specific chunking strategy (paragraph-level vs fixed-token vs semantic chunking) — affects RAG hit rate
- chunk size and overlap values
- Hybrid retrieval weights (BM25 vs vector score blending ratio)
- Chat REPL command list (`:save` / `:undo` / `:show` etc.)
- First-version system prompt text

These are details, decided iteratively during implementation; do not affect overall architecture.

## Future Anchor Points (Beyond M0)

In natural emergence order, not forced:

- M1: Add `users/me.md` + LLM-injected user context
- M2: Simple web UI (FastAPI + static page), replacing CLI as main entry
- M3: Card entity + FSRS SRS submodule (entering scenario C)
- M4: Knowledge mining tasks (entering scenario B)
- M5: Tauri desktop shell + mobile PWA

Each step passes the "feature priority criteria" 4-question test in [`../roadmap/`](../roadmap/) before entering the roadmap.
