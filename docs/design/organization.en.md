# Knowledge Organization Strategy: AI Floor + Human Spotlight

> **English** | [中文](./organization.md)

> Living doc. This document is the unfolding of [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.en.md)'s "lower-burden PKM" narrative on the organizational dimension.

## Re-examining "Manual Organization"

Many PKM tools (Obsidian, Notion, Logseq) by default leave classification / tagging / linking to the user. This pushes all organization cost onto the human, leading to two typical problems:

- **High write friction**: every new note requires deciding which folder, which tags — high mental cost per addition
- **Increasingly chaotic over time**: personal classification taxonomies drift over time; six months later, your own categorization no longer makes sense

But "completely abandoning manual organization" is also wrong. Manual organization actually has two distinct value layers:

| Layer | Value | AI replaceable? | Recommendation |
|---|---|---|---|
| **Classification & filing** | Low | ✅ Fully | AI auto-classifies, tags, extracts key points |
| **Building connections** | High | ⛔ Hard | Reserved for humans, but AI proactively prompts to lower the cost |

Classification & filing is mechanical labor; AI does it faster and more consistently than humans. Building connections (discovering that two seemingly unrelated notes actually point to the same concept, or that a new idea is a counterexample to an old note from three months ago) depends on **personal context and judgment** — this is where humans should invest cognitive effort.

## New Strategy

### 1. Default AI Organization (auto-save)

When new knowledge enters the system, **no human intervention is required by default**:

- AI auto-classifies (by topic / type)
- AI auto-tags
- AI auto-extracts key points / summary into Frontmatter
- Direct save, not blocked by "wait for user to decide where"

Users can review and adjust AI classification anytime, but **default to letting it through**, not default to blocking.

### 2. Optional "Connection Hints"

When AI discovers potential connections between new and existing knowledge, **proactively prompt**:

> This new note discusses the same problem as your "XX" from 3 months ago. Want to link them?

User decides:

- Accept → bidirectional link between the two notes
- Reject → no further prompts for that pair
- Rewrite → user writes their own explanation of the relationship

Prompt timing: at write, at review, in outer-loop scans. Frequency must be restrained to avoid noise.

## 3. Humans Decide "Connections", Not "Classification"

Concentrate human cognitive effort on what genuinely has ROI: **thinking and judging**, rather than **organizing and filing**.

## Design Implications

- **Zero-friction write**: input devices (including mobile voice / OCR) should not be interrupted by classification dialogs
- **AI must be explainable**: when users see AI's classification, they can understand why; one click to adjust
- **Connections are bidirectional**: any AI-suggested connection accepted by the user becomes a formal link, affecting RAG retrieval
- **Rejection is also data**: when users reject a connection prompt, that's useful feedback; AI should learn to avoid similar suggestions

## Connection with [ADR-0004](../decisions/0004-ai-compose-code-execute.en.md)

"AI auto-organization" is engineering-wise not a new dedicated code path, but a set of atomic capabilities (`tag_note` / `link_notes` / `get_user_profile` / ...) orchestrated by the LLM:

- When new content enters, LLM auto-calls `tag_note` and `link_notes` to complete classification and connection
- User feedback in natural language ("link these two together"), LLM calls the same atomic capabilities
- No dedicated "classification dialog" / "connection manager" UI
