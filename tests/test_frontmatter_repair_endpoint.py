"""Task #108 — POST /api/notes/{id}/repair-frontmatter endpoint.

The user clicks "auto-repair" on the warning chip; the endpoint
re-reads the corrupted file, persists the synthesized frontmatter
through Vault.write_note (which atomically replaces + backs up via
.knowlet/backups/), then re-indexes so search / backlinks see the
new title.
"""

from __future__ import annotations

from pathlib import Path

from knowlet.core.note import Note
from tests.test_web import StubLLM, _client_with_stub


def _vault(client) -> Path:
    return client.app.state.web_state.runtime.vault.root  # type: ignore[attr-defined]


def test_repair_endpoint_fixes_yaml_parse_error(tmp_path: Path) -> None:
    """Mirror small-red's path: she edits a note in TextEdit and
    breaks the YAML. She reopens knowlet, sees the warning chip,
    clicks auto-repair. After: file has a clean frontmatter +
    her body content is preserved."""
    client, vault, _ = _client_with_stub(tmp_path, StubLLM([]))
    runtime = client.app.state.web_state.runtime  # type: ignore[attr-defined]
    assert runtime is not None

    # Plant a note with broken YAML (unclosed quote).
    nid = "01HXBR0KEN00000000000000XX"
    p = vault.notes_dir / f"{nid}.md"
    p.write_text(
        '---\nid: 01ABC\ntitle: "unclosed\nbroken: : :\n---\nthe surviving body\n',
        encoding="utf-8",
    )
    # Index it so /api/notes/<id> can resolve the path.
    n = Note.from_file(p)
    runtime.index.upsert_note(
        n,
        chunk_size=runtime.config.retrieval.chunk_size,
        chunk_overlap=runtime.config.retrieval.chunk_overlap,
    )

    # GET first — confirm corruption surfaces.
    r = client.get(f"/api/notes/{nid}")
    assert r.status_code == 200
    body = r.json()
    assert body["frontmatter_status"] == "corrupted"
    assert "yaml" in (body["frontmatter_corruption"] or "").lower()

    # Repair.
    r = client.post(f"/api/notes/{nid}/repair-frontmatter")
    assert r.status_code == 200, r.text
    repaired = r.json()
    assert repaired["frontmatter_status"] == "valid"
    # File on disk is now well-formed YAML + retains the body.
    new_text = p.read_text(encoding="utf-8")
    assert new_text.startswith("---\n")
    assert "schema_version:" in new_text
    assert "the surviving body" in new_text
    # Original was backed up before overwrite (ADR-0018 path).
    backups_dir = vault.root / ".knowlet" / "backups"
    assert backups_dir.exists()


def test_repair_endpoint_409_when_not_corrupted(tmp_path: Path) -> None:
    """Calling repair on a healthy note is a programmer error (the
    UI hides the button when status==valid). Returns 409 rather
    than silently rewriting an intact file."""
    client, _vault, _ = _client_with_stub(tmp_path, StubLLM([]))
    runtime = client.app.state.web_state.runtime  # type: ignore[attr-defined]
    note = Note(id="01KR1J4TEST00000000000000A", title="clean", body="ok")
    runtime.vault.write_note(note)
    runtime.index.upsert_note(
        note,
        chunk_size=runtime.config.retrieval.chunk_size,
        chunk_overlap=runtime.config.retrieval.chunk_overlap,
    )
    r = client.post(f"/api/notes/{note.id}/repair-frontmatter")
    assert r.status_code == 409


def test_repair_endpoint_404_when_unknown(tmp_path: Path) -> None:
    client, _, _ = _client_with_stub(tmp_path, StubLLM([]))
    r = client.post("/api/notes/01NEVERHAPPENED00000000000/repair-frontmatter")
    assert r.status_code == 404
