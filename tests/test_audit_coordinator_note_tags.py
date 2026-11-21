"""Scalar YAML ``tags`` / ``aliases`` must stay a single entry, not be
exploded into characters by ``list()``."""

from knowlet.core.note import Note

_VALID_ID = "01J00000000000000000000000"


def _note(front: str) -> Note:
    return Note.from_text(f"---\nid: {_VALID_ID}\ntitle: T\n{front}\n---\nbody\n")


def test_scalar_tag_string_is_one_tag():
    assert _note("tags: physics").tags == ["physics"]


def test_scalar_numeric_tag_is_one_tag():
    assert _note("tags: 2024").tags == ["2024"]


def test_scalar_alias_is_one_alias():
    assert _note("aliases: Relativity").aliases == ["Relativity"]


def test_list_tags_unchanged_and_blanks_dropped():
    assert _note("tags: [a, b, '']").tags == ["a", "b"]


def test_missing_tags_is_empty():
    assert _note("kind: knowledge").tags == []
