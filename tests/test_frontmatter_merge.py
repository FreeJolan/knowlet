"""S5.5 — rule-based frontmatter merge unit tests.

Locks the per-field rules in ``frontmatter_merge.merge_notes`` so
mechanical churn (updated_at, schema_version, formatter re-flow)
never reaches the user's merge UI as a phantom hunk.
"""

from __future__ import annotations

from knowlet.core.note import Note
from knowlet.core.sync.frontmatter_merge import merge_notes


def _note(
    *,
    nid: str = "01ABC0000000000000000000XX",
    title: str = "alpha",
    body: str = "",
    tags: list[str] | None = None,
    aliases: list[str] | None = None,
    created_at: str = "2024-01-01T00:00:00Z",
    updated_at: str = "2024-06-01T00:00:00Z",
    schema_version: int = 2,
    source: str | None = None,
    status: str = "active",
    trashed_from: str | None = None,
) -> Note:
    return Note(
        id=nid,
        title=title,
        body=body,
        tags=list(tags or []),
        aliases=list(aliases or []),
        created_at=created_at,
        updated_at=updated_at,
        source=source,
        schema_version=schema_version,
        status=status,  # type: ignore[arg-type]
        trashed_from=trashed_from,
    )


def test_merge_picks_newer_title_by_updated_at() -> None:
    mine = _note(title="old title", updated_at="2024-06-01T00:00:00Z")
    theirs = _note(title="new title", updated_at="2024-06-02T00:00:00Z")
    out = merge_notes(mine=mine, theirs=theirs, merged_body="")
    assert out.title == "new title"


def test_merge_picks_local_title_when_local_is_newer() -> None:
    mine = _note(title="my title", updated_at="2024-06-02T00:00:00Z")
    theirs = _note(title="their title", updated_at="2024-06-01T00:00:00Z")
    out = merge_notes(mine=mine, theirs=theirs, merged_body="")
    assert out.title == "my title"


def test_merge_tags_are_union_sorted() -> None:
    mine = _note(tags=["a", "c"])
    theirs = _note(tags=["b", "c", "d"])
    out = merge_notes(mine=mine, theirs=theirs, merged_body="")
    assert out.tags == ["a", "b", "c", "d"]


def test_merge_aliases_are_union_sorted() -> None:
    mine = _note(aliases=["foo", "bar"])
    theirs = _note(aliases=["baz", "bar"])
    out = merge_notes(mine=mine, theirs=theirs, merged_body="")
    assert out.aliases == ["bar", "baz", "foo"]


def test_merge_picks_earliest_created_at() -> None:
    mine = _note(created_at="2024-03-01T00:00:00Z")
    theirs = _note(created_at="2024-01-15T00:00:00Z")
    out = merge_notes(mine=mine, theirs=theirs, merged_body="")
    assert out.created_at == "2024-01-15T00:00:00Z"


def test_merge_picks_latest_updated_at() -> None:
    mine = _note(updated_at="2024-06-01T00:00:00Z")
    theirs = _note(updated_at="2024-06-15T00:00:00Z")
    out = merge_notes(mine=mine, theirs=theirs, merged_body="")
    assert out.updated_at == "2024-06-15T00:00:00Z"


def test_merge_max_schema_version_never_downgrades() -> None:
    mine = _note(schema_version=1)
    theirs = _note(schema_version=3)
    out = merge_notes(mine=mine, theirs=theirs, merged_body="")
    assert out.schema_version == 3


def test_merge_id_taken_from_local() -> None:
    """The URL the user clicked through is mine's id; preserve it
    even if theirs has a different one (real shouldn't happen — they
    should be tied to the same Drive file — but defensive)."""
    mine = _note(nid="01MINE0000000000000000000A")
    theirs = _note(nid="01THEIRS00000000000000000B")
    out = merge_notes(mine=mine, theirs=theirs, merged_body="")
    assert out.id == "01MINE0000000000000000000A"


def test_merge_source_prefers_first_non_empty() -> None:
    mine = _note(source=None)
    theirs = _note(source="https://example.com")
    out = merge_notes(mine=mine, theirs=theirs, merged_body="")
    assert out.source == "https://example.com"

    mine2 = _note(source="https://mine.local")
    theirs2 = _note(source="https://theirs.local")
    out2 = merge_notes(mine=mine2, theirs=theirs2, merged_body="")
    # mine wins when both have a value.
    assert out2.source == "https://mine.local"


def test_merge_status_follows_newer_side() -> None:
    mine = _note(status="active", updated_at="2024-06-01T00:00:00Z")
    theirs = _note(status="deprecated", updated_at="2024-06-15T00:00:00Z")
    out = merge_notes(mine=mine, theirs=theirs, merged_body="")
    assert out.status == "deprecated"


def test_merge_trashed_from_sticks() -> None:
    """If either side was trashed, the trash-from path persists. The
    note enters trash on the more-recent decision."""
    mine = _note(trashed_from=None)
    theirs = _note(trashed_from="projects/old")
    out = merge_notes(mine=mine, theirs=theirs, merged_body="")
    assert out.trashed_from == "projects/old"


def test_merge_body_comes_from_caller() -> None:
    """The user-assembled merged body is the only "user decision"
    surfaced by the merge editor — frontmatter is rules; body is
    the user's call."""
    mine = _note(body="mine body")
    theirs = _note(body="theirs body")
    out = merge_notes(mine=mine, theirs=theirs, merged_body="user-assembled merged body")
    assert out.body == "user-assembled merged body"


def test_merged_note_round_trips_via_to_markdown() -> None:
    """The whole point: the rule-based output must serialize back
    into a clean knowlet markdown file. ``to_markdown`` is what
    Vault.write_note uses, and any field added in the merge needs
    to round-trip without losing semantics."""
    mine = _note(
        nid="01XYZ0000000000000000000Y0",
        title="A",
        tags=["one", "two"],
        aliases=["alt"],
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-06-01T00:00:00Z",
    )
    theirs = _note(
        nid="01XYZ0000000000000000000Y0",
        title="B",
        tags=["three"],
        aliases=["other"],
        created_at="2023-12-01T00:00:00Z",
        updated_at="2024-07-01T00:00:00Z",
    )
    out = merge_notes(mine=mine, theirs=theirs, merged_body="merged body")
    serialized = out.to_markdown()
    # Round-trip through Note.from_text — verifies every rule-merged
    # field survived YAML emission + parse.
    redux = Note.from_text(serialized)
    assert redux.title == "B"  # newer
    assert redux.tags == ["one", "three", "two"]
    assert redux.aliases == ["alt", "other"]
    assert redux.created_at == "2023-12-01T00:00:00Z"
    assert redux.updated_at == "2024-07-01T00:00:00Z"
    assert redux.body.strip() == "merged body"
