"""Thin wrapper over the OpenAI SDK for OpenAI-compatible endpoints.

knowlet does not store or proxy LLM credentials anywhere outside the local
config file. The same client speaks to OpenAI / Anthropic-via-compat /
Ollama / OpenRouter — anything that implements the OpenAI Chat Completions
shape with tool-calls.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

from openai import BadRequestError, OpenAI

from knowlet.config import LLMConfig
from knowlet.core.events import (
    ReplyChunkEvent,
    ReplyDoneEvent,
    ToolCallEvent,
)

log = logging.getLogger(__name__)


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class AssistantMessage:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None


# Some models reject the `temperature` request param (Anthropic Claude 4.x —
# Opus 4.7 / 4.6, Sonnet 4.6, Haiku 4.5, … — and likely future ones). Rather
# than maintain a curated substring list that ages with every release, we
# learn from a 400 once and cache the result per model id.
_no_temp_cache: set[str] = set()


def _is_temp_rejection(exc: BadRequestError) -> bool:
    """Return True iff the BadRequestError clearly complains about temperature."""
    msg = str(exc).lower()
    return "temperature" in msg


class LLMClient:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self._client: OpenAI | None = None

    def _ensure(self) -> OpenAI:
        if self._client is None:
            if not self.cfg.api_key:
                raise RuntimeError(
                    "LLM api_key is empty. Run `knowlet config init` to configure."
                )
            self._client = OpenAI(base_url=self.cfg.base_url, api_key=self.cfg.api_key)
        return self._client

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> AssistantMessage:
        client = self._ensure()
        kwargs: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": messages,
            "max_tokens": max_tokens or self.cfg.max_tokens,
        }
        temp = self.cfg.temperature if temperature is None else temperature
        if temp is not None and self.cfg.model not in _no_temp_cache:
            kwargs["temperature"] = temp
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            resp = client.chat.completions.create(**kwargs)
        except BadRequestError as exc:
            if "temperature" in kwargs and _is_temp_rejection(exc):
                _no_temp_cache.add(self.cfg.model)
                log.info(
                    "model %r rejected `temperature`; will omit it for the rest "
                    "of this process.", self.cfg.model
                )
                kwargs.pop("temperature", None)
                resp = client.chat.completions.create(**kwargs)
            else:
                raise
        choice = resp.choices[0].message
        tool_calls: list[ToolCall] = []
        for tc in choice.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        return AssistantMessage(
            content=choice.content or "",
            tool_calls=tool_calls,
            raw=resp,
        )

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> Iterator[ReplyChunkEvent | ToolCallEvent | ReplyDoneEvent]:
        """Streaming variant of `chat`.

        Yields events in this order:

        1. Zero or more `ReplyChunkEvent` as content tokens arrive.
        2. After the stream is exhausted, zero or more `ToolCallEvent` —
           emitted only when the tool calls are fully assembled (we do not
           expose partial / mid-assembly tool calls).
        3. Exactly one `ReplyDoneEvent` with the final accumulated text.

        The caller (typically `ChatSession.user_turn_stream`) drives the
        tool-loop on top of this primitive.
        """
        client = self._ensure()
        kwargs: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": messages,
            "max_tokens": max_tokens or self.cfg.max_tokens,
            "stream": True,
        }
        temp = self.cfg.temperature if temperature is None else temperature
        if temp is not None and self.cfg.model not in _no_temp_cache:
            kwargs["temperature"] = temp
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        content_buf: list[str] = []
        tc_buf: dict[int, dict[str, Any]] = {}

        try:
            stream = client.chat.completions.create(**kwargs)
        except BadRequestError as exc:
            if "temperature" in kwargs and _is_temp_rejection(exc):
                _no_temp_cache.add(self.cfg.model)
                log.info(
                    "model %r rejected `temperature`; will omit it for the rest "
                    "of this process.", self.cfg.model
                )
                kwargs.pop("temperature", None)
                stream = client.chat.completions.create(**kwargs)
            else:
                raise

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            if getattr(delta, "content", None):
                text = delta.content
                content_buf.append(text)
                yield ReplyChunkEvent(text=text)
            for tc_delta in getattr(delta, "tool_calls", None) or []:
                idx = tc_delta.index
                slot = tc_buf.setdefault(idx, {"id": "", "name": "", "args": ""})
                if tc_delta.id:
                    slot["id"] = tc_delta.id
                fn = getattr(tc_delta, "function", None)
                if fn is not None:
                    if fn.name:
                        slot["name"] = fn.name
                    if fn.arguments:
                        slot["args"] += fn.arguments

        for idx in sorted(tc_buf):
            slot = tc_buf[idx]
            try:
                args = json.loads(slot["args"]) if slot["args"] else {}
            except json.JSONDecodeError:
                args = {"_raw": slot["args"]}
            yield ToolCallEvent(id=slot["id"], name=slot["name"], arguments=args)

        yield ReplyDoneEvent(final_text="".join(content_buf))


def messages_with_assistant(
    messages: list[dict[str, Any]],
    assistant: AssistantMessage,
) -> list[dict[str, Any]]:
    """Append an assistant turn (with tool_calls) to the message log."""
    msg: dict[str, Any] = {"role": "assistant", "content": assistant.content or None}
    if assistant.tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                },
            }
            for tc in assistant.tool_calls
        ]
    return [*messages, msg]


def messages_with_tool_results(
    messages: list[dict[str, Any]],
    results: Iterable[tuple[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Append tool-result turns. results is an iterable of (tool_call_id, payload)."""
    out = list(messages)
    for tc_id, payload in results:
        out.append(
            {
                "role": "tool",
                "tool_call_id": tc_id,
                "content": json.dumps(payload, ensure_ascii=False),
            }
        )
    return out
