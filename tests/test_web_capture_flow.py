"""Stage 3 Step 3.2 — POST /api/capture/url / /file / /decide.

Tests the three-way decide semantics (per ADR-0009 amendment A2.1):
- decision=knowledge → write Note kind=knowledge, no draft.
- decision=reference → write Note kind=reference, no draft.
- decision=defer    → write Draft (kind=defer_kind), no note.
"""

from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient

from knowlet.config import KnowletConfig, save_config
from knowlet.core.vault import Vault
from knowlet.web.server import create_app


def _client(tmp_path: Path) -> tuple[TestClient, Vault]:
    v = Vault(tmp_path)
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = "stub"
    save_config(v.root, cfg)
    app = create_app(v, cfg)
    client = TestClient(app)
    app.state.web_state.runtime_or_init()
    return client, v


# ---------------------------------------------------- /capture/url


def test_capture_url_rejects_non_http(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    r = client.post("/api/capture/url", json={"url": "ftp://x"})
    assert r.status_code == 400
    r = client.post("/api/capture/url", json={"url": ""})
    assert r.status_code == 400


# /capture/url happy path needs a real network or extensive mocking;
# that's covered by the existing M7.2 url-capture tests for the
# underlying ``capture_url`` function. Stage 3 is the routing layer.


# ---------------------------------------------------- /capture/file


def test_capture_file_markdown_extracts_title(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    body = b"# Hello World\n\nSome body content.\n"
    files = {"file": ("note.md", io.BytesIO(body), "text/markdown")}
    r = client.post("/api/capture/file", files=files)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["title"] == "Hello World"
    assert "Some body content" in data["body"]
    assert data["source"] == "note.md"


def test_capture_file_no_heading_falls_back_to_filename(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path)
    body = b"just some text, no heading anywhere"
    files = {"file": ("my-notes.txt", io.BytesIO(body), "text/plain")}
    r = client.post("/api/capture/file", files=files)
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "my-notes"


def test_capture_file_rejects_pdf(tmp_path: Path) -> None:
    """Stage 3 explicitly defers PDF support (per 2026-05-21 decision)."""
    client, _ = _client(tmp_path)
    files = {
        "file": ("doc.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")
    }
    r = client.post("/api/capture/file", files=files)
    assert r.status_code == 415


# ---------------------------------------------------- /capture/decide


def _capsule_payload() -> dict:
    return {
        "title": "Test Capsule",
        "body": "Some content from the AI summary.",
        "source": "https://example.com/article",
        "hostname": "example.com",
        "summary_failed": False,
    }


def test_decide_knowledge_writes_note_kind_knowledge(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    r = client.post(
        "/api/capture/decide",
        json={"capsule": _capsule_payload(), "decision": "knowledge"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["decision"] == "knowledge"
    assert data["note_id"]
    assert data["draft_id"] is None
    # Verify on disk.
    note_path = v.notes_dir / f"{data['note_id']}.md"
    raw = note_path.read_text(encoding="utf-8")
    assert "kind: knowledge" in raw
    assert "Test Capsule" in raw


def test_decide_reference_writes_note_kind_reference(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    r = client.post(
        "/api/capture/decide",
        json={"capsule": _capsule_payload(), "decision": "reference"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["decision"] == "reference"
    assert data["note_id"]
    raw = (v.notes_dir / f"{data['note_id']}.md").read_text("utf-8")
    assert "kind: reference" in raw


def test_decide_defer_writes_draft_not_note(tmp_path: Path) -> None:
    client, v = _client(tmp_path)
    r = client.post(
        "/api/capture/decide",
        json={
            "capsule": _capsule_payload(),
            "decision": "defer",
            # default defer_kind is reference, but we override here to
            # test the field round-trips.
            "defer_kind": "knowledge",
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["decision"] == "defer"
    assert data["draft_id"]
    assert data["note_id"] is None
    # Live draft file exists with kind=knowledge.
    draft_files = list(v.drafts_dir.glob("*.md"))
    assert len(draft_files) == 1
    raw = draft_files[0].read_text("utf-8")
    assert "kind: knowledge" in raw


def test_decide_defer_default_kind_is_reference(tmp_path: Path) -> None:
    """Per ADR-0029 §4.5 default-by-source: URL/file capture defaults
    to reference. The defer path inherits that default unless overridden."""
    client, v = _client(tmp_path)
    r = client.post(
        "/api/capture/decide",
        json={"capsule": _capsule_payload(), "decision": "defer"},
    )
    assert r.status_code == 200
    raw = next(v.drafts_dir.glob("*.md")).read_text("utf-8")
    assert "kind: reference" in raw


def test_defer_then_list_drafts_includes_body(tmp_path: Path) -> None:
    """Regression for 2026-05-22 dogfood: a deferred capsule's body
    must round-trip through to /api/drafts response. The earlier
    DraftSummary lacked the body field — drafts showed empty body in
    the UI even though the markdown file on disk was correct."""
    client, v = _client(tmp_path)
    capsule = {
        "title": "Article with body",
        "body": (
            "This is the actual extracted article body. It contains "
            "multiple sentences and should be returned verbatim from "
            "the drafts list endpoint."
        ),
        "source": "https://example.com/article",
        "hostname": "example.com",
        "summary_failed": False,
    }
    # Defer.
    r = client.post(
        "/api/capture/decide",
        json={"capsule": capsule, "decision": "defer"},
    )
    assert r.status_code == 200

    # GET /api/drafts must return the body, not just metadata.
    r = client.get("/api/drafts")
    assert r.status_code == 200
    drafts = r.json()
    assert len(drafts) == 1
    body = drafts[0].get("body", "")
    assert capsule["body"] in body, (
        f"draft body lost in transit: got {body!r}, expected to contain "
        f"{capsule['body'][:60]!r}"
    )

    # GET /api/drafts/{id} must also return it (was already correct
    # via DraftFull, but assert to be defensive).
    draft_id = drafts[0]["id"]
    r = client.get(f"/api/drafts/{draft_id}")
    assert r.status_code == 200
    assert capsule["body"] in r.json()["body"]


def test_decide_unknown_value_returns_422(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    r = client.post(
        "/api/capture/decide",
        json={"capsule": _capsule_payload(), "decision": "discard"},
    )
    assert r.status_code == 422  # pydantic validation
