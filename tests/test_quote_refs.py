"""Unit tests for `knowlet/core/quote_refs.py` (M7.1)."""

from knowlet.core.quote_refs import (
    MAX_REFERENCES,
    MAX_SECTION_CHARS,
    QuoteRef,
    extract_enclosing_section,
    format_references_block,
    normalize_anchor,
)


def _ref(quote: str, *, title: str = "T", anchor: str = "") -> QuoteRef:
    return QuoteRef(
        note_id="01HX0000000000000000000001",
        note_title=title,
        quote_text=quote,
        paragraph_anchor=anchor or normalize_anchor(quote),
    )


# ---------------------------------------------------------------- normalize


def test_normalize_anchor_collapses_whitespace_and_lowercases():
    assert normalize_anchor("  Hello\n  World  ") == "hello world"


def test_normalize_anchor_truncates_at_64():
    long = "x" * 200
    assert len(normalize_anchor(long)) == 64


def test_normalize_anchor_handles_none_and_empty():
    assert normalize_anchor("") == ""
    assert normalize_anchor(None) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------- extract


def test_extract_enclosing_section_finds_h2_block():
    body = """\
# Top

intro

## Section A

para a1
[[ref-target]] line a2

## Section B

para b1
"""
    section = extract_enclosing_section(body, _ref("[[ref-target]] line a2"))
    assert section.startswith("## Section A")
    assert "[[ref-target]] line a2" in section
    # Must not bleed into Section B (same level).
    assert "## Section B" not in section
    assert "para b1" not in section


def test_extract_enclosing_section_inside_h3_stops_at_next_h2_or_h3():
    body = """\
## A

### Sub 1

quoted line

### Sub 2

other content
"""
    section = extract_enclosing_section(body, _ref("quoted line"))
    assert section.startswith("### Sub 1")
    assert "quoted line" in section
    assert "### Sub 2" not in section


def test_extract_enclosing_section_no_heading_returns_windowed_body():
    """No heading anywhere → fall back to the whole Note (or window if huge)."""
    body = "para 1\n\nQUOTE LINE\n\npara 3"
    section = extract_enclosing_section(body, _ref("QUOTE LINE"))
    assert section == body


def test_extract_enclosing_section_oversize_section_is_windowed():
    """Section longer than MAX_SECTION_CHARS → quote-centered window with ellipses."""
    big = "lead-in " * 400  # ~3200 chars
    quote = "the seminal moment"
    body = f"## A\n\n{big}{quote} happens here\n\nthen {big}"
    section = extract_enclosing_section(body, _ref(quote))
    assert len(section) <= MAX_SECTION_CHARS + 4  # +ellipses padding
    assert quote in section
    assert section.startswith("…") or section.endswith("…")


def test_extract_enclosing_section_quote_not_found_returns_marker():
    body = "## A\n\nhello world"
    section = extract_enclosing_section(body, _ref("xxxxx-not-here-xxxxx"))
    assert section.startswith("(原文已变更")


def test_extract_enclosing_section_anchor_fuzzy_match():
    """User edited the quoted line slightly; exact match fails but
    the anchor (paragraph head) still locks onto the right paragraph."""
    body = """\
## A

The transformer architecture introduces self-attention layers that
weight tokens by their relevance to each other.

## B
"""
    # Original quote (typo'd "weights" plural) — won't exact-match.
    ref = QuoteRef(
        note_id="x",
        note_title="T",
        quote_text="weights tokens by their relevance to each",
        paragraph_anchor=normalize_anchor(
            "The transformer architecture introduces self-attention layers"
        ),
    )
    section = extract_enclosing_section(body, ref)
    # Anchor located the paragraph; we should get Section A back.
    assert section.startswith("## A")
    assert "self-attention" in section


def test_extract_enclosing_section_collapsed_whitespace_fallback():
    """User selected text whose internal newlines differ from the body
    (e.g. PDF copy-paste collapsed two lines into one). Whitespace-relaxed
    search should still find it."""
    body = "## A\n\nThe quick brown\nfox jumps over\nthe lazy dog"
    section = extract_enclosing_section(body, _ref("quick brown fox jumps over"))
    assert section.startswith("## A")
    assert "quick brown" in section


def test_extract_enclosing_section_empty_body():
    assert extract_enclosing_section("", _ref("anything")) == ""


# --------------------------------------------------------------- format block


def test_format_references_block_empty_returns_empty_string():
    assert format_references_block([]) == ""


def test_format_references_block_single_ref_includes_quote_and_section():
    body = "## A\n\nthis is the line we cite"
    ref = _ref("this is the line we cite", title="My Note")
    out = format_references_block([(ref, body)])
    assert "我想就这段问你" in out
    assert "《My Note》" in out
    assert "> this is the line we cite" in out
    assert "## A" in out  # enclosing section
    # Trailing separator so the user message that follows is visually distinct.
    assert out.endswith("———————————————\n\n")


def test_format_references_block_multiple_refs_separated():
    body_a = "## X\n\nfirst line"
    body_b = "## Y\n\nsecond line"
    out = format_references_block(
        [
            (_ref("first line", title="A"), body_a),
            (_ref("second line", title="B"), body_b),
        ]
    )
    assert out.count("我想就这段问你") == 2
    assert "《A》" in out
    assert "《B》" in out
    assert "———————————————" in out


def test_format_references_block_multiline_quote_renders_blockquote_per_line():
    body = "## A\n\nline one\nline two\nline three"
    ref = _ref("line one\nline two")
    out = format_references_block([(ref, body)])
    assert "> line one" in out
    assert "> line two" in out


def test_max_references_constant_is_5():
    """Sanity check: ADR-0015 §2 pinned this at 5; the constant must match
    so any future change to the constant needs an explicit ADR amend."""
    assert MAX_REFERENCES == 5
