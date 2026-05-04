# 0013 — Knowledge-management contract / fragmentation-governance three-layer framework

> **English** | [中文](./0013-knowledge-management-contract.md)

- Status: Proposed
- Date: 2026-05-02

## Context

[ADR-0003](./0003-wedge-pivot-ai-memory-layer.en.md) names the wedge as "AI long-term memory layer." [ADR-0012](./0012-notes-first-ai-optional.en.md) pins the identity to "personal knowledge base / notes app + AI as optional augmentation." Neither answers a question that will surface within six months:

> Every chat sediment + every approved mining draft = +1 Note. M2-M6 dogfood already piled up 37+ Notes in `/tmp/knowlet-real`; six months of real use will reach 1000+. **Nothing in the system lets the user manage that pile without anxiety.**

The user, in dogfood feedback, called this "fragmentation hell" and emphasized:

> LLMs do not have real judgment. If knowledge ultimately serves the human, the human is responsible for the accuracy of that knowledge.

This principle has to extend from ADR-0012's "AI is optional" into a more concrete contract: **structural changes must be triggered by the human; AI may only point out possibilities**. This ADR pins the contract + the matching three-layer response framework as a hard constraint for every "management-class" feature in M7+.

## Decision

### 1. Core contract: AI does not silently change the IA

**Any action that changes vault structure (`notes/` directory, Note content, the tag set, filenames) must require an explicit user click. It cannot happen via default values or background tasks.**

| Type | Allowed | Forbidden |
|---|---|---|
| AI computes clusters / near-duplicates / aging candidates | ✅ (background compute) | — |
| AI suggests merge / split / archive | ✅ (shown as information; default action unchanged) | ❌ Pre-selecting "Merge" as the default button |
| AI auto-archives stale Notes | — | ❌ (including "30 days untouched → archive automatically") |
| User clicks "Merge these two" in the UI | ✅ | — |
| Weekly digest "Archive these 5" — per-row click | ✅ | ❌ "Archive all" bulk button (bulk only via user-selected items) |

This grounds [ADR-0012](./0012-notes-first-ai-optional.en.md)'s "AI is optional" from semantic to behavioral. **ADR-0012 answers "is AI here at all"; this ADR answers "when AI is here, what may it do."**

### 2. Four independent fragmentation mechanisms

Listed so we can pick the right tool for each. Three of these get a layer in the framework; one is a structural paradox handled by the contract above.

| # | Mechanism | Current state | Layer that addresses it |
|---|---|---|---|
| ① | No back-pressure on creation | chat sediment + approved drafts = +1 Note, no counterforce | **Layer A — entry-point ambient** |
| ② | Similarity signal invisible | knowlet has FTS5 + vector indexes that *know* which Notes are about the same thing — **but used only for retrieval, never to guide organization** | **Layer B — passive structuring** |
| ③ | No aging tier | every Note stays "live" forever; in real human knowledge ~80% of Notes are written once and never touched again | **Layer B — passive structuring** |
| ④ | No cross-corpus review trigger | the user only ever sees the local state of the current Note, not cross-cuts | **Layer C — periodic digest** |

### 3. Three-layer framework

#### Layer A — entry-point ambient (M7 candidate)

When the user is about to create a new Note (sediment / approve draft / manual new), **ambient-display top-3 similar Notes** (vector neighbors). No "Suggest merge" verb, no preselected action.

- **The default action is always "Create new"**; merge requires explicit user click.
- Display style is reference-preview-like, not a "suggestion" prompt.
- **No "AI thinks this should merge into X" popups / notifications.**

This grounds the §1 contract: AI provides information, human makes the decision.

#### Layer B — passive structuring (M8 candidate)

The system continuously computes structural signals **in the background, without push notifications**. The user enters a "knowledge map" sidebar to see them:

- Near-duplicate pairs (cosine > threshold)
- Note clusters (over embeddings; k-means / HDBSCAN)
- Orphan Notes (no inbound links + low retrieval frequency + months untouched)
- Aging candidates

**Compute, don't act.** Seeing "3 highly similar" the user merges them themselves; seeing "5 untouched for 6 months" the user archives them themselves. The system never presses the button on the user's behalf.

Explicitly out:
- ❌ Graph view (ADR-0011 already locked: not built)
- ❌ Tag taxonomy (top-down forced classification is a known Notion failure mode)
- ❌ Auto-archive / auto-merge (violates §1 contract)

#### Layer C — periodic digest (M8 candidate)

**The cadence is user-configurable** (start date + every-N-days). Default is 7 days (a weekly digest); the user can change it to 14, 30, or any custom interval. **A weekly digest is not enforced**, but it's the default because daily-frequency triggers backlog guilt loop (the standard Roam / Obsidian failure mode).

Tone: **Sunday newspaper**.
- Information-dense, no nagging.
- **No unread badge** — must be "close it and walk away."
- Content shape (candidates; calibrate during implementation):
  - N notes added this period + 3 longest titles
  - 1-2 Layer B cluster-collapse suggestions (still per-row click required)
  - 5 aging candidates (same)

**Explicitly NOT FSRS / forgetting-curve.** FSRS works well on Cards; at the Note level, "should you reread Note X today?" elicits "I haven't forgotten, I just don't have time" — the metric is uninterpretable. Two independent review tracks > one shared track.

### 4. Boundaries with existing systems

#### Relation to Cards / FSRS

- **Cards = atomic-fact level** (front/back, binary 1-4 self-rating, FSRS scheduling, persistent).
- **Note-level review does NOT use SRS**, because it's not a remember/forgot binary; it's a cross-corpus "still relevant? archive?" judgment.
- The periodic digest **does not** start FSRS reviews on Notes. If the user wants to turn a Note's key points into Cards, they go through "generate Card from Note" (existing tool).

#### Relation to note-quiz mode (`project_knowlet_note_quiz_idea` memory)

Note-quiz mode (scope-driven AI-generated questions + advisory grading) is a **third review modality**, orthogonal to Layer C:

- **Layer C digest**: passively receive "what did I write this period; what should I tidy up."
- **Note-quiz**: actively summon "quiz me on this cluster of notes."

The grading half of quiz mode necessarily involves AI making a judgment, which sits at the §1 contract boundary. The handling: **grading must be advisory (give reasoning + score; user makes the final call), not authoritative**. Quiz mode gets its own ADR (drafted right after this one).

### 5. Implementation boundaries

- This ADR **only locks the framework + contract**; specific UI / thresholds / algorithms are out of scope.
- Each layer (A / B / C) needs an independent design pass (prototype + threshold calibration + dogfood).
- All three layers are in scope (user confirmed 2026-05-02), but **no enforced order**; Layer A is the smallest unit and can ship standalone to validate the entry-point feel.
- Aging thresholds / cosine thresholds / digest frequency are calibrated with the user during dogfood, not hard-coded here.
- Layer B "knowledge map" UI position (AI dock sub-tab vs. dedicated focus mode) is deferred to implementation.
- Note-quiz mode: see [ADR-0014](./0014-note-quiz-mode.en.md) (drafted right after this ADR lands).

### 6. Similarity model (the technical load-bearing piece)

> User pointed out (2026-05-02): "Similarity judgment determines feature effectiveness; everything else is just experience." This section pins the design principles for similarity; specific thresholds are calibrated during implementation.

#### 6.1 Operational definition precedes accuracy

The "similarity" each layer cares about is **a different relation**. Don't measure them with one metric.

| Used in | Relation we want | Failure mode |
|---|---|---|
| Layer A entry ambient | Same-topic close neighbors not yet merged | **Precision first**: one false positive and the user learns to ignore the entire ambient region |
| Layer B near-duplicate | Almost the same content (high cosine + high keyword overlap, both high) | False positive → user merges Notes that should have stayed separate |
| Layer B clusters | Same-domain clusters (granularity tunable) | Too coarse → everything in one cluster, useless; too fine → each Note its own cluster |
| Layer B + C aging / orphans | Whether a Note still connects to recent activity (inbound links + retrieval frequency + most-recent touch) | False orphan → user misses Notes that were still useful |

#### 6.2 Precision over recall (especially Layer A)

**Layer A hard target: `P@3 ≥ 0.67`** (at least 2 of 3 ambient items judged "actually relevant" by the user).

Why: ambient is something the user sees every day. **If 30% is noise, the other 70% gets ignored along with it** (the Notion AI / Roam Copilot death sentence). Recall doesn't matter — missing one related Note is fine; the user can still create the new Note.

Layer B near-duplicate: `cosine > 0.85 AND keyword Jaccard > 0.4` (cross-threshold). Better to skip than over-claim.

Layer B clusters: no ground truth available; **dogfood-calibrated granularity** (user judges "does this cluster make sense").

#### 6.3 Performance budget

| Path | Budget | Current ability |
|---|---|---|
| Layer A entry top-K (<200ms) | < 200ms | sqlite-vec at ~5000 Note scale ≈ 50ms ✓ |
| Layer B cluster batch | < 5s | 5000 × 384-dim cosine all-pairs ≈ 200ms ✓ |
| Embedding recompute (per-Note edit) | already gated by `content_hash` skip-if-unchanged ✓ | — |
| Burst-creation scenario (5 sediments in a row) | async / batched; do not block the entry flow | **needs confirmation during implementation** |

#### 6.4 Explainability — evidence column is mandatory

cosine 0.87 can't tell you why two Notes are close. Any ambient / near-duplicate display **must carry evidence**:
- Shared keywords (top 3-5, drawn from BM25 high-scoring sentence pairs)
- Shared tags
- (Optional, after wikilinks ship) co-citation

**Similarity displays without evidence don't ship.** This turns "AI thinks they're close" into "AI shows you the evidence; you decide" — same family as the §1 contract.

#### 6.5 Hybrid signal beats pure embedding

Pure cosine has known failure modes: short Notes vs. long Notes can falsely look similar; abstract concepts vs. concrete examples may be high-cosine but shouldn't merge; cross-language synonyms (English "RAG" vs. Chinese "检索增强") have low cosine despite same topic.

knowlet already has multiple signals on hand; use them all:
- **Vector cosine** (primary)
- **BM25 / FTS5** (already in place): catches named entities, function names, citations
- **Tag overlap** (cheapest user-curated signal)
- **Co-citation** (after wikilinks land)

Formula skeleton (weights calibrated in implementation; not hard-coded here):
```
score = w1·cosine + w2·bm25_score + w3·tag_jaccard  (+ w4·co_citation)
```

Per-layer weights differ: Layer A leans on cosine; Layer B near-duplicate requires cosine + BM25 both high; Layer B clustering is cosine-dominant (paired with the clustering algorithm's distance metric).

#### 6.6 Calibration — thresholds are NOT hard-coded

Thresholds are dataset-dependent: an academic-paper vault and a journal-entry vault have completely different similarity distributions.

Implementation must:
1. **Hand-label ~50 pairs during dogfood** (each pair: near-duplicate / same-topic-but-independent / unrelated)
2. Compute ROC, pick the threshold that yields `P@3 ≥ 0.67`
3. Give the user a **per-vault manual dial** (`config set similarity.threshold 0.85` or a UI slider)
4. Switching the embedding model = full re-embed + re-calibration (a known cost)

## Consequences

### Hard constraints once this lands

- **Every new feature must answer two questions** before shipping (ADR-0012's "what is this with AI=0" + this ADR's "does this change the IA"):
  - Changes IA → must require an explicit click; no default-action shortcut
  - Doesn't change IA (pure compute / display) → free
- Any PR introducing an "AI auto-archive / merge / split" path is rejected at review.

### Relation to existing ADRs / memories

- Extends [ADR-0012](./0012-notes-first-ai-optional.en.md): AI-optional is the macro contract; this is the sub-contract for "when AI is on."
- Lands the entire content of `project_knowlet_fragmentation_thinking` memory (4 mechanisms + three-layer + IA contract).
- **Orthogonal** to `project_knowlet_note_quiz_idea` memory: this ADR handles passive review; quiz handles active review. ADR-0014 covers the quiz side.
- Consistent with [ADR-0011](./0011-web-ui-redesign.en.md)'s "explicitly no graph view"; Layer B knowledge-map ≠ graph view (graph is Note→Note link visualization; the Map is a cluster / duplicate / orphan signal aggregator).
- Triggers [`feedback_no_hidden_debt`](memory) §6: once this is locked, no M7+ feature can ship-fast-then-add-IA-contract-later.

### Risks / costs

- **Layer A's "show top-3 similar" adds a cognitive step at the entry flow**. The user sees it on every new Note. If implementation is noisy (busy / "AI is nagging"), it will repel the user. Calibrate via dogfood.
- **Layer B background cluster cost** (at thousands of Notes scale): k-means / HDBSCAN on a vector index isn't heavy but the first run could be O(seconds). Tune to data scale.
- **Layer C digest quality depends on Layer B signal quality**. If clustering produces many false positives (mis-grouping unrelated topics), the digest gets noisy. Validate B before shipping C.
- **Not building graph view / tag taxonomy** is an explicit commitment; future requests for those will be pushed back against this ADR.

### Decision provenance

- User's exact words (2026-05-02 dogfood feedback):
  > In typical use, users keep accumulating notes through daily conversation and subscription pushes; without management, the user faces fragmentation hell ... LLMs lack real judgment. If knowledge ultimately serves the human, the human is responsible for the accuracy of that knowledge.
- The user's two rough early ideas (entry-time integration; daily / weekly digest + forgetting curve) were critiqued and folded into this ADR.
- User locked the four open questions on 2026-05-02:
  1. Build all three layers (boldly validate everything).
  2. Digest cadence is user-configurable (start date + every-N-days).
  3. Layer B Map UI position deferred to implementation.
  4. ADR-0014 (note-quiz mode) drafted right after this ADR lands.
- Triggered by 2026-05-02 dogfood + the second-opinion review's critique #6 (product-positioning internal contradiction) — ADR-0012 resolved the macro layer; this ADR handles the natural follow-on "OK, when AI is here, what can it do?"

## Amendment (2026-05-04 — coordinating with ADR-0003 amendment)

§3 Layer B's "explicitly not doing" list, item 1:

> ❌ Graph view (ADR-0011 already decided no)

**Reversed.** Per [ADR-0003 amendment (2026-05-04)](./0003-wedge-pivot-ai-memory-layer.en.md#amendment-2026-05-04--user-course-correction),
bilinks + graph are core knowledge software capabilities;
ADR-0011 has also withdrawn its "vanity feature" verdict. The
matching update here:

- **Graph view ≠ Layer B "knowledge map sidebar"**, but they
  **coexist in M8**, not either/or:
  - **Graph view** = visualization of user-authored `[[Title]]`
    link relationships (ground truth, user-validated relationships)
  - **Layer B knowledge map sidebar** = LLM-inferred structural
    signals (cluster / near-duplicate / orphan / aging — *auxiliary*
    signals, not user-validated relationships)
  - The two UI layers complement, not replace each other

§3 Layer B's other excluded items **stand**:
- ❌ Tag taxonomy (top-down forced classification remains a fail mode)
- ❌ Auto-archive / auto-merge (violates §1 contract)

§7 boundary table (`vs ADR-0011's "explicitly no graph view"`) row is
likewise voided; ADR-0011's amendment handles the symmetric update.
