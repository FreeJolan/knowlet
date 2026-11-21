"""Regression test for the misc-core audit batch — fsrs pin.

Card review state is persisted as fsrs's own ``to_dict()`` shape
(``card.fsrs_state``) and restored with ``FSRSCard.from_dict``. A new
fsrs major can change that shape, so the dependency must not float
across majors without a deliberate wrapper bump + migration.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.version import Version

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def _fsrs_requirement() -> Requirement:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    reqs = [Requirement(r) for r in data["project"]["dependencies"]]
    matches = [r for r in reqs if r.name == "fsrs"]
    assert len(matches) == 1
    return matches[0]


def test_fsrs_dependency_is_capped_below_next_major() -> None:
    spec = _fsrs_requirement().specifier
    assert Version("6.3.1") in spec
    assert Version("7.0.0") not in spec
    assert Version("7.2.0") not in spec
