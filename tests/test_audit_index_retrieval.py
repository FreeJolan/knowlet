"""Regression tests for the 2026-11 audit, batch `index-retrieval`.

Each test is tied to one audit finding (file:line in the test docstring).
They were all written RED against the pre-fix code, then turned green by
the fixes in knowlet/core/{index,embedding,structure_signals,backlinks,
quote_refs}.py.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

import numpy as np
import pytest

import knowlet.core.structure_signals as structure_signals
from knowlet.core.embedding import DummyBackend, make_backend
from knowlet.core.index import Index, IndexDimensionMismatchError, reindex_vault
from knowlet.core.note import Note, new_id
from knowlet.core.quote_refs import QuoteRef, _locate_quote, normalize_anchor
from knowlet.core.structure_signals import (
    compute_signals,
    near_duplicates,
    orphan_notes,
)
from knowlet.core.vault import Vault


def _make_vault(tmp_path: Path) -> Vault:
    v = Vault(tmp_path)
    v.init_layout()
    return v


def _vec_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) AS c FROM chunks_vec").fetchone()["c"])


def _chunk_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) AS c FROM chunks").fetchone()["c"])


# =====================================================================
# index.py:243 — upsert_note must clean stale chunks_vec rows
# =====================================================================


def test_upsert_reindex_does_not_leak_stale_vectors(tmp_path: Path):
    """Editing a note N times must not leave N generations of dead
    vectors in chunks_vec (vec0 has no FK and no trigger)."""
    vault = _make_vault(tmp_path)
    idx = Index(vault.db_path, DummyBackend(dim=32))
    idx.connect()

    n = Note(id=new_id(), title="T", body="first version body text " * 20)
    idx.upsert_note(n, chunk_size=64, chunk_overlap=16)
    conn = idx.connect()
    c1, v1 = _chunk_count(conn), _vec_count(conn)
    assert c1 > 0
    assert v1 == c1

    for i in range(3):
        edited = Note(id=n.id, title="T", body=f"edited version {i} body text " * 20)
        idx.upsert_note(edited, chunk_size=64, chunk_overlap=16)

    c2, v2 = _chunk_count(conn), _vec_count(conn)
    # chunks_vec must track chunks exactly — no orphan vector rows.
    assert v2 == c2
    idx.close()


# =====================================================================
# index.py:284 — embed failure must not leave a dangling write txn
# =====================================================================


class _FlakyBackend(DummyBackend):
    """Fails the first embed_documents call, then behaves normally."""

    def __init__(self, dim: int = 32):
        super().__init__(dim=dim)
        self.fail_next = True

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("simulated model OOM")
        return super().embed_documents(texts)


def test_upsert_embed_failure_rolls_back_and_retry_fully_indexes(tmp_path: Path):
    """If embed_documents raises, the transaction must be rolled back.
    Pre-fix: the half-written notes/chunks rows dangled on the
    connection; the retry hit the content_hash early-exit and committed
    a note with chunks but ZERO vectors — permanently unsearchable via
    the vector channel."""
    vault = _make_vault(tmp_path)
    idx = Index(vault.db_path, _FlakyBackend(dim=32))
    idx.connect()

    n = Note(id=new_id(), title="T", body="hello world content " * 30)
    with pytest.raises(RuntimeError, match="simulated model OOM"):
        idx.upsert_note(n, chunk_size=64, chunk_overlap=16)

    conn = idx.connect()
    # No dangling write transaction after the failure.
    assert not conn.in_transaction
    # And nothing half-written for this note.
    assert (
        conn.execute("SELECT COUNT(*) AS c FROM notes WHERE id = ?", (n.id,)).fetchone()["c"] == 0
    )

    # Retry (same content hash) must fully index, vectors included.
    idx.upsert_note(n, chunk_size=64, chunk_overlap=16)
    joined = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM chunks c JOIN chunks_vec v ON v.chunk_id = c.id
        WHERE c.note_id = ?
        """,
        (n.id,),
    ).fetchone()["c"]
    assert joined > 0
    idx.close()


# =====================================================================
# index.py:111 — close() vs other threads' connections
# =====================================================================


def test_close_invalidates_other_threads_connections(tmp_path: Path):
    """close() cannot close a foreign thread's sqlite3 connection (that
    raises ProgrammingError) — but it must invalidate it so the owning
    thread closes + reopens on its next connect(), instead of silently
    keeping a live handle on a possibly-unlinked DB file."""
    vault = _make_vault(tmp_path)
    idx = Index(vault.db_path, DummyBackend(dim=16))
    idx.connect()

    opened = threading.Event()
    closed = threading.Event()
    result: dict[str, object] = {}

    def worker() -> None:
        c1 = idx.connect()
        opened.set()
        assert closed.wait(5)
        c2 = idx.connect()
        result["new_is_different"] = c2 is not c1
        try:
            c1.execute("SELECT 1")
            result["old_alive"] = True
        except sqlite3.ProgrammingError:
            result["old_alive"] = False
        result["new_works"] = c2.execute("SELECT 1").fetchone() is not None

    t = threading.Thread(target=worker)
    t.start()
    assert opened.wait(5)
    idx.close()
    closed.set()
    t.join(5)

    assert result["new_is_different"] is True
    # The stale connection must actually be closed (by its owner thread
    # inside connect()), not leaked open.
    assert result["old_alive"] is False
    assert result["new_works"] is True
    idx.close()


def test_delete_index_db_removes_wal_sidecars(tmp_path: Path):
    """Rebuild must not leave -wal/-shm behind: a new DB at the same
    path would attach to the old WAL and corrupt itself."""
    from knowlet.core.index import delete_index_db

    vault = _make_vault(tmp_path)
    idx = Index(vault.db_path, DummyBackend(dim=16))
    idx.connect()
    n = Note(id=new_id(), title="T", body="body " * 10)
    idx.upsert_note(n, chunk_size=64, chunk_overlap=16)
    idx.close()

    wal = Path(str(vault.db_path) + "-wal")
    shm = Path(str(vault.db_path) + "-shm")
    # Ensure the sidecars exist regardless of checkpoint behavior.
    if not wal.exists():
        wal.write_bytes(b"x")
    if not shm.exists():
        shm.write_bytes(b"x")

    delete_index_db(vault.db_path)
    assert not vault.db_path.exists()
    assert not wal.exists()
    assert not shm.exists()
    # Idempotent on missing files.
    delete_index_db(vault.db_path)


# =====================================================================
# index.py:574 — reindex id stability for frontmatter-less notes
# =====================================================================


def test_reindex_stable_id_for_plain_markdown_import(tmp_path: Path):
    """A plain `.md` file without frontmatter (external import) must get
    ONE id, persisted to disk, not a fresh random ULID per reindex run
    (which deleted + re-embedded it on every startup)."""
    vault = _make_vault(tmp_path)
    plain = vault.notes_dir / "读书笔记.md"
    plain.write_text("# 读书笔记\n\n一些导入的内容。\n", encoding="utf-8")
    backend = DummyBackend(dim=32)

    reindex_vault(
        vault.root,
        vault.db_path,
        backend,
        chunk_size=64,
        chunk_overlap=16,
        note_paths=list(vault.iter_note_paths()),
    )
    idx = Index(vault.db_path, backend)
    idx.connect()
    ids1 = idx.known_note_ids()
    idx.close()

    reindex_vault(
        vault.root,
        vault.db_path,
        backend,
        chunk_size=64,
        chunk_overlap=16,
        note_paths=list(vault.iter_note_paths()),
    )
    idx = Index(vault.db_path, backend)
    idx.connect()
    ids2 = idx.known_note_ids()
    idx.close()

    assert len(ids1) == 1
    assert ids1 == ids2
    # The id was materialized into the file's frontmatter on disk.
    assert next(iter(ids1)) in plain.read_text(encoding="utf-8")


# =====================================================================
# embedding.py:105 — loud fallback + embedding identity recorded
# =====================================================================


def test_make_backend_missing_dep_fallback_warns(monkeypatch, caplog):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    with caplog.at_level(logging.WARNING, logger="knowlet.core.embedding"):
        backend = make_backend("sentence_transformers", "all-MiniLM-L6-v2", 384)
    assert isinstance(backend, DummyBackend)
    assert any("sentence_transformers" in r.message for r in caplog.records)


class _FakeSTBackend:
    """Same dim as DummyBackend but a different embedding identity."""

    def __init__(self, dim: int = 32):
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def identity(self) -> str:
        return "sentence_transformers:all-MiniLM-L6-v2"

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return np.zeros((len(texts), self._dim), dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        return np.zeros(self._dim, dtype=np.float32)


def test_index_rejects_same_dim_backend_switch(tmp_path: Path):
    """Switching to a different model/backend with the SAME dimension
    must raise (dirty-vector mix), same remedy as a dim mismatch."""
    vault = _make_vault(tmp_path)
    idx = Index(vault.db_path, DummyBackend(dim=32))
    idx.connect()
    idx.close()

    idx2 = Index(vault.db_path, _FakeSTBackend(dim=32))
    with pytest.raises(IndexDimensionMismatchError, match="rebuild"):
        idx2.connect()


def test_index_backfills_identity_for_legacy_db(tmp_path: Path):
    """A pre-fix DB has no embedding_identity row — first open with the
    configured backend backfills it instead of raising."""
    vault = _make_vault(tmp_path)
    idx = Index(vault.db_path, DummyBackend(dim=32))
    conn = idx.connect()
    conn.execute("DELETE FROM meta WHERE key = 'embedding_identity'")
    conn.commit()
    idx.close()

    idx2 = Index(vault.db_path, DummyBackend(dim=32))
    conn2 = idx2.connect()
    row = conn2.execute("SELECT value FROM meta WHERE key = 'embedding_identity'").fetchone()
    assert row is not None
    assert row["value"] == "dummy"
    idx2.close()


# =====================================================================
# structure_signals.py:276 — orphan_notes must be O(notes)
# =====================================================================


def _backdate(idx: Index, note_id: str, days: int) -> None:
    from datetime import UTC, datetime, timedelta

    old_ts = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = idx.connect()
    conn.execute("UPDATE notes SET updated_at = ? WHERE id = ?", (old_ts, note_id))
    conn.commit()


def _add_note(vault: Vault, idx: Index, title: str, body: str, *, days_old: int = 0) -> Note:
    n = Note(id=new_id(), title=title, body=body)
    vault.write_note(n)
    idx.upsert_note(n, chunk_size=64, chunk_overlap=16)
    if days_old:
        _backdate(idx, n.id, days_old)
    return n


def test_orphan_notes_reads_each_file_at_most_once(tmp_path: Path, monkeypatch):
    """Pre-fix, orphan_notes called find_backlinks per candidate, i.e.
    O(candidates * notes) full file reads + YAML parses. It must read
    each vault file at most once."""
    vault = _make_vault(tmp_path)
    idx = Index(vault.db_path, DummyBackend(dim=16))
    idx.connect()

    for i in range(3):
        _add_note(vault, idx, f"old-{i}", f"unlinked body {i}", days_old=120)
    _add_note(vault, idx, "fresh-a", "recent body a")
    _add_note(vault, idx, "fresh-b", "recent body b")

    calls = {"n": 0}
    orig = Note.from_file.__func__

    def counting(cls, path):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return orig(cls, path)

    monkeypatch.setattr(Note, "from_file", classmethod(counting))

    paths = list(vault.iter_note_paths())
    orphans = orphan_notes(paths, idx, untouched_days=90)
    assert sorted(o.title for o in orphans) == ["old-0", "old-1", "old-2"]
    # 3 candidates * 5 files = 15 reads pre-fix; ≤ 5 post-fix.
    assert calls["n"] <= len(paths)
    idx.close()


def test_orphan_notes_respects_anchored_inbound_links(tmp_path: Path):
    """`[[Title#heading]]` is an inbound link to `Title` — the target
    must not be flagged as an orphan (parity with graph.build_graph)."""
    vault = _make_vault(tmp_path)
    idx = Index(vault.db_path, DummyBackend(dim=16))
    idx.connect()

    _add_note(vault, idx, "深度学习", "基础概念笔记", days_old=120)
    _add_note(vault, idx, "索引", "参见 [[深度学习#简介]] 一节")

    orphans = orphan_notes(list(vault.iter_note_paths()), idx, untouched_days=90)
    assert "深度学习" not in [o.title for o in orphans]
    idx.close()


# =====================================================================
# structure_signals.py:169 — near_duplicates computed once + vectorized
# =====================================================================


def test_compute_signals_runs_near_duplicates_once(tmp_path: Path, monkeypatch):
    vault = _make_vault(tmp_path)
    idx = Index(vault.db_path, DummyBackend(dim=16))
    idx.connect()
    _add_note(vault, idx, "a", "alpha body text")
    _add_note(vault, idx, "b", "beta body text")

    calls = {"n": 0}
    orig = structure_signals.near_duplicates

    def counting(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return orig(*args, **kwargs)

    monkeypatch.setattr(structure_signals, "near_duplicates", counting)
    compute_signals(idx, list(vault.iter_note_paths()))
    assert calls["n"] == 1
    idx.close()


class _OneHotBackend:
    """Embeds GROUP_X-tagged text as a one-hot vector so similarity is
    fully controllable (cosine 1 within a group, 0 across groups)."""

    def __init__(self, dim: int = 8):
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self._dim, dtype=np.float32)
        for tag in ("GROUP_A", "GROUP_B", "GROUP_C"):
            if tag in text:
                v[ord(tag[-1]) % self._dim] = 1.0
                return v
        v[self._dim - 1] = 1.0
        return v

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dim), dtype=np.float32)
        return np.stack([self._vec(t) for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._vec(text)


def test_near_duplicates_matches_naive_double_loop(tmp_path: Path):
    """Equivalence guard for the vectorized upper-triangle scan."""
    vault = _make_vault(tmp_path)
    idx = Index(vault.db_path, _OneHotBackend(dim=8))
    idx.connect()
    for i in range(4):
        _add_note(vault, idx, f"a{i}", f"GROUP_A text {i}")
    for i in range(3):
        _add_note(vault, idx, f"b{i}", f"GROUP_B text {i}")
    _add_note(vault, idx, "solo", "GROUP_C text")

    pairs = near_duplicates(idx, cosine_threshold=0.92)

    # Naive reference on the same matrix.
    note_ids, _titles, m = structure_signals._load_note_embeddings(idx)
    sim = m @ m.T
    expected = set()
    for i in range(len(note_ids)):
        for j in range(i + 1, len(note_ids)):
            if float(sim[i, j]) >= 0.92:
                expected.add((note_ids[i], note_ids[j]))

    assert {(p.a_id, p.b_id) for p in pairs} == expected
    # 4 GROUP_A pairs: C(4,2)=6; GROUP_B: C(3,2)=3.
    assert len(pairs) == 9
    # Sorted by cosine desc still holds.
    assert all(pairs[i].cosine >= pairs[i + 1].cosine for i in range(len(pairs) - 1))
    idx.close()


# =====================================================================
# backlinks.py:118 — anchors stripped when matching targets
# =====================================================================


def test_find_backlinks_matches_anchored_wikilinks(tmp_path: Path):
    from knowlet.core.backlinks import find_backlinks

    vault = _make_vault(tmp_path)
    target = Note(id=new_id(), title="机器学习", body="核心概念")
    vault.write_note(target)
    src = Note(
        id=new_id(),
        title="综述",
        body="损失函数见 [[机器学习#损失函数]],块引用见 [[机器学习#^blk42]]。",
    )
    vault.write_note(src)

    backs = find_backlinks("机器学习", vault.iter_note_paths(), exclude_id=target.id)
    assert len(backs) == 2
    assert {b.source_id for b in backs} == {src.id}
    # The raw target (anchor included) is preserved for display.
    assert {b.target for b in backs} == {"机器学习#损失函数", "机器学习#^blk42"}


# =====================================================================
# quote_refs.py:113 — anchor fallback offset must not drift
# =====================================================================


def test_locate_quote_anchor_offset_exact_with_wide_separators():
    """Paragraph separators longer than exactly "\\n\\n" must not make
    the anchor-located offset drift (it fed extract_enclosing_section
    the wrong section)."""
    para = "unique anchor paragraph original content goes right here"
    body = f"# Alpha\n\npara one text\n\n\n\npadding line\n  \n# Beta\n\n{para}"
    quote_edited = "unique anchor paragraph that was edited afterwards"
    ref = QuoteRef(
        note_id="01HX0000000000000000000001",
        note_title="T",
        quote_text=quote_edited,
        paragraph_anchor=normalize_anchor(para),
    )
    offset = _locate_quote(body, ref)
    assert offset == body.index(para)


# =====================================================================
# index.py:243 / :284 — heal DBs already damaged by the old upsert path
# =====================================================================


def test_reindex_repairs_orphan_vectors_and_vectorless_notes(tmp_path: Path):
    """Existing index DBs carry the damage of the pre-fix upsert path:
    dead vector rows from every past edit, and notes committed with
    chunks but no vectors (whose unchanged content_hash made every later
    upsert skip them). A reindex must prune the former and re-embed the
    latter."""
    vault = _make_vault(tmp_path)
    backend = DummyBackend(dim=32)
    n = Note(id=new_id(), title="T", body="body text for vectors " * 20)
    vault.write_note(n)
    paths = list(vault.iter_note_paths())
    reindex_vault(vault.root, vault.db_path, backend, 64, 16, note_paths=paths)

    idx = Index(vault.db_path, backend)
    conn = idx.connect()
    # Damage 1: a dead vector whose chunk no longer exists.
    conn.execute(
        "INSERT INTO chunks_vec(chunk_id, embedding) VALUES (?, ?)",
        (999_999, np.zeros(32, dtype=np.float32).tobytes()),
    )
    # Damage 2: the note's vectors are gone but its hash is current.
    conn.execute(
        "DELETE FROM chunks_vec WHERE chunk_id IN (SELECT id FROM chunks WHERE note_id = ?)",
        (n.id,),
    )
    conn.commit()
    idx.close()

    reindex_vault(vault.root, vault.db_path, backend, 64, 16, note_paths=paths)

    idx = Index(vault.db_path, backend)
    conn = idx.connect()
    vec_ids = {int(r["chunk_id"]) for r in conn.execute("SELECT chunk_id FROM chunks_vec")}
    chunk_ids = {int(r["id"]) for r in conn.execute("SELECT id FROM chunks")}
    assert 999_999 not in vec_ids
    assert chunk_ids and vec_ids == chunk_ids
    idx.close()


# =====================================================================
# index.py:111 — DB file replaced underneath a live Index
# =====================================================================


def test_connect_follows_db_file_replaced_by_another_process(tmp_path: Path):
    """`knowlet reindex --rebuild` from the CLI deletes + recreates the DB
    while the web server holds connections. The server's handle pointed
    at the unlinked inode: its writes vanished and its reads went stale
    until restart. connect() must notice the replacement and reopen."""
    from knowlet.core.index import delete_index_db

    vault = _make_vault(tmp_path)
    backend = DummyBackend(dim=16)
    server_idx = Index(vault.db_path, backend)
    server_idx.connect()

    # "Other process": rebuild from scratch at the same path.
    delete_index_db(vault.db_path)
    cli_idx = Index(vault.db_path, backend)
    cli_idx.connect()
    rebuilt = Note(id=new_id(), title="rebuilt", body="from the cli rebuild")
    cli_idx.upsert_note(rebuilt, chunk_size=64, chunk_overlap=16)
    cli_idx.close()

    # Server sees the rebuilt DB, and its own writes land in it.
    assert rebuilt.id in server_idx.known_note_ids()
    saved = Note(id=new_id(), title="saved", body="saved after the rebuild")
    server_idx.upsert_note(saved, chunk_size=64, chunk_overlap=16)
    server_idx.close()

    check = Index(vault.db_path, backend)
    check.connect()
    assert {rebuilt.id, saved.id} <= check.known_note_ids()
    check.close()


# =====================================================================
# embedding.py:105 — stand-in backend never writes hash vectors
# =====================================================================


def test_make_backend_fallback_is_marked_stand_in(monkeypatch):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    backend = make_backend("sentence_transformers", "sentence-transformers/all-MiniLM-L6-v2", 32)
    assert isinstance(backend, DummyBackend)
    assert backend.stand_in_for == "sentence_transformers:all-MiniLM-L6-v2"


def test_stand_in_backend_withholds_vectors_then_real_backend_reembeds(tmp_path: Path):
    """Dependency missing → the stand-in must (a) not trip the identity
    check of a semantic index, (b) not write hash vectors into it, and
    (c) once the real backend is back, a reindex re-embeds the notes
    edited meanwhile."""
    vault = _make_vault(tmp_path)
    real = _FakeSTBackend(dim=32)
    n = Note(id=new_id(), title="T", body="original body " * 10)
    vault.write_note(n)
    reindex_vault(vault.root, vault.db_path, real, 64, 16, note_paths=list(vault.iter_note_paths()))

    stand_in = DummyBackend(dim=32, stand_in_for=real.identity)
    idx = Index(vault.db_path, stand_in)
    conn = idx.connect()  # must not raise IndexEmbeddingMismatchError
    edited = Note(id=n.id, title="T", body="edited while degraded " * 10, path=n.path)
    idx.upsert_note(edited, chunk_size=64, chunk_overlap=16)
    assert _chunk_count(conn) > 0
    assert _vec_count(conn) == 0  # no hash vectors in a semantic index
    idx.close()
    vault.write_note(edited)

    reindex_vault(vault.root, vault.db_path, real, 64, 16, note_paths=list(vault.iter_note_paths()))
    idx = Index(vault.db_path, real)
    conn = idx.connect()
    assert _chunk_count(conn) > 0
    assert _vec_count(conn) == _chunk_count(conn)
    idx.close()


def test_st_identity_ignores_hf_namespace_prefix():
    from knowlet.core.embedding import SentenceTransformersBackend

    short = SentenceTransformersBackend("all-MiniLM-L6-v2")
    long = SentenceTransformersBackend("sentence-transformers/all-MiniLM-L6-v2")
    other = SentenceTransformersBackend("paraphrase-MiniLM-L6-v2")
    assert short.identity == long.identity  # no model load needed
    assert short.identity != other.identity


# =====================================================================
# index.py:574 — frontmatter present but without `id`
# =====================================================================


def test_reindex_stable_id_for_frontmatter_without_id(tmp_path: Path):
    vault = _make_vault(tmp_path)
    f = vault.notes_dir / "imported.md"
    f.write_text("---\ntitle: 导入笔记\ntags: [a]\n---\n\n正文内容。\n", encoding="utf-8")
    backend = DummyBackend(dim=32)

    def run() -> set[str]:
        reindex_vault(vault.root, vault.db_path, backend, 64, 16, list(vault.iter_note_paths()))
        idx = Index(vault.db_path, backend)
        idx.connect()
        ids = idx.known_note_ids()
        idx.close()
        return ids

    first = run()
    assert len(first) == 1
    assert run() == first


# =====================================================================
# backlinks.py:118 / graph.py — one target-resolution rule everywhere
# =====================================================================


def test_titles_containing_hash_still_resolve_in_graph_and_backlinks(tmp_path: Path):
    """Anchor stripping must not break titles that contain `#` / `^`
    themselves (`C# 入门`): the as-written target is tried first."""
    from knowlet.core.backlinks import find_backlinks
    from knowlet.core.graph import build_graph, read_body_via_note

    vault = _make_vault(tmp_path)
    csharp = Note(id=new_id(), title="C# 入门", body="语言基础")
    ml = Note(id=new_id(), title="机器学习", body="核心概念")
    src = Note(id=new_id(), title="索引", body="见 [[C# 入门]] 与 [[机器学习#损失函数]]")
    for n in (csharp, ml, src):
        vault.write_note(n)

    metas = [{"id": n.id, "title": n.title, "path": n.filename} for n in (csharp, ml, src)]
    g = build_graph(
        metas,
        folder_for=vault.folder_of,
        read_body=lambda p: read_body_via_note(vault.notes_dir / Path(p).name),
    )
    assert {(e.source, e.target) for e in g.edges} == {(src.id, csharp.id), (src.id, ml.id)}

    backs = find_backlinks("C# 入门", vault.iter_note_paths(), exclude_id=csharp.id)
    assert [b.source_id for b in backs] == [src.id]
