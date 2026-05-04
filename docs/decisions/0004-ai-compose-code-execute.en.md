# 0004 — AI Compose, Code Execute

> **English** | [中文](./0004-ai-compose-code-execute.md)

- Status: Accepted
- Date: 2026-04-30

## Context

The wedge established in [ADR-0003](./0003-wedge-pivot-ai-memory-layer.en.md) is "AI long-term memory layer + lower-burden PKM", with core promises including:

- AI takes over mechanical organization (draft + human review)
- User's tool stack keeps thinning (eating the tools the user was previously forced to use)
- Zero migration cost and zero forced learning curve
- AI behavior is transparent + directable

If these promises are implemented with traditional "code-coded workflows + UI exposing every action", we run into two problems:

1. **Every new capability requires adding UI / workflow / onboarding step**, expanding engineering and maintenance cost in lockstep
2. **Users have to learn new UI patterns for every new capability**, directly conflicting with the "zero forced learning curve" promise

Looking at current LLM capabilities (Claude Opus 4.x / GPT 4.x / Gemini 2.x, etc.), they already possess:

- Understanding natural-language intent
- Decomposing multi-step tasks
- Adjusting execution based on feedback
- Calling tools to complete concrete actions

In other words, **the LLM itself is already capable of being the workflow orchestrator**. Code can expose only atomic capabilities; cross-capability workflows are orchestrated by the LLM via tool-calls.

LLM output is probabilistic, meaning orchestration can fail. But when the model is strong enough that failure rates are low enough to be absorbed by design (reversible operations / second-confirmation gates / transparent auditing), **trading orchestration cost for reduction in UI and maintenance cost** is overall a winning trade.

This judgment must be explicitly recorded because it influences nearly every product and engineering decision in knowlet.

## Decision

### Core Principle

Knowlet's code only implements the **"atomic capability layer"**: a set of tools with well-defined inputs/outputs, bounded side effects, ideally reversible, and single-purpose. **All cross-feature workflow logic is orchestrated by the LLM via tool-calls**; no dedicated UI or workflow paths in code.

```
┌─────────────────────────────────────────────┐
│  AI Orchestration Layer (probabilistic)     │
│  Understand intent / decompose / pick tools │
└─────────────────────────────────────────────┘
                    ↓ tool calls
┌─────────────────────────────────────────────┐
│  Atomic Capability Layer (deterministic)    │
│  Defined I/O / bounded effects / testable / │
│  reversible                                 │
└─────────────────────────────────────────────┘
```

### Four Execution Constraints

To keep the cost of "probability tail" failures controllable, the atomic capability layer must obey:

#### 1. Reversible / idempotent first

- LLM mistakenly calls `delete_note(x)` → user can `undo`
- Repeated calls to `tag_note(x, "ai")` produce no side effects
- Reduces the cost of "probability failure" from "data corruption" to "one extra undo press"

#### 2. Destructive operations go through a second gate

- `delete_note` / `move_note` / `merge_notes` and other irreversible tools do not execute directly
- Return a "pending confirmation" state first; the LLM restates the intent in natural language to the user; the user confirms before execution
- This is the safety net for the probability tail, and the tool-layer extension of "AI draft + human review" from ADR-0003

#### 3. Granularity = "one-sentence action"

- Too fine (20 CRUD operations): LLM gets lost, tokens wasted
- Too coarse (god-tool): orchestration flexibility lost
- Heuristic: each atomic capability ≈ **an action a user can describe in one sentence** ("mark this Note as important", "link these two together")

#### 4. Return structured data, not natural language

- The LLM continues orchestrating based on results; natural language requires re-parsing, adding uncertainty
- Errors should include "suggested fix", letting the LLM auto-recover

### Relationship with [ADR-0002](./0002-core-principles.en.md) / [ADR-0003](./0003-wedge-pivot-ai-memory-layer.en.md)

This ADR is the **engineering boundary** support for the above ADRs, not a new principle:

| Higher-level principle | This ADR's support |
|---|---|
| AI is optional enhancement (ADR-0002) | The atomic capability layer is deterministic; turning AI off still works (just loses orchestration) |
| Data sovereignty (ADR-0002) | Atomic capability inputs/outputs are all within the user's vault; LLM orchestration adds no data leakage surface |
| Capability plugin-ization (ADR-0002) | Atomic capabilities are naturally plugin units; new plugin = new tool |
| AI draft + human review (ADR-0003) | "Review" is the human safety net for the probability tail |
| Zero forced learning curve (ADR-0003) | Users speak in natural language; no UI patterns to learn |
| Transparent + directable (ADR-0003) | Tool calls are naturally loggable / auditable |

### Relation to MCP (revised 2026-05-02)

**The original draft overstated this.** It claimed "atomic capability layer = MCP tools," "knowlet is naturally an MCP server," and "the atomic-capability tool schema must follow MCP standards from day one." But **the actual `core/tools/_registry.py` is OpenAI function-calling-shaped** (flat dict input / sync handler / per-vault `ToolContext` closure), with no MCP resources / prompts / JSON-RPC framing / capability negotiation. Continuing to claim "naturally MCP" is an ADR that doesn't match the code.

**Revised positioning:**

- The atomic-capability schema **does not** directly correspond to the MCP protocol; it corresponds to the OpenAI/Anthropic LLM tool-calling shape.
- Cross-AI-tool exposure **is not a free byproduct.** It requires an **MCP adapter layer** that translates knowlet's registry into an MCP server (URI-keyed resources for notes, JSON-RPC framing, prompts capability).
- This adapter is **future work** (M5+ / driven by user demand), not a stage-1 architectural hard constraint.
- When designing the registry, **preserve** the option of bridging to MCP later (handler I/O JSON-serializable; avoid baking tight coupling to OpenAI shape) — but **do not give up any current-day design** to satisfy MCP today.

**The substance of this section is unchanged**: knowlet is still positioned as "a capability layer accessible across AI tools," extending [ADR-0003](./0003-wedge-pivot-ai-memory-layer.en.md)'s wedge. But cross-tool reach happens via a **future adapter**, not via the schema satisfying MCP today.

> **Trigger**: critique #2 in the 2026-05-02 second-opinion engineering review (MCP claim doesn't match code). The claim is **downgraded** from architectural promise to "reachable through a future adapter."

## Consequences

### Benefits

- **Engineering effort drops sharply**: no longer writing UI / code paths for every cross-feature workflow
- **Capability auto-improves with LLM progress**: same atomic capabilities orchestrated more capably as models improve; knowlet doesn't need to chase
- **New capability ships by adding a tool**: development cadence speeds up, consistent with "plugin-ization"
- **User learning cost approaches 0**: speak to use it, no UI patterns or shortcuts to memorize
- **Cross-AI-tool exposure**: reachable via a future MCP adapter (not a free byproduct; see §"Relation to MCP" above)

### Costs / Constraints

- **Discoverability drops**: users don't know "I can ask AI to merge two Notes"
  - Mitigation: on first launch, AI proactively introduces the capability list + provide `/help` showing all tools' plain-language descriptions
- **Performance and cost**: every action goes through LLM = token cost + latency
  - Mitigation: keep explicit shortcuts for the highest-frequency operations (analogous to Claude Code's `/fast` `/clear`)
  - These are "shortcut-level" supplements, **not** workflow UI replicas
- **Debugging difficulty**: when something fails, users can't tell whether prompt / tool / model is at fault
  - Mitigation: UI provides "expand to see which tools AI called, with what parameters, and what results" (extension of the transparency promise)
- **Probability failure**: LLM occasionally orchestrates incorrectly
  - Mitigation: the four execution constraints (reversible / second gate / granularity / structured returns)
- **Depends on model capability floor**: on weak models (small local models / older GPT-3.5), orchestration quality may not meet usable threshold
  - Mitigation: knowlet shows a recommended capability tier in LLM config UI; explicit warning "orchestration quality may degrade" when user picks weak model

## Amendment (2026-05-04 — user clarification: AI ≠ sole entry point)

The original repeatedly emphasizes "code implements only the atomic
capability layer + LLM orchestrates via tool calls" — which is fine
in spirit but **easily misread as "the user can only invoke atomic
capabilities through AI."** This amendment elevates the following
principle from implicit to **a hard constraint**:

### 5th execution constraint: every AI capability must have a UI alternative path

**Any feature reachable via LLM tool-call must also be reachable via
a sequence of UI actions that produce an equivalent result.**

Concretely:

| Allowed | Forbidden |
|---|---|
| `search_notes` is callable by the LLM AND has manual entries (left-rail search, command palette) | `search_notes` is exposed to the LLM only |
| `create_card` is a chat tool AND a "make into Card" button on the quiz summary | `create_card` is reachable only by talking to the AI |
| `web_search` (M7.5) is an LLM tool; UI also provides a search-box entry (**TODO**; M7.5 only has the LLM path today, must add UI) | `web_search` is forever LLM-decision-only |

Reasoning:

1. **AI ≠ the only path**: when the user is unfamiliar with AI, has
   token budget concerns, wants quick precise actions, or doesn't want
   to explain intent in natural language, they must still reach the
   result.
2. **Avoid "users who don't fluent-speak AI lose the whole feature
   set"**: gating capability behind AI fluency contradicts ADR-0002
   "AI is optional augmentation" + ADR-0012 "AI is optional capability."
3. **Reachability**: UI clicks cost N taps + one-time pattern learning;
   LLM calls cost typing + waiting + reading tool-trace. Each fits
   different contexts; there shouldn't be a capability gap.

### Backlog (existing capabilities that still need UI entries)

Audit of the 16 tools after M7.5:

| Tool | Existing UI entry | Status |
|---|---|---|
| `search_notes` | Left-rail search / palette `Cmd+P` jump | ✅ |
| `get_note` | Click a note | ✅ |
| `list_recent_notes` | Left-rail note list (sorted by updated_at) | ✅ |
| `get_user_profile` | Profile modal | ✅ |
| `create_card` | Quiz summary "make Card" + drafts approve flow (partial) | ⚠ Need: Cards focus mode "+ new Card" button |
| `list_due_cards` | Cards focus mode | ✅ |
| `get_card` | Same | ✅ |
| `review_card` | Cards focus mode 1/2/3/4 rating | ✅ |
| `list_mining_tasks` | CLI `knowlet mining ls` (Web TBD) | ⚠ Need: Web mining-config panel |
| `run_mining_task` | CLI `knowlet mining run-all` + palette `mining-run-all` | ✅ |
| `list_drafts` | Drafts focus mode | ✅ |
| `get_draft` | Same | ✅ |
| `approve_draft` | Drafts focus mode A key | ✅ |
| `reject_draft` | Drafts focus mode X key | ✅ |
| `web_search` (M7.5) | **Missing**: LLM path only | ❗ Need: palette command / left-rail search augment |
| `fetch_url` (M7.5) | **Missing**: LLM path only | ❗ Need: unify with the M7.2 url-capture flow |

⚠ / ❗ rows go onto the M8 dogfood-polish list, not deferred indefinitely.

### Coordination with ADR-0011 §"explicitly not doing"

ADR-0011 §6 excluded graph view (now amended alongside ADR-0003);
but ADR-0011 §3's three-pane + palette + focus-mode UI framework was
designed precisely so **every category of atomic capability has a
first-class UI entry**. This amendment makes that intent explicit in
ADR-0004 as the gating criterion for new tools: **every newly
registered tool must declare its UI entry point at registration
time**, otherwise it's incomplete.
