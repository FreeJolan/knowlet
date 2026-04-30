# Architecture Decision Records (ADR)

> **English** | [中文](./README.md)

This directory records important architectural and product decisions for Knowlet. Each ADR, once merged, is treated as immutable; if a decision is overturned, a new ADR is added that declares `Supersedes: NNNN`.

## Index

<!-- Update this index when adding new ADRs -->

- [0001 — Choose "Learning-First" as the Wedge](./0001-wedge-learning-first.en.md) · *Superseded by 0003*
- [0002 — Three Core Principles](./0002-core-principles.en.md)
- [0003 — Wedge Pivot: AI Long-Term Memory Layer + Lower-Burden PKM](./0003-wedge-pivot-ai-memory-layer.en.md)
- [0004 — AI Compose, Code Execute](./0004-ai-compose-code-execute.en.md)
- [0005 — LLM Integration Strategy](./0005-llm-integration-strategy.en.md)
- [0006 — Storage and Sync Strategy](./0006-storage-and-sync.en.md)
- [0007 — MVP Slice Scope and Tech Stack](./0007-mvp-slice.en.md)

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
