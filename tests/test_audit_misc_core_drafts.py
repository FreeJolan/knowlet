"""Regression tests for the misc-core audit batch — DraftStore.

Covers:
- id lookup: exact match wins, unique prefix still works, ambiguous
  prefix raises instead of silently picking the first glob hit
- archive_draft: soft-delete into ``.archive/`` (recoverable)
- scalar ``tags:`` frontmatter is not exploded into single characters
- one corrupt draft file does not break all_drafts / enforce_age_archive
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from knowlet.core.drafts import AmbiguousDraftIdError, Draft, DraftStore


def _write_raw(store: DraftStore, name: str, text: str) -> Path:
    store.root.mkdir(parents=True, exist_ok=True)
    p = store.root / name
    p.write_text(text, encoding="utf-8")
    return p


# ------------------------------------------------------------- id lookup


def test_get_exact_id_wins_over_longer_prefix_sibling(tmp_path: Path) -> None:
    """Legacy / hand-made ids can be prefixes of each other; the exact
    id must resolve to its own draft, not raise as ambiguous."""
    store = DraftStore(tmp_path / "drafts")
    a = Draft(id="01ABC", title="alpha", body="a")
    b = Draft(id="01ABCD", title="beta", body="b")
    store.save(a)
    store.save(b)
    got = store.get("01ABC")
    assert got is not None and got.id == a.id
    got_b = store.get("01ABCD")
    assert got_b is not None and got_b.id == b.id


def test_get_unique_prefix_still_resolves(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "drafts")
    a = Draft(id="01JAAAAAAAAAAAAAAAAAAAAAAA", title="alpha", body="a")
    b = Draft(id="01JBBBBBBBBBBBBBBBBBBBBBBB", title="beta", body="b")
    store.save(a)
    store.save(b)
    got = store.get("01JB")
    assert got is not None and got.id == b.id


def test_get_ambiguous_prefix_raises(tmp_path: Path) -> None:
    """Same-millisecond ULIDs share the 10-char timestamp prefix; a
    truncated id must not silently resolve to whichever file globs
    first (the result feeds delete / commit)."""
    store = DraftStore(tmp_path / "drafts")
    a = Draft(id="01JAAAAAAAAAAAAAAAAAAAAAAA", title="alpha", body="a")
    b = Draft(id="01JAAAAAAAAAAAAAAAAAAAAAAB", title="beta", body="b")
    store.save(a)
    store.save(b)
    with pytest.raises(AmbiguousDraftIdError) as exc_info:
        store.get("01JAAAAAAA")
    assert set(exc_info.value.candidates) == {a.id, b.id}


def test_delete_with_ambiguous_prefix_removes_nothing(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "drafts")
    a = Draft(id="01JAAAAAAAAAAAAAAAAAAAAAAA", title="alpha", body="a")
    b = Draft(id="01JAAAAAAAAAAAAAAAAAAAAAAB", title="beta", body="b")
    store.save(a)
    store.save(b)
    with pytest.raises(AmbiguousDraftIdError):
        store.delete("01JAAAAAAA")
    assert a.path is not None and a.path.exists()
    assert b.path is not None and b.path.exists()


def test_get_empty_id_matches_nothing(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "drafts")
    store.save(Draft(title="only", body="x"))
    assert store.get("") is None


# ------------------------------------------------------------- archive_draft


def test_archive_draft_moves_file_into_archive_dir(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "drafts")
    d = Draft(title="reject me", body="body text")
    store.save(d)
    original = d.path
    assert original is not None

    target = store.archive_draft(d.id)

    assert not original.exists()
    assert target.exists()
    assert target.parent == store.archive_dir
    # Content preserved verbatim — this is a soft delete.
    assert Draft.from_file(target).body == "body text"
    # Gone from the live queue.
    assert store.get(d.id) is None
    assert store.all_drafts() == []


def test_archive_draft_unknown_id_raises_key_error(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "drafts")
    with pytest.raises(KeyError):
        store.archive_draft("01JNOPENOPENOPENOPENOPENOP")


def test_archive_draft_ambiguous_prefix_archives_nothing(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "drafts")
    a = Draft(id="01JAAAAAAAAAAAAAAAAAAAAAAA", title="alpha", body="a")
    b = Draft(id="01JAAAAAAAAAAAAAAAAAAAAAAB", title="beta", body="b")
    store.save(a)
    store.save(b)
    with pytest.raises(AmbiguousDraftIdError):
        store.archive_draft("01JAAAAAAA")
    assert len(store.all_drafts()) == 2
    assert not store.archive_dir.exists() or not any(store.archive_dir.iterdir())


# ------------------------------------------------------------- scalar tags


def test_scalar_string_tag_is_one_tag_not_characters(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "drafts")
    p = _write_raw(
        store,
        "01JCCCCCCCCCCCCCCCCCCCCCCC-x.md",
        "---\nid: 01JCCCCCCCCCCCCCCCCCCCCCCC\ntitle: x\ntags: physics\n---\nbody\n",
    )
    d = Draft.from_file(p)
    assert d.tags == ["physics"]
    assert d.to_note().tags == ["physics"]


def test_scalar_int_tag_does_not_crash(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "drafts")
    p = _write_raw(
        store,
        "01JDDDDDDDDDDDDDDDDDDDDDDD-x.md",
        "---\nid: 01JDDDDDDDDDDDDDDDDDDDDDDD\ntitle: x\ntags: 2024\n---\nbody\n",
    )
    assert Draft.from_file(p).tags == ["2024"]


def test_list_tags_unchanged(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "drafts")
    p = _write_raw(
        store,
        "01JEEEEEEEEEEEEEEEEEEEEEEE-x.md",
        "---\nid: 01JEEEEEEEEEEEEEEEEEEEEEEE\ntitle: x\ntags: [a, b]\n---\nbody\n",
    )
    assert Draft.from_file(p).tags == ["a", "b"]


# ------------------------------------------------------------- corrupt files

_BROKEN_YAML = "---\ntitle: John: Doe\n  bad: [unclosed\n---\nbody\n"


def test_all_drafts_skips_corrupt_yaml_file(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "drafts")
    good = Draft(title="good", body="ok")
    store.save(good)
    _write_raw(store, "01JZZZZZZZZZZZZZZZZZZZZZZZ-broken.md", _BROKEN_YAML)

    drafts = store.all_drafts()

    assert [d.id for d in drafts] == [good.id]


def test_enforce_age_archive_survives_corrupt_yaml_file(tmp_path: Path) -> None:
    store = DraftStore(tmp_path / "drafts")
    old = Draft(
        title="old",
        body="x",
        created_at=(datetime.now(UTC) - timedelta(days=120)).isoformat(),
    )
    store.save(old)
    broken = _write_raw(store, "01JZZZZZZZZZZZZZZZZZZZZZZZ-broken.md", _BROKEN_YAML)

    assert store.enforce_age_archive() == 1
    # The corrupt file is left untouched for the user to repair.
    assert broken.exists()
    assert broken.read_text(encoding="utf-8") == _BROKEN_YAML
