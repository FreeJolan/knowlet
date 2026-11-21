"""Regression tests for LLMClient findings (llm-chat audit batch).

Covers: client rebuild on base_url / api_key change, request timeouts,
tool calls carried only by ``response.completed`` in a stream, the
temperature-rejection heuristic, and history repair for tool calls that
never got an output.
"""

from __future__ import annotations

from typing import Any, ClassVar
from unittest import mock

import httpx
import pytest
from openai import BadRequestError

from knowlet.config import LLMConfig
from knowlet.core import llm as llm_mod
from knowlet.core.events import ReplyDoneEvent, ToolCallEvent
from knowlet.core.llm import (
    LLMClient,
    _no_temp_cache,
    messages_with_tool_results,
    responses_input_from_messages,
)


class _RecordingOpenAI:
    """Stands in for ``openai.OpenAI``; records constructor kwargs."""

    instances: ClassVar[list[_RecordingOpenAI]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.responses = mock.Mock()
        self.responses.create.return_value = {
            "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]
        }
        _RecordingOpenAI.instances.append(self)


@pytest.fixture
def recording_openai(monkeypatch: pytest.MonkeyPatch) -> type[_RecordingOpenAI]:
    _RecordingOpenAI.instances = []
    monkeypatch.setattr(llm_mod, "OpenAI", _RecordingOpenAI)
    return _RecordingOpenAI


# ------------------------------------------------------------ llm.py:91


def test_client_rebuilt_when_base_url_changes(recording_openai) -> None:
    cfg = LLMConfig(api_key="old-key", base_url="http://old.example/v1")
    client = LLMClient(cfg)
    client.chat([{"role": "user", "content": "hi"}])
    assert recording_openai.instances[-1].kwargs["base_url"] == "http://old.example/v1"

    # Settings PUT mutates the shared config object in place.
    cfg.base_url = "http://new.example/v1"
    client.chat([{"role": "user", "content": "hi"}])

    assert len(recording_openai.instances) == 2
    assert recording_openai.instances[-1].kwargs["base_url"] == "http://new.example/v1"
    assert recording_openai.instances[-1].responses.create.called


def test_client_rebuilt_when_api_key_rotates(recording_openai) -> None:
    cfg = LLMConfig(api_key="expired", base_url="http://proxy.example/v1")
    client = LLMClient(cfg)
    client.chat([{"role": "user", "content": "hi"}])
    cfg.api_key = "fresh"
    client.chat([{"role": "user", "content": "hi"}])

    assert [i.kwargs["api_key"] for i in recording_openai.instances] == ["expired", "fresh"]


def test_client_reused_when_config_unchanged(recording_openai) -> None:
    cfg = LLMConfig(api_key="k", base_url="http://proxy.example/v1")
    client = LLMClient(cfg)
    client.chat([{"role": "user", "content": "hi"}])
    cfg.model = "another-model"  # model is read per call; no rebuild needed
    client.chat([{"role": "user", "content": "hi"}])
    assert len(recording_openai.instances) == 1


# ------------------------------------------------------------ llm.py:94


def test_client_has_bounded_timeouts_and_retries(recording_openai) -> None:
    client = LLMClient(LLMConfig(api_key="k"))
    client._ensure()
    kwargs = recording_openai.instances[-1].kwargs
    timeout = kwargs.get("timeout")
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect is not None and timeout.connect <= 10
    # Streams: the read timeout bounds the gap between chunks.
    assert timeout.read is not None and timeout.read <= 120
    assert kwargs.get("max_retries") is not None and kwargs["max_retries"] <= 1


def test_non_stream_call_gets_bounded_per_request_timeout(recording_openai) -> None:
    client = LLMClient(LLMConfig(api_key="k"))
    client.chat([{"role": "user", "content": "hi"}])
    create_kwargs = recording_openai.instances[-1].responses.create.call_args.kwargs
    timeout = create_kwargs.get("timeout")
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect is not None and timeout.connect <= 10
    # A non-streamed reply arrives in one piece, so read covers the whole
    # generation; it must still be bounded well below the SDK's 600s.
    assert timeout.read is not None and timeout.read <= 300


# ------------------------------------------------------------ llm.py:256


class _StreamOpenAI:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.responses = mock.Mock()
        self.responses.create.return_value = iter(events)


def _stream_client(events: list[dict[str, Any]]) -> LLMClient:
    client = LLMClient(LLMConfig(api_key="stub"))
    client._client = _StreamOpenAI(events)  # type: ignore[assignment]
    return client


_FUNCTION_CALL_ITEM = {
    "type": "function_call",
    "call_id": "call_9",
    "name": "search_notes",
    "arguments": '{"query":"rag"}',
}


def test_stream_tool_call_only_in_completed_response_is_emitted() -> None:
    client = _stream_client(
        [
            {"type": "response.created"},
            {"type": "response.completed", "response": {"output": [_FUNCTION_CALL_ITEM]}},
        ]
    )
    events = list(client.chat_stream([{"role": "user", "content": "search"}]))
    calls = [e for e in events if isinstance(e, ToolCallEvent)]
    assert [(c.id, c.name, c.arguments) for c in calls] == [
        ("call_9", "search_notes", {"query": "rag"})
    ]
    assert isinstance(events[-1], ReplyDoneEvent)


def test_stream_tool_call_in_both_item_done_and_completed_is_emitted_once() -> None:
    client = _stream_client(
        [
            {"type": "response.output_item.done", "item": _FUNCTION_CALL_ITEM},
            {"type": "response.completed", "response": {"output": [_FUNCTION_CALL_ITEM]}},
        ]
    )
    events = list(client.chat_stream([{"role": "user", "content": "search"}]))
    calls = [e for e in events if isinstance(e, ToolCallEvent)]
    assert len(calls) == 1


# ------------------------------------------------------------ llm.py:73


def _bad_request(message: str) -> BadRequestError:
    return BadRequestError(
        message=message,
        response=mock.Mock(status_code=400, request=mock.Mock()),
        body=None,
    )


def test_out_of_range_temperature_is_not_cached_as_unsupported() -> None:
    _no_temp_cache.clear()
    cfg = LLMConfig(api_key="stub", model="range-model", temperature=2.5)
    client = LLMClient(cfg)
    fake = mock.Mock()
    fake.responses.create.side_effect = _bad_request(
        "Invalid 'temperature': decimal above maximum value. "
        "Expected a value <= 2, but got 2.5 instead."
    )
    client._client = fake

    with pytest.raises(BadRequestError):
        client.chat([{"role": "user", "content": "hi"}])
    assert "range-model" not in _no_temp_cache

    # Once the user fixes the value, temperature is sent again without a restart.
    cfg.temperature = 0.2
    fake.responses.create.side_effect = None
    fake.responses.create.return_value = {"output": []}
    client.chat([{"role": "user", "content": "hi"}])
    assert fake.responses.create.call_args.kwargs["temperature"] == 0.2


def test_between_range_wording_is_not_cached_as_unsupported() -> None:
    _no_temp_cache.clear()
    client = LLMClient(LLMConfig(api_key="stub", model="range-model-2", temperature=3))
    fake = mock.Mock()
    fake.responses.create.side_effect = _bad_request("temperature must be between 0 and 2")
    client._client = fake
    with pytest.raises(BadRequestError):
        client.chat([{"role": "user", "content": "hi"}])
    assert "range-model-2" not in _no_temp_cache


def test_unsupported_temperature_is_still_cached() -> None:
    _no_temp_cache.clear()
    client = LLMClient(LLMConfig(api_key="stub", model="reasoning-x", temperature=0.3))
    fake = mock.Mock()
    fake.responses.create.side_effect = [
        _bad_request("Unsupported parameter: 'temperature' is not supported with this model."),
        {"output": []},
    ]
    client._client = fake
    client.chat([{"role": "user", "content": "hi"}])
    assert "reasoning-x" in _no_temp_cache
    _no_temp_cache.clear()


# ------------------------------------------- history repair (session.py:120)


def test_responses_input_drops_function_call_without_output() -> None:
    """A persisted history whose assistant tool call never got a tool
    result (interrupted turn) must not be replayed as a dangling
    function_call — the Responses API rejects that with a 400."""
    history = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "search the web"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_lost",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": "{}"},
                }
            ],
        },
        {"role": "user", "content": "hello again"},
    ]
    items = responses_input_from_messages(history)
    assert not [i for i in items if i.get("type") == "function_call"]
    assert [i.get("content") for i in items if i.get("type") == "message"] == [
        "sys",
        "search the web",
        "hello again",
    ]


def test_responses_input_drops_orphan_function_call_output() -> None:
    history = [
        {"role": "user", "content": "x"},
        {"role": "tool", "tool_call_id": "call_orphan", "content": "{}"},
    ]
    items = responses_input_from_messages(history)
    assert not [i for i in items if i.get("type") == "function_call_output"]


def test_responses_input_keeps_paired_tool_calls() -> None:
    history = [
        {"role": "user", "content": "x"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_ok",
                    "type": "function",
                    "function": {"name": "search_notes", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_ok", "content": "{}"},
    ]
    items = responses_input_from_messages(history)
    assert [i.get("type") for i in items] == ["message", "function_call", "function_call_output"]


def test_tool_results_with_non_json_payload_do_not_raise() -> None:
    class Opaque:
        def __str__(self) -> str:
            return "opaque-value"

    out = messages_with_tool_results([], [("call_1", {"value": Opaque()})])
    assert out[0]["tool_call_id"] == "call_1"
    assert "opaque-value" in out[0]["content"]
