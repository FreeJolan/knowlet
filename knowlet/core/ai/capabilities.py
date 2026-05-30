"""Runtime AI capability probing.

The useful unit is not "provider" or even "model" by itself. The behavior
knowlet can rely on is the combination of base URL, account/API key, model,
and API surface exposed by the endpoint wrapper.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from knowlet.core.events import ReplyChunkEvent, ReplyDoneEvent
from knowlet.core.llm import LLMClient, response_has_output_type
from knowlet.core.tools._registry import default_registry

_CACHE_TTL_SECONDS = 300
_CACHE: dict[tuple[str, str, str, bool], tuple[float, CapabilityProfile]] = {}


@dataclass
class CapabilityCheck:
    name: str
    ok: bool
    detail: str
    latency_ms: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CapabilityProfile:
    model: str
    checks: list[CapabilityCheck] = field(default_factory=list)

    @property
    def supported(self) -> dict[str, bool]:
        return {check.name: check.ok for check in self.checks}

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "checks": [check.to_dict() for check in self.checks],
            "supported": self.supported,
        }


def _timed(name: str, fn: Any) -> CapabilityCheck:
    started = time.monotonic()
    try:
        detail = fn()
        return CapabilityCheck(
            name=name,
            ok=True,
            detail=str(detail),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
    except Exception as exc:
        return CapabilityCheck(
            name=name,
            ok=False,
            detail=f"{type(exc).__name__}: {exc}",
            latency_ms=int((time.monotonic() - started) * 1000),
            error=repr(exc)[:500],
        )


def probe_capabilities(
    llm: LLMClient,
    *,
    include_hosted_web_search: bool = False,
    use_cache: bool = True,
) -> CapabilityProfile:
    """Probe the current endpoint and return a concrete capability profile."""
    cache_key = _cache_key(llm, include_hosted_web_search=include_hosted_web_search)
    if use_cache:
        cached = _CACHE.get(cache_key)
        if cached is not None:
            created_at, profile = cached
            if time.monotonic() - created_at <= _CACHE_TTL_SECONDS:
                return profile

    checks: list[CapabilityCheck] = [
        _timed("responses_chat", lambda: _probe_chat(llm)),
        _timed("responses_streaming", lambda: _probe_stream(llm)),
        _timed("responses_tools", lambda: _probe_chat_tools(llm)),
        _timed("responses_api", lambda: _probe_responses(llm)),
    ]
    if include_hosted_web_search:
        checks.append(
            _timed(
                "hosted_web_search",
                lambda: _probe_hosted_web_search(llm),
            )
        )
    profile = CapabilityProfile(model=llm.cfg.model, checks=checks)
    if use_cache:
        _CACHE[cache_key] = (time.monotonic(), profile)
    return profile


def _cache_key(
    llm: LLMClient,
    *,
    include_hosted_web_search: bool,
) -> tuple[str, str, str, bool]:
    key_hash = hashlib.sha256((llm.cfg.api_key or "").encode("utf-8")).hexdigest()[:16]
    return (
        (llm.cfg.base_url or "").rstrip("/"),
        key_hash,
        llm.cfg.model,
        include_hosted_web_search,
    )


def _probe_chat(llm: LLMClient) -> str:
    resp = llm.chat(
        [{"role": "user", "content": "Reply with exactly: pong"}],
        max_tokens=8,
        temperature=0,
        role="capability_probe",
    )
    content = (resp.content or "").strip()
    if "pong" not in content.lower():
        raise RuntimeError(f"unexpected reply {content!r}")
    return f"got {content!r}"


def _probe_stream(llm: LLMClient) -> str:
    events = list(
        llm.chat_stream(
            [{"role": "user", "content": "Reply with exactly: ok"}],
            max_tokens=8,
            temperature=0,
            role="capability_probe",
        )
    )
    text = "".join(ev.text for ev in events if isinstance(ev, ReplyChunkEvent))
    done = next((ev for ev in events if isinstance(ev, ReplyDoneEvent)), None)
    final = (done.final_text if done else text).strip()
    if "ok" not in final.lower():
        raise RuntimeError(f"unexpected streamed reply {final!r}")
    return f"got {final!r}"


def _probe_chat_tools(llm: LLMClient) -> str:
    registry = default_registry()
    resp = llm.chat(
        [
            {
                "role": "user",
                "content": (
                    "Call the search_notes tool with query='ping' and limit=1. "
                    "Do not answer in prose."
                ),
            }
        ],
        tools=registry.openai_schema(),
        max_tokens=128,
        temperature=0,
        role="capability_probe",
    )
    if not resp.tool_calls:
        raise RuntimeError("no tool_calls in response")
    names = ", ".join(tc.name for tc in resp.tool_calls)
    return f"{len(resp.tool_calls)} call(s): {names}"


def _probe_responses(llm: LLMClient) -> str:
    resp = llm.responses(
        "Reply with exactly: ok",
        max_output_tokens=16,
        role="capability_probe",
    )
    content = (resp.content or "").strip()
    if "ok" not in content.lower():
        raise RuntimeError(f"unexpected Responses reply {content!r}")
    return f"got {content!r}"


def _probe_hosted_web_search(llm: LLMClient) -> str:
    last_error: Exception | None = None
    candidates: list[list[dict[str, Any]]] = [
        [{"type": "web_search", "external_web_access": True}],
        [{"type": "web_search"}],
        [{"type": "web_search_preview"}],
    ]
    for tools in candidates:
        try:
            resp = llm.responses(
                "Find the official OpenAI Codex GitHub repository URL. Reply with only the URL.",
                tools=tools,
                max_output_tokens=80,
                role="capability_probe",
            )
            if response_has_output_type(resp.raw, "web_search_call"):
                preview = (resp.content or "").strip()[:120]
                return f"{tools[0]['type']} call observed; reply={preview!r}"
            raise RuntimeError("Responses succeeded but no web_search_call was observed")
        except Exception as exc:
            last_error = exc
    assert last_error is not None
    raise last_error
