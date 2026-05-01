"""SQLite-backed index: FTS5 + sqlite-vec, hybrid search via RRF."""

from __future__ import annotations

import json
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import sqlite_vec

from knowlet.core.embedding import EmbeddingBackend
from knowlet.core.note import Note
from knowlet.core.splitter import chunk_text

SCHEMA_VERSION = 1


class IndexDimensionMismatchError(RuntimeError):
    """Raised when the configured embedding dim differs from the indexed dim."""


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


def _check_trigram(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE _trigram_probe USING fts5(x, tokenize='trigram')")
        conn.execute("DROP TABLE _trigram_probe")
        return True
    except sqlite3.OperationalError:
        return False


class Index:
    """Persistent index over Notes. One DB per vault."""

    def __init__(self, db_path: Path, embedding: EmbeddingBackend):
        self.db_path = db_path
        self.embedding = embedding
        self._conn: sqlite3.Connection | None = None
        self._tokenizer: str | None = None

    # ------------------------------------------------------------------ lifecycle

    def connect(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False is intentional: knowlet's web UI runs sync
        # endpoints across uvicorn's threadpool, so the same Index connection
        # is reused from multiple worker threads. SQLite WAL mode + the GIL
        # serialize writes safely for our single-user, single-writer pattern.
        # If we ever go multi-user / multi-writer, switch to a per-request
        # connection or aiosqlite.
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        self._conn = conn
        self._tokenizer = "trigram" if _check_trigram(conn) else "unicode61"
        self._migrate()
        return conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------ schema

    def _migrate(self) -> None:
        conn = self._conn
        assert conn is not None
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        row = cur.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        version = int(row["value"]) if row else 0

        if version == 0:
            self._create_v1()
            cur.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            cur.execute(
                "INSERT INTO meta(key, value) VALUES('embedding_dim', ?)",
                (str(self.embedding.dim),),
            )
            conn.commit()
            return

        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"index DB schema version {version} is newer than supported "
                f"({SCHEMA_VERSION}). Upgrade knowlet."
            )

        # Existing schema — verify embedding dim matches.
        dim_row = cur.execute(
            "SELECT value FROM meta WHERE key = 'embedding_dim'"
        ).fetchone()
        if dim_row is not None:
            stored_dim = int(dim_row["value"])
            if stored_dim != self.embedding.dim:
                raise IndexDimensionMismatchError(
                    f"index was built with embedding dim={stored_dim}, but the "
                    f"configured backend reports dim={self.embedding.dim}. "
                    f"Run `knowlet reindex --rebuild` to rebuild the index for "
                    f"the new embedding model."
                )

    def _create_v1(self) -> None:
        conn = self._conn
        assert conn is not None
        dim = self.embedding.dim
        tok = self._tokenizer or "unicode61"
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
            """
        )

    # ------------------------------------------------------------------ upsert

    def upsert_note(
        self,
        note: Note,
        chunk_size: int,
        chunk_overlap: int,
    ) -> None:
        conn = self.connect()
        cur = conn.cursor()
        existing = cur.execute(
            "SELECT content_hash FROM notes WHERE id = ?", (note.id,)
        ).fetchone()
        if existing and existing["content_hash"] == note.content_hash:
            return  # unchanged, skip reindex

        rel_path = str(note.path) if note.path else note.filename

        cur.execute("DELETE FROM notes WHERE id = ?", (note.id,))
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

        body_for_chunking = f"# {note.title}\n\n{note.body}".strip()
        chunks = chunk_text(body_for_chunking, size=chunk_size, overlap=chunk_overlap)
        if not chunks:
            conn.commit()
            return

        chunk_ids: list[int] = []
        for c in chunks:
            cur.execute(
                "INSERT INTO chunks(note_id, position, text) VALUES (?, ?, ?)",
                (note.id, c.position, c.text),
            )
            chunk_ids.append(int(cur.lastrowid))

        embeddings = self.embedding.embed_documents([c.text for c in chunks])
        for cid, vec in zip(chunk_ids, embeddings):
            cur.execute(
                "INSERT INTO chunks_vec(chunk_id, embedding) VALUES (?, ?)",
                (cid, _vec_to_blob(vec)),
            )
        conn.commit()

    def delete_note(self, note_id: str) -> None:
        conn = self.connect()
        cur = conn.cursor()
        # Collect chunk ids first because vec table is independent (no FK).
        chunk_rows = cur.execute(
            "SELECT id FROM chunks WHERE note_id = ?", (note_id,)
        ).fetchall()
        if chunk_rows:
            ids = [int(r["id"]) for r in chunk_rows]
            placeholders = ",".join("?" * len(ids))
            cur.execute(f"DELETE FROM chunks_vec WHERE chunk_id IN ({placeholders})", ids)
        cur.execute("DELETE FROM notes WHERE id = ?", (note_id,))  # cascades to chunks
        conn.commit()

    def known_note_ids(self) -> set[str]:
        conn = self.connect()
        rows = conn.execute("SELECT id FROM notes").fetchall()
        return {r["id"] for r in rows}

    def get_note_meta(self, note_id: str) -> dict | None:
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

    def list_notes(self, limit: int | None = None, order: str = "updated_at") -> list[dict]:
        conn = self.connect()
        col = "updated_at" if order == "updated_at" else "created_at"
        sql = f"SELECT id, title, path, tags, created_at, updated_at FROM notes ORDER BY {col} DESC"
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

    # ------------------------------------------------------------------ search

    def search(self, query: str, top_k: int = 5, rrf_k: int = 60) -> list[SearchHit]:
        if not query.strip():
            return []
        conn = self.connect()

        fts_rows = self._search_fts(conn, query, limit=top_k * 4)
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
) -> tuple[int, int, int]:
    """Bring the index in sync with the on-disk Notes.

    Returns (added_or_updated, deleted, unchanged).
    """
    from knowlet.core.note import Note

    idx = Index(state_db, embedding)
    idx.connect()
    seen: set[str] = set()
    changed = 0
    unchanged = 0
    for path in note_paths:
        try:
            note = Note.from_file(path)
        except Exception:
            continue
        seen.add(note.id)
        before = idx.get_note_meta(note.id)
        idx.upsert_note(note, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        after = idx.get_note_meta(note.id)
        if before is None or (after is not None and after["updated_at"] != (before or {}).get("updated_at")):
            changed += 1
        else:
            unchanged += 1

    deleted = 0
    for note_id in idx.known_note_ids() - seen:
        idx.delete_note(note_id)
        deleted += 1
    idx.close()
    return changed, deleted, unchanged
