"""Tests for Stage D — single-note calibration ("查这篇").

The check-note path is intentionally narrow: user-triggered, one note,
structured report only. It never edits the note; D2 routes any fix through
the existing diff-accept path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from knowlet.config import KnowletConfig, save_config
from knowlet.core.llm import AssistantMessage
from knowlet.core.note import Note, new_id
from knowlet.core.vault import Vault


class ChatStubLLM:
    def __init__(self, content: str):
        self._content = content
        self.seen: list[dict[str, Any]] | None = None

    def chat(self, messages, tools=None, max_tokens=None, temperature=None):
        self.seen = messages
        return AssistantMessage(content=self._content, tool_calls=[])


def _client_with_note(tmp_path: Path, body: str, stub: Any) -> tuple[TestClient, Note]:
    from knowlet.core.audit_log import AuditEventStore
    from knowlet.core.backups import BackupStore
    from knowlet.web.server import create_app

    v = Vault(
        tmp_path,
        audit_log=AuditEventStore(tmp_path),
        backups=BackupStore(tmp_path),
    )
    v.init_layout()
    cfg = KnowletConfig()
    cfg.embedding.backend = "dummy"
    cfg.embedding.dim = 32
    cfg.llm.api_key = "stub"
    save_config(v.root, cfg)

    note = Note(id=new_id(), title="Photosynthesis", body=body, tags=["bio"])
    v.write_note(note)
    app = create_app(v, cfg)
    client = TestClient(app)
    runtime = app.state.web_state.runtime_or_init()
    runtime.llm = stub  # type: ignore[assignment]
    runtime.session.llm = stub  # type: ignore[assignment]
    return client, note


def test_check_note_builds_grounded_prompt_and_parses_findings() -> None:
    from knowlet.chat.note_check import check_note

    payload = {
        "summary": "One material omission.",
        "findings": [
            {
                "severity": "high",
                "paragraph": 2,
                "quote": "Photosynthesis only makes oxygen.",
                "finding": "This misses glucose production.",
                "why": "The standard answer includes glucose as an output.",
                "suggestion": "Mention glucose and oxygen as products.",
                "fix_instruction": "Add glucose as a product in paragraph 2.",
                "confidence": 0.91,
            }
        ],
    }
    stub = ChatStubLLM(json.dumps(payload))
    note = Note(
        id="n1",
        title="Photosynthesis",
        body="Plants use light.\n\nPhotosynthesis only makes oxygen.",
        tags=[],
    )

    report = check_note(
        llm=stub,
        note=note,
        standard_answer="Photosynthesis converts light, CO2, and water into glucose and oxygen.",
    )

    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.paragraph == 2
    assert finding.severity == "high"
    assert "glucose" in finding.fix_instruction
    assert stub.seen is not None
    user_blob = "\n".join(m["content"] for m in stub.seen if m["role"] == "user")
    assert '<paragraph n="1">' in user_blob
    assert '<paragraph n="2">' in user_blob
    assert "Photosynthesis converts light" in user_blob


def test_check_note_invalid_model_output_degrades_to_empty_report() -> None:
    from knowlet.chat.note_check import check_note

    stub = ChatStubLLM("not json")
    note = Note(id="n1", title="T", body="Body", tags=[])
    report = check_note(llm=stub, note=note, standard_answer="")

    assert report.summary == "无法从 AI 回复中解析出可用报告"
    assert report.findings == []


def test_web_note_check_returns_report_without_writing(tmp_path: Path):
    payload = {
        "summary": "Missing one output.",
        "findings": [
            {
                "severity": "medium",
                "paragraph": 1,
                "quote": "Plants use light.",
                "finding": "The note omits glucose.",
                "why": "The standard answer names glucose.",
                "suggestion": "Add glucose as an output.",
                "fix_instruction": "Revise paragraph 1 to mention glucose.",
                "confidence": 0.8,
            }
        ],
    }
    stub = ChatStubLLM(json.dumps(payload))
    client, note = _client_with_note(tmp_path, "Plants use light.", stub)

    r = client.post(
        f"/api/chat/note/{note.id}/check",
        json={"standard_answer": "Plants make glucose and oxygen."},
    )

    assert r.status_code == 200
    data = r.json()
    assert data["note_id"] == note.id
    assert data["findings"][0]["paragraph"] == 1
    assert data["findings"][0]["fix_instruction"].startswith("Revise")
    after = client.get(f"/api/notes/{note.id}").json()
    assert after["body"] == "Plants use light."
