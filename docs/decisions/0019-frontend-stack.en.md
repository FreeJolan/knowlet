# 0019 — Frontend stack: React 19 + Vite + TypeScript + ready-made component libraries

> **English** | [中文](./0019-frontend-stack.md)

- Status: Accepted
- Date: 2026-05-05
- Supersedes: [ADR-0011](./0011-web-ui-redesign.en.md) §"Stack" "no SPA framework" rule

## Context

[ADR-0011](./0011-web-ui-redesign.en.md) §"Stack" (2026-04-29) said: **don't introduce a SPA framework**, and pinned the stack at Tailwind + Alpine.js + marked.js + Split.js. The reasoning at the time was "fewer deps / easier audit / LLM-maintainable."

On 2026-05-04 the project owner finished the first formal dogfood pass ([report](../dogfood/M7-M8.1-report-2026-05-04.md)). Verdict: **the frontend is basically unusable**. Failures:

- AI chat: empty bubble / hidden prompt leaks into the user bubble / chat input disappears after refresh (3 unrelated bugs)
- IME (Chinese pinyin) intermittently swallows characters
- File ops nowhere near Obsidian / Bear baseline (× as delete / restore is CLI-only / folders must be created in Finder)
- Selection capsule overflows the input
- Cmd+Shift+C doesn't toggle out of focus mode
- A pile of small visual / interaction issues

**Root-cause diagnosis** (full transcript in 5/5 conversation):

1. **Hand-rolled chat UI**: SSE event streams crossed with Alpine reactive proxy edges produced multiple hard-to-find bugs. Chat is a solved category — Vercel AI SDK + useChat / assistant-ui / deep-chat exist; we shouldn't write our own.
2. **Alpine is niche**: ~25k GitHub stars (vs React's ~225k). **LLM agent training data has far more React than Alpine**, my own familiarity is shallower, and I've repeatedly tripped on reactive proxy corners.
3. **No static types**: JS + Alpine, 17k LOC of typos / forgotten fields / state-machine races, with zero compile-time interception.
4. **No chat-specific tests**: 376 backend tests pass, but the chat full-stack flow (user input → SSE → render → persist → refresh-restore) has zero e2e tests.

The three reasons for ADR-0011 §"Stack" **no longer hold today**:

| Original argument | 2026-05-05 reality |
|---|---|
| Fewer deps | We replaced deps with ~2000 lines of hand-written app.js + ~1100 lines of Alpine templates. **Net larger.** |
| Easier audit | Alpine itself is small, but the hand-written code is ~100× larger. **Net worse.** |
| LLM-maintainable | **Inverted** — LLMs handle React far better; Alpine reactive-proxy edges trip them up |

Plus the owner admitted "I've never even heard of Alpine" — a stack so niche the owner can't read their own project violates ADR-0002 §"AI is optional, owner is autonomous."

## Decision

### Replace the frontend stack entirely

**New stack** (effective 2026-05-05):

```
React 19           SPA framework
Vite               build / dev server / HMR
TypeScript         static types
Tailwind CSS       utility classes (kept; existing paper-light + dark tokens carry over)
shadcn/ui          generic components (Modal / Popover / Select / Tooltip / Cmd+K palette / etc)
Vercel AI SDK      Chat streaming (useChat hook handles SSE / streaming / tool trace)
CodeMirror 6       Markdown editor (replaces textarea; was already on the M7+ schedule)
react-arborist     File tree (virtualization + drag + multi-select + inline rename)
Tanstack Query     API calls + caching + retry + state management
Vitest             unit / component tests
Playwright         e2e tests (especially chat full-stack)
```

### Removed (full delete)

- ❌ Alpine.js (all `x-data` / `x-show` / `x-text` / `x-model`)
- ❌ Split.js (replaced by react-resizable-panels)
- ❌ marked.js (CodeMirror 6 built-in / or unified + remark)
- ❌ highlight.js (CodeMirror 6 built-in)
- ❌ marked-highlight (same)
- ❌ Custom SSE parser (`knowlet/web/static/lib/sse.js`) — AI SDK handles streaming
- ❌ Custom palette parser (`knowlet/web/static/lib/palette.js`) — cmdk / shadcn replaces

### Kept (zero change)

- ✅ All Python backend (per ADR-0020 hardened separately, not rewritten)
- ✅ Vault data format / Markdown + frontmatter / `.knowlet/` state directory
- ✅ Token system (paper-light + dark mirror) — migrated to Tailwind config + CSS variables
- ✅ ADRs / design briefs / dogfood reports — historical record, untouched
- ✅ 363+ backend tests

### Why React, not Vue / Svelte / Solid

Direct answer: **ecosystem dominance**.

- The libraries we want (AI SDK / shadcn / CodeMirror React wrappers / react-arborist / Tanstack Query) are all **React-first**
- Vue is usable, but many component libraries lag in their Vue ports
- Svelte / Solid are smaller and more modern, but **repeat the Alpine mistake** (niche ecosystem + scarce agent training data)

### Why not hybrid (Alpine + React)

(Discussed and rejected on 2026-05-05):

- Two paradigms coexisting: state splits + cognitive cost doubles + glue layer becomes a new bug source
- Same component double-implemented (capsule in Alpine + React)
- Migration period stretches forever; bugs need to be chased on both sides

**We're in development phase** (per [ADR-0022](./0022-product-lifecycle-phases.en.md)) — no compat baggage, clean cutover allowed.

### Why not full-stack TypeScript

See 5/5 conversation: LLM / ML ecosystem (sentence-transformers / trafilatura / OpenAI SDK / etc) keeps Python as first-class citizen. Backend stays Python; ADR-0020 hardens it.

## Implementation slices

See [ADR-0021](./0021-knowledge-base-first-roadmap.en.md). Brief:

```
Phase 0  ADR + Vite/React scaffold + backend hardening (parallel)  2-3 days
Phase 1  Knowledge-base baseline A (file ops) + B (editor) + C (links)  4-5 weeks
Phase 2  Knowledge-base D (entry + templates + Daily notes) + E (versions / import-export)  1-2 weeks (deferrable)
Phase 3  AI features re-done in new React (chat / capsule / quiz / mining / web search)  3-4 weeks
Phase 4  Full dogfood + ADR-0018 data durability + gray-release prep
```

### File layout

```
knowlet/
├── web/                  ← old Alpine UI (full delete; git history preserves it)
│   └── static/
└── frontend/             ← new React UI
    ├── package.json
    ├── vite.config.ts
    ├── tsconfig.json
    ├── tailwind.config.ts
    ├── src/
    │   ├── main.tsx
    │   ├── App.tsx
    │   ├── components/   shadcn-derived + custom
    │   ├── routes/       react-router or tanstack-router
    │   ├── lib/          API client / utils
    │   ├── stores/       light global state (Zustand / Tanstack Query primary)
    │   └── styles/       Tailwind + CSS variables (paper-light + dark)
    └── tests/            Vitest + Playwright
```

Backend continues to launch FastAPI from `knowlet/web/server.py`; Vite dev server reverse-proxies `/api/*`; build output from `frontend/dist/` is statically served by FastAPI.

### Old Alpine UI deletion strategy

**We're in development phase**: no dual-render / feature flag needed. When the first Phase 1 slice ships, delete `knowlet/web/static/` entirely (git history preserves it).

In the interim (~1 week from Phase 0 → first Phase 1 slice), if anyone needs to dogfood the old UI they can git checkout an earlier commit.

## Consequences

### Positive

- **Ready-made components**: chat UI bugs zeroed by AI SDK; file tree borrows react-arborist Obsidian baseline; palette borrows cmdk
- **TypeScript static types**: refactor safe (rename a field → 17 compile errors), eliminates a major class of runtime bugs
- **Agent friendly**: LLM training density on React + TS is the highest of any web stack
- **Owner can read it**: project owner has React-domain familiarity; can review code
- **e2e tests viable**: Playwright + chat e2e is required in Phase 1, plugging the chronic "no chat full-stack tests" hole
- **Design tokens reusable**: paper-light + dark CSS variables are pure CSS, not Alpine-bound; migration cost is zero

### Negative

- **Big rewrite cost**: ~2000 lines of app.js + 1100 lines of index.html discarded; multiple ADR / memory references to Alpine need amendment
- **Learning curve** (for me as agent): shadcn / AI SDK / cmdk / Tanstack Query / CodeMirror 6 each have ramp-up cost
- **New deps**: from "a few CDN scripts" to "an npm toolchain" (node + bun / npm + lockfile + build step)
- **Bundle size**: from vanilla ~200KB to React + libs ~500KB-1MB (production gzip) — single-user desktop doesn't care, but worth recording

### Mitigations

- Rewrite cost: dev phase has no users, fully manageable
- Learning curve: Phase 0 scaffolds without writing real features; I learn the stack first
- New deps: lockfile in git; `uv sync` equivalent is `bun install --frozen-lockfile`
- Bundle size: Vite tree-shake + lazy-load (focus modes load on demand) + shadcn is copy-paste, not a precompiled library

### Out of scope

- React Native / mobile native (per ADR-0003 stage 2)
- SSR / Next.js — knowlet is single-user localhost; SPA suffices
- Heavy state-management (Redux Toolkit / Zustand global) — Tanstack Query handles server state, local component state via React useState

## References

- [ADR-0011](./0011-web-ui-redesign.en.md) §"Stack" — superseded by this ADR
- [ADR-0020](./0020-backend-python-discipline.en.md) — backend hardening (parallel; not a rewrite)
- [ADR-0021](./0021-knowledge-base-first-roadmap.en.md) — implementation order
- [ADR-0022](./0022-product-lifecycle-phases.en.md) — dev phase licenses aggressive iteration; no compat needed
- [Dogfood report 2026-05-04](../dogfood/M7-M8.1-report-2026-05-04.md) — the original signal triggering this rewrite decision
- [Claude Design 2nd pass bundle](../design/bundle-2026-05-04/) — visual / interaction reference (will be mapped during React implementation)
