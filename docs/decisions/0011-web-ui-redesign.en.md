# 0011 — Web UI redesign: notes-first + focus modes

> **English** | [中文](./0011-web-ui-redesign.md)

- Status: Proposed
- Date: 2026-05-01

## Context

ADR-0003 frames knowlet literally as a "**personal knowledge base + AI long-term memory layer**" — **notes are the subject, AI is an organizing tool.**

But the web UI accumulated through M0–M4 is chat-first: chat takes ~70% of the screen; Notes / Cards / Drafts are 30% sidebar widgets. That shape is identical to ChatGPT / Claude.ai's "agent + context sidebar," which **violates the literal promise of ADR-0003.**

After dogfood experiment 2 on 2026-05-01 the user said plainly:

> I'm not happy with the overall UI and interaction design. Is this just MVP-grade scaffolding that you'll throw away later? If you plan to keep patching and stacking features on top, I'm going to be very unhappy.
> We've confirmed multiple times that knowlet is fundamentally a notes app. But right now? The interface feels like an agent wrapper.
> Maybe we should first agree on a basic vision and tonal direction for the UI as a whole.

We need to **pin down the information architecture and design tone in an ADR before touching code**. That's what this ADR is for.

To avoid the "one developer unilaterally decides product-grade UI shape" risk, the direction selected here rests on:

1. The user's 2026-05-01 pick: **Obsidian-style + focus modes** (notes-first; full-screen workflow when needed).
2. Three independent Claude consultations (`Agent` tool, fresh-eyes, no project context), each from a different angle: ① direct design, ② pitfall warnings, ③ cross-product IA comparison — all three converged on four core points.
3. Project principles: ADR-0008 CLI parity discipline, ADR-0002 data sovereignty, the no-hidden-debt memory.

## Decision

### 1. Three-column layout (Obsidian-style)

```
┌──────────────────────────────────────────────────────────────────┐
│ knowlet  vault·model·lang             [icons]  [Cmd+K palette]  │  ← header (32px)
├──────────────┬───────────────────────────────┬──────────────────┤
│              │                               │                  │
│   vault tree │       Note editor / view      │   Right rail     │
│   (notes/    │       (tab bar + content)     │   (collapsible   │
│    only)     │                               │    to 32px rail) │
│   18%        │       54%                     │   28% / 32px     │
│              │                               │                  │
├──────────────┴───────────────────────────────┴──────────────────┤
│ [Drafts ●12] [Cards ●3] [Mining ●HF blog]   [v0.0.1 · zh]      │  ← footer (28px)
└──────────────────────────────────────────────────────────────────┘
```

- **Left column (18%)**: vault file tree; **shows only `<vault>/notes/`** as a tree (Obsidian-style). A fuzzy-search box and new-note button sit at the top.
- **Center column (54%)**: note editing / viewing. A tab bar supports multiple notes open at once; breadcrumb + status row (word count / mtime / language).
- **Right column (28%, collapsed to a 32px rail by default)**: three stacked, foldable panels: **Outline** / **Backlinks** / **AI**. AI is a dock-style mini chat with a scope toggle ("this note" / "whole vault" / "no context"); default scope = current note.
- **Footer status bar (28px)**: three icons — `drafts` / `cards` / `mining` — each with a count. Click → enter the corresponding focus mode.
- **Top header (32px)**: logo + vault meta + Cmd+K palette entry + a few icon buttons (profile / fullscreen / theme, etc.).
- All panels are drag-resizable; layout preferences persist in localStorage.

### 2. The file tree shows `notes/` only

**`cards/`, `drafts/`, `tasks/`, `users/` are not exposed.** These are still files the user owns (data sovereignty), but **they are not what the user browses or edits via the file tree:**

- `cards/` is SRS scheduling data — JSON, no value to read.
- `drafts/` is an AI draft queue; once reviewed they vanish, so showing them in the tree implies permanence.
- `tasks/` is configuration, not content.
- `users/me.md` is the user profile, redundant with the toolbar "profile" button.

**Entry points to those areas:**
- Footer status icons (quick view + enter focus mode)
- Command palette (Cmd+K → typing "drafts" / "cards" / "task" surfaces the right entries)
- The CLI is always reachable (`knowlet drafts list`, etc.)

ADR-0002 data sovereignty still holds literally — the files are still in the user's vault, visible in Finder / Obsidian; but **knowlet's own web UI doesn't promote them to first-class folders that compete with notes.**

### 3. AI defaults to collapsed in the right rail

AI is not a town square — it's a **collaborator summoned on demand.** Concretely:

- The right-rail AI region **collapses to a 32px vertical rail by default**. The rail shows the AI logo + current chat status (idle / thinking / N messages).
- Click to expand → a dock-style mini chat. **Scope is bound to the current note by default** (each user message auto-prepends "context: this note title + body excerpt").
- Scope toggle at the top of the dock: **this note** / **whole vault** / **no context** (default order; user can switch).
- Long conversations enter chat focus mode (Cmd+Shift+C) — that's where the full chat history + multi-session sidebar live.

### 4. The command palette (Cmd+K) is the main navigation

**Cmd+K unifies all action entry points**, replacing the cluttered button row at the top of the current chat-first UI:

- **Quick jump to a note**: type a title → fuzzy match → Enter to open.
- **Run a command**: `reindex` / `run mining` / `cards review` / `doctor` / `clear chat`, etc. (each maps to a CLI command, per ADR-0008 parity).
- **Ask AI (`>` prefix)**: `> what have I read this week about RAG?` → fires a one-shot answer (does not enter chat history; popup in place).
- **Create a new note**: `+ <title>` or `new note <title>`.

**Cmd+P** is a dedicated note quick-switcher (pure fuzzy filename search, no commands mixed in) — high-frequency enough to deserve its own shortcut.

### 5. Focus modes

**Three** (the user explicitly asked for these on 2026-05-01):

| Mode          | Trigger                                          | Exit | State preserved on exit                       |
|---------------|--------------------------------------------------|------|-----------------------------------------------|
| Chat focus    | `Cmd+Shift+C` / click AI rail's "expand" icon    | `Esc` | Outer layout / open notes / scroll positions |
| Drafts review | `Cmd+Shift+D` / click footer drafts icon         | `Esc` | Same as above                                 |
| Cards review  | `Cmd+Shift+R` / click footer cards icon          | `Esc` | Same as above                                 |

Each focus mode is a **full-screen overlay** (no navigation); Esc returns the user to exactly where they were (cursor / selection / scrollbars all restored).

### 6. Drafts count: don't build inbox hell

A direct response to A2's pitfall #3:

- The footer `drafts` icon: **count ≤ 9 shows a number; > 9 shows `9+`; > 50 shows a red "inbox is full" hint instead of a number.**
- Top of drafts focus mode: shows the current batch size (sliced by task / source / created_at — never the entire backlog at once).
- Mining tasks gain a `max_keep` field (default 30): when new drafts exceed the threshold, **the oldest auto-archives instead of queuing forever** (archive is a soft-delete, recoverable; doesn't pollute the main list).

### 7. Sentence-level backlinks preview (M6 phase 2)

**Not in phase 1** — backlinks implementation is involved; leave the panel empty for now.

Future shape (M6 phase 2): the right rail's Backlinks panel shows, per backlink, **the paragraph containing the `[[link]]`** (paragraph preview), not just a list of note titles. Click → jump; Cmd+click → open in a new tab.

### 8. Empty vault, first launch

- Center: open the `users/me.md` template in edit mode, with the prompt "Who are you? What do you want to capture?"
- Left: empty file tree, with a hint "Cmd+N to create your first note."
- Right: collapsed.
- Footer: zero counts.
- **No modal wizard;** no forced setup flow.

### 9. Out of scope / explicitly deferred

- ❌ Graph view — A2 / A3 both flagged it as a "pretty but used once a month" vanity feature; this ADR explicitly does not build it.
- ⏳ CodeMirror editor — deferred to M7+; M6 keeps `<textarea>` + marked.js preview (full-screen editor is already in place).
- ⏳ Inline slash menu / selection-based AI actions ("summarize this", "make a card from this") — deferred to M7+; first stabilize the chat dock shape.
- ⏳ Drag-rearrange / multi-select bulk operations — deferred.

### 10. Phased implementation (M6 slices)

| Phase     | Scope                                                                                                       | Goal                                                                  |
|-----------|-------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------|
| **M6.0**  | Wireframe (HTML mock + prose description)                                                                   | User reviews before any code lands                                    |
| **M6.1**  | Three-column layout + file tree (notes/ only) + Markdown viewer/editor center column + collapsible right rail | Stand up the notes-first default view; chat moves to focus mode      |
| **M6.2**  | Cmd+K command palette (open note / commands / `>` ask AI)                                                   | Replace the cluttered top-button row with a single primary navigation |
| **M6.3**  | Three focus modes (chat / drafts / cards)                                                                   | Complete the workflow experience                                      |
| **M6.4**  | Multi-session chat history (per `project_knowlet_multi_session_chat`) + chat focus session sidebar          | Make scenario A usable long-term                                      |
| **M6.5**  | Drafts count cap + max_keep + status bar polish                                                             | Prevent the "247 unread" hell                                         |

Each phase ships as its own commit with its own tag (`m6.0` … `m6.5`); between phases, the user can fully use the previous stage's features.

## Consequences

### Wins

- **The product positioning becomes literal**: opening knowlet shows vault tree + note in the center = "this is a notes app," not an agent wrapper.
- **AI doesn't dominate**: right rail collapsed by default; Cmd+K, focus mode, and footer entries are always reachable, but the user isn't disturbed while writing.
- **Cmd+K is the single authoritative entry point**: aligns with ADR-0008 CLI parity discipline; every palette item maps 1:1 to a CLI command.
- **Focus mode addresses a real "I need full screen during this workflow" need** without sacrificing the daily notes-first surface.
- **Drafts anxiety is prevented at the design layer**: no "247 unread" failure pattern.
- **Vanity features (graph) are explicitly out**: keeps development focus, immune to screenshot-driven temptation.

### Costs / constraints

- **`knowlet/web/static/*` is almost entirely rewritten**: `index.html` / `app.js` / `app.css` all change; backend APIs are fully preserved (the dividend of ADR-0008).
- **New backend endpoints**: full-text fuzzy note search (for Cmd+K), Notes CRUD endpoints (read-only today), Backlinks API (M6.2+).
- **Multi-session chat history** is a literal promise from ADR-0003 that has been outstanding; M6.4 must ship it — touches conversation log + storage schema + UI session sidebar.
- **Vanilla JS + DOM for three columns + drag resize + tab bar + command palette** is more engineering than it looks; the no-SPA-framework promise stands (per `feedback_no_wheel_reinvention`), but a few components (e.g. the palette) will be ~30 lines of hand-rolled minimalism rather than pulling in something like fzf-for-js.
- **CodeMirror deferred**: textarea + preview is a worse experience than CodeMirror, but it's good enough for M6; revisit in M7.

### Relation to existing ADRs / memories

- Delivers on [ADR-0003](./0003-wedge-pivot-ai-memory-layer.en.md)'s literal promise (notes are the subject, AI is the long-term memory layer).
- Honors [ADR-0008](./0008-cli-parity-discipline.en.md): every Cmd+K command is a thin shell over a CLI command; backend APIs are untouched.
- Honors [ADR-0002](./0002-core-principles.en.md): user files remain visible (file tree + system footer + CLI); data sovereignty is preserved.
- Triggers `project_knowlet_multi_session_chat` (memory) — must land in M6.4, no more deferral.
- Resolves the concrete dissatisfactions raised in `project_knowlet_ui_redesign_pending` (memory).

## Open questions — user has confirmed each (2026-05-01)

1. ✅ Palette `>` prefix ask-AI: **one-shot popup answer in place.**
2. ✅ Multi-session chat titles: **auto-summarized in the background after the first user message; LLM picks the title.**
3. ✅ Theme (revised 2026-05-02): **paper-feel light is the default backbone; dark is preserved as an optional toggle.** Reasoning: knowlet is literally a notes app; paper-feel light is the natural surface for long reading / writing sessions (Bear / Ulysses / Notion / Apple Notes default this way); dark is preserved for "night-time / high-contrast preference" but is not the baseline. Specific token values (`--bg` closer to page-cream than pure white, `--surface` slightly deeper for hierarchy, `--text` near-black not pure black, `--accent` recalibrated against a light ground) will be locked when the Claude Design mock comes back; the dark tokens currently in `wireframe.html` are kept only as historical reference and will be replaced in the M6.x implementation.
4. ✏️ Type (user revision after wireframe v1, 2026-05-01): **sans-serif body (Inter / system CJK) + monospace for code / paths / IDs / kbd hints only.** Reasoning: all-monospace renders "too geek," more like VS Code than a notes app. Same pass replaces ASCII glyph icons (▸ ↩ ✦) with inline SVG (heroicons-style, ~12 of them); the accent color is recalibrated on the light ground alongside the theme revision (the prior dark-ground value `#92b3dc` no longer applies).

## 11. Tech stack (user confirmed the recommendation, 2026-05-01)

### Selected

**Tailwind CSS + Alpine.js + Split.js + a hand-rolled thin component layer.**

No React / Vue / any SPA framework. No DaisyUI / Naive UI / shadcn / etc. pre-styled component lib (reasons below).

### Why we don't pick the popular alternatives — short version

Not adopted: **React / Vue / any SPA framework** (50+ MB node_modules + build pipeline; violates ADR-0002's lean / distributable tone); **DaisyUI / Naive UI / shadcn etc. pre-styled component libs** (visual tone is "modern SaaS," clashes with knowlet's "terminal + information-dense" tone; adopting one means override-fighting more code than we'd write from scratch); **htmx + server-rendered** (drag-resize / palette / live multi-pane editing are too client-heavy for swap-based UIs). Detailed comparison in git history.

### Why Tailwind + Alpine + Split

**1. Tailwind = the "library" for color / spacing / typography (token layer, not component layer)**

- One `tailwind.config.js` + one CSS custom-properties file decides **all** tokens: colors (`--bg` / `--surface` / `--text` / `--accent` …), font sizes (`text-sm` / `text-base` …), spacing (`p-2` / `gap-3` …), radii (`rounded` / `rounded-lg` …).
- The theme backbone is now paper-feel light (revised 2026-05-02); dark is an optional toggle. Switching = updating the config / CSS variables → the whole app re-themes automatically.
- We don't import a library's component look — components hand-assembled out of utility classes preserve knowlet's terminal-monospace tone naturally.
- AI assistants (including future Claude sessions) are extremely fluent in Tailwind, so changes go fast.

**2. Alpine.js (15 kb) = declarative state, not an SPA framework**

- Used for: palette dropdown, modal toggles, tab switching, focus mode enter/exit, resize state, theme toggle.
- Syntax is HTML-attribute-inline: `x-data="{ open: false }"` / `x-show="open"` / `@click="open = !open"`.
- **No build step, no virtual DOM, no component model.**
- Reads as straightforwardly as the HTML; debug in browser devtools.

**3. Split.js (3 kb) = drag resize**

- The drag handle the three-column layout requires.
- Simple API: `Split([leftEl, midEl, rightEl], { sizes: [18, 54, 28] })`.
- State serializes to localStorage to preserve user layout preferences.

**4. Hand-rolled thin component layer (~200 lines of HTML templates + Tailwind classes), 8–10 components**

Each component is one HTML partial + one set of Tailwind utility-class conventions:

| Component         | Used in                                                             |
|-------------------|---------------------------------------------------------------------|
| `button`          | Everywhere. Four variants: primary / ghost / icon-only / danger.    |
| `input` / `textarea` | composer / palette / center editor / profile modal              |
| `modal-card`      | drafts focus / cards focus / chat focus / profile editor / draft commit |
| `tab-bar`         | center column note tabs / palette section switcher                  |
| `panel-section`   | right rail Outline / Backlinks / AI                                 |
| `file-tree-node`  | left rail recursive nodes (expand / collapse / selected states)     |
| `palette-item`    | each row of the Cmd+K palette                                       |
| `status-icon`     | footer drafts / cards / mining entries (with counts)                |
| `tooltip`         | hover-show original quote / explanation / kbd hint                  |
| `toast`           | already in place                                                    |

Each ≤ 30 lines. Sharing one token base, consistency holds automatically.

### Bundle budget (release)

- Tailwind purged CSS: ~10 kb gzipped
- Alpine.js: ~15 kb
- Split.js: ~3 kb
- marked.js (already in place, untouched): ~30 kb
- Hand-rolled app.js: estimated ~15 kb (currently ~12 kb)
- **Total: ~75 kb gzipped**

For comparison: React + shadcn full stack ≈ 250 kb; Vue 3 + Naive UI ≈ 500 kb. Order-of-magnitude gap.

### Build pipeline tradeoffs

- **Dev**: Tailwind via the CDN play script (`https://cdn.tailwindcss.com`), JIT-compiled on the fly, edit-HTML-and-it-works. Alpine / marked / Split all via CDN ESM. **Completely build-step-free**, identical to the current setup.
- **Release** (one-time when committing to main): `npx @tailwindcss/cli -i input.css -o static/dist/tailwind.css --minify` purges + minifies utility classes to a ~10 kb static file, served by FastAPI.
- **CI**: add a `tailwind --check` that fails on undefined classes.
- **Not introducing**: PostCSS / Vite / esbuild / webpack or any heavier toolchain.

### Relation to existing ADRs / memories

- Honors [ADR-0008](./0008-cli-parity-discipline.en.md): backend functions and HTTP API are untouched; Alpine is just thin glue between HTML and `fetch`.
- Honors `feedback_no_wheel_reinvention` memory: that memory targets "framework abstractions over LLM workflows" (LangChain / LlamaIndex) and "dependencies whose APIs aren't stable." Tailwind / Alpine / Split are 6+ years mature, API-stable, large communities, high AI-assistant fluency. **Hand-rolled thin components** fit the memory's "small utilities can be self-written."
- Honors [ADR-0002](./0002-core-principles.en.md): no build-time dependency that fetches remote services; the CDN is a dev-time convenience, not a release-time requirement (release ships a self-contained static file).
- Resolves the user's question about "is there a library for colors / components?": **the encapsulation is at the token layer, not the component layer.**

### Evolution path

- M6 stays on this stack throughout.
- M7 (if useful): CodeMirror 6 (replaces textarea) — a real editor, ~150 kb full but ~50 kb tree-shaken; lives as its own "Editor area," doesn't pollute other components.
- M8 (if useful): add the **optional dark toggle** (light is now the default backbone; dark tokens get filled in once, plus a header / settings switch + localStorage persistence + "follow system" option).
- M5 / M9 Tauri desktop shell: the same `knowlet/web/static/` ships into Tauri unchanged, no rewrite needed.

## Amendment (2026-05-04 — coordinating with ADR-0003 amendment)

§"## Consequences" stated:

> Graph etc. vanity features explicitly not done — concentrate dev
> resources, not screenshot-driven

**Reversed.** Per [ADR-0003 amendment (2026-05-04)](./0003-wedge-pivot-ai-memory-layer.en.md#amendment-2026-05-04--user-course-correction),
bilinks + graph are core knowledge-software capabilities, not
"vanity / screenshot-driven" decorations.

Corrected stance:

- **Graph view re-enters the roadmap** (target: M8; specific landing
  point depends on Claude Design's second-pass feedback)
- The original ADR's other intent stays: **graph view shouldn't be
  the product's narrative spine** (that *would* be screenshot-driven).
  Graph is a visualization of user-authored link relationships, complementary
  to LLM-inferred signals (cluster / near-duplicate, ADR-0013 §3 Layer B);
  the two are layers, not substitutes.
- M7.0.4 already shipped wikilinks `[[Title]]` + backlinks panel as
  the **list form** of bilinks (commit 62b4d6e); M8 adds a graph
  form as another view over the same data, not a fresh build.

Other items in the "explicitly not doing" list (team collab / mobile
native / etc) are **unchanged**.
