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

### Implication: Knowlet Is Naturally an MCP Server

If "atomic capability layer = MCP tools", then knowlet requires no extra development to **become an MCP server**:

- Stage 1: user uses these tools in knowlet's embedded chat
- Stage 2 / long-term: Claude Desktop / Cursor / any MCP-compatible tool can directly invoke knowlet's capabilities

This is consistent with [ADR-0003](./0003-wedge-pivot-ai-memory-layer.en.md)'s wedge narrative — **knowlet is not an app, it is the user's AI long-term memory layer, accessible across AI tools**.

Architectural requirement: **the atomic-capability tool schema must follow MCP standards from day one**, even if external access is not opened in stage 1.

## Consequences

### Benefits

- **Engineering effort drops sharply**: no longer writing UI / code paths for every cross-feature workflow
- **Capability auto-improves with LLM progress**: same atomic capabilities orchestrated more capably as models improve; knowlet doesn't need to chase
- **New capability ships by adding a tool**: development cadence speeds up, consistent with "plugin-ization"
- **User learning cost approaches 0**: speak to use it, no UI patterns or shortcuts to memorize
- **Naturally an MCP server**: cross-AI-tool exposure is a free byproduct

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
