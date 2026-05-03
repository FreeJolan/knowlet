"""Unit tests for `knowlet/core/structure_signals.py` (M8.1)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import numpy as np

from knowlet.config import KnowletConfig
from knowlet.core.index import Index
from knowlet.core.note import Note, new_id
from knowlet.core.structure_signals import (
    DEFAULT_AGING_UNTOUCHED_DAYS,
    DEFAULT_NEAR_DUP_COSINE,
    DEFAULT_ORPHAN_UNTOUCHED_DAYS,
    aging_candidates,
    cluster_notes,
    compute_signals,
    near_duplicates,
    orphan_notes,
)
from knowlet.core.vault import Vault


class _GroupedBackend:
    """Test embedding that *encodes group membership* deterministically.

    Real semantic embeddings are heavy (sentence-transformers, ~300 MB
    download); the in-tree DummyBackend hashes each chunk to a random
    vector with no notion of similarity. For structure-signals tests we
    need to assert "these N notes should cluster together," which
    requires controllable similarity. This fake encodes a group label
    (the first GROUP_TAG in the text) into a one-hot dimension so two
    notes sharing a tag produce cosine-1 vectors and notes without a
    shared tag stay orthogonal.
    """

    def __init__(self, dim: int = 16):
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self._dim, dtype=np.float32)
        # Find a "GROUP_X" tag in the text — X is a single ASCII letter
        # mapped to dimension index by ord(letter) % dim.
        for ch in text:
            pass
        for tag in ("GROUP_A", "GROUP_B", "GROUP_C", "GROUP_D", "GROUP_E"):
            if tag in text:
                idx = ord(tag[-1]) % self._dim
                v[idx] = 1.0
                return v
        # No tag → orthogonal dim (last index reserved for "other").
        v[self._dim - 1] = 1.0
        return v

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._dim), dtype=np.float32)
        return np.stack([self._vec(t) for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._vec(text)


def _ready_vault(tmp_path: Path) -> tuple[Vault, KnowletConfig, Index]:
    """Build a Vault + Index with a group-aware fake embedding so
    similarity tests can drive grouping deterministically."""
    v = Vault(tmp_path)
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"  # config name; actual backend injected below
    backend = _GroupedBackend(dim=16)
    cfg.embedding.dim = backend.dim
    idx = Index(v.db_path, backend)
    idx.connect()
    return v, cfg, idx


def _add(v: Vault, idx: Index, *, title: str, body: str, updated_days_ago: int = 0) -> Note:
    """Create + index a note. `updated_days_ago` lets tests backdate
    updated_at to exercise the orphan / aging time filters.

    Vault.write_note unconditionally sets updated_at = now(), so the
    backdate has to happen *after* both write_note and upsert_note;
    we patch the index row + rewrite the markdown so Note.from_file
    sees the same timestamp the SQL filter sees."""
    n = Note(id=new_id(), title=title, body=body)
    v.write_note(n)
    idx.upsert_note(n, chunk_size=64, chunk_overlap=16)
    if updated_days_ago > 0:
        old_ts = (datetime.now(UTC) - timedelta(days=updated_days_ago)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        conn = idx.connect()
        conn.execute("UPDATE notes SET updated_at = ? WHERE id = ?", (old_ts, n.id))
        conn.commit()
        n.updated_at = old_ts
        (v.notes_dir / n.filename).write_text(n.to_markdown(), encoding="utf-8")
    return n


# ----------------------------------------- near_duplicates


def test_near_duplicates_empty_vault(tmp_path: Path):
    v, _, idx = _ready_vault(tmp_path)
    assert near_duplicates(idx) == []


def test_near_duplicates_skips_orthogonal_pairs(tmp_path: Path):
    """Notes in different GROUP tags → orthogonal one-hot vectors →
    cosine 0 → never appear as near duplicates."""
    v, _, idx = _ready_vault(tmp_path)
    _add(v, idx, title="A", body="GROUP_A topic alpha")
    _add(v, idx, title="B", body="GROUP_B topic beta")
    pairs = near_duplicates(idx)
    assert pairs == []


def test_near_duplicates_finds_same_group(tmp_path: Path):
    """Two notes with the same GROUP tag → cosine 1.0 → guaranteed pair."""
    v, _, idx = _ready_vault(tmp_path)
    a = _add(v, idx, title="A", body="GROUP_A discussion of attention")
    b = _add(v, idx, title="A copy", body="GROUP_A another take on attention")
    pairs = near_duplicates(idx, cosine_threshold=0.95)
    assert any(
        {p.a_id, p.b_id} == {a.id, b.id} for p in pairs
    )


def test_near_duplicates_caps_at_max_pairs(tmp_path: Path):
    """A high-similarity vault (all in one group) stays response-bounded."""
    v, _, idx = _ready_vault(tmp_path)
    for i in range(6):
        _add(v, idx, title=f"copy-{i}", body=f"GROUP_A note number {i}")
    # 6 notes, 6*5/2 = 15 possible pairs.
    pairs = near_duplicates(idx, cosine_threshold=0.95, max_pairs=5)
    assert len(pairs) == 5


def test_near_duplicates_sorted_by_cosine_desc(tmp_path: Path):
    v, _, idx = _ready_vault(tmp_path)
    _add(v, idx, title="A", body="GROUP_A and GROUP_B")  # tag found = A
    _add(v, idx, title="B", body="GROUP_A only")  # tag = A
    _add(v, idx, title="C", body="GROUP_C something")  # tag = C
    pairs = near_duplicates(idx, cosine_threshold=0.0)
    cosines = [p.cosine for p in pairs]
    assert cosines == sorted(cosines, reverse=True)


# ----------------------------------------- cluster_notes


def test_cluster_notes_groups_transitively(tmp_path: Path):
    """All three GROUP_A notes pull together via the near-dup graph."""
    v, _, idx = _ready_vault(tmp_path)
    a = _add(v, idx, title="A", body="GROUP_A first")
    b = _add(v, idx, title="B", body="GROUP_A second")
    c = _add(v, idx, title="C", body="GROUP_A third")
    clusters = cluster_notes(idx, cosine_threshold=0.95)
    assert len(clusters) == 1
    assert set(clusters[0].note_ids) == {a.id, b.id, c.id}


def test_cluster_notes_respects_min_size(tmp_path: Path):
    v, _, idx = _ready_vault(tmp_path)
    _add(v, idx, title="A", body="GROUP_A x")
    _add(v, idx, title="B", body="GROUP_A y")
    # min_size=3 ignores the pair; min_size=2 keeps it.
    assert cluster_notes(idx, cosine_threshold=0.95, min_size=3) == []
    assert len(cluster_notes(idx, cosine_threshold=0.95, min_size=2)) == 1


def test_cluster_notes_largest_first(tmp_path: Path):
    v, _, idx = _ready_vault(tmp_path)
    # Cluster X: 3 GROUP_A notes
    for i in range(3):
        _add(v, idx, title=f"X-{i}", body=f"GROUP_A iter {i}")
    # Cluster Y: 2 GROUP_B notes
    for i in range(2):
        _add(v, idx, title=f"Y-{i}", body=f"GROUP_B iter {i}")
    clusters = cluster_notes(idx, cosine_threshold=0.95)
    assert len(clusters) == 2
    assert len(clusters[0].note_ids) == 3
    assert len(clusters[1].note_ids) == 2


# ----------------------------------------- orphan_notes


def test_orphan_notes_filters_recent(tmp_path: Path):
    v, _, idx = _ready_vault(tmp_path)
    # Recent note (0 days) should NOT be orphaned even with no inbound links.
    fresh = _add(v, idx, title="fresh", body="recent thinking", updated_days_ago=0)
    # Old note with no inbound links → orphan.
    old = _add(v, idx, title="old", body="ancient note", updated_days_ago=120)
    orphans = orphan_notes(v.iter_note_paths(), idx, untouched_days=90)
    ids = [o.id for o in orphans]
    assert old.id in ids
    assert fresh.id not in ids


def test_orphan_notes_excluded_when_inbound_link_exists(tmp_path: Path):
    """A note that's referenced via [[Title]] from another note is NOT an
    orphan, even if it's old."""
    v, _, idx = _ready_vault(tmp_path)
    target = _add(v, idx, title="target", body="ancient", updated_days_ago=120)
    # Source note is recent but it references target.
    _add(v, idx, title="source", body="see [[target]] for context")
    orphans = orphan_notes(v.iter_note_paths(), idx, untouched_days=90)
    assert all(o.id != target.id for o in orphans)


def test_orphan_notes_sorted_by_days_untouched_desc(tmp_path: Path):
    v, _, idx = _ready_vault(tmp_path)
    _add(v, idx, title="O90", body="x", updated_days_ago=100)
    _add(v, idx, title="O200", body="y", updated_days_ago=200)
    _add(v, idx, title="O150", body="z", updated_days_ago=150)
    orphans = orphan_notes(v.iter_note_paths(), idx, untouched_days=90)
    days = [o.days_untouched for o in orphans]
    assert days == sorted(days, reverse=True)


# ----------------------------------------- aging_candidates


def test_aging_candidates_pure_time_based(tmp_path: Path):
    """aging_candidates doesn't care about backlinks — only updated_at."""
    v, _, idx = _ready_vault(tmp_path)
    target = _add(v, idx, title="old", body="content", updated_days_ago=200)
    # Add an inbound link — this doesn't save the note from "aging."
    _add(v, idx, title="recent", body="see [[old]]", updated_days_ago=10)

    aging = aging_candidates(idx, untouched_days=180)
    assert any(a.id == target.id for a in aging)


def test_aging_candidates_threshold_strict(tmp_path: Path):
    v, _, idx = _ready_vault(tmp_path)
    _add(v, idx, title="month-old", body="x", updated_days_ago=30)
    aging = aging_candidates(idx, untouched_days=180)
    assert aging == []


def test_constants_have_reasonable_defaults():
    assert DEFAULT_NEAR_DUP_COSINE == 0.92
    assert DEFAULT_ORPHAN_UNTOUCHED_DAYS == 90
    assert DEFAULT_AGING_UNTOUCHED_DAYS == 180


# ----------------------------------------- compute_signals


def test_compute_signals_returns_all_four(tmp_path: Path):
    v, _, idx = _ready_vault(tmp_path)
    # Two near-duplicates via shared group tag
    a = _add(v, idx, title="A", body="GROUP_D first")
    b = _add(v, idx, title="A copy", body="GROUP_D second")
    # An orphan + aging note
    _add(v, idx, title="lonely", body="GROUP_E alone", updated_days_ago=300)
    out = compute_signals(idx, v.iter_note_paths())
    assert len(out.near_duplicates) >= 1
    assert any({a.id, b.id}.issubset(set(c.note_ids)) for c in out.clusters)
    assert any(o.title == "lonely" for o in out.orphan_notes)
    assert any(item.title == "lonely" for item in out.aging_candidates)
