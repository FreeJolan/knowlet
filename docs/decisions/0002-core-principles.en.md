# 0002 — Three Core Principles

> **English** | [中文](./0002-core-principles.md)

- Status: Accepted
- Date: 2026-04-30

## Context

PKM-class projects easily fall into two traps: one is over-reliance on a particular LLM / cloud service, losing offline usability; the other is data being locked into proprietary formats or proprietary clouds, making migration costly. At the same time, as features expand without boundary constraints, the core code quickly becomes a "big ball of mud" where every new module requires changes to the core.

To avoid the above issues, the project must establish architectural and product red lines early on, as the floor for all subsequent ADRs and design decisions.

## Decision

Establish three **non-negotiable** foundational principles. Any feature, module, or external dependency must clear these three before being introduced:

### 1. AI is an optional enhancement, not a requirement

- Without AI (no network, no API key, no model configured), Knowlet remains **a usable note library**
- AI capabilities are exposed as "value-adds", not as "prerequisites"
- Core data structures and core interactions (write, retrieve, review) must work in zero-AI configuration

### 2. Data sovereignty belongs to the user

- All data is **local-first**, stored as plain text / Markdown / Frontmatter
- Cloud sync is **optional** (Git / WebDAV and other open protocols), not bound to any proprietary cloud
- Users can pack up and take all data with them at any time, and after leaving Knowlet the data remains readable in other tools

### 3. Capability plugin-ization

- "Scheduled fetching", "OCR cards", "Q&A assessment" and other capabilities are built as **independent modules**
- Modules communicate via well-defined interfaces, no direct dependencies between them
- Users / community can replace, add, or disable any capability module without affecting core operation

## Consequences

**Benefits**

- Offline usability → users can continue working in any environment (airplane, subway, intranet)
- Data portability → lowers user trial cost, increases trust
- Clear module boundaries → community contributors can engage more easily, and avoids feature conflicts (e.g., "learning-first wants SRS, intelligence-first wants subscriptions" architectural infighting)

**Costs / Constraints**

- Any "must be online" or "must use a particular LLM" elegant design must be rejected; extra effort needed for fallback paths
- Data formats must remain open; cannot introduce proprietary binary formats for some advanced feature
- Module boundaries must be strictly held; up-front development is slower than "all-in-one cowboy mode", but avoids later refactor cost

**Relationship with other ADRs**

- Synergistic with [0001 — Wedge](./0001-wedge-learning-first.en.md): the wedge focuses on learning-first, but the three foundational principles ensure future expansion is not locked in by early paths
