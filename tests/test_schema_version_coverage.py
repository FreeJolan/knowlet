"""Phase 2 E Slice 4.D — schema_version on Card / Draft / MiningTask.

ADR-0018 §2 says: any persisted entity must carry schema_version. Note
+ QuickActions + index.meta already do; this slice extends that contract
to the remaining first-class entities.

Tests verify:
- New entities default to v1.
- Pre-versioned (legacy) on-disk records read back as v1.
- Writes always stamp the current schema version.
"""

from __future__ import annotations

import json
from pathlib import Path

from knowlet.core.card import CARD_SCHEMA_VERSION, Card
from knowlet.core.drafts import DRAFT_SCHEMA_VERSION, Draft
from knowlet.core.mining.task import (
    MINING_TASK_SCHEMA_VERSION,
    MiningTask,
    Schedule,
)


def test_card_default_v1() -> None:
    c = Card(front="f", back="b")
    assert c.schema_version == CARD_SCHEMA_VERSION == 1


def test_card_writes_schema_version(tmp_path: Path) -> None:
    c = Card(front="f", back="b")
    out = tmp_path / "c.json"
    out.write_text(json.dumps(c.to_dict()), encoding="utf-8")
    raw = json.loads(out.read_text(encoding="utf-8"))
    assert raw["schema_version"] == CARD_SCHEMA_VERSION


def test_card_pre_versioned_reads_as_v1(tmp_path: Path) -> None:
    """A card on disk without schema_version (legacy shape) reads as
    v1. This is the forward-compat clause of ADR-0018 §1."""
    legacy = tmp_path / "c.json"
    legacy.write_text(
        json.dumps(
            {
                "id": "01ABC",
                "type": "basic",
                "front": "f",
                "back": "b",
                "tags": [],
                "created_at": "2026-05-09T10:00:00Z",
                "updated_at": "2026-05-09T10:00:00Z",
                "fsrs_state": {},
            }
        ),
        encoding="utf-8",
    )
    c = Card.from_file(legacy)
    assert c.schema_version == 1
    assert c.front == "f"


def test_draft_default_v1() -> None:
    d = Draft(title="t", body="b")
    assert d.schema_version == DRAFT_SCHEMA_VERSION == 1


def test_draft_round_trip_with_version(tmp_path: Path) -> None:
    d = Draft(title="t", body="b")
    out = tmp_path / "d.md"
    out.write_text(d.to_markdown(), encoding="utf-8")
    raw = out.read_text(encoding="utf-8")
    assert f"schema_version: {DRAFT_SCHEMA_VERSION}" in raw
    re_read = Draft.from_file(out)
    assert re_read.schema_version == DRAFT_SCHEMA_VERSION


def test_draft_legacy_reads_as_v1(tmp_path: Path) -> None:
    legacy = tmp_path / "d.md"
    legacy.write_text(
        "---\n"
        "id: 01ABC\n"
        "title: legacy\n"
        "tags: []\n"
        "status: draft\n"
        "created_at: 2026-05-09T10:00:00Z\n"
        "updated_at: 2026-05-09T10:00:00Z\n"
        "---\n"
        "body\n",
        encoding="utf-8",
    )
    d = Draft.from_file(legacy)
    assert d.schema_version == 1


def test_mining_task_default_v1() -> None:
    t = MiningTask(name="x", schedule=Schedule(), sources=[])
    assert t.schema_version == MINING_TASK_SCHEMA_VERSION == 1


def test_mining_task_writes_schema_version(tmp_path: Path) -> None:
    t = MiningTask(name="x", schedule=Schedule(), sources=[], prompt="p")
    out = tmp_path / "t.md"
    out.write_text(t.to_markdown(), encoding="utf-8")
    raw = out.read_text(encoding="utf-8")
    assert f"schema_version: {MINING_TASK_SCHEMA_VERSION}" in raw
    re_read = MiningTask.from_file(out)
    assert re_read.schema_version == MINING_TASK_SCHEMA_VERSION


def test_mining_task_legacy_reads_as_v1(tmp_path: Path) -> None:
    legacy = tmp_path / "t.md"
    legacy.write_text(
        "---\n"
        "id: 01ABC\n"
        "name: legacy\n"
        "enabled: true\n"
        "schedule: {}\n"
        "sources: []\n"
        'prompt: ""\n'
        "created_at: 2026-05-09T10:00:00Z\n"
        "updated_at: 2026-05-09T10:00:00Z\n"
        "---\n"
        "body\n",
        encoding="utf-8",
    )
    t = MiningTask.from_file(legacy)
    assert t.schema_version == 1
