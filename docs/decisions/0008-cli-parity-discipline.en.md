# 0008 — CLI / UI Parity Development Discipline

> **English** | [中文](./0008-cli-parity-discipline.md)

- Status: Accepted
- Date: 2026-05-01

## Context

[ADR-0007](./0007-mvp-slice.en.md) fixed the MVP access form as a CLI and acknowledged that "before opening to external users, a UI must be added." After M0 finished, the user clarified two further points:

1. **GUI is a hard constraint on product viability** (see project memory `project_knowlet_gui_priority`), not an optional extension. Most knowledge workers will not perform sedimentation tasks via a CLI; the CLI is acceptable only for the self-use phase.
2. **knowlet is ~99% written by an agent** (see global CLAUDE.md §Collaboration principles and project memory `feedback_no_hidden_debt`). Under that working mode, debugging and maintenance dominate writing cost. Maximizing automated test coverage is the binding constraint — manual UI regression testing is not sustainable long-term.

Combined with [ADR-0004](./0004-ai-compose-code-execute.en.md)'s "code exposes only atomic capabilities + LLM orchestrates" philosophy and [ADR-0007](./0007-mvp-slice.en.md)'s "backend designed daemon-style for later UI reuse" guidance, an engineering discipline naturally follows: **every functional UI operation must have a CLI mirror, and every piece of business logic lives in the backend exactly once**.

Without this written discipline, new contributors (including future agents) will easily produce code that bleeds backend logic into the UI layer ("UI reads frontmatter directly", "UI talks to sqlite directly", "UI implements its own reindex"), causing:

- the same logic implemented in CLI and UI separately, drifting over time;
- UI bugs that only manifest under manual click-through;
- test coverage diluted — strong backend tests cannot guarantee product correctness.

## Decision

### Top-level rule

`knowlet/core/*` and `knowlet/chat/*` are the **single source of truth** for knowlet's business logic. `knowlet/cli/*` and the future `knowlet/web/*` are **thin shells**: they speak CLI / HTTP / WebSocket protocols, translate to backend module calls, and serialize results back. **Any business logic appearing in a shell is a design defect.**

### Five hard rules

#### 1. Backend first, shell last

A new functional capability must first land as a function (with tests) in `core/` or `chat/`, and only then get a CLI / UI surface. Allowed evolution order:

```
backend function (+ test) → CLI entry → UI entry
```

Not allowed:

```
UI button → ad-hoc logic in frontend → (never backfilled) backend function
```

#### 2. Every functional UI operation has a CLI entry

CLI entry forms can be: an explicit subcommand (`knowlet user edit`), a slash command (`:user edit`), a generic `config set <key> <value>`-style entry, or stdin / file-arg batch invocation. **Form is unconstrained; reachability is the requirement.**

The only allowed exception is "purely visual / UX" operations: panel layout, animation, dark-mode color values, drag-and-drop feel, font tuning, keyboard hints. These do not affect product **correctness**, only **comfort**.

#### 3. Streaming is layered on a structured event stream

Any streaming output (LLM tokens, tool-call traces, knowledge-mining task progress, intermediate query results) must be produced from the backend as an "event generator." Each event is a structured object (dataclass / TypedDict) with a `type` field and a payload.

- The UI layer subscribes to events and dispatches by type to components for rendering;
- The CLI layer serializes events to lines (`json.dumps(event)` per line);
- Tests assert event sequences directly (order, type, key fields).

The backend's "event generator" is written once; UI and CLI consume it through the same interface. **Forbidden** for the UI to hold its own streaming logic (e.g., accumulating partial tokens itself, maintaining its own tool-call state).

#### 4. Tests primarily target backend functions

Test pyramid:

```
              ┌──────────────────────────┐
              │ UI smoke (mostly manual)  │   covers UI-only behavior
              ├──────────────────────────┤
              │  CLI integration         │   small, smoke wiring layer
              ├──────────────────────────┤
              │  Backend unit + integ    │   bulk; core coverage
              └──────────────────────────┘
```

- **Backend unit + integration tests** are the bulk: they cover search, indexing, sedimentation, retrieval, tool dispatch, user-context injection, and so on.
- **CLI integration smoke**: covers wiring between CLI and backend (argument parsing, exit codes, stdout shape). Each CLI entry gets at least one smoke test.
- **UI tests** cover only what the UI uniquely owns: rendering, mouse / touch / key events, state machines, SSE / WebSocket connection management. **Never** retest search, indexing, or sedimentation that the backend has already covered.

#### 5. Hard "done" criteria

A feature must satisfy all of the following before being considered "done":

- ✅ A backend function with at least one happy-path test and one typical-error-path test;
- ✅ At least one CLI surface that reaches it (subcommand / slash / generic entry);
- ✅ (When UI exists) a UI surface plus one manual UI smoke run.

Any item missing means the feature is not done. **Forbidden** to bypass with "merge first, UI/test later."

### Implication for daemon evolution

[ADR-0007](./0007-mvp-slice.en.md) already designates the backend as daemon-style. Under this ADR's discipline, the daemon's eventual form becomes concrete:

- When the web UI (M2) ships, the daemon serves a local HTTP / WebSocket interface exposing backend capabilities.
- After the daemon is up, the CLI shifts to "CLI talks to daemon" mode (similar to `gh` / `stripe`'s local-client form), no longer paying the import cost of torch / sentence-transformers per invocation.
- The HTTP API becomes the single interface contract between backend and shells. **HTTP API tests** then take over from "backend unit tests" as the bulk of coverage.

This evolution is M2-phase work; until then, the CLI directly importing backend modules remains valid. The five core rules of this ADR apply in either form.

## Consequences

### Benefits

- **Automated test coverage rises sharply.** Backend tests + CLI integration smoke cover almost all functional regressions. Once UI ships, manual QA only needs to test visual and interaction feel; **it no longer needs to click through dozens of buttons to verify logical correctness.**
- **Architecture corrosion-resistant.** The UI can never "steal" the backend's job; the structure pins this down. Three months from now, when another agent revisits a piece of logic, they only need to look at the corresponding module in `core/`, not search across `cli/` and `web/`.
- **CLI naturally becomes a power-user / scripting interface.** Every capability has a CLI entry, meaning users can orchestrate knowlet via shell scripts — which fits the ADR-0003 wedge ("AI long-term memory layer, available across tools").
- **Daemon evolution path stays clear.** When M2 lands, only "CLI direct-import" → "CLI HTTP-call" needs to change; the backend stays put.

### Costs / constraints

- **5–10% extra work per feature** (CLI entry + tests). Given that agent-written code is near zero cost, this overhead is dwarfed by future debug savings.
- **Streaming-API design cost.** Designing streams as structured event streams up-front is more expensive than "just pipe out raw text"; but once a fork happens it is irreversible.
- **Resisting "quick bypass" temptations requires sustained discipline.** New contributors (especially external ones) may submit PRs that "implement in UI first, abstract later." Code review must firmly redirect to the discipline this ADR lays out.

### Relation to existing ADRs

- Subordinate to [ADR-0002](./0002-core-principles.en.md): this ADR introduces no new principle; it is engineering support for the "capability pluginization" principle.
- Synergistic with [ADR-0004](./0004-ai-compose-code-execute.en.md): the boundary of an atomic-capability tool schema coincides exactly with that of a backend function; LLM-orchestrating-via-tool = UI-orchestrating-via-function-call = CLI-orchestrating-via-command — three layers sharing one set of atomic capabilities.
- Reinforces [ADR-0007](./0007-mvp-slice.en.md): the "backend designed daemon-style" promise is given concrete rules by this ADR.
- Does not affect [ADR-0005](./0005-llm-integration-strategy.en.md) / [ADR-0006](./0006-storage-and-sync.en.md): those concern external interfaces and data; this ADR concerns internal layering.

## Update 2026-05-02 — UI grew, test strategy extends

**Trigger**: actual M6 shape (measured 2026-05-02):

- `frontend/index.html` ≈ **850 lines** (three columns + command palette + three focus modes + modals)
- `frontend/app.js` ≈ **1130 lines** (Alpine state machine + hand-rolled SSE parser + keyboard bindings + focus stack)
- Backend tests ≈ 137 cases; UI auto-tests = 0

The §3 assumption "very little UI auto-smoke" held in M0/M1 (a few hundred lines, no state machine); after M6, the UI **has its own state-machine problems**: palette triggered mid-stream / focus stack across three focus modes / hand-rolled SSE buffer with partial chunks / Cmd+K opened inside chat focus / etc. Backend unit tests cover **none** of this; the original "5–10% extra work" estimate is off by an order of magnitude.

### Revised testing discipline (client-side only; backend rules unchanged)

1. **Hand-rolled stream / parser logic must be its own module with unit tests.** `app.js`'s SSE parser, the Markdown render wrapper, future quote-pill parsers — all of them **must** be extracted into an ES module and tested for partial chunks, malformed lines, and edge cases. Framework not locked (Node's native test runner / vitest / jest all OK), but **no tests, no ship**.

2. **UI state machines must be isolatable for tests.** Cmd+K query parsing, focus-stack push/pop ordering, ChatHistory transitions during sediment / clear / mid-stream — these are state-machine behaviors. Extract them as pure functions (or Alpine factories) and unit-test the transitions. Don't test rendered HTML; do test state transitions.

### What we don't do

- **No Playwright / Cypress / E2E.** E2E is high-maintenance, conflicts with ADR-0011's ~75 kb distribution budget and the "AI iteration velocity" gain.
- **No 100% UI coverage requirement.** Risk-driven: state machines / stream parsers must be tested; pure rendering helpers don't need to be.

### Relation to the original clauses

§3's "very little UI auto-smoke" is **partially superseded**: UI modules with state machines / streaming / parser logic must have unit tests; pure presentation rendering remains untested. The ADR's core assertions (backend is the single source of truth; CLI is a thin shell; tool schema = backend function boundary) **still hold**.

> **Trigger**: critique #3 in the 2026-05-02 second-opinion engineering review. This section is a patch, not a reversal.
