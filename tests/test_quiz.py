"""Unit tests for `knowlet/core/quiz.py` (M7.4.0)."""

from datetime import UTC, datetime

import pytest

from knowlet.core.quiz import (
    DEFAULT_N_QUESTIONS,
    MAX_QUESTION_SCORE,
    MIN_QUESTION_SCORE,
    PASS_QUESTION_SCORE,
    QUESTION_TYPES,
    QuizQuestion,
    QuizSession,
    aggregate_score,
    generate_quiz,
    grade_answer,
)


# -------------------------------------------------- ADR-0014 constants


def test_constants_match_adr_0014():
    """Catch silent drift from the ADR (§3.3 / §4.1)."""
    assert DEFAULT_N_QUESTIONS == 5
    assert MIN_QUESTION_SCORE == 1
    assert MAX_QUESTION_SCORE == 5
    assert PASS_QUESTION_SCORE == 3
    assert set(QUESTION_TYPES) == {
        "concept-explanation",
        "application",
        "contrast",
        "inference",
        "recall",
    }


# -------------------------------------------------- generate_quiz


class _StubLLM:
    """Returns a fixed JSON reply via .chat()."""

    def __init__(self, reply: str):
        self.reply = reply
        self.last_messages: list = []

    def chat(self, messages, tools=None, max_tokens=None, temperature=None):
        self.last_messages = messages

        class _M:
            content = self.reply

        return _M()


def test_generate_quiz_parses_well_formed_output():
    reply = """{"questions": [
      {"type": "concept-explanation",
       "question": "Explain RRF",
       "reference_answer": "Reciprocal rank fusion combines ranks.",
       "source_note_ids": ["n1"]},
      {"type": "contrast",
       "question": "BM25 vs cosine?",
       "reference_answer": "BM25 weights term frequency, cosine compares directions.",
       "source_note_ids": ["n1"]}
    ]}"""
    llm = _StubLLM(reply)
    qs = generate_quiz(llm, [("n1", "RAG", "body about RAG")], n=2)
    assert len(qs) == 2
    assert qs[0].type == "concept-explanation"
    assert qs[0].question == "Explain RRF"
    assert qs[1].type == "contrast"
    # User-answer / score fields default to empty/None.
    assert qs[0].user_answer == ""
    assert qs[0].ai_score is None


def test_generate_quiz_tolerates_markdown_fence():
    """Some LLMs ignore 'no markdown fence' instructions; the parser
    handles ```json ... ``` as a soft fallback."""
    reply = (
        "```json\n"
        '{"questions": [{"type": "recall", "question": "Q?", '
        '"reference_answer": "A.", "source_note_ids": []}]}\n'
        "```"
    )
    llm = _StubLLM(reply)
    qs = generate_quiz(llm, [("n", "T", "body")], n=1)
    assert len(qs) == 1


def test_generate_quiz_normalizes_unknown_question_type():
    """If the LLM emits an unknown type, fall back to 'recall' rather
    than dropping the question — preserves quiz length."""
    reply = (
        '{"questions": [{"type": "bogus-type", "question": "Q?", '
        '"reference_answer": "A.", "source_note_ids": []}]}'
    )
    llm = _StubLLM(reply)
    qs = generate_quiz(llm, [("n", "T", "body")], n=1)
    assert len(qs) == 1
    assert qs[0].type == "recall"


def test_generate_quiz_skips_questions_missing_required_fields():
    reply = (
        '{"questions": ['
        '{"type": "recall", "question": "Q?", "reference_answer": ""},'  # empty ref
        '{"type": "recall", "question": "", "reference_answer": "A."},'  # empty q
        '{"type": "recall", "question": "Real?", "reference_answer": "Yes."}'
        "]}"
    )
    llm = _StubLLM(reply)
    qs = generate_quiz(llm, [("n", "T", "b")], n=3)
    assert len(qs) == 1
    assert qs[0].question == "Real?"


def test_generate_quiz_raises_on_zero_valid_questions():
    reply = '{"questions": []}'
    llm = _StubLLM(reply)
    with pytest.raises(ValueError, match="0 valid questions"):
        generate_quiz(llm, [("n", "T", "b")], n=3)


def test_generate_quiz_raises_on_empty_notes_list():
    llm = _StubLLM('{"questions": []}')
    with pytest.raises(ValueError, match="non-empty"):
        generate_quiz(llm, [], n=3)


def test_generate_quiz_raises_on_invalid_n():
    llm = _StubLLM('{"questions": []}')
    with pytest.raises(ValueError, match="n=0"):
        generate_quiz(llm, [("n", "T", "b")], n=0)


def test_generate_quiz_raises_on_unparseable_output():
    llm = _StubLLM("totally not json at all")
    with pytest.raises((ValueError, Exception)):
        generate_quiz(llm, [("n", "T", "b")], n=3)


# -------------------------------------------------- grade_answer


def _q(text="Q?", ref="The answer is A."):
    return QuizQuestion(type="recall", question=text, reference_answer=ref)


def test_grade_answer_empty_user_answer_short_circuits():
    """Empty answer = 1, no LLM call (saves a token)."""

    class NeverCalled:
        def chat(self, *a, **kw):
            raise AssertionError("LLM was called for an empty answer")

    score, reason, missing = grade_answer(NeverCalled(), _q(), "")
    assert score == MIN_QUESTION_SCORE
    assert "Empty" in reason
    assert missing == ["The answer is A."]


def test_grade_answer_parses_well_formed_output():
    reply = '{"score": 4, "reason": "Solid coverage of the key idea.", "missing": []}'
    llm = _StubLLM(reply)
    score, reason, missing = grade_answer(llm, _q(), "Some answer about A.")
    assert score == 4
    assert "Solid" in reason
    assert missing == []


def test_grade_answer_clamps_out_of_range_score():
    """LLM occasionally emits 0 or 7; clamp to [1, 5]."""
    llm = _StubLLM('{"score": 7, "reason": "great", "missing": []}')
    s_high, _, _ = grade_answer(llm, _q(), "ans")
    assert s_high == 5

    llm = _StubLLM('{"score": 0, "reason": "weak", "missing": []}')
    s_low, _, _ = grade_answer(llm, _q(), "ans")
    assert s_low == 1


def test_grade_answer_degrades_on_malformed_json():
    """Malformed grading output → score=3 + reason flags the failure.
    Lets the quiz finish rather than crashing mid-loop."""
    llm = _StubLLM("not even close to json")
    score, reason, missing = grade_answer(llm, _q(), "ans")
    assert score == PASS_QUESTION_SCORE
    assert "grading failed" in reason.lower()


def test_grade_answer_degrades_on_llm_exception():
    class BlowsUp:
        def chat(self, *a, **kw):
            raise RuntimeError("boom")

    score, reason, missing = grade_answer(BlowsUp(), _q(), "ans")
    assert score == PASS_QUESTION_SCORE
    assert "boom" in reason


def test_grade_answer_handles_non_int_score():
    llm = _StubLLM('{"score": "four", "reason": "...", "missing": []}')
    score, _, _ = grade_answer(llm, _q(), "ans")
    assert score == PASS_QUESTION_SCORE  # safe-default when score isn't an int


# -------------------------------------------------- aggregate_score


def _now():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_aggregate_score_zero_questions():
    s = QuizSession(id="s", started_at=_now())
    aggregate_score(s)
    assert s.session_score == 0
    assert s.n_questions == 0
    assert s.n_correct == 0


def test_aggregate_score_perfect():
    s = QuizSession(
        id="s",
        started_at=_now(),
        questions=[
            QuizQuestion(type="recall", question="q1", reference_answer="r", ai_score=5),
            QuizQuestion(type="recall", question="q2", reference_answer="r", ai_score=5),
        ],
    )
    aggregate_score(s)
    assert s.session_score == 100
    assert s.n_correct == 2
    assert s.n_questions == 2


def test_aggregate_score_uses_adr_formula():
    """ADR-0014 §4.1: round( (sum / (n * 5)) * 100 ).
    n=5, scores=[5,4,3,2,1] → sum=15, score=round(15/25*100)=60."""
    s = QuizSession(
        id="s",
        started_at=_now(),
        questions=[
            QuizQuestion(type="recall", question=f"q{i}", reference_answer="r", ai_score=score)
            for i, score in enumerate([5, 4, 3, 2, 1], start=1)
        ],
    )
    aggregate_score(s)
    assert s.session_score == 60
    assert s.n_correct == 3  # scores ≥ 3
    assert s.n_questions == 5


def test_aggregate_score_counts_disagreements():
    s = QuizSession(
        id="s",
        started_at=_now(),
        questions=[
            QuizQuestion(type="recall", question="q1", reference_answer="r", ai_score=4),
            QuizQuestion(
                type="recall",
                question="q2",
                reference_answer="r",
                ai_score=2,
                user_disagrees=True,
            ),
        ],
    )
    aggregate_score(s)
    assert s.n_disagreement == 1


def test_aggregate_score_counts_card_reflux():
    s = QuizSession(
        id="s",
        started_at=_now(),
        questions=[
            QuizQuestion(
                type="recall",
                question="q",
                reference_answer="r",
                ai_score=2,
                card_id_after_reflux="01HX0000000000000000000000",
            ),
        ],
    )
    aggregate_score(s)
    assert s.cards_created == 1
