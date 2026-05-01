from pathlib import Path

from knowlet.core.note import Note, new_id, slugify


def test_slugify_basic():
    assert slugify("Hello World") == "hello-world"
    assert slugify("RAG: hybrid retrieval!") == "rag-hybrid-retrieval"


def test_slugify_cjk_kept():
    assert slugify("注意力机制") == "注意力机制"
    assert slugify("attention 注意力 paper").startswith("attention-注意力-paper")


def test_slugify_empty_falls_back():
    assert slugify("") == "note"
    assert slugify("---") == "note"


def test_note_round_trip(tmp_path: Path):
    note = Note(id=new_id(), title="Hello", body="some body\n\nmore body", tags=["a", "b"])
    path = tmp_path / note.filename
    path.write_text(note.to_markdown(), encoding="utf-8")

    loaded = Note.from_file(path)
    assert loaded.id == note.id
    assert loaded.title == note.title
    assert loaded.body.strip() == note.body.strip()
    assert loaded.tags == note.tags


def test_content_hash_stable():
    a = Note(id="x", title="T", body="B")
    b = Note(id="y", title="T", body="B")  # different id, same content
    assert a.content_hash == b.content_hash
    c = Note(id="x", title="T2", body="B")
    assert a.content_hash != c.content_hash
