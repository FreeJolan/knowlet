"""Structure signals over the vault (M8.1, ADR-0013 Layer B).

Pure compute — never mutates the vault, never enqueues actions, never
runs in a loop. Just answers four questions on demand:

  near_duplicates   — pairs of notes whose mean embedding has cosine
                      ≥ threshold (default 0.92). Tells the user "these
                      two might be saying the same thing."
  clusters          — single-link components on the near-dup graph.
                      Sets of 2+ notes that all collapse together at the
                      threshold. Stable + deterministic, no heavy deps.
  orphan_notes      — notes with no inbound `[[…]]` links AND last
                      edited > N days ago (default 90). Tells the user
                      "this note isn't connecting to anything."
  aging_candidates  — notes whose updated_at is > M days old (default
                      180). Tells the user "you haven't touched this
                      since spring."

ADR-0013 §1 contract: this module **only computes**; it never decides.
The web layer surfaces the result as a read-only payload (M8.2 sidebar);
no auto-merge, no auto-archive, no scores rendered as judgement.

Tradeoffs vs full HDBSCAN: single-link components are cheaper (O(n²) but
the constant is small) and produce stable, explainable groups
("everything reachable via cosine ≥ 0.92 chains"). For vault sizes
≤ 5k notes this fits in well under a second. If/when we need
density-aware clustering we swap the implementation here without
changing the wire payload.
"""

from __future__ import annotations

import sqlite3
import struct
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable

import numpy as np

from knowlet.core.backlinks import find_backlinks
from knowlet.core.index import Index

# Defaults pinned here so callers / tests have a single source.
DEFAULT_NEAR_DUP_COSINE = 0.92
DEFAULT_ORPHAN_UNTOUCHED_DAYS = 90
DEFAULT_AGING_UNTOUCHED_DAYS = 180


@dataclass(frozen=True)
class NearDuplicatePair:
    a_id: str
    a_title: str
    b_id: str
    b_title: str
    cosine: float


@dataclass(frozen=True)
class NoteCluster:
    note_ids: list[str]
    note_titles: list[str]


@dataclass(frozen=True)
class OrphanNote:
    id: str
    title: str
    days_untouched: int


@dataclass(frozen=True)
class AgingCandidate:
    id: str
    title: str
    days_untouched: int


@dataclass(frozen=True)
class StructureSignals:
    near_duplicates: list[NearDuplicatePair]
    clusters: list[NoteCluster]
    orphan_notes: list[OrphanNote]
    aging_candidates: list[AgingCandidate]


# ------------------------------------------------------- helpers


def _blob_to_vec(blob: bytes, dim: int) -> np.ndarray:
    """Inverse of `index._vec_to_blob` — unpacks float32 LE blob."""
    return np.array(struct.unpack(f"{dim}f", blob), dtype=np.float32)


def _l2_normalize(v: np.ndarray) -> np.ndarray:
    """L2-normalize so dot product == cosine similarity."""
    n = float(np.linalg.norm(v))
    if n == 0.0:
        return v
    return v / n


def _load_note_embeddings(idx: Index) -> tuple[list[str], dict[str, str], np.ndarray]:
    """Average each note's chunk embeddings into a single vector. Returns
    (note_ids in order, {id: title}, matrix [N, D]).

    Notes with zero indexed chunks (e.g., trash that escaped) are
    skipped — they can't contribute a similarity score."""
    conn = idx.connect()
    rows = conn.execute(
        """
        SELECT n.id AS id, n.title AS title, c.id AS chunk_id, cv.embedding AS emb
        FROM notes n
        JOIN chunks c ON c.note_id = n.id
        JOIN chunks_vec cv ON cv.chunk_id = c.id
        ORDER BY n.id, c.position
        """
    ).fetchall()
    if not rows:
        return [], {}, np.zeros((0, idx.embedding.dim), dtype=np.float32)

    dim = idx.embedding.dim
    by_note: dict[str, list[np.ndarray]] = {}
    titles: dict[str, str] = {}
    for r in rows:
        nid = r["id"]
        titles[nid] = r["title"]
        by_note.setdefault(nid, []).append(_blob_to_vec(r["emb"], dim))

    note_ids = sorted(by_note.keys())
    matrix = np.zeros((len(note_ids), dim), dtype=np.float32)
    for i, nid in enumerate(note_ids):
        avg = np.mean(np.stack(by_note[nid]), axis=0)
        matrix[i] = _l2_normalize(avg)
    return note_ids, titles, matrix


def _parse_iso_z(ts: str) -> datetime | None:
    """Parse the `YYYY-MM-DDTHH:MM:SSZ` timestamps the vault writes.
    Returns None on malformed input — caller treats as "unknown age"."""
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        return None


# ------------------------------------------------------- near duplicates


def near_duplicates(
    idx: Index,
    *,
    cosine_threshold: float = DEFAULT_NEAR_DUP_COSINE,
    max_pairs: int = 500,
) -> list[NearDuplicatePair]:
    """All (a, b) pairs with cosine(mean_emb_a, mean_emb_b) ≥ threshold.

    O(n²) — fine for vault sizes ≤ 5k. Sorted by cosine desc; capped at
    `max_pairs` so a high-similarity vault (translated copies / heavy
    revision history) doesn't blow up the response."""
    note_ids, titles, M = _load_note_embeddings(idx)
    n = len(note_ids)
    if n < 2:
        return []
    sim = M @ M.T  # since rows are L2-normalized
    pairs: list[NearDuplicatePair] = []
    for i in range(n):
        for j in range(i + 1, n):
            c = float(sim[i, j])
            if c >= cosine_threshold:
                pairs.append(
                    NearDuplicatePair(
                        a_id=note_ids[i],
                        a_title=titles[note_ids[i]],
                        b_id=note_ids[j],
                        b_title=titles[note_ids[j]],
                        cosine=c,
                    )
                )
    pairs.sort(key=lambda p: p.cosine, reverse=True)
    return pairs[:max_pairs]


# ------------------------------------------------------- clusters


def cluster_notes(
    idx: Index,
    *,
    cosine_threshold: float = DEFAULT_NEAR_DUP_COSINE,
    min_size: int = 2,
) -> list[NoteCluster]:
    """Single-link clustering on the near-dup graph: notes are in the
    same cluster iff there's a chain of ≥ threshold cosine pairs
    connecting them.

    Stable + deterministic + no heavy deps. Density-aware clustering
    (HDBSCAN) is a future swap that would change neither the signature
    nor the wire shape."""
    pairs = near_duplicates(idx, cosine_threshold=cosine_threshold, max_pairs=10_000)
    if not pairs:
        return []
    # Union-find over note ids in any pair.
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    titles: dict[str, str] = {}
    for p in pairs:
        parent.setdefault(p.a_id, p.a_id)
        parent.setdefault(p.b_id, p.b_id)
        titles[p.a_id] = p.a_title
        titles[p.b_id] = p.b_title
        union(p.a_id, p.b_id)

    groups: dict[str, list[str]] = {}
    for nid in parent:
        groups.setdefault(find(nid), []).append(nid)

    clusters: list[NoteCluster] = []
    for ids in groups.values():
        if len(ids) < min_size:
            continue
        ids_sorted = sorted(ids)
        clusters.append(
            NoteCluster(
                note_ids=ids_sorted,
                note_titles=[titles.get(nid, "") for nid in ids_sorted],
            )
        )
    # Largest clusters first — most actionable surface.
    clusters.sort(key=lambda c: len(c.note_ids), reverse=True)
    return clusters


# ------------------------------------------------------- orphans


def orphan_notes(
    vault_iter_paths: Iterable[Path],
    idx: Index,
    *,
    untouched_days: int = DEFAULT_ORPHAN_UNTOUCHED_DAYS,
) -> list[OrphanNote]:
    """Notes with **zero inbound `[[…]]` references** AND last touched
    longer than `untouched_days` ago.

    Inbound counted via `core/backlinks.find_backlinks` (M7.0.4) so
    "orphan" matches the user's own [[Title]] writing convention. Notes
    edited recently are spared regardless of incoming links — fresh work
    isn't orphaned."""
    cutoff = datetime.now(UTC) - timedelta(days=untouched_days)
    paths = list(vault_iter_paths)
    out: list[OrphanNote] = []
    # Build a quick title → meta map for the iteration. list_notes()
    # walks the index DB once; cheap.
    metas_by_id = {row["id"]: row for row in idx.list_notes(limit=None)}
    for note_id, meta in metas_by_id.items():
        ts = _parse_iso_z(meta.get("updated_at") or "")
        if ts is None or ts > cutoff:
            continue
        title = meta.get("title") or ""
        if not title:
            continue
        backs = find_backlinks(title, paths, exclude_id=note_id)
        if backs:
            continue
        days = (datetime.now(UTC) - ts).days
        out.append(OrphanNote(id=note_id, title=title, days_untouched=days))
    out.sort(key=lambda o: o.days_untouched, reverse=True)
    return out


# ------------------------------------------------------- aging


def aging_candidates(
    idx: Index,
    *,
    untouched_days: int = DEFAULT_AGING_UNTOUCHED_DAYS,
) -> list[AgingCandidate]:
    """Notes whose updated_at is older than `untouched_days`. Pure
    time-based; doesn't care about backlinks. Distinct from `orphan_notes`
    because aging is the broader category — every orphan is aging-eligible
    if untouched_days is shorter, but not every aging note is orphaned."""
    cutoff = datetime.now(UTC) - timedelta(days=untouched_days)
    out: list[AgingCandidate] = []
    for row in idx.list_notes(limit=None):
        ts = _parse_iso_z(row.get("updated_at") or "")
        if ts is None or ts > cutoff:
            continue
        title = row.get("title") or ""
        if not title:
            continue
        days = (datetime.now(UTC) - ts).days
        out.append(AgingCandidate(id=row["id"], title=title, days_untouched=days))
    out.sort(key=lambda a: a.days_untouched, reverse=True)
    return out


# ------------------------------------------------------- top-level


def compute_signals(
    idx: Index,
    vault_iter_paths: Iterable[Path],
    *,
    near_dup_cosine: float = DEFAULT_NEAR_DUP_COSINE,
    orphan_days: int = DEFAULT_ORPHAN_UNTOUCHED_DAYS,
    aging_days: int = DEFAULT_AGING_UNTOUCHED_DAYS,
) -> StructureSignals:
    """One-shot: compute all four signal types. The web endpoint
    `GET /api/structure/signals` hits this; the M8.2 knowledge map
    sidebar consumes the read-only payload."""
    pairs = near_duplicates(idx, cosine_threshold=near_dup_cosine)
    clusters = cluster_notes(idx, cosine_threshold=near_dup_cosine)
    orphans = orphan_notes(vault_iter_paths, idx, untouched_days=orphan_days)
    aging = aging_candidates(idx, untouched_days=aging_days)
    return StructureSignals(
        near_duplicates=pairs,
        clusters=clusters,
        orphan_notes=orphans,
        aging_candidates=aging,
    )
