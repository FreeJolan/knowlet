# Bundle — knowlet Graph view (2026-05-08)

Single-surface design pass from Claude Design (claude.ai/design),
scoped strictly to the Graph view of user-authored bilinks (per
ADR-0023 §1). The 2026-05-04 bundle covered 11 surfaces but Graph
view (§9b) wasn't shipped — this bundle delivers it.

> Note: the original `chats/` transcript dir from the export has been
> removed for the public repo (it's chat process residue, not durable
> design intent — same policy as the 2026-05-04 bundle). The intent
> narrative lives in the brief in conversation history + the
> `graph.jsx` 设计判断 comments + the Q1/Q2/Q3 SpecCard frame inside
> `Graph.html`.

## Primary file

`project/graph.jsx` — the implementation reference. It contains:

- 5 frames: rail-tab + focus-mode + 3 edge states (empty / big-hub /
  orphans pile)
- `GraphCanvas` — the shared SVG/positioning logic that the React
  implementation should match in spirit (production code uses
  `react-force-graph-2d` for live force-direction)
- `SpecCard` frame — Q1/Q2/Q3 design judgments (see below)

## Q1/Q2/Q3 design judgments (binding for implementation)

**Q1 — default landing**: auto-pick by vault size, threshold 300.
- rail-tab → always ego 1-hop
- focus-mode <300 nodes → full graph
- focus-mode ≥300 → ego 2-hop default + "expand to full" button

**Q2 — visual differentiation**: user-authored bilinks are this view's
default state, not a special highlight.
- 1.4px solid `--ink-mute` edges
- 5px arrow at 70% of edge length (avoids overlapping target node)
- node `r = clamp(4, 4 + √deg × 2.4, 14)`, fill `--card`, stroke
  `--ink-mute` 1.5px
- LLM-inferred edges (future, not this view): `1px dashed
  --accent-tint, opacity 0.5, default hidden`

**Q3 — force-directed tuning**: react-force-graph-2d with overrides
- `charge.strength(-180)`
- `link.distance(d => 50 + min(deg_sum, 12) * 4)`
- `center.strength(0.04)`
- `x/y forces strength 0.02`
- `alphaDecay 0.04, velocityDecay 0.5`
- Runtime computation up to 500 nodes; runtime + session-pin for
  500-2000; backend indexer for >2000 (future, schema reserved)

## Bundle contents

- `README.md` — this file
- `project/graph.jsx` — primary reference (1300 LOC)
- `project/Graph.html` — entry that loads design-canvas + graph.jsx
- `project/*.html` + `project/*.jsx` — 2026-05-04 bundle carry-over
  (kept for visual-system reference; surfaces other than graph view
  are NOT in scope for this design pass)
- `project/styles.css` — visual-system tokens (paper-light + dusk-blue)
