"""Thin wrapper over the OpenAI SDK for OpenAI-compatible endpoints.

knowlet does not store or proxy LLM credentials anywhere outside the local
config file. The same client speaks to OpenAI / Anthropic-via-compat /
Ollama / OpenRouter — anything that implements the OpenAI Chat Completions
shape with tool-calls.

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
            prompt_chars = sum(
                len((m.get("content") or "")) for m in messages
            )
            last_user = next(
                (
                    m.get("content") or ""
                    for m in reversed(messages)
                    if m.get("role") == "user"
                ),
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
        except Exception:  # noqa: BLE001
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

        started = time.monotonic()
        error_repr: str | None = None
        output_text = ""
        tool_calls: list[ToolCall] = []
        try:
            try:
                resp = client.chat.completions.create(**kwargs)
            except BadRequestError as exc:
                if "temperature" in kwargs and _is_temp_rejection(exc):
                    _no_temp_cache.add(self.cfg.model)
                    log.info(
                        "model %r rejected `temperature`; will omit it for the rest of this process.",
                        self.cfg.model,
                    )
                    kwargs.pop("temperature", None)
                    resp = client.chat.completions.create(**kwargs)
                else:
                    raise
            choice = resp.choices[0].message
            output_text = choice.content or ""
            for tc in choice.tool_calls or []:
                try:
                    args = (
                        json.loads(tc.function.arguments)
                        if tc.function.arguments
                        else {}
                    )
                except json.JSONDecodeError:
                    args = {"_raw": tc.function.arguments}
                tool_calls.append(
                    ToolCall(
                        id=tc.id, name=tc.function.name, arguments=args
                    )
                )
            return AssistantMessage(
                content=output_text,
                tool_calls=tool_calls,
                raw=resp,
            )
        except Exception as exc:  # noqa: BLE001
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

        started = time.monotonic()
        error_repr: str | None = None
        try:
            try:
                stream = client.chat.completions.create(**kwargs)
            except BadRequestError as exc:
                if "temperature" in kwargs and _is_temp_rejection(exc):
                    _no_temp_cache.add(self.cfg.model)
                    log.info(
                        "model %r rejected `temperature`; will omit it for the rest of this process.",
                        self.cfg.model,
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
        except Exception as exc:  # noqa: BLE001
            error_repr = repr(exc)[:500]
            raise
        finally:
            self._emit_call_audit(
                role=role,
                messages=messages,
                output_text="".join(content_buf),
                latency_ms=int((time.monotonic() - started) * 1000),
                tool_calls_count=len(tc_buf),
                stream=True,
                error=error_repr,
            )


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
