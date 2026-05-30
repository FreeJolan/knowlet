"""Thin wrapper over the OpenAI SDK for OpenAI-compatible endpoints.

knowlet does not store or proxy LLM credentials anywhere outside the local
config file. The same client speaks to OpenAI / Codex-via-compat /
Ollama / OpenRouter — anything that implements the OpenAI Responses API
shape with hosted tools and function-calls.

Every call (sync ``chat`` and streaming ``chat_stream``) emits an
``ai.call`` audit event when an :class:`AuditEventStore` is provided
— per Phase 3 Stage 1 / ADR-0028 §2 "audit trail". Audit failures
are swallowed (logged at debug) so a misconfigured audit store can
never break the actual LLM call.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from openai import BadRequestError, OpenAI

from knowlet.config import LLMConfig
from knowlet.core.audit_log import AuditEvent, AuditEventStore
from knowlet.core.events import (
    ReplyChunkEvent,
    ReplyDoneEvent,
    ToolCallEvent,
)

log = logging.getLogger(__name__)

# Max chars kept in audit payload previews. Long prompts / responses
# don't belong in the audit log (huge sqlite rows, leaks vault content
# into log readers). 200 chars is enough to recognize "ah, that was
# the editor-advisor call" without dumping the full payload.
_AUDIT_PREVIEW_CHARS = 200


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


@dataclass
class ResponsesMessage:
    """Minimal normalized wrapper for the OpenAI Responses API surface."""

    content: str
    raw: Any = None


# Some OpenAI-compatible backends reject the `temperature` request param for
# particular models. Rather than maintain a curated substring list that ages
# with every release, we learn from a 400 once and cache the result per model id.
_no_temp_cache: set[str] = set()


def _is_temp_rejection(exc: BadRequestError) -> bool:
    """Return True iff the BadRequestError clearly complains about temperature."""
    msg = str(exc).lower()
    return "temperature" in msg


class LLMClient:
    def __init__(
        self,
        cfg: LLMConfig,
        audit_store: AuditEventStore | None = None,
    ):
        self.cfg = cfg
        self._client: OpenAI | None = None
        # Optional. When set, every chat() / chat_stream() call emits
        # an ``ai.call`` audit event. None = no audit (test harnesses,
        # one-off REPL calls, knowlet web before runtime init).
        self.audit_store = audit_store

    def _ensure(self) -> OpenAI:
        if self._client is None:
            if not self.cfg.api_key:
                raise RuntimeError("LLM api_key is empty. Run `knowlet config init` to configure.")
            self._client = OpenAI(base_url=self.cfg.base_url, api_key=self.cfg.api_key)
        return self._client

    # ----------------------------------------------- audit helpers

    def _emit_call_audit(
        self,
        *,
        role: str | None,
        messages: list[dict[str, Any]],
        output_text: str,
        latency_ms: int,
        tool_calls_count: int,
        stream: bool,
        error: str | None,
    ) -> None:
        """Best-effort emit of an ``ai.call`` audit event.

        Swallows all exceptions — audit must never break the actual
        LLM call. Caller passes ``error=`` so we capture failures too
        (post-mortem visibility into why a call blew up)."""
        if self.audit_store is None:
            return
        try:
            prompt_chars = sum(len(m.get("content") or "") for m in messages)
            last_user = next(
                (m.get("content") or "" for m in reversed(messages) if m.get("role") == "user"),
                "",
            )
            payload: dict[str, Any] = {
                "role": role or "unknown",
                "model": self.cfg.model,
                "prompt_chars": prompt_chars,
                "response_chars": len(output_text),
                "latency_ms": latency_ms,
                "tool_calls": tool_calls_count,
                "stream": stream,
                "input_preview": last_user[:_AUDIT_PREVIEW_CHARS],
                "output_preview": output_text[:_AUDIT_PREVIEW_CHARS],
            }
            if error:
                payload["error"] = error[:500]
            self.audit_store.append(
                AuditEvent(
                    kind="ai.call",
                    entity_type="ai_call",
                    entity_id="",  # auto-filled with ULID by AuditEvent
                    actor="llm",
                    payload=payload,
                )
            )
        except Exception:
            log.debug("ai.call audit emit failed", exc_info=True)

    # ----------------------------------------------- chat (sync)

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        role: str | None = None,
    ) -> AssistantMessage:
        kwargs: dict[str, Any] = {
            "model": self.cfg.model,
            "input": responses_input_from_messages(messages),
            "max_output_tokens": max_tokens or self.cfg.max_tokens,
        }
        temp = self.cfg.temperature if temperature is None else temperature
        if temp is not None and self.cfg.model not in _no_temp_cache:
            kwargs["temperature"] = temp
        if tools:
            kwargs["tools"] = responses_tools_from_openai_schema(tools)
            kwargs["tool_choice"] = "auto"

        started = time.monotonic()
        error_repr: str | None = None
        output_text = ""
        tool_calls: list[ToolCall] = []
        raw_resp: Any = None
        try:
            raw_resp = self._create_response(kwargs)
            output_text = response_output_text(raw_resp)
            tool_calls = response_tool_calls(raw_resp)
            return AssistantMessage(
                content=output_text,
                tool_calls=tool_calls,
                raw=raw_resp,
            )
        except Exception as exc:
            error_repr = repr(exc)[:500]
            raise
        finally:
            self._emit_call_audit(
                role=role,
                messages=messages,
                output_text=output_text,
                latency_ms=int((time.monotonic() - started) * 1000),
                tool_calls_count=len(tool_calls),
                stream=False,
                error=error_repr,
            )

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        role: str | None = None,
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

        Emits an ``ai.call`` audit event when the stream finishes
        (success or exception) and an audit store is configured.
        """
        kwargs: dict[str, Any] = {
            "model": self.cfg.model,
            "input": responses_input_from_messages(messages),
            "max_output_tokens": max_tokens or self.cfg.max_tokens,
            "stream": True,
        }
        temp = self.cfg.temperature if temperature is None else temperature
        if temp is not None and self.cfg.model not in _no_temp_cache:
            kwargs["temperature"] = temp
        if tools:
            kwargs["tools"] = responses_tools_from_openai_schema(tools)
            kwargs["tool_choice"] = "auto"

        content_buf: list[str] = []
        tool_calls_count = 0
        completed_response: Any = None

        started = time.monotonic()
        error_repr: str | None = None
        final_text = ""
        try:
            stream = self._create_response(kwargs)

            for event in stream:
                data = _to_plain(event)
                if not isinstance(data, dict):
                    continue
                event_type = data.get("type")
                if event_type == "response.output_text.delta":
                    text = str(data.get("delta") or "")
                    if not text:
                        continue
                    content_buf.append(text)
                    yield ReplyChunkEvent(text=text)
                elif event_type == "response.output_item.done":
                    tc = response_tool_call_from_item(data.get("item"))
                    if tc is not None:
                        tool_calls_count += 1
                        yield ToolCallEvent(id=tc.id, name=tc.name, arguments=tc.arguments)
                elif event_type == "response.completed":
                    completed_response = data.get("response")

            final_text = "".join(content_buf)
            if completed_response is not None:
                response_text = response_output_text(completed_response)
                if response_text:
                    final_text = response_text
            yield ReplyDoneEvent(final_text=final_text)
        except Exception as exc:
            error_repr = repr(exc)[:500]
            raise
        finally:
            self._emit_call_audit(
                role=role,
                messages=messages,
                output_text=final_text,
                latency_ms=int((time.monotonic() - started) * 1000),
                tool_calls_count=tool_calls_count,
                stream=True,
                error=error_repr,
            )

    # ----------------------------------------------- responses (sync)

    def responses(
        self,
        input_text: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        max_output_tokens: int | None = None,
        role: str | None = None,
        temperature: float | None = None,
    ) -> ResponsesMessage:
        """Call the Responses API when the configured endpoint exposes it.

        This is intentionally a thin, optional surface beside Chat
        Completions. Older OpenAI-compatible endpoints may not implement
        `/v1/responses`; callers should treat failure as a capability result,
        not as proof that the model itself lacks the feature.
        """
        kwargs: dict[str, Any] = {
            "model": self.cfg.model,
            "input": input_text,
        }
        temp = self.cfg.temperature if temperature is None else temperature
        if temp is not None and self.cfg.model not in _no_temp_cache:
            kwargs["temperature"] = temp
        if max_output_tokens is not None:
            kwargs["max_output_tokens"] = max_output_tokens
        if tools:
            kwargs["tools"] = responses_tools_from_openai_schema(tools)

        started = time.monotonic()
        error_repr: str | None = None
        output_text = ""
        raw_resp: Any = None
        try:
            raw_resp = self._create_response(kwargs)
            output_text = response_output_text(raw_resp)
            return ResponsesMessage(content=output_text, raw=raw_resp)
        except Exception as exc:
            error_repr = repr(exc)[:500]
            raise
        finally:
            self._emit_call_audit(
                role=role or "responses",
                messages=[{"role": "user", "content": input_text}],
                output_text=output_text,
                latency_ms=int((time.monotonic() - started) * 1000),
                tool_calls_count=(
                    1
                    if raw_resp is not None
                    and response_has_output_type(raw_resp, "web_search_call")
                    else 0
                ),
                stream=False,
                error=error_repr,
            )

    def _create_response(self, kwargs: dict[str, Any]) -> Any:
        client = self._ensure()
        responses_api = getattr(client, "responses", None)
        if responses_api is None:
            raise RuntimeError("OpenAI SDK does not expose responses API")
        try:
            return responses_api.create(**kwargs)
        except BadRequestError as exc:
            if "temperature" in kwargs and _is_temp_rejection(exc):
                _no_temp_cache.add(self.cfg.model)
                log.info(
                    "model %r rejected `temperature`; will omit it for the rest of this process.",
                    self.cfg.model,
                )
                kwargs = dict(kwargs)
                kwargs.pop("temperature", None)
                return responses_api.create(**kwargs)
            if "max_output_tokens" in kwargs and "max_output_tokens" in str(exc):
                kwargs = dict(kwargs)
                kwargs.pop("max_output_tokens", None)
                return responses_api.create(**kwargs)
            raise


def _to_plain(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return obj
    return getattr(obj, "__dict__", obj)


def responses_input_from_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Chat Completions-style history into Responses input items."""
    out: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "tool":
            out.append(
                {
                    "type": "function_call_output",
                    "call_id": str(message.get("tool_call_id") or ""),
                    "output": str(message.get("content") or ""),
                }
            )
            continue

        if role in {"system", "developer", "user", "assistant"}:
            content = message.get("content")
            if content:
                out.append(
                    {
                        "role": role,
                        "content": content,
                        "type": "message",
                    }
                )
            for tool_call in message.get("tool_calls") or []:
                converted = _responses_function_call_from_chat_tool_call(tool_call)
                if converted is not None:
                    out.append(converted)
    return out


def _responses_function_call_from_chat_tool_call(
    tool_call: dict[str, Any],
) -> dict[str, Any] | None:
    fn = tool_call.get("function")
    if not isinstance(fn, dict):
        return None
    name = str(fn.get("name") or "").strip()
    if not name:
        return None
    return {
        "type": "function_call",
        "call_id": str(tool_call.get("id") or ""),
        "name": name,
        "arguments": str(fn.get("arguments") or "{}"),
    }


def responses_tools_from_openai_schema(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert Chat Completions function tools to Responses function tools.

    Hosted Responses tools such as web_search are already in Responses shape and
    pass through unchanged.
    """
    converted: list[dict[str, Any]] = []
    for tool in tools:
        if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
            fn = tool["function"]
            item: dict[str, Any] = {
                "type": "function",
                "name": fn.get("name"),
                "parameters": fn.get("parameters") or {},
                "strict": fn.get("strict", False),
            }
            if fn.get("description") is not None:
                item["description"] = fn.get("description")
            converted.append(item)
        else:
            converted.append(tool)
    return converted


def response_output_text(resp: Any) -> str:
    """Extract final text from OpenAI Responses objects or compatible dicts."""
    text = getattr(resp, "output_text", None)
    if isinstance(text, str) and text:
        return text

    data = _to_plain(resp)
    if not isinstance(data, dict):
        return ""
    out: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            value = content.get("text") or content.get("output_text")
            if isinstance(value, str):
                out.append(value)
    return "".join(out)


def response_tool_call_from_item(item: Any) -> ToolCall | None:
    data = _to_plain(item)
    if not isinstance(data, dict) or data.get("type") != "function_call":
        return None
    name = str(data.get("name") or "").strip()
    call_id = str(data.get("call_id") or data.get("id") or "").strip()
    if not name or not call_id:
        return None
    raw_args = str(data.get("arguments") or "{}")
    try:
        args = json.loads(raw_args) if raw_args else {}
    except json.JSONDecodeError:
        args = {"_raw": raw_args}
    if not isinstance(args, dict):
        args = {"_value": args}
    return ToolCall(id=call_id, name=name, arguments=args)


def response_tool_calls(resp: Any) -> list[ToolCall]:
    data = _to_plain(resp)
    if not isinstance(data, dict):
        return []
    calls: list[ToolCall] = []
    for item in data.get("output") or []:
        call = response_tool_call_from_item(item)
        if call is not None:
            calls.append(call)
    return calls


def response_has_output_type(resp: Any, type_name: str) -> bool:
    """Return True when a Responses payload contains an output item type."""
    data = _to_plain(resp)
    if not isinstance(data, dict):
        return False

    def visit(value: Any) -> bool:
        if isinstance(value, dict):
            if value.get("type") == type_name:
                return True
            return any(visit(v) for v in value.values())
        if isinstance(value, list):
            return any(visit(v) for v in value)
        return False

    return visit(data.get("output") or data)


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
