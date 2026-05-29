"""Phase 1 C slice 3 — Graph view backend.

Builds a snapshot of the user-authored `[[Title]]` wikilink graph:
nodes are notes, edges are direct references that resolve to an
existing note in the vault. Dangling (`[[Foo]]` with no target Note)
links are surfaced separately by the Linter (per ADR-0023 §5) — this
view shows only validated connections, the user-authored ground truth
that ADR-0023 §1 marks as core IA.

Cheap at ADR-0021 vault sizes (<5k notes): one pass of
`list_notes` + per-note read for wikilink extraction. No precomputed
edge index for v1 — keeps "no stale-index bug" tradeoff (same call as
backlinks.py made for the same reason).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from knowlet.core.backlinks import extract_wikilinks
from knowlet.core.note import Note

log = logging.getLogger(__name__)


def _normalize(title: str) -> str:
    return " ".join(title.split()).lower()


@dataclass(frozen=True)
class GraphNode:
    """One vault note in the graph payload."""

    id: str
    title: str
    folder: str  # forward-slash relative to notes_dir; "" = root
    in_degree: int
    out_degree: int


@dataclass(frozen=True)
class GraphEdge:
    """One resolved `[[Title]]` reference. `source` references `target`."""

    source: str
    target: str


@dataclass(frozen=True)
class Graph:
    nodes: list[GraphNode]
    edges: list[GraphEdge]


def build_graph(
    note_metas: list[dict],
    *,
    folder_for: callable,
    read_body: callable,
) -> Graph:
    """Build the graph snapshot.

    Args:
      note_metas: rows from `KnowletIndex.list_notes(limit=None)`. Each
        row must have ``id``, ``title``, ``path``.
      folder_for: callable returning the folder string ("" for root) for
        a given vault-relative path string. Caller passes the existing
        `Vault.folder_of` shim or equivalent.
      read_body: callable returning the markdown body for a given
        absolute or vault-relative path. Caller wraps `Note.from_file`
        or `Vault.read_note`.

    Edges are deduplicated per ``(source, target)`` pair — multiple
    `[[Title]]` mentions in the same source note count as **one** edge.
    Self-edges (note linking to itself) are dropped.
    """
    # Title → id resolution table (case + whitespace insensitive, same
    # rule as `find_backlinks`).
    title_to_id: dict[str, str] = {}
    for meta in note_metas:
        title = (meta.get("title") or "").strip()
        if not title:
            continue
        title_to_id.setdefault(_normalize(title), meta["id"])

    in_degree: dict[str, int] = defaultdict(int)
    out_degree: dict[str, int] = defaultdict(int)
    edges: list[GraphEdge] = []

    for meta in note_metas:
        note_id = meta["id"]
        path = meta.get("path")
        if not path:
            continue
        try:
            body = read_body(path)
        except Exception:
            log.debug("skip unreadable note while building graph: %s", path, exc_info=True)
            continue
        seen_targets: set[str] = set()
        for w in extract_wikilinks(body):
            # Strip heading anchor before resolution: `[[Foo#Heading]]`
            # still points at note `Foo`.
            target_title = w.target.split("#", 1)[0].split("^", 1)[0].strip()
            target_id = title_to_id.get(_normalize(target_title))
            if not target_id or target_id == note_id:
                continue
            if target_id in seen_targets:
                continue
            seen_targets.add(target_id)
            edges.append(GraphEdge(source=note_id, target=target_id))
            in_degree[target_id] += 1
            out_degree[note_id] += 1

    nodes: list[GraphNode] = []
    for meta in note_metas:
        path = meta.get("path") or ""
        folder = ""
        if path:
            try:
                folder = folder_for(Path(path))
            except (TypeError, ValueError):
                folder = ""
        nodes.append(
            GraphNode(
                id=meta["id"],
                title=(meta.get("title") or "").strip() or "(untitled)",
                folder=folder,
                in_degree=in_degree.get(meta["id"], 0),
                out_degree=out_degree.get(meta["id"], 0),
            )
        )

    return Graph(nodes=nodes, edges=edges)


def read_body_via_note(path: Path) -> str:
    """Default `read_body` impl using `Note.from_file`. Caller can pass
    a custom reader if it has a faster path (e.g., already-cached
    bodies)."""
    note = Note.from_file(path)
    return note.body
