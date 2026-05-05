# 0022 — Product Lifecycle Phases (development / gray / production)

> **English** | [中文](./0022-product-lifecycle-phases.md)

- Status: Accepted
- Date: 2026-05-05

## Context

knowlet has no external users yet, but every ADR / design / fix decision implicitly assumes some user base. That assumption was unstated, leading to two failure modes:

1. **Over-conservative**: I burned cycles on "what if users have data" / "what if this is a breaking change" when there was only one dogfooder (the project owner) and aggressive iteration was free.
2. **Over-aggressive in the wrong way**: some "good enough for now" decisions (M7.0 file ops as a checklist) were fine without users, but the moment we cross into having users, "compatibility / migration" cost compounds — by then it's too late to fix cheaply.

This ADR pins the **user-base → risk-preference** mapping as the implicit framework for every future ADR / PR review.

## Decision

### Three phases

#### 1. Development (current, 2026-05-05)

- **Users**: project owner only (local dogfood), **0 external**
- **Data**: owner's vault (disposable)
- **Decision preference**: **aggressive iteration**
  - ❌ No legacy compatibility required
  - ❌ No migration scripts required
  - ❌ No deprecation cycle
  - ✅ Can delete entire files / redo entire surfaces / change schemas without migration
  - ✅ Breaking changes only need an ADR / commit-message annotation noting "dev phase allows it"
- **Floor commitment**: **none** (owner accepts responsibility for own data)

#### 2. Gray release

- **Users**: owner + a handful of early users
- **Data**: those users have already deposited **real notes from their daily life**
- **Decision preference**: **functional / interaction can change aggressively, data must be preserved**
  - ✅ UI / UX may still change significantly (early days)
  - ✅ Features may be removed (with a deprecation toast warning ≥1 version ahead)
  - ❌ **Must NEVER break existing user notes**
  - ❌ Schema changes require migration (auto-runs + rollback on failure + snapshot fallback)
  - ✅ Breaking API changes allowed but require version + migration + upgrade guide
- **Floor commitment**: **users' vault data always opens** (even if knowlet has bugs in a given version, they can export / copy out)
- **Entry conditions** (estimated, adjustable):
  - Phase 1 knowledge-base baseline (per ADR-0021) complete
  - Phase 3 AI features re-implemented
  - Data-durability ADR-0018 in place (snapshot / restore / schema versioning / migration test suite)
  - At least 4 weeks of dev-phase dogfood with no major regressions

#### 3. Production

- **Users**: anyone willing to install
- **Data**: diverse use cases (personal / team subset / academic / etc)
- **Decision preference**: **conservative + compatibility-first**
  - ❌ No breaking API / schema changes without major version bump + deprecation cycle
  - ❌ No silent default-behavior changes
  - ✅ Breaking changes require ADR + user docs + migration path
  - ✅ Bug fixes / additive features still iterate quickly
- **Floor commitment**:
  - Data durability (same as gray)
  - **API compat** (strict SemVer): only major bumps allow breaking
  - Security / privacy (per ADR-0006: data sovereignty rests with the user, but knowlet must not introduce new exfiltration surfaces)
- **Entry conditions**:
  - Gray release ≥3 months with real external feedback
  - 0 known P0 / P1 bugs
  - ADR-0019 (frontend) + ADR-0020 (backend hardening) + ADR-0018 (durability) all mature
  - User documentation complete (install / use / troubleshoot / contribute)

### Phase transition protocol

- **Entering a new phase requires explicit declaration by the project owner** — not agent / contributor inference
- Transition timestamps in commit messages + roadmap + memory headers
- Default state (when no transition declared / agent uncertain) = **current phase** (initially development)

### Agent decision matrix

When deciding "do I need compat / migration / deprecation?", first ask: **what phase are we in?**

| Question | Dev | Gray | Production |
|---|---|---|---|
| Add Note schema field | Just add | + migration script + bump schema_version | + ADR + docs |
| Remove / rename Note schema field | Just change | Mandatory ADR + auto migration + snapshot | + major version bump |
| Change API endpoint path | Just change | Deprecation cycle, old path kept ≥1 version | + user announcement |
| Remove UI feature | Just remove | Toast ≥1 version | + docs + ADR |
| Add (optional) config field | Just add | Add + document default | Same |
| Bug fix | Just fix | Same | Same |
| Refactor | Free | Free if external behavior unchanged | Same |

### Relationship to other ADRs

- **ADR-0006 data sovereignty**: gray / production "floor" extends ADR-0006 with stricter discipline
- **ADR-0018 (planned, data durability)**: a gray-release entry condition; this ADR references it without duplicating
- **ADR-0019 / 0020 / 0021**: those exist under this ADR's "aggressive iteration" license and can ship fast

## Consequences

### Positive

- **Decision framework is explicit**: agents stop wasting time on "what if users…" assumptions in the dev phase
- **Aggressive iteration has legitimacy**: redoing file ops / rewriting frontend / changing schemas in dev are all explicitly licensed by §"Development"
- **Phase-transition checklists are concrete**: no surprise "guess we're in production now"

### Negative

- **Habits set in dev phase will need re-education at gray transition**: I'll get used to "just change it" and forget migrations
  - Mitigation: at every phase transition, reinforce in memory + ADR header + commit messages

### Out of scope

- How gray release is actually distributed (installer / email invite / public GitHub) — ADR before entering
- Production SemVer details (what major / minor / patch each allow) — ADR before entering

## References

- [ADR-0006 storage and sync](./0006-storage-and-sync.en.md)
- [ADR-0018 data durability (planned)](#) — see `docs/roadmap/README.en.md` §"🟣 Data durability"
- [ADR-0019 frontend stack](./0019-frontend-stack.en.md) — dev phase license = no dual-render / feature flag needed
