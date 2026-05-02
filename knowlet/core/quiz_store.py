"""Filesystem store for quiz sessions (ADR-0014 §5.2, M7.4.1).

`<vault>/.knowlet/quizzes/<id>.json`. Hidden under `.knowlet/` —
quizzes are NOT entries in the user-facing IA (`notes/` / `drafts/` /
`cards/`). Past-quizzes UI is a focus-mode-only entry coming in
M7.4.3.

90-day aging policy lives here too (move to `.archive/` unless the
session has card_id_after_reflux on any question — that's evidence
the user learned something specific, worth keeping live).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterator

from knowlet.core.quiz import QuizQuestion, QuizSession

QUIZZES_DIR = "quizzes"
ARCHIVE_DIR = ".archive"
DEFAULT_AGING_DAYS = 90


class QuizStore:
    """File-backed CRUD over `<state_dir>/quizzes/<id>.json`.

    `state_dir` is the vault's `.knowlet/` (i.e. `vault.state_dir`).
    The store creates `quizzes/` lazily so a vault that's never run a
    quiz doesn't acquire an empty directory."""

    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.quizzes_dir = state_dir / QUIZZES_DIR

    @property
    def archive_dir(self) -> Path:
        return self.quizzes_dir / ARCHIVE_DIR

    def _path_for(self, quiz_id: str) -> Path:
        return self.quizzes_dir / f"{quiz_id}.json"

    def save(self, session: QuizSession) -> Path:
        """Atomic write — `<id>.json.tmp` → rename. Survives a crash
        mid-write the same way M0 vault writes do."""
        self.quizzes_dir.mkdir(parents=True, exist_ok=True)
        target = self._path_for(session.id)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(
            json.dumps(session.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(target)
        return target

    def load(self, quiz_id: str) -> QuizSession | None:
        target = self._path_for(quiz_id)
        if not target.exists():
            return None
        return _session_from_json(json.loads(target.read_text(encoding="utf-8")))

    def list_recent(self, limit: int = 50) -> list[QuizSession]:
        """Return live (non-archived) sessions, newest first by
        started_at. M7.4.1 doesn't expose this in the UI yet — M7.4.3
        will, when the past-quizzes focus mode lands."""
        if not self.quizzes_dir.exists():
            return []
        rows: list[QuizSession] = []
        for p in self.quizzes_dir.glob("*.json"):
            try:
                rows.append(
                    _session_from_json(json.loads(p.read_text(encoding="utf-8")))
                )
            except (json.JSONDecodeError, KeyError):
                continue
        rows.sort(key=lambda s: s.started_at, reverse=True)
        return rows[:limit]

    def delete(self, quiz_id: str) -> bool:
        target = self._path_for(quiz_id)
        if not target.exists():
            return False
        target.unlink()
        return True

    # ---------------------------------------------------- aging (M7.4.3)

    def archive_aged(self, *, max_age_days: int = DEFAULT_AGING_DAYS) -> int:
        """Move sessions older than `max_age_days` to `.archive/`,
        UNLESS the session has at least one Card-reflux mark (= the
        user learned something specific from it). M7.4.1 ships the
        function but the UI hook (a periodic task or a startup
        check) lands with the past-quizzes UI in M7.4.3.

        Returns the number of sessions archived."""
        if not self.quizzes_dir.exists():
            return 0
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
        moved = 0
        for p in self.quizzes_dir.glob("*.json"):
            try:
                payload = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            started = payload.get("started_at") or ""
            try:
                ts = datetime.strptime(started, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            except ValueError:
                continue
            if ts > cutoff:
                continue
            # Spare sessions whose error questions seeded Cards.
            qs = payload.get("questions") or []
            if any(q.get("card_id_after_reflux") for q in qs):
                continue
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            p.rename(self.archive_dir / p.name)
            moved += 1
        return moved


def _session_from_json(payload: dict) -> QuizSession:
    """Inverse of `QuizSession.to_dict()`. Tolerates older JSON shapes
    by falling back to dataclass defaults for absent fields."""
    questions = [
        QuizQuestion(
            type=str(q.get("type") or "recall"),
            question=str(q.get("question") or ""),
            reference_answer=str(q.get("reference_answer") or ""),
            source_note_ids=list(q.get("source_note_ids") or []),
            user_answer=str(q.get("user_answer") or ""),
            ai_score=q.get("ai_score"),
            ai_reason=str(q.get("ai_reason") or ""),
            ai_missing=list(q.get("ai_missing") or []),
            user_disagrees=bool(q.get("user_disagrees", False)),
            user_disagree_reason=str(q.get("user_disagree_reason") or ""),
            card_id_after_reflux=q.get("card_id_after_reflux"),
        )
        for q in (payload.get("questions") or [])
    ]
    return QuizSession(
        id=str(payload.get("id") or ""),
        started_at=str(payload.get("started_at") or ""),
        finished_at=str(payload.get("finished_at") or ""),
        model=str(payload.get("model") or ""),
        scope_type=str(payload.get("scope_type") or "notes"),
        scope_note_ids=list(payload.get("scope_note_ids") or []),
        scope_tag=str(payload.get("scope_tag") or ""),
        scope_cluster_id=str(payload.get("scope_cluster_id") or ""),
        questions=questions,
        n_questions=int(payload.get("n_questions") or 0),
        n_correct=int(payload.get("n_correct") or 0),
        n_disagreement=int(payload.get("n_disagreement") or 0),
        cards_created=int(payload.get("cards_created") or 0),
        session_score=int(payload.get("session_score") or 0),
    )
