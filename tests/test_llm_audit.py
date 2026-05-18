"""Tests for ai.call audit emission from LLMClient (Phase 3 Stage 1 Step 1.2).

We don't make real LLM calls. Instead we monkey-patch
``LLMClient._ensure`` to return a fake OpenAI client whose
``chat.completions.create`` returns canned responses. That lets us
assert the audit-emission path without needing network / a real
provider.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from knowlet.config import LLMConfig
from knowlet.core.audit_log import AuditEventStore
from knowlet.core.llm import LLMClient


# ----------------------------------------------- fakes


class _FakeMessage:
    def __init__(
        self, content: str, tool_calls: list[Any] | None = None
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls or []


class _FakeChoice:
    def __init__(self, message: _FakeMessage) -> None:
        self.message = message


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(_FakeMessage(content))]


class _FakeCompletions:
    def __init__(self, response_text: str = "ok", raises: Exception | None = None) -> None:
        self._response_text = response_text
        self._raises = raises
        self.last_kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.last_kwargs = kwargs
        if self._raises is not None:
            raise self._raises
        return _FakeResponse(self._response_text)


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeOpenAI:
    def __init__(self, response_text: str = "ok", raises: Exception | None = None) -> None:
        self.chat = _FakeChat(_FakeCompletions(response_text=response_text, raises=raises))


def _make_client(
    tmp_path: Path,
    *,
    response_text: str = "ok",
    raises: Exception | None = None,
    with_audit: bool = True,
) -> tuple[LLMClient, AuditEventStore | None]:
    cfg = LLMConfig(
        base_url="http://fake",
        api_key="fake-key",
        model="fake-model",
        max_tokens=64,
    )
    store: AuditEventStore | None = None
    if with_audit:
        store = AuditEventStore(tmp_path / "events.sqlite")
    client = LLMClient(cfg, audit_store=store)
    fake = _FakeOpenAI(response_text=response_text, raises=raises)
    # Bypass _ensure() so we don't try a real connection.
    client._client = fake  # type: ignore[assignment]
    return client, store


# ----------------------------------------------- chat() audit


def test_chat_emits_ai_call_audit(tmp_path: Path) -> None:
    client, store = _make_client(tmp_path, response_text="hello world")
    assert store is not None
    client.chat(
        messages=[{"role": "user", "content": "say hi"}],
        role="editor_advisor",
    )
    events = store.query(kinds=["ai.call"])
    assert len(events) == 1
    ev = events[0]
    assert ev.kind == "ai.call"
    assert ev.entity_type == "ai_call"
    assert ev.actor == "llm"
    p = ev.payload
    assert p["role"] == "editor_advisor"
    assert p["model"] == "fake-model"
    assert p["response_chars"] == len("hello world")
    assert p["output_preview"] == "hello world"
    assert p["input_preview"] == "say hi"
    assert p["stream"] is False
    assert "error" not in p
    assert isinstance(p["latency_ms"], int)


def test_chat_audit_records_role_unknown_when_omitted(tmp_path: Path) -> None:
    client, store = _make_client(tmp_path)
    assert store is not None
    client.chat(messages=[{"role": "user", "content": "x"}])
    events = store.query(kinds=["ai.call"])
    assert len(events) == 1
    assert events[0].payload["role"] == "unknown"


def test_chat_error_still_audited(tmp_path: Path) -> None:
    """LLM raises → exception propagates AND audit row is still written."""
    boom = RuntimeError("upstream 502")
    client, store = _make_client(tmp_path, raises=boom)
    assert store is not None
    with pytest.raises(RuntimeError):
        client.chat(
            messages=[{"role": "user", "content": "x"}],
            role="capture_extractor",
        )
    events = store.query(kinds=["ai.call"])
    assert len(events) == 1
    ev = events[0]
    assert ev.payload["role"] == "capture_extractor"
    assert "upstream 502" in ev.payload["error"]
    assert ev.payload["response_chars"] == 0


def test_chat_without_audit_store_is_silent(tmp_path: Path) -> None:
    client, store = _make_client(tmp_path, with_audit=False)
    assert store is None
    result = client.chat(messages=[{"role": "user", "content": "x"}])
    assert result.content == "ok"
    # No store → no rows to query, but also no exception.


# ----------------------------------------------- chat_stream() audit


def _drain_stream(client: LLMClient, **kwargs: Any) -> list[Any]:
    return list(client.chat_stream(**kwargs))


def test_chat_stream_emits_audit_after_completion(tmp_path: Path) -> None:
    """Streaming path also emits ai.call after the stream exhausts."""

    # Build a small "stream" of chunks.
    class _Delta:
        def __init__(self, content: str = "", tool_calls: Any = None) -> None:
            self.content = content
            self.tool_calls = tool_calls

    class _StreamChoice:
        def __init__(self, delta: _Delta) -> None:
            self.delta = delta

    class _StreamChunk:
        def __init__(self, content: str = "") -> None:
            self.choices = [_StreamChoice(_Delta(content=content))]

    class _FakeStream:
        def __iter__(self):
            yield _StreamChunk("Hel")
            yield _StreamChunk("lo!")

    class _StreamingCompletions:
        def create(self, **kwargs: Any) -> _FakeStream:
            return _FakeStream()

    class _StreamingChat:
        def __init__(self) -> None:
            self.completions = _StreamingCompletions()

    class _StreamingOpenAI:
        def __init__(self) -> None:
            self.chat = _StreamingChat()

    cfg = LLMConfig(
        base_url="http://fake",
        api_key="fake-key",
        model="fake-streaming-model",
    )
    store = AuditEventStore(tmp_path / "events.sqlite")
    client = LLMClient(cfg, audit_store=store)
    client._client = _StreamingOpenAI()  # type: ignore[assignment]

    events_yielded = _drain_stream(
        client,
        messages=[{"role": "user", "content": "hi"}],
        role="chat_companion",
    )
    # Sanity: streaming yielded ReplyChunk + ReplyDone.
    assert any(getattr(e, "text", None) == "Hel" for e in events_yielded)

    audits = store.query(kinds=["ai.call"])
    assert len(audits) == 1
    p = audits[0].payload
    assert p["role"] == "chat_companion"
    assert p["model"] == "fake-streaming-model"
    assert p["stream"] is True
    assert p["output_preview"] == "Hello!"
    assert p["response_chars"] == 6
