"""Thin wrapper over the `fsrs` library so the rest of knowlet doesn't need
to know fsrs's exact types. Lets us swap algorithm versions later without
touching tools / CLI / web layers.

Per the no-wheel-reinvention memory, the FSRS algorithm itself is a hard
dependency we **reuse** rather than reimplement — the surface here is just
adapter glue.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fsrs import Card as FSRSCard
from fsrs import Rating, Scheduler

from knowlet.core.card import Card

_RATING_NAMES = {1: "again", 2: "hard", 3: "good", 4: "easy"}
_NAME_TO_INT: dict[str, int] = {
    **{str(k): k for k in _RATING_NAMES},  # "1" → 1, …
    **{v: k for k, v in _RATING_NAMES.items()},  # "again" → 1, …
}


_scheduler: Scheduler | None = None


def _scheduler_singleton() -> Scheduler:
    """Lazy singleton — fsrs Scheduler is stateless w.r.t. cards but holds
    the algorithm parameters; one per process is fine."""
    global _scheduler
    if _scheduler is None:
        _scheduler = Scheduler()
    return _scheduler


def parse_rating(rating: int | str) -> Rating:
    """Coerce a rating from int or string into the fsrs Rating enum.

    Accepts: 1 | 2 | 3 | 4 | "1".."4" | "again" | "hard" | "good" | "easy"
    (case-insensitive).
    """
    if isinstance(rating, int):
        if rating in _RATING_NAMES:
            return Rating(rating)
        raise ValueError(f"invalid rating: {rating}; expected 1-4")
    if isinstance(rating, str):
        key = rating.strip().lower()
        if key in _NAME_TO_INT:
            return Rating(_NAME_TO_INT[key])
    raise ValueError(
        f"invalid rating: {rating!r}; expected 1-4 or one of "
        f"{list(_RATING_NAMES.values())}"
    )


def schedule_next(card: Card, rating: int | str, now: datetime | None = None) -> Card:
    """Apply a review rating; returns a new Card with updated FSRS state.

    Mutates the input card's `fsrs_state` in place (and returns it) so the
    caller can save it back to disk through CardStore.save without juggling
    two references.
    """
    if now is None:
        now = datetime.now(UTC)
    sched = _scheduler_singleton()

    if card.fsrs_state:
        fsrs_card = FSRSCard.from_dict(card.fsrs_state)
    else:
        fsrs_card = FSRSCard()  # brand new

    new_fsrs_card, _log = sched.review_card(fsrs_card, parse_rating(rating), now)
    card.fsrs_state = new_fsrs_card.to_dict()
    return card


def initial_state() -> dict[str, Any]:
    """FSRS state for a freshly-created card (due = now, learning state)."""
    return FSRSCard().to_dict()
