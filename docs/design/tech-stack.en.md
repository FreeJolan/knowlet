# Tech Stack & Competitor Reference

> **English** | [中文](./tech-stack.md)

> Living doc. Concrete implementation choices may shift during prototyping; this document only records current leanings and reasoning. Decision-grade content is in [`../decisions/`](../decisions/).

## Current Leanings

| Dimension | Leaning | Reason |
|---|---|---|
| **Backend language** | Python or Go (to be evaluated during prototyping) | Python ecosystem mature (LLM SDK / embedding / FSRS implementations); Go performance and single-binary distribution friendly |
| **Desktop** | Tauri + Svelte / React | Lighter than Electron; native web stack cross-platform |
| **Mobile (stage 1)** | Responsive PWA | Native experience deferred to stage 2; see [`../roadmap/`](../roadmap/) |
| **Vector library** | SQLite + sqlite-vec | Zero external deps, consistent with ADR-0006's "`.knowlet/` derived data" pattern |
| **LLM integration** | OpenAI-compatible adapter layer | Unified API; see [ADR-0005](../decisions/0005-llm-integration-strategy.en.md) |
| **Storage** | Markdown / JSON by nature | See [ADR-0006](../decisions/0006-storage-and-sync.en.md) |
| **Sync** | User-managed pipeline (iCloud / Syncthing, etc.) | Knowlet doesn't ship sync in stage 1; see [ADR-0006](../decisions/0006-storage-and-sync.en.md) |
| **SRS algorithm** | FSRS | Currently best-in-class; Anki adopted as default; consistent with "algorithm is not our differentiator" tone |

Backend language not finalized; needs evaluation during prototyping on two questions:

1. Python single-binary distribution (PyInstaller / Nuitka) impact on end-user experience
2. Go's LLM client / embedding ecosystem maturity — could it become an application-layer bottleneck

## Hard Lines (Regardless of Stack Decisions)

The following are locked by [ADR-0002](../decisions/0002-core-principles.en.md) and subsequent ADRs:

- No proprietary data formats (Markdown / JSON / SQLite are all open)
- No binding to a single cloud service (sync pipeline is user-chosen)
- LLM must be swappable and disengageable (see [ADR-0005](../decisions/0005-llm-integration-strategy.en.md))
- Any capability module must be replaceable / disableable (see [ADR-0004](../decisions/0004-ai-compose-code-execute.en.md) atomic-capability plugin-ization)

## Competitor Reference

| Product | Characteristic | Borrowable / Difference |
|---|---|---|
| **Obsidian + Smart Connections** | Knowledge base + AI plugin | Borrow: plugin ecosystem. Difference: knowlet doesn't require manual organization; management is taken on by AI |
| **Reor** | Local-first + AI notes | Borrow: local-first architecture. Difference: knowlet emphasizes LLM-driven retrieval and cross-scenario context |
| **Khoj** | AI search over local notes | Borrow: RAG implementation. Difference: knowlet is embedded chat + knowledge mining tasks, not just search |
| **RemNote** | Notes + SRS unified | Borrow: unified card-and-note model. Difference: knowlet's SRS is a submodule, not the main form |
| **Anki / FSRS** | SRS standard-bearer | Borrow: directly adopt FSRS algorithm. Difference: knowlet doesn't try to replace Anki's advanced deck features |
| **Notion AI / ChatGPT memory** | AI assistant with embedded memory | Difference: knowlet is user-owned, cross-tool, and local-first memory layer |

## Differentiation

See [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.en.md). Three combined characteristics (any single one isn't enough; the combination has no mature alternative on the market):

1. **Combined positioning of AI long-term memory layer + lower-burden PKM**
2. **Cross-scenario context accumulation** (papers / information stream / learning all share one user context)
3. **MCP server form (stage 3)**: cross-AI-tool exposure, not an isolated app
