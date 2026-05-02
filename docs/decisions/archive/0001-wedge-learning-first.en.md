# 0001 — Choose "Learning-First" as the Wedge

> **English** | [中文](./0001-wedge-learning-first.md)

- Status: Superseded by [0003](./0003-wedge-pivot-ai-memory-layer.en.md)
- Date: 2026-04-30

## Context

Knowlet's capability landscape can simultaneously cover three directions:

1. **Learning-first** — A fusion of Anki + ChatGPT + Readwise, oriented toward personal growth
2. **Intelligence-first** — Scheduled fetching + auto-summarization + knowledge sedimentation, oriented toward researchers / DevRel
3. **Knowledge-base-first** — Like Obsidian + AI Agent, oriented toward general PKM

Pushing all three as external narratives in parallel runs into four practical problems:

| # | Reason | Explanation |
|---|---|---|
| 1 | User mindshare retains only one label | Obsidian = backlinks, Anki = SRS, Readwise = highlights. No successful PKM product breaks out by being "all-in-one" |
| 2 | Early R&D resources are limited | MVP stage budgets only "go deep on one + go shallow on two"; going deep on all means each gets only 60% |
| 3 | Feature priorities conflict | Learning-first needs SRS, intelligence-first needs subscriptions, knowledge-base-first needs graphs; architecture decisions become internally contradictory |
| 4 | Acquisition communities differ | Learning-first → exam communities; intelligence-first → researcher communities; knowledge-base-first → PKM communities. Cold start cannot hit all three at once |

## Decision

Adopt **Wedge Strategy**: at the capability layer, all three directions share the same source and reinforce each other; at the **narrative layer, "learning-first" is the sole wedge** to attack first. After establishing a foothold, expand horizontally in this order:

```
Stage 1 (0→1, MVP~V1): Learning-first leads
  Slogan: "Use AI to turn any content into reviewable cards"
  Core:   OCR cards + SRS + AI question generation + mistake feedback
  Byproduct: Plain-text knowledge base (forms naturally underneath)
  Acquisition: Exam / language-learning communities

Stage 2 (V1→V2): Fill in knowledge-base capabilities horizontally
  After users review for a while, they naturally want a knowledge overview
  Roll out backlinks, tags, graphs — pulled in by demand
  Slogan upgrades to: "Not just a card tool, but your second brain"

Stage 3 (V2→V3): Introduce intelligence pushing
  With stable users and knowledge-base foundation
  Roll out subscription sources + daily reports
  New intelligence **auto-becomes candidate cards**; tightly coupled with learning, builds a moat

Stage 4: All-in-one platform
  Three capabilities reinforce each other, not parallel:
  Intelligence fetch → AI generates cards → user reviews → mistakes feed back to knowledge base → knowledge base drives more precise subscriptions
```

Why learning-first over the other two:

1. **OCR + cards + memory science** combination — no mature open source solution exists in the market
2. **Mistake-driven AI weighted question generation** is the most distinctive design; the learning scenario maximizes its value
3. The other two capabilities are **hidden underneath**, not abandoned:
   - MD foundation → knowledge-base capability is naturally there, just not the lead pitch
   - Path 3 scheduled fetching → intelligence capability is also there, initially used to feed cards, not separately marketed

## Consequences

**Benefits**

- Narrative is focused; first user persona is clear (exam communities, language-learning communities)
- MVP scope is controlled; architecture decisions have a clear anchor (deep around "cards + SRS + mistakes")
- Subsequent expansion is a **natural evolution driven by user needs**, not arbitrarily layered on

**Costs / Constraints**

- Requires up-front restraint: even capabilities that *could* be in scope ("knowledge-base / intelligence" features) should not become the external narrative unless they serve the learning scenario
- Architecture must leave extension points for later stages (MD foundation, capability plugin-ization, first-class domain entities, etc.); otherwise stage 2 augmentation will hit walls
- Avoid marketing as an "all-in-one PKM" early — preserves clarity of mindshare

**Analogy**

Notion was also originally all-in-one (notes + database + wiki + tasks), but broke through with the extremely focused slogan "all-in-one workspace", penetrating "startups tired of switching between tools" — a niche segment. Only after establishing a foothold did it expand to individuals, enterprises, and education. Knowlet follows the same logic: **capabilities are full, but the story must be narrow.**
