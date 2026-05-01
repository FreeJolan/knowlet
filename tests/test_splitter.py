from knowlet.core.splitter import chunk_text


def test_short_text_one_chunk():
    out = chunk_text("hello world", size=100, overlap=20)
    assert len(out) == 1
    assert out[0].text == "hello world"


def test_empty_text_no_chunks():
    assert chunk_text("", size=100, overlap=20) == []
    assert chunk_text("   \n\n  ", size=100, overlap=20) == []


def test_long_text_splits_with_overlap():
    text = "a" * 1200
    out = chunk_text(text, size=500, overlap=100)
    assert len(out) >= 3
    # Each chunk respects the size cap.
    assert all(len(c.text) <= 500 for c in out)
    # Positions are sequential.
    assert [c.position for c in out] == list(range(len(out)))


def test_prefers_paragraph_boundary():
    block = "para one is here.\n\npara two is here.\n\npara three is here.\n\n"
    text = block * 5
    out = chunk_text(text, size=120, overlap=30)
    # At least one chunk should end exactly on a paragraph break.
    boundary_endings = sum(1 for c in out if c.text.rstrip().endswith("here."))
    assert boundary_endings >= 1


def test_invalid_overlap_raises():
    import pytest

    with pytest.raises(ValueError):
        chunk_text("x" * 100, size=10, overlap=10)
    with pytest.raises(ValueError):
        chunk_text("x" * 100, size=0, overlap=0)
