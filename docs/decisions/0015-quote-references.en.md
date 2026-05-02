# 0015 — Selection → Chat Reference Capsules

> **English** | [中文](./0015-quote-references.md)

- Status: Proposed
- Date: 2026-05-02

## Context

knowlet's biggest UX gap right now: **"I'm reading a note and want to ask the AI about *this* passage."**

Today there are only two paths:

1. **Right-rail AI dock scope toggle** (this note / all notes / none) — feeds the **whole Note**. Coarse-grained.
2. **Manual copy-paste** the passage into the input box. Loses traceability, brute-force.

Neither expresses "just this passage." This ADR adds a third path: **selection → reference capsule**, letting the user highlight a passage in a Note, attach it as a small "capsule" to the chat input, and use it as fine-grained context for the next turn.

This complements the existing right-rail AI dock + scope toggle from [ADR-0011](./0011-web-ui-redesign.en.md) orthogonally:
- scope toggle = **coarse-grained** entry (this note / whole vault)
- reference capsule = **fine-grained** entry (a passage the user picked, can span multiple Notes)

Stays consistent with [ADR-0012](./0012-notes-first-ai-optional.en.md) "AI is optional capability" — user explicitly selects, explicitly asks; AI is always the requested party.

## Decision

### 1. Trigger (dual rail)

**Auto popover + manual shortcut, both wired**:

- In any editor mode (edit / split / preview), selecting ≥ 2 chars → small button (`+ Quote in chat`) appears anchored to the selection's top-right.
- Same time: `Cmd+Shift+A` (`A` for **A**dd) attaches the current selection directly, skipping the popover.

Reasoning: mouse users already have the cursor in motion while reading; popover doesn't intrude. Keyboard users get a shortcut. Both end up in the same `attach()` call.

The popover dismisses when:
- Selection is cleared (clicking elsewhere)
- Esc
- After successful attach (popover collapses, selection stays highlighted ≤ 600ms as visual confirmation)

### 2. Multiple capsules + soft cap

A single message can carry up to **5 capsules**. Reasoning:

- Single-only is too rigid (cross-note comparisons happen)
- Unbounded fills up and the LLM context can't take it
- 5 × ~1500 chars ≈ 7500 chars ≈ 2000 tokens — well within Claude's window

Past 5 → toast "max 5 capsules; remove one first." No silent enqueue.

### 3. Citation back-references in AI replies — **deferred**

Replies showing `[1] [2]` clickable jumps back to the source passage involves:
- Chat system prompt change to require structured citation IDs
- Frontend parsing + jump + paragraph re-locate
- Graceful fallback when re-locate fails

Non-trivial work that would slow down the main feature. **Ship without citation back-refs first**; if dogfooding makes the case, follow up with ADR-0015b.

### 4. Capsule storage + context construction

#### 4.1 Capsule fields

```python
@dataclass
class QuoteRef:
    note_id: str            # source Note's ULID
    note_title: str         # display only (frontend already has it; no extra lookup on send)
    quote_text: str         # selected text (normalized: trim + collapse \n\n+)
    paragraph_anchor: str   # first 64 normalized chars of the enclosing paragraph (fuzzy re-locate after edits)
```

Deliberately **no** offset / line number / character range — they all break under edits.

#### 4.2 LLM context construction (computed at send-time, not stored)

Every capsule sent to the LLM carries **not just the quote, but also the heading-bounded section that contains it** as ambient context.

Algorithm:

```
1. find() the quote_text in the latest Note body
   ├─ hit → take the offset
   └─ miss (Note edited) → fuzzy match via paragraph_anchor
       └─ both fail: degrade to "(original passage changed)"
2. From the quote offset, walk back to the nearest markdown heading (# / ## / ###)
   └─ section runs from that heading to the next same-or-higher heading
3. Cap the section at 1500 chars
   ├─ over the cap: window 750 before + quote + 750 after with ellipses
   └─ no heading anywhere: take the whole Note, same 1500 cap
```

**The LLM sees** (one block per capsule, concatenated):

```
I want to ask about this (from note "{title}"):
> {quote_text}

(For context, the heading section it's in:)
> {enclosing_section}
———————————————

(user's actual question follows)
```

This gives the LLM both the user's pinpoint interest *and* the structural backdrop, producing focused, on-topic answers without disorientation.

#### 4.3 Click-through (capsule → Note)

Clicking a capsule opens the source Note and scrolls to the anchor's match. Match miss → just open the Note + toast "original passage seems changed."

### 5. Capsule persistence

**One-shot + grayed retain**:

- After sending, capsule **stays visible** but grays out (opacity drop, "Use again" button)
- Grayed capsules don't ride the next message; clicking "Use again" re-activates them
- Switching chat session clears all (including grayed)

Reasoning: one-shot matches "attach" semantics. Follow-up patterns get a one-click re-use without re-selecting.

### 6. Shortcut — `Cmd+Shift+A`

Reasoning: zero macOS system conflict, semantically apt (**A**dd reference), doesn't collide with `Cmd+K` (palette) / `Cmd+N` (new note) / `Cmd+Shift+{C,D,R}` (focus modes).

**Explicitly rejected**:

- `Cmd+Q` / `Cmd+Shift+Q` — macOS quit-app / log-out user. System-level conflict. Hard no.
- `Cmd+'` / `Cmd+;` — dead keys under Chinese IME. Unreliable.
- `Cmd+L` — browser address bar.
- `Cmd+J` — Chrome Downloads.

### 7. Surface coverage

#### 7.1 Web — three interfaces all reach it

- Right-rail AI dock (default)
- Chat focus mode (`Cmd+Shift+C`) — popover + shortcut work as usual; capsule rides into the focus chat input
- Cmd+K palette ask-once (`>` prefix) — **not wired this phase**; palette is ephemeral one-shot, capsule semantics fit better with sustained conversation

#### 7.2 CLI parity not enforced

CLI `knowlet chat` has no notion of "selection." CLI users continue pasting passages by hand.

[ADR-0008](./0008-cli-parity-discipline.en.md) governs "feature must reach every interface," not "every interface must have the same input model." A GUI has selection; a terminal doesn't. Not violating ADR-0008's spirit.

**Future**: CLI could grow `:quote <note_id> <line_range>` REPL syntax, but low priority and out of M7.1 scope.

### 8. Phase plan

```
M7.1.0  ADR-0015 + user approval                 (this commit)
M7.1.1  Backend: references payload + extract_enclosing_section
M7.1.2  Frontend popover (selection + anchor follow)
M7.1.3  Frontend capsule UI (attach / gray / click-through)
M7.1.4  Cmd+Shift+A shortcut + chat focus coverage
M7.1.5  i18n + docs + demo
                                                  tag → m7.1
```

Each phase: separate commit + push. m7.1 tag once §8 fully ✅.

## Consequences

### Positive

- Note ↔ AI finally has a **fine-grained** bridge — biggest UX gap closed
- Capsule isn't persisted (only frontend state) — no vault schema bloat
- Enclosing-section ambient context defuses the "missing context" risk; token budget controlled
- Dual-rail trigger (popover + shortcut) covers both mouse and keyboard users

### Negative

- Popover may overlap editor chrome (footer / mode switcher) at certain selection positions — needs smart anchor avoidance
- Citation back-refs deferred to ADR-0015b → dogfood means users can only ask forward, not retrace which passage the AI cited
- Enclosing-section "find nearest heading" degenerates to whole-note for unstructured Notes; token usage skews higher than expected — 1500 cap protects but semantics are weaker

### Mitigations

- Smart anchor: prefer top-right of selection; flip to bottom-right when near top of viewport
- Citation back-refs as fast follow-up; if dogfooding likes it, immediate ADR-0015b
- Encourage `# / ## / ###` structure habit (the paper-light UI already makes serif headings inviting)

### Out of scope

- Citation back-refs (→ future ADR-0015b)
- Cross-session capsule "draft tray" (user only said "until next message," not "across sessions")
- CLI selection simulation (REPL `:quote`) — low priority
- "Deep-link" editor protocol (`knowlet://note/<id>?line=42`) for AI replies — desktop / mobile concern

## References

- [ADR-0008](./0008-cli-parity-discipline.en.md) — CLI parity discipline (§7.2 explains why this isn't a violation)
- [ADR-0011](./0011-web-ui-redesign.en.md) — Web UI redesign (right-rail AI dock + scope toggle = coarse-grained entry)
- [ADR-0012](./0012-notes-first-ai-optional.en.md) — Notes-first / AI is optional (user-initiated design lineage)
- [ADR-0013](./0013-knowledge-management-contract.en.md) §1 — AI doesn't auto-modify IA (this ADR doesn't touch IA; capsules don't enter storage)
