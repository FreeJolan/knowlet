"""Unit tests for `knowlet/core/backlinks.py` (M7.0.4)."""

from pathlib import Path

from knowlet.core.backlinks import (
    Wikilink,
    extract_wikilinks,
    find_backlinks,
)
from knowlet.core.note import Note, new_id
from knowlet.core.vault import Vault


# -------------------------------------------------------------- extract


def test_extract_wikilinks_basic():
    body = "see [[Attention is All You Need]] and [[Transformer]] for more"
    links = extract_wikilinks(body)
    assert [l.target for l in links] == ["Attention is All You Need", "Transformer"]
    assert all(l.line == 1 for l in links)


def test_extract_wikilinks_multiline():
    body = "first line has [[A]]\nsecond line\nthird line has [[B]] and [[C]]"
    links = extract_wikilinks(body)
    targets = [(l.target, l.line) for l in links]
    assert targets == [("A", 1), ("B", 3), ("C", 3)]


def test_extract_wikilinks_strips_alias():
    """`[[Title|alias]]` resolves to `Title` for matching purposes."""
    links = extract_wikilinks("see [[RAG|retrieval-aug-gen]] details")
    assert [l.target for l in links] == ["RAG"]


def test_extract_wikilinks_ignores_empty():
    """`[[]]` and `[[ ]]` are not valid links."""
    assert extract_wikilinks("[[]] and [[ ]]") == []


def test_extract_wikilinks_no_cross_line():
    """A `[[` that doesn't close on the same line should NOT match across
    a newline. Markdown wikilinks are line-bounded by convention."""
    assert extract_wikilinks("[[unclosed\nstill open]]") == []


def test_extract_wikilinks_empty_body():
    assert extract_wikilinks("") == []
    assert extract_wikilinks(None) == []  # type: ignore[arg-type]


# -------------------------------------------------------------- find


def _write(v: Vault, title: str, body: str) -> Note:
    n = Note(id=new_id(), title=title, body=body)
    v.write_note(n)
    return n


def test_find_backlinks_simple_match(tmp_path: Path):
    v = Vault(tmp_path)
    v.init_layout()
    target = _write(v, "Attention", "core idea")
    src = _write(v, "Survey", "see [[Attention]] for the seminal paper")

    backs = find_backlinks(target.title, v.iter_note_paths(), exclude_id=target.id)
    assert len(backs) == 1
    b = backs[0]
    assert b.source_id == src.id
    assert b.source_title == "Survey"
    assert b.target == "Attention"
    assert "[[Attention]]" in b.sentence


def test_find_backlinks_case_insensitive_and_whitespace(tmp_path: Path):
    """Matching collapses whitespace + ignores case so the user can type
    `[[ attention ]]` and still get a hit on Note titled "Attention"."""
    v = Vault(tmp_path)
    v.init_layout()
    target = _write(v, "Attention", "x")
    src = _write(v, "Notes", "see [[ ATTENTION ]] elsewhere")

    backs = find_backlinks(target.title, v.iter_note_paths(), exclude_id=target.id)
    assert len(backs) == 1
    assert backs[0].source_id == src.id


def test_find_backlinks_excludes_self(tmp_path: Path):
    """A note that references its own title shouldn't show up in its own
    backlinks panel."""
    v = Vault(tmp_path)
    v.init_layout()
    self_ref = _write(v, "Self", "I am [[Self]] referencing myself")

    backs = find_backlinks(self_ref.title, v.iter_note_paths(), exclude_id=self_ref.id)
    assert backs == []


def test_find_backlinks_no_results(tmp_path: Path):
    v = Vault(tmp_path)
    v.init_layout()
    _write(v, "Lonely", "no inbound links")
    _write(v, "Other", "totally unrelated content")

    backs = find_backlinks("Lonely", v.iter_note_paths(), exclude_id=None)
    assert backs == []


def test_find_backlinks_long_sentence_is_trimmed(tmp_path: Path):
    """A 1000-char paragraph containing the wikilink shouldn't dump all
    1000 chars into the panel — the preview should window around the
    match and add ellipses."""
    v = Vault(tmp_path)
    v.init_layout()
    target = _write(v, "Target", "x")
    long_body = "lead-in " * 200 + "[[Target]] is the seminal " + "tail " * 200
    src = _write(v, "Long", long_body)

    backs = find_backlinks("Target", v.iter_note_paths(), exclude_id=target.id)
    assert len(backs) == 1
    assert len(backs[0].sentence) <= 260  # 240 window + a couple ellipses
    assert "[[Target]]" in backs[0].sentence
    assert backs[0].sentence.startswith("…") or backs[0].sentence.endswith("…")


def test_find_backlinks_sorted_by_source_title_then_line(tmp_path: Path):
    v = Vault(tmp_path)
    v.init_layout()
    target = _write(v, "T", "x")
    _write(v, "Zebra", "see [[T]] line 1\n\nand [[T]] line 3")
    _write(v, "Apple", "we [[T]] here")

    backs = find_backlinks("T", v.iter_note_paths(), exclude_id=target.id)
    titles = [b.source_title for b in backs]
    assert titles == ["Apple", "Zebra", "Zebra"]
    # Within Zebra: lines ascending
    zebra_lines = [b.line for b in backs if b.source_title == "Zebra"]
    assert zebra_lines == sorted(zebra_lines)


def test_find_backlinks_handles_alias_form(tmp_path: Path):
    v = Vault(tmp_path)
    v.init_layout()
    target = _write(v, "Retrieval-Augmented Generation", "RAG")
    src = _write(v, "Notes", "[[Retrieval-Augmented Generation|RAG]] is great")

    backs = find_backlinks(target.title, v.iter_note_paths(), exclude_id=target.id)
    assert len(backs) == 1
    assert backs[0].source_id == src.id
