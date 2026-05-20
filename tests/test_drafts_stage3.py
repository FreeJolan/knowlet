"""Stage 3 Step 3.1 — Draft.kind + age helpers + age-based auto-archive.

Tests target the behavior, not internals:
- kind field round-trips and defaults correctly (forward-compat for v1)
- age_days / is_stale / is_warn_age / should_auto_archive thresholds
- enforce_age_archive: 90+ day drafts land in .archive/<YYYY-MM>/
- active_count excludes archived
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from knowlet.core.drafts import (
    ARCHIVE_AGE_DAYS,
    STALE_AGE_DAYS,
    WARN_AGE_DAYS,
    Draft,
    DraftStore,
)


def _iso_days_ago(n: int) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(days=n)
    ).isoformat()


# --------------------------------------------------- kind field


def test_draft_default_kind_is_knowledge() -> None:
    d = Draft(title="t", body="b")
    assert d.kind == "knowledge"


def test_draft_kind_round_trips_via_frontmatter(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "drafts")
    d = Draft(title="reference url draft", body="...", kind="reference")
    store.save(d)
    raw = d.path.read_text(encoding="utf-8")  # type: ignore[union-attr]
    assert "kind: reference" in raw
    re_read = Draft.from_file(d.path)  # type: ignore[arg-type]
    assert re_read.kind == "reference"


def test_legacy_draft_without_kind_defaults_to_knowledge(
    tmp_path: Path,
) -> None:
    """A pre-Stage-3 file with no `kind` in frontmatter reads back as
    knowledge — forward-compat default per ADR-0018 §1."""
    p = tmp_path / "draft-legacy.md"
    p.write_text(
        "---\nid: 01ABC\ntitle: legacy\n---\nbody\n",
        encoding="utf-8",
    )
    d = Draft.from_file(p)
    assert d.kind == "knowledge"


def test_invalid_kind_falls_back_to_knowledge(tmp_path: Path) -> None:
    p = tmp_path / "draft-bogus.md"
    p.write_text(
        "---\nid: 01XYZ\ntitle: bogus\nkind: nonsense\n---\nbody\n",
        encoding="utf-8",
    )
    assert Draft.from_file(p).kind == "knowledge"


def test_to_note_preserves_kind() -> None:
    d = Draft(id="x", title="t", body="b", kind="reference")
    n = d.to_note()
    assert n.kind == "reference"


# --------------------------------------------------- age helpers


def test_age_days_zero_for_just_created() -> None:
    d = Draft()  # created_at = now
    assert d.age_days == 0
    assert not d.is_stale
    assert not d.is_warn_age
    assert not d.should_auto_archive


def test_age_helpers_at_thresholds() -> None:
    # 1 day before each threshold → not yet
    assert not Draft(created_at=_iso_days_ago(STALE_AGE_DAYS - 1)).is_stale
    assert not Draft(created_at=_iso_days_ago(WARN_AGE_DAYS - 1)).is_warn_age
    assert not Draft(
        created_at=_iso_days_ago(ARCHIVE_AGE_DAYS - 1)
    ).should_auto_archive

    # At threshold → yes
    assert Draft(created_at=_iso_days_ago(STALE_AGE_DAYS)).is_stale
    assert Draft(created_at=_iso_days_ago(WARN_AGE_DAYS)).is_warn_age
    assert Draft(
        created_at=_iso_days_ago(ARCHIVE_AGE_DAYS)
    ).should_auto_archive


def test_age_days_handles_invalid_iso() -> None:
    """Malformed created_at must not raise — degrades to age=0."""
    d = Draft(created_at="not-a-date")
    assert d.age_days == 0
    assert not d.should_auto_archive


# --------------------------------------------------- enforce_age_archive


def test_enforce_age_archive_moves_old_drafts(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "drafts")
    fresh = Draft(title="fresh")
    stale = Draft(title="stale-warn", created_at=_iso_days_ago(40))
    ancient = Draft(
        title="ancient", created_at=_iso_days_ago(ARCHIVE_AGE_DAYS + 5)
    )
    store.save(fresh)
    store.save(stale)
    store.save(ancient)

    archived = store.enforce_age_archive()
    assert archived == 1

    # `all_drafts` looks at live queue only — ancient should be gone.
    live_titles = {d.title for d in store.all_drafts()}
    assert live_titles == {"fresh", "stale-warn"}

    # Archived file is under .archive/<YYYY-MM>/ — not flat .archive/.
    archive_root = store.archive_dir
    month_dirs = [
        p for p in archive_root.iterdir() if p.is_dir()
    ]
    assert len(month_dirs) == 1
    # Month subdir name pattern YYYY-MM.
    assert len(month_dirs[0].name) == 7 and month_dirs[0].name[4] == "-"
    assert any(p.suffix == ".md" for p in month_dirs[0].iterdir())


def test_enforce_age_archive_is_idempotent(tmp_path: Path) -> None:
    """Re-running with no new stale drafts does nothing."""
    store = DraftStore(tmp_path / "drafts")
    store.save(Draft(title="fresh"))
    assert store.enforce_age_archive() == 0
    assert store.enforce_age_archive() == 0


# --------------------------------------------------- active_count


def test_active_count_excludes_archived(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "drafts")
    d1 = Draft(title="d1")
    d2 = Draft(title="d2")
    store.save(d1)
    store.save(d2)
    assert store.active_count() == 2
    store.archive(d1)
    assert store.active_count() == 1
