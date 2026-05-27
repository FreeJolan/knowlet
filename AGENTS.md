# knowlet — Collaboration workflow for AI agents

This file is the **ordered workflow** for how AI agents (Codex or
others) approach work on knowlet. Not a list of principles — a sequence.
Read it at the start of each stage. Skipping phases has documented cost.

Per-user / per-machine preferences live in `~/.codex/AGENTS.md` (not
committed). Architectural decisions live in `docs/decisions/` (ADRs).
This file covers **process**.

Current roadmap pointer (2026-05-28): for AI product work, use
`docs/roadmap/ai-modes-roadmap.md` as the source of truth. The old
`docs/roadmap/phase-3-stages.md`, `docs/roadmap/phase-3-slicing.md`,
and ADR-0021 Phase 3 envelope plan are historical context only. Stage B
has passed dogfood; the next product step is F0 AI capability foundation
refactor, not direct Quiz/E work.

---

## Personas — used at B.3

- **新用户** — never opened the app. Tests entry / discoverability / "can I leave without committing?"
- **小红** — opens weekly, writes occasionally. Tests "can I remember / discover this?"
- **小张** — daily, power features. Tests "does this shave steps off my flow?"

**Scope rule**: 新用户 is in scope for every entry point; 小红 for every read or write path; 小张 only for power-feature paths.

---

## Definitions used throughout

**"User OK"** — an **explicit affirmative** in chat: 继续 / yes / go / ship / proceed / 同意 / equivalent. The following are NOT user OK:

- A question or follow-up ("interesting, what about X?")
- An adjacent comment without explicit go-ahead
- A 👍 reaction or silence
- Anything the agent has to *interpret* as approval

If unsure, treat the response as Phase A.3 input (reframe) and re-ask. Forward-motion bias is the most common gate-bypass failure mode — when in doubt, do not proceed.

---

## The workflow: A → B → C → D → E

Each phase has explicit **outputs** that gate the next. Produce the
artifact, don't hand-wave.

**Trigger**: any work that (a) touches >1 file, OR (b) changes >50 LOC,
OR (c) changes user-visible behavior. Below all three thresholds, only
Phase E (verification) applies. Trivial mechanical refactors with NO
behavior change (token rename, formatter sweep, import sort) skip the
full workflow but still must leave C.2's commands green.

For bug-fixes that change observable behavior, Phase B.2's path
checklist + Phase E still apply.

---

### Phase A — Frame the problem

**A.1 — Abstract**: write 1-2 sentences. What problem? What does this do?
**No fields, no UI, no timeline.** Product-positioning level. Example
of a violating abstract: "Add a `kind` field to drafts and a chip
component." Example of a passing abstract: "Drafts should show users
which items are knowledge vs reference so they can prioritize what to
internalize first."

**A.2 — User calibration**: post A.1 to the user. Wait for **user OK**
(as defined above). Until user OK arrives, do NOT proceed to Phase B.

*Escalation rule (used here and throughout — single source)*: ✅ ask
the user about product experience, IA, decisions with month-long
impact, target users / scope / milestones, anything contradicting an
ADR or memory. ❌ don't ask about: file names, parameter order, error
wording, internal library picks within established constraints,
default values, formatting.

**A.3 — If the user rejects A.1's framing**: do NOT jump to a revised
plan. Return to A.1, rewrite, re-post. Two iterations of A is normal
and cheap; one wrong B is expensive.

**A.4 — If the user does not respond within the session**: stop and
surface what's blocked. Do NOT assume tacit approval.

---

### Phase B — Research the solution shape

**B.1 — Prior art**: VS Code (north star) + at least 1 other mainstream
(Obsidian / macOS Settings / Cursor / Things 3 / Readwise / …). Describe
in writing how each handles the problem space. Weak parallels that
share a noun but not a pattern do NOT count — name the load-bearing
similarity. If you genuinely find nothing comparable, that claim
itself requires user OK before B.2.

**B.2 — Path checklist (THE scope contract)**:

First, list every user verb each persona would naturally try once they
encounter this feature. Examples for a list-of-things UI:
**see / read / create / edit / approve / archive / delete / move /
link / search / filter / sort / share / bulk-act / undo**.

Then for EACH verb in scope, write its full **interaction path**:

- **Entry state**: how does the user get here? (e.g. "panel open, row visible")
- **Step sequence**: what they click / type / drag, in order.
- **Final assertion**: what state must hold after? (DOM + backend)
- **Two branches required**:
  - (i) the happy "they did it right" branch
  - (ii) a meaningful second branch — in priority order:
    1. genuine redo / undo / cancel sub-path
    2. error / failure path (network down / invalid input / 4xx)
    3. action interrupted mid-way (close modal mid-edit / navigate during save)
  - "Navigate away and come back" is NOT a valid second branch unless
    the path is specifically about state preservation.

**Save this list as a literal checklist** (in the PR description or
stage tracking note) marked per-path as:

```
P1  [reference name]
    □ implemented   □ tested   □ dogfooded   (or: ⏸ deferred + rationale)
P2  ...
```

Update the marks AS you work — not retroactively at the end. **The
checklist is the scope contract. Phase E.5 reconciles against it.
Any path neither implemented nor explicitly deferred = NOT done,
regardless of test results.**

**Deferral budget**: if >30% of paths are deferred, that is a scope
signal — surface it to the user before continuing, not silently in
E.5.

**B.3 — Walk each path through each persona** per the scope rule. For
each in-scope persona × path cell, 2 sentences: "what I see / what I
do / where I get stuck." Stuck points = bugs to design around NOW.

**B.4 — Build-or-borrow with forcing** (applies when the workflow
trigger applies — a 6-line helper is exempt). For each non-trivial
piece of logic (algorithm / parser / UI primitive / state machine / IO):

- Check existing deps + ecosystem + project conventions.
- **Writeup must include at least one concrete package name + version
  + last-publish date per piece of logic — even for packages you
  rejected.** "Considered and rejected" without a name = "did not
  search." If the only candidates are >2 years stale, flag that
  explicitly — "no actively-maintained match" is a different decision
  from "found and rejected."
- Self-implement only when (a) adapter cost > self-implement, (b) dep
  cost > self-implement, or (c) it IS the project's core innovation.
- *(Surface-your-reasoning is general: applies to every non-trivial
  choice in this document, not just here. B.4 is the same rule applied
  to build-or-borrow specifically.)*

**B.5 — Produce the artifact + user OK**: by end of Phase B you have:
- The path checklist (B.2)
- The persona walkthrough across paths (B.3)
- The prior-art + library lookup (B.1 + B.4, with package names)

Post a summary. Wait for **user OK** before Phase C.

**Length self-check**: an unusually long Phase B writeup (multi-page
prior-art essay, paragraph-justifications for every package) is a
smell, not a virtue — it usually means justification is being used
as a work-substitute. If your writeup runs longer than the path
checklist itself, trim.

---

### Phase C — Survey infrastructure

**C.1 — Read similar code first**: before writing ANY new file, find
2-3 existing files in the codebase solving a similar problem. Match
their pattern unless deliberately departing (and say so).

**C.2 — Map the testing surface — record EXACT commands**:

- Backend tests (knowlet: `uv run pytest tests/`)
- E2E suites (knowlet: `cd frontend && npm run e2e`, or
  `SKIP_BUILD=1 node scripts/e2e/<file>.mjs` for one suite)
- Type / lint (knowlet: `cd frontend && npx tsc --noEmit`)
- CI workflow file: read once, note what it gates on.

**Do not build parallel test infrastructure.** Record the EXACT
commands now; Phase E.2 will run the SAME commands.

**C.3 — Map the dev cycle**: how to run dev server / build / each
suite. Run all of them once BEFORE changes to establish a green
baseline.

---

### Phase D — Implement, per path, test-first

**D.1 — Pick the next path** from B.2 in this priority order
(risk dominates across tiers; smallest-LOC is only a within-tier
tiebreaker):

1. **Foundational state / data path** other paths depend on
2. **Entry / read path for 新用户**
3. **Write paths** (create / edit / move / delete)
4. **Branches and edge cases**

Do NOT pick "easiest to implement" when "highest risk if broken"
exists in an earlier tier.

**D.2 — Write the test first. No exceptions for UI.**
- Backend logic → unit + integration test (pytest)
- UI / events / keyboard → E2E test in the existing suite directory
- **Show the red→green transition**: run the new test against current
  `main` and either (a) paste the failing test output into chat, or
  (b) commit the failing test as its own commit, **before writing the
  implementation in D.3**. A test you write alongside the
  implementation has not demonstrated that it would fail without it.

"I cannot write a failing test for this UI" is the agent's most
common dodge here. Before invoking the exception, name the specific
existing E2E test in `frontend/scripts/e2e/` that has a comparable
shape — if you can't, the dodge is unjustified.

**D.3 — Implement**:

- **No hidden tech debt**: proper modules, no globals, no quick-fixes
  that bypass root cause. If understanding a 10-line behavior requires
  reading >3 files or >100 LOC of indirection, refactor before adding.
- **Thin shells per interface**: business logic in `knowlet/core/...`;
  web / CLI / desktop / MCP are thin adapters. Streaming events are
  structured generators shared across interfaces, never re-emitted.

**D.4 — Run the test**. Iterate until green. Update B.2's checklist:
mark the path `☑ implemented · ☑ tested · □ dogfooded`. **Leave the
`dogfooded` box explicitly empty** — it is set in Phase E.3, not
here. An empty `dogfooded` box is what tells E.5 this path still owes
verification.

**D.5 — Loop** back to D.1 for the next path.

---

### Phase E — Verification (done criteria)

A stage is NOT done until every line below holds.

**E.1 — Path × test reconciliation** (an artifact D.4 did NOT produce):

Walk B.2's checklist. For each path on the list, write a line:

```
P1 [name]  →  frontend/scripts/e2e/<file>.mjs:<line>   ☑
P2 [name]  →  tests/test_<file>.py::<test_name>        ☑
P3 [name]  →  ⏸ deferred — rationale
```

If a path has no test file:line mapping AND is not deferred, return
to Phase D. This step exists because an agent under context-pressure
will pattern-match "I already verified this in D.4" and skip E.1 —
forcing a fresh path↔test mapping prevents that skip.

Every non-deferred path's E2E must cover ALL of:

- **a)** Entry state correct
- **b)** Happy-step sequence
- **c)** Both branches identified in B.2 (happy + meaningful second)
- **d)** Final state assertion (DOM + backend)

"Button click doesn't error" is NOT coverage. "User journey
end-to-end with branches" IS.

**E.2 — Run the EXACT commands recorded at C.2**. All green. Any
pre-existing breakage must be fixed or explicitly deferred.

**E.3 — Manual dogfood (mandatory, mechanical, adversarial)**:

1. **Cache bust**: stop the dev server. Rebuild. Restart with a fresh
   Playwright context (`browser.newContext({ storageState: undefined })`)
   or browser launched with `--disable-cache`. If a human will also
   visually review, they look at a hard-reloaded production build,
   not the HMR dev server.

2. **Name the change-surface in one phrase** (e.g. "popover with
   hover + dismiss-on-outside-click"; "list with inline expand +
   modal editor"). List the probes you are adding for that surface
   **beyond** the floor below. If your added list is empty, write
   one sentence justifying why the floor alone is sufficient. An
   empty added list with no justification = NOT done.

3. **Floor probes** (run these every time, via Playwright `evaluate`
   or DevTools):
   - `getComputedStyle(el).backgroundColor` must not be `rgba(0,0,0,0)`
     for opaque panels
   - For every `var(--x)` referenced in changed CSS, grep the repo
     for `--x:` definition — fail loud if missing
   - `document.elementFromPoint(center)` lands on the expected element
   - `document.activeElement` is what the path expects
   - Console: zero errors and zero new warnings introduced

4. **Adversarial pass**: for each in-scope path, ALSO try to break it:
   - resize the window mid-action
   - rapid double-click / spam-press the trigger
   - empty / oversized input
   - refresh mid-action
   - keyboard navigation (Tab / Esc / Enter) from each focal point
   The mechanical probes catch what they were written to catch; the
   unknown unknowns require adversarial intent.

5. **Vault data probe** (when the change writes to vault / changes
   schema):
   - Run against a **copy of a real existing vault**, not an empty fixture
   - Confirm no data loss
   - Confirm no silent format upgrade without a backup file
   - Confirm reopening with the **previous** knowlet version still
     works OR there is a documented, tested migration

6. **Perf probe** (when the change touches a hot path — vault scan /
   index rebuild / chat retrieval / paint-on-keystroke):
   - Time the operation against a realistic vault size
   - Verify effects don't fire on every keystroke when they only need
     to fire on commit / blur

7. **Capture a screenshot** of the final state for each path. Attach
   to E.5.

8. **Update B.2's checklist**: for each path that passed all
   applicable probes, set `✓ dogfooded`.

**Tests passing + floor probes + added probes + screenshots + vault
probe (when applicable) + perf probe (when applicable) = done. Any
one missing = NOT done.**

Mechanical reminder: Playwright's `state: "visible"` accepts a
transparent panel as visible. Floor probes exist to corrective that
class of false-green.

**E.4 — Cross-interface check (capabilities, not affordances)**: list
every **backend capability** touched (a method that mutates or reads
vault state). For each, confirm the CLI / MCP can invoke it. UI-only
interaction affordances (drag-to-reorder, keyboard nav, focus
indicators) are exempt and listed explicitly under "UI-only
affordances."

A new backend capability without a CLI / MCP entry point is incomplete.

**E.4b — Exercise the experience path through the CLI (not just confirm
parity exists)**: E.4 checks the door exists; this checks you walked
through it. For each changed capability / experience path, **actually
run it via the CLI** and confirm the behavior — this is the no-UI way
to verify a core path (per ADR-0008), and it catches what UI dogfood
catches but earlier and cheaper.

**For any AI / LLM path this is mandatory and MUST hit a real model.**
Stub-based pytest faithfully passes `system` messages and otherwise
cannot reproduce provider / proxy behavior. Canonical reverse-example
(2026-05-25): cliproxyapi silently dropped the OpenAI `system` message,
so the model never saw the anchored note — yet every stub-LLM test was
green because the stub honored `system`. The bug only surfaced in UI
dogfood; a `knowlet discuss <note>` run against the real model would
have caught it pre-UI. **A green stub test is necessary but NOT
sufficient for an AI path; a CLI run against a real model is required.**
(See memory `project_cliproxyapi_drops_system_messages`.)

**E.5 — Reconcile against B.2 and report**:

Walk every path on B.2's checklist. Each must be `☑ implemented · ☑
tested · ✓ dogfooded` OR `⏸ deferred + rationale`. Anything else =
NOT done; return to the relevant phase.

Report:
- ✓ paths done (with test file:line + screenshots)
- ⏸ paths deferred (with rationale — silence is not deferral)
- 🎨 UI-only affordances (exempt from E.4)
- ⚠ open concerns from dogfood
- ⏱ anything that took notably longer than estimated

**E.6 — Every "this is broken" gets a regression test**, at every
lifecycle stage — between dogfood and ship, post-ship dogfood, weeks
later in a follow-up PR. If the user reports unexpected behavior, the
fix MUST include a regression test that would have caught it. The
test added at fix-time is the version of the agent that should have
caught it.

Only after E.5 reconciliation acknowledged: declare done.

---

## Domain risks (knowlet-specific concerns, always-on)

Three risk classes the workflow phases handle in spots; these are the
principles to keep in mind whenever the trigger applies.

**Vault data safety (local-first PKM = user data on the line)**:

- File writes go through write-then-rename atomic paths, never
  in-place truncation
- "Delete" goes to `.trash/` or `.archive/`, never `unlink()` direct
- Vault paths must be validated against traversal (no `..` resolving
  outside the vault root)
- Schema changes require a documented migration + a backup of the
  previous shape on first upgrade run
- Verification probe: E.3 step 5

**Performance regressions (vaults grow; 100 notes today, 5000 in two years)**:

- Effects must not fire on every keystroke when they only need to fire
  on commit / blur
- Backend operations on the vault list should be O(notes), not
  O(notes × something else)
- Verification probe: E.3 step 6

**Dependency pinning**:

- New deps must be pinned to an exact version (or `~exact`) in
  pyproject.toml / package.json, never `^latest` or unbounded
- B.4's "name + version + last-publish date" requirement is the audit
  trail; the pin is the reproducibility

---

## See also

- `docs/decisions/0029-cognitive-contract.md` — root principle anchor
  for AI / IA decisions on this project
- `docs/decisions/` (broader index)
- `docs/roadmap/` — current milestone slicing
- `~/.codex/AGENTS.md` — per-user / per-machine (not committed)
