from pathlib import Path

from knowlet.core.embedding import DummyBackend
from knowlet.core.index import Index, _fts_escape
from knowlet.core.note import Note, new_id
from knowlet.core.vault import Vault


def _make_vault(tmp_path: Path) -> Vault:
    v = Vault(tmp_path)
    v.init_layout()
    return v


def test_fts_escape_handles_quotes_and_spaces():
    assert _fts_escape("hello world") == '"hello" OR "world"'
    assert _fts_escape("") == '""'
    out = _fts_escape('foo "bar" baz')
    assert '"foo"' in out
    assert '"baz"' in out


def test_index_upsert_and_search(tmp_path: Path):
    vault = _make_vault(tmp_path)
    backend = DummyBackend(dim=64)
    idx = Index(vault.db_path, backend)
    idx.connect()

    n1 = Note(
        id=new_id(),
        title="Attention paper notes",
        body="self-attention scales as O(n^2). query key value projections.",
    )
    n2 = Note(
        id=new_id(),
        title="RAG retrieval",
        body="hybrid BM25 plus dense vector via reciprocal rank fusion.",
    )
    vault.write_note(n1)
    vault.write_note(n2)
    idx.upsert_note(n1, chunk_size=200, chunk_overlap=40)
    idx.upsert_note(n2, chunk_size=200, chunk_overlap=40)

    hits = idx.search("attention", top_k=2)
    assert hits, "expected at least one hit"
    assert hits[0].title == "Attention paper notes"

    hits = idx.search("BM25", top_k=2)
    assert hits and hits[0].title == "RAG retrieval"

    # delete propagates
    idx.delete_note(n1.id)
    hits = idx.search("attention", top_k=2)
    assert all(h.note_id != n1.id for h in hits)
    idx.close()


def test_index_dedup_on_unchanged_content(tmp_path: Path):
    vault = _make_vault(tmp_path)
    backend = DummyBackend(dim=32)
    idx = Index(vault.db_path, backend)
    idx.connect()

    n = Note(id=new_id(), title="X", body="some body text" * 10)
    vault.write_note(n)
    idx.upsert_note(n, chunk_size=200, chunk_overlap=40)

    # Count chunks
    before = idx.connect().execute(
        "SELECT COUNT(*) AS c FROM chunks WHERE note_id = ?", (n.id,)
    ).fetchone()["c"]
    idx.upsert_note(n, chunk_size=200, chunk_overlap=40)  # idempotent
    after = idx.connect().execute(
        "SELECT COUNT(*) AS c FROM chunks WHERE note_id = ?", (n.id,)
    ).fetchone()["c"]
    assert before == after
    idx.close()
