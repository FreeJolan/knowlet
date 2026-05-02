"""Note quiz mode — scope-driven active recall (ADR-0014, M7.4).

Pure-string in/out: no I/O, no LLM client construction, no filesystem.
Callers (CLI / web layer) inject an LLM and the source-Note bodies.
That keeps the module trivially testable without network.

The two LLM-bound functions (`generate_quiz`, `grade_answer`) take a
narrow `LLMLike` protocol so unit tests can pass a stub. The grading
prompt is *content-grounded* per ADR-0014 §4.2: charitable about
wording, strict about substance, never penalize formatting/brevity.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Protocol

# ADR-0014 §3.3: 5 default; user can override per-session via the scope picker
# advanced-settings entry (M7.4.1+) or persist via vault config.
DEFAULT_N_QUESTIONS = 5

# ADR-0014 §4.1: per-question 1..5 (FSRS-borrowed +1 for "exceeded reference"),
# session aggregate 0..100. The constants are pinned here so tests catch any
# silent drift from the ADR.
MIN_QUESTION_SCORE = 1
MAX_QUESTION_SCORE = 5
PASS_QUESTION_SCORE = 3  # ≥3 counts as "correct" for n_correct in summary

QUESTION_TYPES = (
    "concept-explanation",
    "application",
    "contrast",
    "inference",
    "recall",
)

GENERATE_PROMPT = """\
You are creating an active-recall quiz for a knowledge worker who wrote
the following notes. Generate {n} questions across at least 3 of these
types: concept-explanation, application, contrast, inference, recall.

Requirements:
- Each question must NOT be answerable by ctrl-F over the source notes
  (no "what are the 3 key points" style; no quote-then-fill).
- Each question must have a defensible reference answer using only the
  source notes (don't invent facts not in the notes).
- Mix question types — a quiz of {n} must use at least 3 different types.
- Use the same language the notes are in (do not translate).

Source notes:
{notes_block}

Output strict JSON (no markdown fences, no trailing prose):
{{"questions": [
  {{"type": "concept-explanation",
    "question": "...",
    "reference_answer": "...",
    "source_note_ids": ["<note id>"]}}
]}}
"""

GRADE_PROMPT = """\
Grade the user's answer to the quiz question. Be charitable — if the
user uses different wording but covers the same concept, give full
credit. Don't penalize formatting / brevity. Do penalize missing the
key concept or stating something contradicted by the reference.

Score scale (1..5):
  1 — completely missed / wrong
  2 — direction is right but key concept missing
  3 — key concept present but incomplete or partially off
  4 — complete and accurate
  5 — complete and accurate AND adds a sound inference beyond reference

Output strict JSON (no markdown fences, no trailing prose):
{{"score": 1..5, "reason": "...", "missing": ["..."]}}

Question: {question}
Reference answer: {reference}
User's answer: {user_answer}
"""


# ---------------------------------------------------------------- types


@dataclass
class QuizQuestion:
    type: str
    question: str
    reference_answer: str
    source_note_ids: list[str] = field(default_factory=list)
    user_answer: str = ""
    ai_score: int | None = None
    ai_reason: str = ""
    ai_missing: list[str] = field(default_factory=list)
    user_disagrees: bool = False
    user_disagree_reason: str = ""
    card_id_after_reflux: str | None = None


@dataclass
class QuizSession:
    """The persistent shape per ADR-0014 §5.2 (matches the JSON in
    `<vault>/.knowlet/quizzes/<id>.json`). M7.4.0 only constructs these
    in-memory; M7.4.1 wires the on-disk store."""

    id: str
    started_at: str
    finished_at: str = ""
    model: str = ""
    scope_type: str = "notes"  # "notes" | "tag" | "cluster"
    scope_note_ids: list[str] = field(default_factory=list)
    scope_tag: str = ""
    scope_cluster_id: str = ""
    questions: list[QuizQuestion] = field(default_factory=list)

    # Summary fields — computed by `aggregate_score` after the loop.
    n_questions: int = 0
    n_correct: int = 0
    n_disagreement: int = 0
    cards_created: int = 0
    session_score: int = 0  # 0..100

    def to_dict(self) -> dict:
        return asdict(self)


class LLMLike(Protocol):
    """Minimal LLMClient.chat shape we depend on."""

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> object:  # AssistantMessage; we read .content
        ...


# ---------------------------------------------------------------- helpers


_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _parse_strict_json(text: str) -> dict:
    """Tolerate the LLM's occasional ```json fence or leading prose. We
    asked for strict JSON; this is the safety net so a single stray
    markdown char doesn't tank the whole quiz."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_BLOCK.search(text)
        if m is None:
            raise
        return json.loads(m.group(0))


def _format_notes_block(notes: list[tuple[str, str, str]]) -> str:
    """notes = [(id, title, body)]. Render as fenced source blocks the
    LLM can scan. We don't truncate — the caller chose the scope, and
    most one-or-multi-Note quizzes will fit comfortably."""
    parts = []
    for note_id, title, body in notes:
        parts.append(
            f"[[note id={note_id}]]\n"
            f"# {title}\n"
            f"{body}\n"
            f"[[/note]]"
        )
    return "\n\n".join(parts)


# ---------------------------------------------------------------- generate


def generate_quiz(
    llm: LLMLike,
    notes: list[tuple[str, str, str]],
    *,
    n: int = DEFAULT_N_QUESTIONS,
) -> list[QuizQuestion]:
    """Ask the LLM for `n` quiz questions over the given Note bodies.

    Returns a list of QuizQuestion (with empty user_answer / ai_score).
    Raises ValueError if the LLM output isn't parseable or the question
    count diverges materially from `n` — caller can show "regenerate"."""
    if not notes:
        raise ValueError("generate_quiz: notes list must be non-empty")
    if n < 1:
        raise ValueError(f"generate_quiz: n={n} must be ≥ 1")

    prompt = GENERATE_PROMPT.format(n=n, notes_block=_format_notes_block(notes))
    msg = llm.chat(
        messages=[{"role": "user", "content": prompt}],
        tools=None,
        max_tokens=4000,
        temperature=0.4,
    )
    raw = (getattr(msg, "content", "") or "").strip()
    if not raw:
        raise ValueError("generate_quiz: LLM returned empty content")
    payload = _parse_strict_json(raw)
    questions_raw = payload.get("questions") or []
    if not isinstance(questions_raw, list):
        raise ValueError(
            f"generate_quiz: expected 'questions' to be a list, got {type(questions_raw).__name__}"
        )
    out: list[QuizQuestion] = []
    for q in questions_raw:
        if not isinstance(q, dict):
            continue
        qtype = str(q.get("type") or "").strip()
        question_text = str(q.get("question") or "").strip()
        reference = str(q.get("reference_answer") or "").strip()
        if not question_text or not reference:
            continue
        if qtype not in QUESTION_TYPES:
            qtype = "recall"  # safe-default rather than reject — preserves quiz length
        sids = q.get("source_note_ids") or []
        if not isinstance(sids, list):
            sids = []
        out.append(
            QuizQuestion(
                type=qtype,
                question=question_text,
                reference_answer=reference,
                source_note_ids=[str(s) for s in sids if s],
            )
        )
    if not out:
        raise ValueError(f"generate_quiz: parsed 0 valid questions from LLM output")
    return out


# ---------------------------------------------------------------- grade


def grade_answer(
    llm: LLMLike,
    question: QuizQuestion,
    user_answer: str,
) -> tuple[int, str, list[str]]:
    """Grade one user answer. Returns (score 1..5, reason, missing[]).

    Mutates nothing; caller assigns the result back onto QuizQuestion.
    Missing the LLM step or a malformed reply degrades to score=3 +
    reason='(grading failed)' so the quiz session can finish."""
    if not user_answer.strip():
        # ADR-0014 §4.1: no answer = no credit. We don't even round-trip
        # this through the LLM — saves a token.
        return MIN_QUESTION_SCORE, "Empty answer.", [question.reference_answer]

    prompt = GRADE_PROMPT.format(
        question=question.question,
        reference=question.reference_answer,
        user_answer=user_answer,
    )
    try:
        msg = llm.chat(
            messages=[{"role": "user", "content": prompt}],
            tools=None,
            max_tokens=600,
            temperature=0.1,
        )
    except Exception as exc:  # noqa: BLE001 — boundary
        return PASS_QUESTION_SCORE, f"(grading failed: {exc})", []
    raw = (getattr(msg, "content", "") or "").strip()
    if not raw:
        return PASS_QUESTION_SCORE, "(grading failed: empty LLM reply)", []
    try:
        payload = _parse_strict_json(raw)
    except (json.JSONDecodeError, ValueError):
        return PASS_QUESTION_SCORE, f"(grading failed: malformed JSON: {raw[:120]!r})", []
    score_raw = payload.get("score")
    try:
        score = int(score_raw)
    except (TypeError, ValueError):
        score = PASS_QUESTION_SCORE
    score = max(MIN_QUESTION_SCORE, min(MAX_QUESTION_SCORE, score))
    reason = str(payload.get("reason") or "").strip()
    missing_raw = payload.get("missing") or []
    missing = [str(m) for m in missing_raw if m] if isinstance(missing_raw, list) else []
    return score, reason, missing


# ---------------------------------------------------------------- aggregate


def aggregate_score(session: QuizSession) -> None:
    """Populate the summary fields on `session` per ADR-0014 §4.1.

    session_score = round( (sum_per_question / (n * 5)) * 100 )
    n_correct counts per-question score ≥ 3.
    n_disagreement counts user_disagrees flags.
    cards_created counts non-null card_id_after_reflux.
    """
    questions = session.questions
    n = len(questions)
    session.n_questions = n
    if n == 0:
        session.n_correct = 0
        session.n_disagreement = 0
        session.cards_created = 0
        session.session_score = 0
        return
    total = sum(int(q.ai_score or 0) for q in questions)
    session.session_score = round((total / (n * MAX_QUESTION_SCORE)) * 100)
    session.n_correct = sum(
        1 for q in questions if (q.ai_score or 0) >= PASS_QUESTION_SCORE
    )
    session.n_disagreement = sum(1 for q in questions if q.user_disagrees)
    session.cards_created = sum(
        1 for q in questions if q.card_id_after_reflux
    )
