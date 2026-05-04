# Design brief — M7 audit + M8 new surfaces

> 2026-05-03 · Internal record of what we asked Claude Design for in the
> second design pass (the first pass produced the paper-light + dusk-blue
> mock at 2026-05-02 that became M6.1.5 visual backbone).

## Paste-ready brief for Claude Design

---

> **Project**: knowlet — local-first personal knowledge base + AI long-
> term memory layer. Single-user, localhost-only web UI. Stack: FastAPI
> backend + Alpine.js + Tailwind + marked.js (no SPA framework). 200+
> notes typical, scaling to ~5k.
>
> **Existing visual system** (locked, don't change): paper-light cream
> palette `--bg #f4f0e8 / --panel #ede7d9 / --card #fbf8f1 / --ink
> #2a2823 / --accent #5b7a9c`; **Source Serif 4** for h1-h3 / card faces /
> modal titles, **Inter** for UI chrome, **JetBrains Mono** for code /
> paths / timestamps / shortcuts. Right-side dusk-blue accent. Three-pane
> layout (notes tree / center editor / right rail with AI dock). Existing
> mock at https://api.anthropic.com/v1/design/h/T5VSDW6haqyY5nnLDed01w
>
> Since that first pass shipped, **8 new surfaces have landed without a
> design review**, plus 3 more are imminent. We need:
>
> ## (A) Audit — refine interaction, keep visual tokens
>
> 1. **Selection popover (M7.1)** — when user selects ≥2 chars in any
>    editor mode, a small floating button "+ 引用至聊天" appears
>    anchored to selection's top-right (flips below near viewport top).
>    Click → attaches a "chat capsule" referencing that quote.
>    *Risk*: position algorithm may overlap mode switcher / footer /
>    palette. *Want*: better anchor heuristic + visual treatment that
>    doesn't startle.
>
> 2. **Capsule strip (M7.1 + M7.2)** — chips above chat input. Two
>    variants: NOTE-source (link icon, `《Title》quote_text…`) and
>    URL-source (globe icon, `[网页] Title · hostname`). Up to 5 chips.
>    Active = accent-soft + ×; sent = panel-grey + "再用".
>    *Risk*: 5 chips + 2-line textarea in 340px right rail looks dense.
>    *Want*: density / wrapping policy, visual differentiation between
>    note vs URL variant.
>
> 3. **URL capture banner (M7.2)** — paste detection: when user pastes
>    a URL into chat input, an inline banner appears below it
>    ("[抓取并讨论这个网页] · cancel"). 3 states: ready / fetching
>    (spinner) / error.
>    *Risk*: layout shift may startle while typing. *Want*: less
>    intrusive entry pattern, possibly inline-with-input rather than
>    a separate row.
>
> 4. **Sediment ambient panel (M7.2 / ADR-0013 Layer A)** — when the
>    sediment modal opens (commit chat as Note), a collapsible
>    `<details>` panel above the title field shows top-3 similar notes
>    with snippet + click-to-open. Default collapsed. ADR-0013 §1
>    requires no auto-merge buttons / no scores / pure information.
>    *Risk*: default collapsed buries useful info; expanded is too
>    visually heavy in the modal stack.
>    *Want*: better information hierarchy; how to surface "you might
>    want to merge with these" *without* a merge button.
>
> 5. **Hover quote tooltip (M7.3)** — `<q data-original="原文">译文</q>`
>    inline; on hover, a tooltip shows the source-language verbatim
>    sentence. Pure CSS via `::after { content: attr(...) }`.
>    Currently 360px max-width, paper-light background, Source Serif 4
>    body, no JS.
>    *Risk*: viewport-edge clipping; CJK density at 360px.
>    *Want*: fallback for narrow viewports; positioning logic.
>
> 6. **Recursive folder tree (M7.0.2)** — left rail tree now walks
>    `notes/` subdirs with collapsible folders. Inline `padding-left:
>    10 + depth * 14 px`. Folder rows show chevron + folder icon +
>    note count.
>    *Risk*: deep nesting (3+ levels) gets cramped at 240px rail width.
>    *Want*: depth-density tradeoff, possibly indentation guides.
>
> 7. **Backlinks panel (M7.0.4)** — right rail tab. List grouped by
>    source note: title + sentence preview with `[[…]]` highlighted +
>    `L<line_no>` indicator. Click → opens source note.
>    *Risk*: long sentences truncate awkwardly; the `<mark>` highlight
>    may not have enough contrast against accent-soft chip background.
>    *Want*: sentence-truncation policy, highlight styling refinement.
>
> 8. **Quiz focus mode (M7.4)** — full-screen overlay (Cmd+Shift+Q).
>    4 stages: scope picker (with note-list checkbox or tag-radio
>    sub-tabs + advanced settings collapsible) → loading → loop
>    (one question + textarea per page) → summary (per-question review
>    with disagreement loop + Cards reflux checkboxes). Plus a "history"
>    tab at the top showing past sessions.
>    *Risk*: scope picker is checkbox-list-heavy with 100+ notes;
>    summary page can scroll long with 5+ questions; "is this question
>    correct?" UX is buried in a 2-stage disagree confirm flow.
>    *Want*: the most thoughtful redesign here — quiz is the largest
>    new surface and the densest interaction territory.
>
> ## (B) New — design before we build
>
> 9. **Knowledge map sidebar (M8.2)** — read-only panel that surfaces
>    pre-computed structure signals from M8.1 backend. Four signal
>    types: `near_duplicates` (note pairs with cosine > 0.92), `clusters`
>    (single-link components on the near-dup graph), `orphan_notes`
>    (no inbound `[[]]` links + last-edited > 90 days), `aging_candidates`
>    (last-edited > 180 days).
>    *Constraints*: ADR-0013 §1 — **no auto-action buttons**, **no
>    "merge"/"archive" verbs**. Pure information.
>    *Want*: how to make 4 different signal types navigable without
>    overwhelming; what's the entry pattern (right-rail tab? new focus
>    mode? collapsible card?).
>
> 9b. **Graph view of user-authored bilinks (NEW after 2026-05-04
>     ADR amendments)** — visualization of `[[Title]]` link relationships
>     the user wrote themselves. Conceptually distinct from #9: the
>     knowledge-map sidebar surfaces *LLM-inferred* signals; this one
>     surfaces *user-validated* connections (ground truth). The two
>     should coexist as parallel modes / tabs, not either/or.
>     *Want*: a graph rendering that doesn't fall into the "Roam
>     screenshot" anti-pattern (pretty but not actionable). Include
>     interaction model: hover a node = see Note title + 1-line preview;
>     click = open Note; pan/zoom for >50 nodes; default landing view
>     for a vault of any size (pre-computed layout vs on-the-fly?).
>     *Earlier ADR-0011/0013 said "no graph view" — that's reversed,
>     graph view is now in scope*.
>
> 10. **Weekly digest (M8.3 / ADR-0013 Layer C)** — Sunday-newspaper
>     tone. **No unread badge, no notification dots.** Default cadence
>     7 days (user-configurable to 14/30). Content: this period's new
>     notes / drafts processed / structural signals from M8.1 / quiz
>     activity. User opens, reads, closes — done.
>     *Anti-patterns explicitly forbidden*: Roam-style backlog guilt,
>     Notion-style "you have 47 unread" anxiety. Sunday newspaper =
>     "if you don't read it, nothing breaks."
>     *Want*: layout / typography / cadence-config UI.
>
> 11. **Dark mode toggle (M8.4)** — paper-light is the default backbone;
>     this introduces a dark counterpart. Need a dark-token system that
>     mirrors the existing paper tokens: dark `--bg / --panel / --card /
>     --ink / --accent`. Source Serif 4 should hold up at high contrast
>     too. Toggle via system preference + localStorage manual override.
>     *Want*: dark token palette + the toggle UI's resting place
>     (settings? command palette? top bar?).
>
> ## Output requested
>
> - Refined component specs / Figma frames for (A) 1-8
> - Net-new component design for (B) 9-11
> - Updated dark-mode token palette
> - **Don't** redesign the existing 3-pane layout, palette, or focus modes for chat / drafts / cards — those are validated and shipped
> - **Don't** suggest framework changes (we're staying on Alpine.js + Tailwind)
> - Format: same as the M6.1.5 mock (Knowlet.html style HTML preview)
> works well; alternatively React/JSX-style annotated sketches like the
> palette mock.

---

## Why this brief, not "redesign all"

- First Claude Design pass (2026-05-02) covered the visual backbone;
  tokens are stable.
- 8 new surfaces shipped without design review during M7. Each is
  reversible, but together they're risky to dogfood blind.
- M8.2/3/4 surfaces are about to ship — designing them with M7 polish
  in the same pass avoids two design rounds.
- Per `feedback_no_hidden_debt` — UI debt is technical debt; better to
  pay it before M8 stacks more on top.

## What we kept conservative

- Visual tokens locked
- 3-pane layout untouched
- Focus modes for chat / drafts / cards untouched (those were in scope
  for the first pass and are working)
- No framework migration request
- ADR-0013 §1 "no auto-action buttons" is non-negotiable; the brief
  flags it
- ⚠ ADR-0011 §6 "no graph view" was **reversed by 2026-05-04
  amendment** (alongside ADR-0003) — graph view is now requested.
  The dropped exclusion only applies to graph view; other §6 items
  (no team collab / no mobile native / etc) still hold
