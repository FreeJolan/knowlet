# 0007 — MVP Slice Scope and Tech Stack

> **English** | [中文](./0007-mvp-slice.md)

- Status: Accepted
- Date: 2026-04-30

## Context

[ADR-0003](./0003-wedge-pivot-ai-memory-layer.en.md) through [ADR-0006](./0006-storage-and-sync.en.md) completed the decisions on product positioning, architectural philosophy, LLM integration, and storage and sync. The remaining "unknown unknowns" must be exposed through real use; the marginal value of continued whiteboard discussion has dropped substantially.

The most direct way to honor ADR-0003's "use first, open source second" tone is to establish a minimum end-to-end usable version (MVP) as quickly as possible, letting real-use feedback drive subsequent iteration.

But "do all of stage 1" is too large a scope and would delay the first implementation by months. This ADR decides the minimum scope and tech stack of the MVP slice as the basis for starting to write code.

## Decision

### MVP Scope

Implement only the end-to-end loop of the following:

| Dimension | MVP includes | MVP doesn't do |
|---|---|---|
| **Scenario** | Scenario A: research / paper reading | Scenario B mining / Scenario C SRS |
| **Domain entities** | Note (Markdown + Frontmatter) | Card / Mistake / Source |
| **Core loop** | Embedded chat → LLM-driven retrieval → AI draft → user review → Note saved | Knowledge mining tasks, SRS review, mistake feedback |
| **Platform** | Desktop | Mobile PWA / native mobile |
| **Interface form** | CLI (backend designed as daemon, reusable for later UI) | Tauri shell, visual settings |
| **Configuration** | TOML config file | Visual LLM config UI |
| **Sync** | User has placed vault inside iCloud / Syncthing etc.; knowlet only reads the local directory | Knowlet built-in sync |

### Tech Stack Final Choices

- **Language**: Python 3.11+
- **Architecture form**: Local backend service (MVP enters via CLI; backend designed in daemon mode for later UI reuse)
- **Core libraries and judgments**: see [`../design/mvp-slice.en.md`](../design/mvp-slice.en.md)
- **Not used**: LangChain / LlamaIndex and similar architectural-layer frameworks (reasons: conflict with [ADR-0004](./0004-ai-compose-code-execute.en.md) "atomic capability + LLM compose" philosophy; unstable APIs; transitive dependency bloat)

The core reason to pick Python over Go: **Knowlet's workload is IO + low-level library calls dominant** (LLM API, SQLite, embedding models, Markdown parsing). Python performs within 1% of Go in this kind of scenario. Python's ecosystem maturity in LLM SDK / embedding / sqlite-vec / Markdown is significantly ahead, more in line with the "no wheel reinvention" principle.

Python's slow startup (`import torch` etc. takes seconds) is absorbed by **daemon residency** (MVP CLI accepts the one-time startup cost; later UI form serves continuously via daemon).

### Validation Criteria (How to Decide MVP Is "Working")

Quantifiable behavioral criteria:

1. CLI launches a chat session without errors
2. During chat, the LLM automatically calls the local knowledge base retrieval tool (visible in logs as a tool call)
3. After triggering "sediment this conversation", the LLM produces a Note draft; after user review the Note lands in the vault
4. Exiting and starting a new session, the LLM can recall content from previously sedimented Notes

Subjective but key criterion:

5. **It's not annoying to use** (interaction pace, error feedback, prompt density are all acceptable)

Four objective + one subjective criteria, all satisfied → MVP works, ready to proceed (gradually adding scenario B / C / mobile etc.).

## Consequences

### Benefits

- **Quickly enters real use**: estimated 1-2 weeks to first working version (zero to one)
- **Focused scope, controllable risk**: doesn't try to solve all stage-1 problems at once
- **Real feedback replaces abstract discussion**: product blind spots only emerge with actual use
- **Python choice grounded in "no wheel reinvention" principle**: LLM SDK / embedding / sqlite-vec / Markdown — Python has the most mature ecosystem, lowest implementation cost

### Costs / Constraints

- **MVP cannot fully embody ADR-0003's wedge narrative** (especially scenario B mining tasks, scenario C learning augmentation); must honestly acknowledge that capabilities beyond MVP are added gradually in later iterations
- **Python slow startup** (1-3 seconds for imports); CLI form acceptable, daemon-ize later
- **CLI lacks visual appeal**: OK for self-use phase; UI needed (Tauri or web) before opening to outside users
- **MVP's temporary implementation may be fully rewritten**: scratch-your-own-itch mode accepts this cost
- **Python's single-binary distribution disadvantage** (PyInstaller / Nuitka large bundles): unimportant in self-use MVP; addressed at distribution time

### Relationship with Existing ADRs

Fully subordinate to [ADR-0002](./0002-core-principles.en.md) / [ADR-0003](./0003-wedge-pivot-ai-memory-layer.en.md) / [ADR-0004](./0004-ai-compose-code-execute.en.md) / [ADR-0005](./0005-llm-integration-strategy.en.md) / [ADR-0006](./0006-storage-and-sync.en.md); this ADR is the engineering unfolding of those principles at the MVP stage.

At some future point this ADR will be superseded by a new one (as the MVP expands toward complete stage 1, scope changes; a new slice will be described).
