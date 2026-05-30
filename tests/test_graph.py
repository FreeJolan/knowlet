"""Tests for Phase 1 C slice 3 — user-authored bilink graph."""

from pathlib import Path

from knowlet.core.graph import build_graph, read_body_via_note
from knowlet.core.note import Note, new_id
from knowlet.core.vault import Vault


def _seed(tmp_path: Path) -> tuple[Vault, list[Note]]:
    """Helper: init a vault + write a fixed cohort of notes for graph tests."""
    v = Vault(tmp_path)
    v.init_layout()
    notes = [
        Note(id=new_id(), title="Alpha", body="See [[Beta]] for details."),
        Note(id=new_id(), title="Beta", body="Refers back to [[Alpha]] and [[Gamma#section]]."),
        Note(id=new_id(), title="Gamma", body="standalone — no outbound links"),
        Note(id=new_id(), title="Orphan", body="Nothing here."),
        Note(
            id=new_id(),
            title="Hub",
            body="Links to [[Alpha]] and [[Beta]] and [[NonExistent]].",
        ),
    ]
    for n in notes:
        v.write_note(n)
    return v, notes


def _list_metas(notes: list[Note]) -> list[dict]:
    """Mimic what `KnowletIndex.list_notes(limit=None)` returns for the
    seeded notes — graph builder only uses id/title/path."""
    return [
        {
            "id": n.id,
            "title": n.title,
            "path": n.filename,
            "tags": [],
            "created_at": "",
            "updated_at": "",
        }
        for n in notes
    ]


def test_build_graph_basic_nodes_and_edges(tmp_path: Path):
    v, notes = _seed(tmp_path)
    metas = _list_metas(notes)
    g = build_graph(
        metas,
        folder_for=v.folder_of,
        read_body=lambda p: read_body_via_note(v.notes_dir / Path(p).name),
    )
    # 5 nodes, 4 resolved edges:
    #   Alpha → Beta
    #   Beta → Alpha
    #   Beta → Gamma  (heading anchor stripped before resolution)
    #   Hub → Alpha
    #   Hub → Beta
    # NonExistent is dangling → excluded.
    assert len(g.nodes) == 5
    edge_pairs = {(e.source, e.target) for e in g.edges}
    by_title = {n.title: n.id for n in g.nodes}
    assert (by_title["Alpha"], by_title["Beta"]) in edge_pairs
    assert (by_title["Beta"], by_title["Alpha"]) in edge_pairs
    assert (by_title["Beta"], by_title["Gamma"]) in edge_pairs
    assert (by_title["Hub"], by_title["Alpha"]) in edge_pairs
    assert (by_title["Hub"], by_title["Beta"]) in edge_pairs
    assert len(g.edges) == 5


def test_degree_counts_correct(tmp_path: Path):
    v, notes = _seed(tmp_path)
    metas = _list_metas(notes)
    g = build_graph(
        metas,
        folder_for=v.folder_of,
        read_body=lambda p: read_body_via_note(v.notes_dir / Path(p).name),
    )
    by_title = {n.title: n for n in g.nodes}
    # in_degree
    assert by_title["Alpha"].in_degree == 2  # from Beta + Hub
    assert by_title["Beta"].in_degree == 2  # from Alpha + Hub
    assert by_title["Gamma"].in_degree == 1  # from Beta
    assert by_title["Orphan"].in_degree == 0
    assert by_title["Hub"].in_degree == 0
    # out_degree
    assert by_title["Alpha"].out_degree == 1
    assert by_title["Beta"].out_degree == 2
    assert by_title["Gamma"].out_degree == 0
    assert by_title["Orphan"].out_degree == 0
    assert by_title["Hub"].out_degree == 2


def test_dangling_links_excluded(tmp_path: Path):
    v, notes = _seed(tmp_path)
    metas = _list_metas(notes)
    g = build_graph(
        metas,
        folder_for=v.folder_of,
        read_body=lambda p: read_body_via_note(v.notes_dir / Path(p).name),
    )
    # `[[NonExistent]]` from Hub doesn't appear as an edge. Verify by
    # checking total out-edges from Hub.
    by_title = {n.title: n.id for n in g.nodes}
    out_from_hub = [e for e in g.edges if e.source == by_title["Hub"]]
    assert len(out_from_hub) == 2  # Alpha + Beta only


def test_dedup_multiple_mentions_per_source_pair(tmp_path: Path):
    """A source linking to the same target multiple times still counts
    as ONE edge — graph view shows structure, not occurrences."""
    v = Vault(tmp_path)
    v.init_layout()
    target = Note(id=new_id(), title="Target", body="x")
    spammer = Note(
        id=new_id(),
        title="Spam",
        body="[[Target]] line 1\n[[Target]] line 2\n[[Target]] line 3",
    )
    for n in (target, spammer):
        v.write_note(n)
    metas = _list_metas([target, spammer])
    g = build_graph(
        metas,
        folder_for=v.folder_of,
        read_body=lambda p: read_body_via_note(v.notes_dir / Path(p).name),
    )
    edges = [e for e in g.edges if e.source == spammer.id]
    assert len(edges) == 1
    assert edges[0].target == target.id


def test_self_links_dropped(tmp_path: Path):
    v = Vault(tmp_path)
    v.init_layout()
    selfie = Note(id=new_id(), title="Selfie", body="I link to [[Selfie]] :)")
    v.write_note(selfie)
    metas = _list_metas([selfie])
    g = build_graph(
        metas,
        folder_for=v.folder_of,
        read_body=lambda p: read_body_via_note(v.notes_dir / Path(p).name),
    )
    assert g.edges == []
    assert g.nodes[0].in_degree == 0
    assert g.nodes[0].out_degree == 0


def test_empty_vault(tmp_path: Path):
    v = Vault(tmp_path)
    v.init_layout()
    g = build_graph(
        [],
        folder_for=v.folder_of,
        read_body=lambda p: "",
    )
    assert g.nodes == []
    assert g.edges == []


def test_case_insensitive_title_resolution(tmp_path: Path):
    """`[[alpha]]` should resolve to the note titled `Alpha`."""
    v = Vault(tmp_path)
    v.init_layout()
    target = Note(id=new_id(), title="Alpha", body="x")
    src = Note(id=new_id(), title="Source", body="See [[ALPHA]] please.")
    for n in (target, src):
        v.write_note(n)
    metas = _list_metas([target, src])
    g = build_graph(
        metas,
        folder_for=v.folder_of,
        read_body=lambda p: read_body_via_note(v.notes_dir / Path(p).name),
    )
    assert len(g.edges) == 1
    assert g.edges[0].source == src.id
    assert g.edges[0].target == target.id
