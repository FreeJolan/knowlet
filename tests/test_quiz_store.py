"""Unit tests for `knowlet/core/quiz_store.py` (M7.4.1)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from knowlet.core.quiz import QuizQuestion, QuizSession
from knowlet.core.quiz_store import QuizStore


def _now_minus(days: int) -> str:
    """Return an ISO-Z timestamp `days` days in the past."""
    return (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _q(score: int = 4, card_id: str | None = None) -> QuizQuestion:
    return QuizQuestion(
        type="recall",
        question="Q?",
        reference_answer="A.",
        ai_score=score,
        card_id_after_reflux=card_id,
    )


def test_save_and_load_round_trip(tmp_path: Path):
    store = QuizStore(tmp_path)
    s = QuizSession(
        id="01HX0000000000000000000001",
        started_at=_now_minus(0),
        scope_note_ids=["n1", "n2"],
        questions=[_q(score=5), _q(score=3)],
        session_score=80,
    )
    p = store.save(s)
    assert p.exists()
    loaded = store.load("01HX0000000000000000000001")
    assert loaded is not None
    assert loaded.id == s.id
    assert loaded.scope_note_ids == ["n1", "n2"]
    assert len(loaded.questions) == 2
    assert loaded.questions[0].ai_score == 5
    assert loaded.session_score == 80


def test_load_missing_returns_none(tmp_path: Path):
    store = QuizStore(tmp_path)
    assert store.load("nonexistent") is None


def test_save_is_atomic_no_dot_tmp_left_behind(tmp_path: Path):
    """The atomic-write pattern shouldn't leak a `<id>.json.tmp` after
    a successful save."""
    store = QuizStore(tmp_path)
    s = QuizSession(id="x", started_at=_now_minus(0))
    store.save(s)
    leftover = list(store.quizzes_dir.glob("*.tmp"))
    assert leftover == []


def test_list_recent_sorts_by_started_at_desc(tmp_path: Path):
    store = QuizStore(tmp_path)
    store.save(QuizSession(id="old", started_at=_now_minus(10)))
    store.save(QuizSession(id="new", started_at=_now_minus(1)))
    store.save(QuizSession(id="middle", started_at=_now_minus(5)))
    rows = store.list_recent()
    assert [r.id for r in rows] == ["new", "middle", "old"]


def test_list_recent_skips_archive_dir(tmp_path: Path):
    store = QuizStore(tmp_path)
    store.save(QuizSession(id="live", started_at=_now_minus(1)))
    # Manually drop a file into .archive/ — list_recent must not pick it up.
    store.archive_dir.mkdir(parents=True, exist_ok=True)
    (store.archive_dir / "archived.json").write_text("{}", encoding="utf-8")
    ids = [s.id for s in store.list_recent()]
    assert ids == ["live"]


def test_archive_aged_moves_old_sessions_to_archive(tmp_path: Path):
    store = QuizStore(tmp_path)
    store.save(QuizSession(id="recent", started_at=_now_minus(10)))
    store.save(QuizSession(id="old", started_at=_now_minus(95)))
    moved = store.archive_aged(max_age_days=90)
    assert moved == 1
    assert (store.archive_dir / "old.json").exists()
    assert (store.quizzes_dir / "recent.json").exists()
    assert not (store.quizzes_dir / "old.json").exists()


def test_archive_aged_spares_sessions_with_card_reflux(tmp_path: Path):
    """Per ADR-0014 §5.2: a session that produced Cards is evidence the
    user learned something — archived only if the user opts in."""
    store = QuizStore(tmp_path)
    s_with_card = QuizSession(
        id="cared",
        started_at=_now_minus(120),
        questions=[_q(score=2, card_id="01HX0000000000000000000ABC")],
    )
    s_no_card = QuizSession(id="plain", started_at=_now_minus(120))
    store.save(s_with_card)
    store.save(s_no_card)
    moved = store.archive_aged(max_age_days=90)
    assert moved == 1
    assert (store.quizzes_dir / "cared.json").exists()
    assert not (store.quizzes_dir / "plain.json").exists()


def test_archive_aged_handles_empty_dir(tmp_path: Path):
    """No quizzes → no error, no archive dir created."""
    store = QuizStore(tmp_path)
    moved = store.archive_aged(max_age_days=30)
    assert moved == 0
    assert not store.archive_dir.exists()


def test_delete_removes_file(tmp_path: Path):
    store = QuizStore(tmp_path)
    store.save(QuizSession(id="x", started_at=_now_minus(0)))
    assert store.delete("x") is True
    assert store.load("x") is None
    assert store.delete("x") is False  # already gone
