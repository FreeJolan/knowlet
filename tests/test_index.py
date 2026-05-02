import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
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


# ----------------------------------------------------------------- concurrency


def test_each_thread_gets_its_own_connection(tmp_path: Path):
    """connect() returns a different sqlite3.Connection per thread."""
    vault = _make_vault(tmp_path)
    idx = Index(vault.db_path, DummyBackend(dim=16))
    main_conn = idx.connect()

    other_conn_id_holder: dict[str, int] = {}

    def child() -> None:
        c = idx.connect()
        other_conn_id_holder["id"] = id(c)

    t = threading.Thread(target=child)
    t.start()
    t.join()

    assert other_conn_id_holder["id"] != id(main_conn)
    idx.close()


def test_cross_thread_use_of_one_connection_raises(tmp_path: Path):
    """A connection created in thread A must not be usable from thread B.

    With our default `check_same_thread=True`, the misuse is loud (raises),
    not silent (corrupts). This test pins that contract.
    """
    vault = _make_vault(tmp_path)
    idx = Index(vault.db_path, DummyBackend(dim=16))
    main_conn = idx.connect()

    box: dict[str, BaseException | None] = {"err": None}

    def child() -> None:
        try:
            main_conn.execute("SELECT 1").fetchone()
        except sqlite3.ProgrammingError as exc:
            box["err"] = exc

    t = threading.Thread(target=child)
    t.start()
    t.join()
    assert isinstance(box["err"], sqlite3.ProgrammingError)
    idx.close()


def test_concurrent_upserts_from_many_threads(tmp_path: Path):
    """Many threads writing different notes in parallel must not corrupt the
    index. WAL mode + busy_timeout serializes writers; no per-row collisions
    expected since note_ids are unique.
    """
    vault = _make_vault(tmp_path)
    idx = Index(vault.db_path, DummyBackend(dim=16))
    idx.connect()  # ensure migration has run before threads pile in

    notes = [
        Note(id=new_id(), title=f"note-{i}", body=f"body number {i} " * 20)
        for i in range(20)
    ]
    for n in notes:
        vault.write_note(n)

    def upsert(note: Note) -> str:
        idx.upsert_note(note, chunk_size=120, chunk_overlap=20)
        return note.id

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = [f.result() for f in as_completed([pool.submit(upsert, n) for n in notes])]

    assert sorted(ids) == sorted(n.id for n in notes)
    # Every note has at least one chunk indexed.
    main = idx.connect()
    rows = main.execute("SELECT note_id, COUNT(*) AS c FROM chunks GROUP BY note_id").fetchall()
    assert len(rows) == len(notes)
    assert all(row["c"] >= 1 for row in rows)
    idx.close()
