from __future__ import annotations

from typing import Any

from knowlet.config import LLMConfig
from knowlet.core.events import ReplyChunkEvent, ReplyDoneEvent, ToolCallEvent
from knowlet.core.llm import (
    LLMClient,
    ToolCall,
    messages_with_assistant,
    messages_with_tool_results,
)


class _FakeResponses:
    def __init__(self, response: Any | None = None, stream: list[Any] | None = None) -> None:
        self.response = response or {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "ok"}],
                }
            ]
        }
        self.stream = stream or []
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            return iter(self.stream)
        return self.response


class _FakeOpenAI:
    def __init__(self, responses: _FakeResponses) -> None:
        self.responses = responses


def _client(responses: _FakeResponses) -> LLMClient:
    cfg = LLMConfig(api_key="stub", model="gpt-5.5", max_tokens=123)
    client = LLMClient(cfg)
    client._client = _FakeOpenAI(responses)  # type: ignore[assignment]
    return client


def test_chat_uses_responses_api_and_converts_function_tools() -> None:
    responses = _FakeResponses(
        {
            "output": [
                {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "search_notes",
                    "arguments": "{\"query\":\"ping\"}",
                    "status": "completed",
                }
            ]
        }
    )
    client = _client(responses)

    msg = client.chat(
        [{"role": "user", "content": "call search_notes"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "search_notes",
                    "description": "Search local notes",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                },
            }
        ],
        max_tokens=77,
        temperature=0,
    )

    assert msg.tool_calls == [
        ToolCall(id="call_1", name="search_notes", arguments={"query": "ping"})
    ]
    call = responses.calls[0]
    assert call["input"] == [{"role": "user", "content": "call search_notes", "type": "message"}]
    assert call["max_output_tokens"] == 77
    assert call["temperature"] == 0
    assert call["tools"] == [
        {
            "type": "function",
            "name": "search_notes",
            "description": "Search local notes",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            "strict": False,
        }
    ]


def test_chat_converts_tool_history_to_responses_input_items() -> None:
    responses = _FakeResponses()
    client = _client(responses)
    history = [{"role": "user", "content": "search"}]
    history = messages_with_assistant(
        history,
        assistant=type(
            "_Assistant",
            (),
            {
                "content": "",
                "tool_calls": [
                    ToolCall(id="call_1", name="search_notes", arguments={"query": "ping"})
                ],
            },
        )(),
    )
    history = messages_with_tool_results(history, [("call_1", {"results": []})])

    client.chat(history)

    assert responses.calls[0]["input"] == [
        {"role": "user", "content": "search", "type": "message"},
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "search_notes",
            "arguments": "{\"query\": \"ping\"}",
        },
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "{\"results\": []}",
        },
    ]


def test_chat_stream_uses_responses_stream_events() -> None:
    responses = _FakeResponses(
        stream=[
            {
                "type": "response.output_text.delta",
                "delta": "Hel",
            },
            {
                "type": "response.output_text.delta",
                "delta": "lo",
            },
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "search_notes",
                    "arguments": "{\"query\":\"ping\"}",
                },
            },
            {
                "type": "response.completed",
                "response": {
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": "Hello"}],
                        }
                    ]
                },
            },
        ]
    )
    client = _client(responses)

    events = list(client.chat_stream([{"role": "user", "content": "hi"}]))

    assert [ev.text for ev in events if isinstance(ev, ReplyChunkEvent)] == ["Hel", "lo"]
    assert [
        (ev.id, ev.name, ev.arguments)
        for ev in events
        if isinstance(ev, ToolCallEvent)
    ] == [("call_1", "search_notes", {"query": "ping"})]
    assert [
        ev.final_text for ev in events if isinstance(ev, ReplyDoneEvent)
    ] == ["Hello"]
    assert responses.calls[0]["stream"] is True
