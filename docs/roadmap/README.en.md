# Roadmap

> **English** | [中文](./README.md)

Knowlet evolves in phases under the Wedge Strategy. Capabilities share source and reinforce each other; the narrative focuses by phase. See [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.en.md).

## Phase Overview

```
Stage 1 (MVP / V1):    AI long-term memory layer + lower-burden PKM
Stage 2 (V1 → V2):     User-demand-driven extensions
Stage 3 (V2 → V3):     Cross-AI-tool memory layer (MCP server)
Stage 4:               All-in-one form
```

## Stage 1 — MVP / V1

**Slogan:** A personal knowledge base that organizes itself. / 会自己整理的个人知识库

### Real Scenarios Served

See [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.en.md) Scenarios A / B / C. Briefly:

- **A. Research / paper reading** — Discuss in knowlet chat → AI draft → user reviews → save; later AI conversations auto-recall historical conclusions
- **B. Information stream subscription and organization** — User configures knowledge mining tasks → scheduled fetching + LLM organization → user reviews → save
- **C. Structured repeated memory + AI augmentation** — Foreign language vocabulary / domain concept distinction / writing assessment; SRS submodule + AI adjusts feedback by user context

### Core Features

- **Embedded chat**: LLM brought by user (see [ADR-0005](../decisions/0005-llm-integration-strategy.en.md))
- **LLM-driven retrieval**: LLM retrieves from the knowledge base on demand each turn
- **Knowledge mining tasks**: scheduled + Prompt + source constraints + transparent fetching
- **AI draft + human review**: default sedimentation mode
- **SRS submodule (FSRS)**: an "active review view" inside the knowledge base
- **Layered user context**: Markdown intent + JSON derived analytics + SQLite derived state
- **Desktop + mobile PWA**: covers fragment scenarios

### Explicitly Out of Scope

See [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.en.md) "Explicitly Out of Scope" section. Summary:

- Team collaboration / multi-user (never)
- Content recommendation / discovery / social
- Tasks / calendar / Todo management
- Traditional PKM dedicated UI for backlinks / graphs (achieved indirectly via LLM agent + tools)
- Replicating AI Chat product features
- knowlet's chat doesn't displace Claude / Cursor

### Conditions for Entering Stage 2

- Three-scenario happy paths run stably
- AI draft + human review sedimentation loop is not annoying in real use
- LLM-driven retrieval hit rate reaches a usable threshold (specific number determined during prototyping)
- Cross-scenario context accumulation has observable effect (writing assessment uses historical mistake patterns / reading drives vocabulary queue, etc.)

## Stage 2 — V1 → V2: User-Demand-Driven Extensions

After stage 1 stabilizes, users naturally surface new needs. Possible directions (in expected priority):

- **Graph / backlink visualization**: users want to see their "knowledge overview"; achievable via LLM agent + tools, but needs intuitive UI
- **Plugin ecosystem**: open interfaces for users / community to write custom tools, extending the atomic capability layer
- **Native mobile**: PWA isn't enough; audio / OCR / notification scenarios need native capabilities
- **Knowlet's own sync service**: when file-level sync's conflict experience falls short, add CRDT or encrypted sync paths
- **Full encryption path**: when high-privacy needs emerge (see [ADR-0006](../decisions/0006-storage-and-sync.en.md))
- **Fallback fetching backend**: support LLMs without native web_search (SearXNG / Brave / self-hosted)

Stage 2 is **pulled by user need**, not built first looking for need. Specific features must pass the priority criteria below before entering the roadmap.

## Stage 3 — V2 → V3: Cross-AI-Tool Memory Layer

Stage 1 atomic capabilities are designed to MCP standards (see [ADR-0004](../decisions/0004-ai-compose-code-execute.en.md)). Stage 3 formally opens MCP server form:

- Claude Desktop / Cursor / other MCP-compatible tools can directly invoke knowlet's capabilities
- Knowlet is no longer just a "standalone app" but the "private memory layer for all the user's AI tools"
- Fully consistent with ADR-0003's wedge narrative

## Stage 4 — Long-Term All-in-One Form

When the three core capabilities (consumption sedimentation / information mining / learning augmentation) reinforce each other in the MCP form:

```
Information mining → AI organizes candidates → user reviews and saves
              ↓
       LLM-driven retrieval recalls in all AI tools
              ↓
       Used knowledge becomes cards → SRS review
              ↓
       Mistakes feed back to notes and adjust mining task prompts
```

Stage 4 is no longer "stack new capabilities" but maxing out the feedback loops of existing capabilities.

## Feature Priority Criteria

Before any new feature enters the roadmap, run it through four questions:

1. **Does it serve the current stage's wedge?** No → backlog
2. **Does it harm the three core principles?** (AI optional / data sovereignty / plugin-ization) Yes → reject
3. **Can it be expressed with existing domain entities?** No → consider whether to add a new entity, not stuff into existing
4. **What's the cost of rejection?** If it's "lose some users not in current stage persona", that's acceptable

This avoids the "want to do everything" early trap; each candidate's verdict is recorded in corresponding ADR or design docs.
