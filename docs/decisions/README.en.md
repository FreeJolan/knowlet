# Architecture Decision Records (ADR)

> **English** | [中文](./README.md)

This directory records important architectural and product decisions for Knowlet. Each ADR, once merged, is treated as immutable; if a decision is overturned, a new ADR is added that declares `Supersedes: NNNN`.

## Index

<!-- Update this index when adding new ADRs -->

- [0002 — Three Core Principles](./0002-core-principles.en.md)
- [0003 — Wedge Pivot: AI Long-Term Memory Layer + Lower-Burden PKM](./0003-wedge-pivot-ai-memory-layer.en.md)
- [0004 — AI Compose, Code Execute](./0004-ai-compose-code-execute.en.md)
- [0005 — LLM Integration Strategy](./0005-llm-integration-strategy.en.md)
- [0006 — Storage and Sync Strategy](./0006-storage-and-sync.en.md)
- [0008 — CLI / UI Parity Development Discipline](./0008-cli-parity-discipline.en.md)
- [0009 — Mining Tasks and Drafts](./0009-mining-tasks-and-drafts.en.md)
- [0010 — i18n Strategy](./0010-i18n.en.md)
- [0011 — Web UI Redesign: Notes-First + Focus Modes](./0011-web-ui-redesign.en.md)
- [0012 — Notes-First / AI as Optional Capability](./0012-notes-first-ai-optional.en.md)
- [0013 — Knowledge-Management Contract / Fragmentation-Governance Framework](./0013-knowledge-management-contract.en.md)

ADRs that no longer represent the current direction are kept in [`archive/`](./archive/).

## ADR Template

```markdown
# NNNN — Title

- Status: Accepted | Proposed | Superseded by NNNN
- Date: YYYY-MM-DD

## Context
The problem and background at the time of this decision.

## Decision
What was chosen.

## Consequences
Benefits, costs, and constraints that follow.
```
