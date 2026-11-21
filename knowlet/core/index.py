"""SQLite-backed index: FTS5 + sqlite-vec, hybrid search via RRF."""

from __future__ import annotations

import contextlib
import json
import sqlite3
import struct
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import sqlite_vec

from knowlet.core.embedding import EmbeddingBackend, configured_identity, writes_vectors
from knowlet.core.note import Note
from knowlet.core.splitter import chunk_text

if TYPE_CHECKING:
    from knowlet.core.vault import Vault

SCHEMA_VERSION = 1


class IndexDimensionMismatchError(RuntimeError):
    """Raised when the configured embedding dim differs from the indexed dim."""


class IndexEmbeddingMismatchError(IndexDimensionMismatchError):
    """Raised when the index was built with a different embedding backend /
    model than the configured one, even if the dimension happens to match
    (same-dim model switches silently mix incompatible vector spaces).
    Subclasses IndexDimensionMismatchError so existing handlers (doctor,
    chat bootstrap) keep catching it — the remedy is the same rebuild."""


@dataclass
class SearchHit:
    note_id: str
    title: str
    path: str
    snippet: str
    chunk_position: int
    score: float


def _vec_to_blob(v: np.ndarray) -> bytes:
    arr = np.ascontiguousarray(v, dtype=np.float32)
    return struct.pack(f"{arr.size}f", *arr.tolist())


def _db_file_identity(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_dev, st.st_ino)


def delete_index_db(db_path: Path) -> None:
    """Remove an index DB together with its WAL / SHM sidecars.

    Unlinking only the main file leaves ``-wal`` / ``-shm`` behind, and a
    fresh DB created at the same path would adopt (replay) the stale WAL.
    Every ``Index`` on this path must be ``close()``d first. Sidecars go
    before the main file so no opener can pair the old WAL with a new DB.
    """
    for suffix in ("-wal", "-shm", "-journal", ""):
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)


def _check_trigram(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE _trigram_probe USING fts5(x, tokenize='trigram')")
        conn.execute("DROP TABLE _trigram_probe")
        return True
    except sqlite3.OperationalError:
        return False


class Index:
    """Persistent index over Notes. One DB per vault.

    Concurrency model: one SQLite connection **per thread** (uvicorn's request
    threadpool, APScheduler executors, the CLI). WAL mode + a 5-second
    `busy_timeout` lets concurrent readers proceed and serializes writers via
    SQLite's own file locking. We deliberately keep `check_same_thread=True`
    (the default) so that misuse — accidentally sharing one connection across
    threads — fails loudly instead of silently corrupting the DB.
    """

    def __init__(self, db_path: Path, embedding: EmbeddingBackend):
        self.db_path = db_path
        self.embedding = embedding
        self._tls = threading.local()
        # (owner thread ident, connection) — the ident is needed because
        # sqlite3 refuses to close a connection from a foreign thread.
        self._conns: list[tuple[int, sqlite3.Connection]] = []
        self._conns_lock = threading.Lock()
        # Bumped by close(). A thread whose cached connection belongs to
        # an older generation closes it and reopens on next connect().
        self._generation = 0
        self._migrated = False
        self._migration_lock = threading.Lock()
        self._tokenizer: str | None = None

    # ------------------------------------------------------------------ lifecycle

    def connect(self) -> sqlite3.Connection:
        conn: sqlite3.Connection | None = getattr(self._tls, "conn", None)
        if conn is not None:
            current_file = _db_file_identity(self.db_path)
            # A missing file may mean a rebuild is mid-flight elsewhere; keep
            # the handle rather than racing it to create an empty DB.
            file_replaced = current_file is not None and current_file != getattr(
                self._tls, "db_file", None
            )
            if getattr(self._tls, "generation", -1) == self._generation and not file_replaced:
                return conn
            # Either close() ran since this thread last connected, or the
            # DB file was deleted + recreated (e.g. `knowlet reindex
            # --rebuild` from another process). The old handle points at
            # an unlinked inode where writes vanish silently. Only the
            # owning thread may close a sqlite3 connection — we are it.
            with contextlib.suppress(sqlite3.Error):
                conn.close()
            with self._conns_lock:
                self._conns = [(t, c) for (t, c) in self._conns if c is not conn]
            self._tls.conn = None
            if file_replaced:
                with self._migration_lock:
                    self._migrated = False

        # Read before opening: a close() racing with this open must leave
        # the new handle stale rather than stamped with the newer generation.
        generation = self._generation
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            # If another thread holds the writer lock, wait up to 5s before
            # raising `database is locked`. Long enough to absorb routine
            # contention; short enough to surface a real deadlock.
            conn.execute("PRAGMA busy_timeout = 5000")

            # Migration runs once across all threads. The first thread to
            # connect detects the FTS5 tokenizer and creates / upgrades the
            # schema; later threads skip straight to their own connection.
            with self._migration_lock:
                if not self._migrated:
                    self._tokenizer = "trigram" if _check_trigram(conn) else "unicode61"
                    self._migrate(conn)
                    self._migrated = True
        except BaseException:
            with contextlib.suppress(sqlite3.Error):
                conn.close()
            raise

        self._tls.conn = conn
        self._tls.generation = generation
        self._tls.db_file = _db_file_identity(self.db_path)
        with self._conns_lock:
            self._conns.append((threading.get_ident(), conn))
        return conn

    def close(self) -> None:
        me = threading.get_ident()
        with self._conns_lock:
            self._generation += 1
            still_open: list[tuple[int, sqlite3.Connection]] = []
            for owner, c in self._conns:
                try:
                    c.close()
                except sqlite3.ProgrammingError:
                    # Foreign-thread connection: sqlite3 only lets the
                    # owner close it. The generation bump makes the owner
                    # close it on its next connect() instead of reusing it.
                    if owner != me:
                        still_open.append((owner, c))
                except sqlite3.Error:
                    pass
            self._conns = still_open
        self._tls.conn = None
        self._migrated = False

    # ------------------------------------------------------------------ schema

    def _migrate(self, conn: sqlite3.Connection) -> None:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        row = cur.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        version = int(row["value"]) if row else 0
        identity = configured_identity(self.embedding)

        if version == 0:
            self._create_v1(conn)
            cur.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            cur.execute(
                "INSERT INTO meta(key, value) VALUES('embedding_dim', ?)",
                (str(self.embedding.dim),),
            )
            cur.execute(
                "INSERT INTO meta(key, value) VALUES('embedding_identity', ?)",
                (identity,),
            )
            conn.commit()
            return

        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"index DB schema version {version} is newer than supported "
                f"({SCHEMA_VERSION}). Upgrade knowlet."
            )

        # Existing schema — verify embedding dim matches.
        dim_row = cur.execute("SELECT value FROM meta WHERE key = 'embedding_dim'").fetchone()
        if dim_row is not None:
            stored_dim = int(dim_row["value"])
            if stored_dim != self.embedding.dim:
                raise IndexDimensionMismatchError(
                    f"index was built with embedding dim={stored_dim}, but the "
                    f"configured backend reports dim={self.embedding.dim}. "
                    f"Run `knowlet reindex --rebuild` to rebuild the index for "
                    f"the new embedding model."
                )

        # Same dim does not mean same vector space: a model switch between
        # two 384-d models passes the dim check but makes cosines meaningless.
        id_row = cur.execute("SELECT value FROM meta WHERE key = 'embedding_identity'").fetchone()
        if id_row is None:
            # Pre-identity DB: the best available evidence is the backend
            # it is being opened with.
            cur.execute(
                "INSERT INTO meta(key, value) VALUES('embedding_identity', ?)",
                (identity,),
            )
            conn.commit()
        elif id_row["value"] != identity:
            raise IndexEmbeddingMismatchError(
                f"index was built with embedding backend {id_row['value']!r}, but "
                f"the configured backend is {identity!r}. Vectors from different "
                f"models are not comparable. Run `knowlet reindex --rebuild` to "
                f"rebuild the index for the new embedding model."
            )

    def _create_v1(self, conn: sqlite3.Connection) -> None:
        dim = self.embedding.dim
        tok = self._tokenizer or "unicode61"
        # `tok` and `dim` come from pinned constants/config, not user input.
        conn.executescript(
            f"""
            CREATE TABLE notes (
                id TEXT PRIMARY KEY,
                slug TEXT NOT NULL,
                title TEXT NOT NULL,
                path TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                content_hash TEXT NOT NULL
            );

            CREATE TABLE chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                note_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                text TEXT NOT NULL,
                FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE
            );

            CREATE INDEX idx_chunks_note ON chunks(note_id);

            CREATE VIRTUAL TABLE chunks_fts USING fts5(
                text,
                content='chunks',
                content_rowid='id',
                tokenize='{tok}'
            );

            CREATE TRIGGER chunks_ai AFTER INSERT ON chunks BEGIN
                INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
            END;
            CREATE TRIGGER chunks_ad AFTER DELETE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
            END;
            CREATE TRIGGER chunks_au AFTER UPDATE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
                INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
            END;

            CREATE VIRTUAL TABLE chunks_vec USING vec0(
                chunk_id INTEGER PRIMARY KEY,
                embedding FLOAT[{dim}]
            );
            """  # noqa: S608
        )

    # ------------------------------------------------------------------ upsert

    def upsert_note(
        self,
        note: Note,
        chunk_size: int,
        chunk_overlap: int,
    ) -> None:
        conn = self.connect()
        existing = conn.execute(
            "SELECT content_hash FROM notes WHERE id = ?", (note.id,)
        ).fetchone()

        rel_path = str(note.path) if note.path else note.filename

        if existing and existing["content_hash"] == note.content_hash:
            # Body + title unchanged → no need to re-chunk / re-embed.
            # But tags / updated_at can still differ (e.g. user added a
            # tag via the chip strip without touching the body). Refresh
            # the metadata row so tag-only edits land in the index.
            with conn:
                conn.execute(
                    """
                    UPDATE notes
                       SET tags = ?, updated_at = ?, path = ?
                     WHERE id = ?
                    """,
                    (
                        json.dumps(note.tags, ensure_ascii=False),
                        note.updated_at,
                        rel_path,
                        note.id,
                    ),
                )
            return

        body_for_chunking = f"# {note.title}\n\n{note.body}".strip()
        # Phase 3 Stage 1 Step 1.5: Markdown-aware chunking. Falls
        # back to the legacy sliding-window splitter if the langchain
        # dep isn't importable (e.g. partial install during tests).
        try:
            from knowlet.core.retrieval.chunking import smart_chunk_markdown

            chunks = smart_chunk_markdown(body_for_chunking, size=chunk_size, overlap=chunk_overlap)
        except ImportError:
            chunks = chunk_text(body_for_chunking, size=chunk_size, overlap=chunk_overlap)

        # Embed BEFORE the first write statement opens the transaction:
        # encoding is the slow, failure-prone step. Inside the txn it held
        # SQLite's writer lock for seconds, and a raise left half-written
        # rows pending on this connection for a later commit to persist.
        embeddings: np.ndarray | None = None
        if chunks and writes_vectors(self.embedding):
            embeddings = self.embedding.embed_documents([c.text for c in chunks])

        with conn:  # commit on success, roll back on any error
            cur = conn.cursor()
            self._delete_note_rows(cur, note.id)
            cur.execute(
                """
                INSERT INTO notes(id, slug, title, path, tags, created_at, updated_at, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    note.id,
                    note.slug,
                    note.title,
                    rel_path,
                    json.dumps(note.tags, ensure_ascii=False),
                    note.created_at,
                    note.updated_at,
                    note.content_hash,
                ),
            )
            chunk_ids: list[int] = []
            for c in chunks:
                cur.execute(
                    "INSERT INTO chunks(note_id, position, text) VALUES (?, ?, ?)",
                    (note.id, c.position, c.text),
                )
                assert cur.lastrowid is not None
                chunk_ids.append(int(cur.lastrowid))
            if embeddings is not None:
                for cid, vec in zip(chunk_ids, embeddings, strict=False):
                    cur.execute(
                        "INSERT INTO chunks_vec(chunk_id, embedding) VALUES (?, ?)",
                        (cid, _vec_to_blob(vec)),
                    )

    @staticmethod
    def _delete_note_rows(cur: sqlite3.Cursor, note_id: str) -> None:
        # chunks_vec is a vec0 virtual table: no FK, no trigger, so the
        # notes → chunks cascade never reaches it. Delete vectors first.
        chunk_rows = cur.execute("SELECT id FROM chunks WHERE note_id = ?", (note_id,)).fetchall()
        if chunk_rows:
            ids = [int(r["id"]) for r in chunk_rows]
            placeholders = ",".join("?" * len(ids))
            cur.execute(f"DELETE FROM chunks_vec WHERE chunk_id IN ({placeholders})", ids)  # noqa: S608 — placeholders are only `?` repeats, ids are bound parameters
        cur.execute("DELETE FROM notes WHERE id = ?", (note_id,))  # cascades to chunks

    def update_note_path(self, note_id: str, new_path: str) -> None:
        """Update only the `path` column for a note. Used by move_note /
        rename_folder where the on-disk location changes but the body and
        chunks don't, so we skip the (expensive) re-chunk + re-embed.
        """
        conn = self.connect()
        with conn:
            conn.execute("UPDATE notes SET path = ? WHERE id = ?", (new_path, note_id))

    def delete_note(self, note_id: str) -> None:
        conn = self.connect()
        with conn:
            self._delete_note_rows(conn.cursor(), note_id)

    def repair_vectors(self) -> tuple[int, int]:
        """Heal chunk ↔ vector drift left in existing index DBs.

        - Drops ``chunks_vec`` rows whose chunk no longer exists (older
          upserts leaked one vector generation per edit; chunk ids are
          AUTOINCREMENT so dead ids are never reused).
        - Clears ``content_hash`` of notes having a chunk without a vector
          (a failed embed got committed, or vectors were withheld while a
          stand-in backend was active) so the next upsert re-embeds them
          instead of taking the unchanged-content early exit.

        Skipped while a stand-in backend is active — it cannot re-embed.
        Returns ``(vectors_pruned, notes_invalidated)``. O(chunks).
        """
        conn = self.connect()
        vec_ids = {int(r["chunk_id"]) for r in conn.execute("SELECT chunk_id FROM chunks_vec")}
        chunk_rows = conn.execute("SELECT id, note_id FROM chunks").fetchall()
        orphan_vecs = sorted(vec_ids - {int(r["id"]) for r in chunk_rows})
        stale_notes: set[str] = set()
        if writes_vectors(self.embedding):
            stale_notes = {r["note_id"] for r in chunk_rows if int(r["id"]) not in vec_ids}
        if not orphan_vecs and not stale_notes:
            return 0, 0
        with conn:
            for start in range(0, len(orphan_vecs), 500):
                batch = orphan_vecs[start : start + 500]
                placeholders = ",".join("?" * len(batch))
                conn.execute(f"DELETE FROM chunks_vec WHERE chunk_id IN ({placeholders})", batch)  # noqa: S608 — placeholders are only `?` repeats, ids are bound parameters
            conn.executemany(
                "UPDATE notes SET content_hash = '' WHERE id = ?",
                [(nid,) for nid in sorted(stale_notes)],
            )
        return len(orphan_vecs), len(stale_notes)

    def known_note_ids(self) -> set[str]:
        conn = self.connect()
        rows = conn.execute("SELECT id FROM notes").fetchall()
        return {r["id"] for r in rows}

    def get_note_meta(self, note_id: str) -> dict[str, Any] | None:
        conn = self.connect()
        row = conn.execute(
            "SELECT id, title, path, tags, created_at, updated_at FROM notes WHERE id = ?",
            (note_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "title": row["title"],
            "path": row["path"],
            "tags": json.loads(row["tags"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_notes(
        self, limit: int | None = None, order: str = "updated_at"
    ) -> list[dict[str, Any]]:
        conn = self.connect()
        col = "updated_at" if order == "updated_at" else "created_at"
        # `col` is a closed set of ORDER BY columns; `limit` is coerced to int.
        sql = f"SELECT id, title, path, tags, created_at, updated_at FROM notes ORDER BY {col} DESC"  # noqa: S608
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        rows = conn.execute(sql).fetchall()
        return [
            {
                "id": r["id"],
                "title": r["title"],
                "path": r["path"],
                "tags": json.loads(r["tags"]),
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------ tags

    def aggregate_tags(self) -> list[tuple[str, int]]:
        """Return ``[(tag, count)]`` across the whole vault, sorted by
        count desc then by name asc. Empty / whitespace-only tags are
        dropped. Tags are stored as JSON arrays in a TEXT column, so we
        decode in Python rather than try a SQL JSON1 path (sqlite-vec
        compiled extension may not have JSON1; the loop is fast at any
        vault size we support per ADR-0021)."""
        from collections import Counter

        conn = self.connect()
        counter: Counter[str] = Counter()
        for row in conn.execute("SELECT tags FROM notes").fetchall():
            try:
                arr = json.loads(row["tags"])
            except (TypeError, ValueError):
                continue
            if not isinstance(arr, list):
                continue
            for t in arr:
                if isinstance(t, str) and t.strip():
                    counter[t.strip()] += 1
        # Counter.most_common() ties are insertion-ordered; we want
        # alpha-sorted tie-break for a stable UI.
        return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0].lower()))

    def list_notes_by_tag(self, tag: str) -> list[dict[str, Any]]:
        """Return note rows whose `tags` JSON array contains `tag`
        (case-sensitive — tags are user-typed labels, identity matters).
        Linear scan via `list_notes`; fine up to ~5k notes."""
        if not tag.strip():
            return []
        out: list[dict[str, Any]] = []
        for n in self.list_notes(limit=None):
            if tag in n["tags"]:
                out.append(n)
        return out

    # ------------------------------------------------------------------ search

    def search(self, query: str, top_k: int = 5, rrf_k: int = 60) -> list[SearchHit]:
        if not query.strip():
            return []
        conn = self.connect()

        # SQLite FTS5 with the trigram tokenizer indexes 3-char
        # substrings — queries with any token < 3 chars cannot produce
        # a trigram, so they always return 0 hits. That's wrong for
        # users searching short prefixes / numbers (e.g. "88" should
        # match "888999910"). Detect that case + fall back to a
        # direct LIKE scan over chunks.text.
        needs_substring_fallback = any(len(t) < 3 for t in query.split() if t)
        if needs_substring_fallback:
            fts_rows = self._search_substring(conn, query, limit=top_k * 4)
        else:
            fts_rows = self._search_fts(conn, query, limit=top_k * 4)
        # When the embedding backend is the deterministic-hash DummyBackend
        # (test harness + first-run vaults without an API key / model),
        # vector search returns near-uniform cosine across the entire vault
        # — every note "matches" every query. Pure noise. Skip it; FTS
        # alone gives precise keyword matches. Real backends (BGE / OpenAI /
        # Ollama) keep the hybrid RRF behavior.
        from knowlet.core.embedding import DummyBackend

        if isinstance(self.embedding, DummyBackend):
            vec_rows: list[tuple[int, float]] = []
        else:
            vec_rows = self._search_vec(conn, query, limit=top_k * 4)

        ranks: dict[int, float] = {}
        for rank, (chunk_id, _) in enumerate(fts_rows, start=1):
            ranks[chunk_id] = ranks.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)
        for rank, (chunk_id, _) in enumerate(vec_rows, start=1):
            ranks[chunk_id] = ranks.get(chunk_id, 0.0) + 1.0 / (rrf_k + rank)

        if not ranks:
            return []

        ordered = sorted(ranks.items(), key=lambda kv: kv[1], reverse=True)

        hits: list[SearchHit] = []
        seen_notes: set[str] = set()
        for chunk_id, score in ordered:
            row = conn.execute(
                """
                SELECT c.id AS chunk_id, c.note_id, c.position, c.text,
                       n.title, n.path
                FROM chunks c JOIN notes n ON n.id = c.note_id
                WHERE c.id = ?
                """,
                (chunk_id,),
            ).fetchone()
            if row is None:
                continue
            if row["note_id"] in seen_notes:
                continue  # one hit per note
            seen_notes.add(row["note_id"])
            hits.append(
                SearchHit(
                    note_id=row["note_id"],
                    title=row["title"],
                    path=row["path"],
                    snippet=_snippet(row["text"], query),
                    chunk_position=row["position"],
                    score=score,
                )
            )
            if len(hits) >= top_k:
                break
        return hits

    def _search_fts(
        self, conn: sqlite3.Connection, query: str, limit: int
    ) -> list[tuple[int, float]]:
        try:
            rows = conn.execute(
                """
                SELECT rowid AS chunk_id, bm25(chunks_fts) AS score
                FROM chunks_fts
                WHERE chunks_fts MATCH ?
                ORDER BY score
                LIMIT ?
                """,
                (_fts_escape(query), limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [(int(r["chunk_id"]), float(r["score"])) for r in rows]

    def _search_substring(
        self, conn: sqlite3.Connection, query: str, limit: int
    ) -> list[tuple[int, float]]:
        """Direct case-insensitive LIKE scan over chunk text. Used when
        FTS5 trigram can't handle the query (any token < 3 chars).
        Linear scan; fine at <5k notes per ADR-0021. Multiple tokens
        are OR-combined so `88 99` matches notes containing either."""
        tokens = [t for t in query.split() if t]
        if not tokens:
            return []
        where = " OR ".join(["text LIKE ? COLLATE NOCASE"] * len(tokens))
        # Constant uniform score (1.0) — RRF only cares about rank, and
        # we don't have a meaningful "relevance" measure for a LIKE
        # match. Substring match is binary: in / out.
        sql = f"SELECT id AS chunk_id FROM chunks WHERE {where} LIMIT ?"  # noqa: S608
        args: list[object] = [f"%{t}%" for t in tokens]
        args.append(int(limit))
        rows = conn.execute(sql, args).fetchall()
        return [(int(r["chunk_id"]), 1.0) for r in rows]

    def _search_vec(
        self, conn: sqlite3.Connection, query: str, limit: int
    ) -> list[tuple[int, float]]:
        try:
            qv = self.embedding.embed_query(query)
        except Exception:
            return []
        rows = conn.execute(
            """
            SELECT chunk_id, distance
            FROM chunks_vec
            WHERE embedding MATCH ?
            ORDER BY distance
            LIMIT ?
            """,
            (_vec_to_blob(qv), limit),
        ).fetchall()
        return [(int(r["chunk_id"]), float(r["distance"])) for r in rows]


def _fts_escape(query: str) -> str:
    """Wrap query for FTS5: quote and escape internal quotes; OR by whitespace."""
    parts = [p for p in query.split() if p]
    if not parts:
        return '""'
    quoted = [f'"{p.replace(chr(34), chr(34) * 2)}"' for p in parts]
    return " OR ".join(quoted)


def _snippet(text: str, query: str, width: int = 160) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) <= width:
        return text
    needle = next((p for p in query.split() if p), "")
    if needle:
        idx = text.lower().find(needle.lower())
        if idx >= 0:
            start = max(0, idx - width // 3)
            end = min(len(text), start + width)
            prefix = "…" if start > 0 else ""
            suffix = "…" if end < len(text) else ""
            return prefix + text[start:end] + suffix
    return text[:width] + "…"


def reindex_vault(
    vault_root: Path,
    state_db: Path,
    embedding: EmbeddingBackend,
    chunk_size: int,
    chunk_overlap: int,
    note_paths: Iterable[Path],
    *,
    vault: Vault | None = None,
) -> tuple[int, int, int]:
    """Bring the index in sync with the on-disk Notes.

    Notes are loaded through ``Vault.read_note`` so a file whose id had to
    be synthesized (no frontmatter, or frontmatter without ``id``) gets
    that id persisted once instead of a fresh random ULID per run — which
    used to delete + re-embed such notes on every startup. Pass ``vault``
    to reuse a configured Vault (backups / audit log) for that write.

    Returns (added_or_updated, deleted, unchanged).
    """
    from knowlet.core.vault import Vault

    reader = vault if vault is not None else Vault(vault_root)
    idx = Index(state_db, embedding)
    try:
        idx.connect()
        idx.repair_vectors()
        seen: set[str] = set()
        changed = 0
        unchanged = 0
        for path in note_paths:
            try:
                note = reader.read_note(path)
            except Exception:  # noqa: S112 — skip malformed notes; reindex is best-effort
                continue
            seen.add(note.id)
            before = idx.get_note_meta(note.id)
            idx.upsert_note(note, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            after = idx.get_note_meta(note.id)
            if before is None or (
                after is not None and after["updated_at"] != (before or {}).get("updated_at")
            ):
                changed += 1
            else:
                unchanged += 1

        deleted = 0
        for note_id in idx.known_note_ids() - seen:
            idx.delete_note(note_id)
            deleted += 1
    finally:
        idx.close()
    return changed, deleted, unchanged
