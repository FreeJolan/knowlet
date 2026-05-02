# 0014 — Note-quiz mode / Scope-driven active recall

> **English** | [中文](./0014-note-quiz-mode.md)

- Status: Proposed
- Date: 2026-05-02

## Context

[ADR-0012](./0012-notes-first-ai-optional.en.md) pins the identity ("notes app + AI as optional augmentation"); [ADR-0013](./0013-knowledge-management-contract.en.md) handles the **fragmentation** problem on the *passive* review side (entry-point ambient / passive structuring / periodic digest).

But ADR-0013 §4 calls out a problem the passive side cannot fix:

> When the user collaborates with AI to build a Note, AI does the heavy lifting of "extract key points / summarize concepts." The Note exists, but **learning may not have happened**. Active recall (self-testing) is the canonical remedy for this kind of bleed.

[ADR-0001 (archived)](./archive/0001-wedge-learning-first.en.md) had `AI question generation + wrong-answer recycling` as part of the original wedge — but **as an SRS exam tool** (Form A). [ADR-0003](./0003-wedge-pivot-ai-memory-layer.en.md) cut the entire branch when pivoting to Form B.

This ADR **revives the idea inside the Form B frame**, but completely reshaped: it's no longer SRS exam prep — it's **user-summoned, scope-driven active recall, AI generates questions, AI grades advisory, complementary to (not a replacement for) Cards**.

## Decision

### 1. Three core decisions

#### (a) User-summoned, scope-explicit

**No automatic "let me quiz you" popups, ever.** The user must trigger explicitly, and must pick a scope:
- A single Note ("Quiz me on this")
- Multiple Notes (multi-select in file tree → quiz)
- A tag / cluster (after Layer B knowledge map ships)

**Anti-pattern**: Anki / Duolingo's "N cards due, push notification" passive flow — that's the Cards lane. This modality is "I want to test my understanding of this RAG cluster *now*."

#### (b) AI generates questions; multiple types

Avoid shallow questions ("list the 3 key points of this Note" — that's extraction, not active recall). Force question-type variety:

| Type | Example | What it tests |
|---|---|---|
| Concept explanation | "Explain in your own words what `k` does in RRF" | Internalization |
| Application | "If a vault has 10K Notes, is `k=60` still appropriate? Why?" | Transfer |
| Contrast | "On which query types do BM25 and cosine fail differently?" | Discrimination |
| Inference | "If vector recall fails entirely, can RRF still produce a meaningful result?" | Reasoning |
| Recall | "What is cross-encoder re-ranking? When should you use it?" | Recall + application |

The generation prompt requires ≥ 3 question types out of N.

**Explicit rejection** for these question shapes:
- Answers found verbatim by ctrl-F over source Notes → too shallow
- "Summarize the key points" → extraction, not recall
- Open-ended discussion with no ground truth → ungradeable

#### (c) AI grading is advisory, not authoritative

**Grade must include reasoning + a one-click user override.** Same family as ADR-0013 §1's contract: AI provides information, human decides.

Per question display:
```
Question:        [...]
Your answer:     [...]
AI reference:    [...]
AI score:        [n/5] · [reason]
[ ✓ I agree ]    [ ✗ I disagree ]   ← disagree opens a reason text box
```

Session summary **must** show the disagreement count: "5/7 correct (you disagreed with AI on 1)." **The system never decides for the user whether they got it right.**

### 2. Quiz session lifecycle

```
[user] trigger → [scope picker] → [generation] → [N-question loop] → [summary + reflux entry]
   │              │                  │              │                       │
   palette        Note / Notes /     LLM call       answer + grade          Cards reflux (opt)
   Cmd+K          tag / cluster      generates N    + user confirms         past-quiz archive
   or Note        (P2 only)
   right-click
```

**Trigger points**:
- Cmd+K palette command: `Quiz me`
- Single-Note right-click / icon: `Quiz me on this`
- File-tree multi-select action: `Quiz me on these`
- (P2) inside a tag or cluster view: `Quiz me on this cluster`

**After generation**: user sees "N questions generated, based on [scope summary]"; can `Start` / `Regenerate` / `Cancel`.

**During the loop**: each question is shown standalone; no time pressure (active recall isn't a timed exam); `pause` / `quit` always available (whatever's been answered is archived).

**Summary**: shows score (with disagreement annotation) + missed-question list + per-question "Make a Card" 1-click.

### 3. Question quality (the technical load-bearing piece)

Like ADR-0013 §6, this is the engineering hard part.

#### 3.1 Generation prompt skeleton

```
You are creating an active-recall quiz for a knowledge worker who wrote
the following notes. Generate {n} questions across at least 3 of these
types: concept-explanation, application, contrast, inference, recall.

Requirements:
- Each question must NOT be answerable by ctrl-F over the source notes
  (no "what are the 3 key points" style; no quote-then-fill).
- Each question must have a defensible reference answer using only the
  source notes (don't invent facts not in the notes).
- Mix question types — a quiz of 5 must use at least 3 different types.
- Use the same language the notes are in.

Source notes:
[source ...]

Output strict JSON: {questions: [{type, question, reference_answer, source_note_ids}]}.
```

#### 3.2 Rejection / regeneration

If the LLM's questions don't satisfy the requirements (subjective user judgment / heuristic detection like "≥50% of question text overlaps source verbatim"), provide a `Regenerate` button. **Don't charge for the second attempt** — free Q&A regeneration shouldn't make the user hesitate (active recall value ≫ token cost).

#### 3.3 Default session length

**Default 5 questions per session; user can adjust via the scope picker's "Advanced settings" entry** (one-shot for this session, or check `Remember this setting` to persist to vault config). Reasoning:
- Too few (1-2): high variance in error rate
- Too many (15+): fatigue; active recall has diminishing returns
- 5 questions ≈ 5-10 minutes, comparable to a Cards review session

Aligns with [`feedback_default_plus_advanced_override`](memory) — give a default; allow temporary or persistent override via UI advanced settings.

### 4. Grading model

#### 4.1 Score scale

**Per-question 1-5 (integer)** — borrows from FSRS's 1-4 with one extra slot ("excellent, beyond expected"):
- 1 Completely wrong / no answer
- 2 Right direction but missed key elements
- 3 Hit the key but with omissions / drift
- 4 Complete and accurate
- 5 Complete, accurate, and added reasonable inference beyond the source notes

Reasoning: LLMs are **unstable** at percentage grading (95 vs 88 has no real distribution support inside the model); a 5-level scale gives stable discrimination.

**Session final score = 0-100 integer** (locked 2026-05-02 by user).

Aggregation formula:
```
session_score = round( (sum_of_per_question_scores / (n_questions * 5)) * 100 )
```

Reasoning: users have intuition for 0-100 (passing 60, excellent 90), and it makes "I scored 70 on RAG cluster six months ago, 85 today" comparable. **But per-question stays at 1-5** — single questions have no comparable longitudinal data, and percentages just create false-precision angst (95 vs 88).

#### 4.2 Grading prompt skeleton

```
Grade the user's answer to the quiz question. Output strict JSON:
{score: 1..5, reason: "...", missing: ["...", ...]}.

Be charitable — if the user uses different wording but covers the same
concept, full credit. Don't penalize formatting / brevity.

Question: [...]
Reference answer: [...]
User's answer: [...]
```

#### 4.3 User override

`Disagree` opens a (possibly empty) text box; the reason is stored on the session. The session summary always shows `correct / disagreement` separately rather than a single conflated total.

### 5. Storage model

#### 5.1 Trade-off

- **Ephemeral** (close it, gone): aligns with ADR-0013 anti-fragmentation; simpler.
- **Persistent**: enables "review my past mistakes," supports Cards reflux which needs the Q+A pair retained, supports long-term active-recall progress tracking.

#### 5.2 Decision

**Persistent, but kept out of the main UI.**

- Path: `<vault>/.knowlet/quizzes/<id>.json`
- **Not in** `notes/` file tree
- **Not in** the main UI listings (Notes / Drafts / Cards)
- Access entry: a dedicated "Past quizzes" focus mode (M7.4 Phase 3).
- Aging policy: **default 90-day archive to `.knowlet/quizzes/.archive/`**, except sessions that produced a Cards reflux (the user learned from those — worth keeping longer).
- Cadence is user-configurable (same pattern as ADR-0013 Layer C).

Session schema sketch:
```json
{
  "id": "<ulid>",
  "started_at": "...",
  "finished_at": "...",
  "model": "claude-opus-4-7",
  "scope": {
    "type": "notes" | "tag" | "cluster",
    "note_ids": ["..."],
    "tag": "...",
    "cluster_id": "..."
  },
  "questions": [
    {
      "type": "concept-explanation",
      "question": "...",
      "reference_answer": "...",
      "source_note_ids": ["..."],
      "user_answer": "...",
      "ai_score": 4,
      "ai_reason": "...",
      "user_disagrees": false,
      "user_disagree_reason": null,
      "card_id_after_reflux": null
    }
  ],
  "summary": {
    "n_questions": 5,
    "n_correct": 4,
    "n_disagreement": 1,
    "cards_created": 2
  }
}
```

### 6. Cards reflux

The session summary lists **all missed questions** (AI score < 3 or user marked unsure) with checkboxes + a `Make Cards in bulk` button (locked 2026-05-02 by user):

- **Missed-question list defaults to all checked**; user unchecks the ones they don't want.
- Each Card draft is inline-editable (front / back / tags).
- `back` defaults to `reference_answer`; user can rewrite to their corrected version.
- `tags` defaults to source-Note tags ∪ `{quiz}`.
- `source_note_id` filled when known.

**Only missed questions enter the reflux candidate list** (correct answers don't get a "Make a Card" prompt — avoids redundant Cards).

This **echoes the "wrong-answer recycling" idea cut from ADR-0001, but completely different in the Form B frame**: not "an exam-system mistake notebook," but "targeted spaced retrieval for the cognitive gaps surfaced by active recall."

### 7. Boundaries

| vs | Difference |
|---|---|
| Cards / FSRS | Cards = atomic-fact-level, time-driven SRS scheduling, passive lane; Quiz = cross-Note active recall, user-driven, scope-explicit |
| ADR-0013 Layer C digest | Digest is passive ("here's what's new / aging this period"); Quiz is active ("quiz me on this cluster") |
| ADR-0013 §6 Similarity | Quiz scope picker may **use** similarity for "based on this Note, find related ones to quiz on" as a UX add-on, **but that's enhancement, not core** |
| ADR-0001's cut "AI quiz" | The old framing was OCR + SRS Card + AI questions (Form A exam prep); this ADR is Form B knowledge-worker active recall — Cards remain passive SRS, Quiz is a *new* modality |

### 8. Implementation phases (M7.4)

| Phase | Scope | Acceptance |
|---|---|---|
| **M7.4.0** | Design prompts + run generation + grading via CLI (no UI) | Command line produces readable questions + advisory grades |
| **M7.4.1** | UI MVP: scope = single / multi-Note manual select; question types = concept + recall; advisory grading **without** disagreement loop | User can trigger from palette / Note and complete a 5-question flow |
| **M7.4.2** | + 4 question types + disagreement loop + Cards reflux | Summary supports per-row "Make Card" + disagreement reason field |
| **M7.4.3** | + tag / cluster scope (depends on ADR-0013 Layer B landing) + past-quizzes focus mode + 90-day aging | Past quizzes browseable; scope picker supports tags |

Each phase commits independently; one tag `m7.4` for the whole milestone.

## Decisions locked (user, 2026-05-02)

1. **Score scale** — per-question 1-5 integer; session-final 0-100 integer (formula in §4.1)
2. **Default session length** — 5 questions; user can override per-session or persist via scope-picker advanced settings (§3.3)
3. **Quiz UI form** — dedicated focus mode `Cmd+Shift+Q`, peer to chat / drafts / cards focus modes
4. **Cards reflux default** — only missed questions enter the candidate list; **list defaults to all checked**; user can uncheck unwanted ones; supports inline edit (§6)
5. **When generation is unsatisfactory** — `Regenerate` is unlimited (active-recall value ≫ token cost; don't gate this)

## Consequences

### After this lands

- **Each new ADR-0013 Layer A/B/C feature is mirrored by Quiz on the active side**: the fragmentation-governance side handles passive review, Quiz handles active review — the product story is whole.
- **Cards reflux from Quiz becomes a primary new-Card-creation path** (currently Cards mostly come from chat-driven LLM generation or CLI hand-write).
- **`.knowlet/quizzes/` is the third LLM-generated persistent data shape inside a vault** (after `notes/` and `drafts/`); needs a one-line addition to ADR-0006 §"Rebuild" (M7.4.1 commit).

### Risks / costs

- **Question quality is a non-deterministic LLM output**; P@quality may sit < 0.7 — needs prompt calibration during dogfood.
- **AI grading vs. ADR-0013 §1 contract**: grading IS judgment, but because it's advisory + always shows disagreement, **the user holds final authority** — the contract isn't violated.
- **Long-term storage outside the main vault**: some users may want "find that quiz I took six months ago"; the 90-day aging needs dogfood calibration.
- **scope = tag / cluster depends on Layer B landing**; P3 cannot proceed in parallel with ADR-0013 Layer B work.

### Relation to existing ADRs / memories

- Delivers on [ADR-0013](./0013-knowledge-management-contract.en.md) §4's promise that "ADR-0014 is the other review modality."
- Lands all of `project_knowlet_note_quiz_idea` memory (5 待考虑 points + Cards comparison + history).
- Reverse-informs [ADR-0001 (archived)](./archive/0001-wedge-learning-first.en.md): the "wrong-answer recycling" idea cut there reappears, reframed for Form B; ADR-0001's archive note can be amended to point here.
- Triggers a small change in [ADR-0006](./0006-storage-and-sync.en.md): `.knowlet/quizzes/` joins the rebuild-mechanism listing (done at M7.4.1 commit).

### Decision provenance

- User's exact words (2026-05-02):
  > When the user and AI collaborate to build a Note, the user can select (multiple) notes — even select a topic / label (tag) — and have the AI generate questions and grade. This realizes the user's "active absorption" goal, since AI participation otherwise siphons off the reward of building the knowledge.
- The 5 待考虑 points came from `project_knowlet_note_quiz_idea` memory (organized 2026-05-02).
- Same-period as ADR-0013: when the user locked ADR-0013's open questions, they confirmed "draft ADR-0014 immediately after this one."
- Historical link: ADR-0001's (2026-04-30, archived) SRS-exam-prep wedge was cut, but the "AI generates questions" idea regains value in the Form B frame; the two ADRs echo conceptually but tell completely different product stories.
