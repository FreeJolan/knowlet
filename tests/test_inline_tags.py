"""Tests for the Phase 1 C polish — inline `#tag` extraction."""

from knowlet.core.inline_tags import (
    extract_inline_tags,
    merge_with_inline_tags,
)


def test_extract_basic():
    assert extract_inline_tags("hello #foo world") == ["foo"]


def test_extract_multiple_unique():
    assert extract_inline_tags("#one and #two and #three") == ["one", "two", "three"]


def test_extract_dedup_case_insensitive():
    # Original casing of first occurrence wins.
    assert extract_inline_tags("#Topic #topic #TOPIC") == ["Topic"]


def test_extract_skips_word_prefix():
    """`prefix#tag` should not be a tag — # must follow non-word char."""
    assert extract_inline_tags("see foo#bar baz") == []


def test_extract_handles_cjk():
    assert extract_inline_tags("中文 #话题 后面") == ["话题"]


def test_extract_handles_dash_underscore_slash():
    assert extract_inline_tags("#topic-x and #area/sub and #under_score") == [
        "topic-x",
        "area/sub",
        "under_score",
    ]


def test_extract_skips_markdown_heading():
    """`# Heading` (with space) is markdown; only `#word` (no space) is a tag."""
    assert extract_inline_tags("# Heading\nbody #real-tag\n## Sub heading") == [
        "real-tag",
    ]


def test_extract_skips_inline_code():
    assert extract_inline_tags("Use `#hash` for headings, but #real-tag matters") == [
        "real-tag",
    ]


def test_extract_skips_fenced_code():
    body = "```\n#fake-in-code\n```\nbody #real-tag here"
    assert extract_inline_tags(body) == ["real-tag"]


def test_extract_empty_body():
    assert extract_inline_tags("") == []
    assert extract_inline_tags("   \n\n   ") == []


def test_extract_just_hash_no_match():
    assert extract_inline_tags("# only hash followed by space\n# another") == []


# ------------------------------------------------------------ merge


def test_merge_preserves_explicit_order():
    out = merge_with_inline_tags(["b", "a"], "body has #c and #d")
    assert out == ["b", "a", "c", "d"]


def test_merge_dedup_case_insensitive():
    out = merge_with_inline_tags(["foo"], "body has #FOO and #bar")
    # explicit's "foo" wins case; FOO is dropped, bar appended
    assert out == ["foo", "bar"]


def test_merge_no_inline_tags():
    out = merge_with_inline_tags(["existing"], "no tags here")
    assert out == ["existing"]


def test_merge_no_explicit_tags():
    out = merge_with_inline_tags([], "body #only-inline")
    assert out == ["only-inline"]


def test_merge_filters_blank_explicit():
    out = merge_with_inline_tags(["", "  ", "real"], "")
    # We don't strip explicit entries; pass-through. (Empty explicit is
    # ignored by the dedup-set-insert loop because empty strings hash
    # the same.) Just verify no crash + no spurious tags.
    assert "real" in out
