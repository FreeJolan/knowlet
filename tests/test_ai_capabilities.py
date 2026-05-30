from types import SimpleNamespace
from typing import Any

from knowlet.core.ai.capabilities import probe_capabilities
from knowlet.core.events import ReplyChunkEvent, ReplyDoneEvent
from knowlet.core.llm import AssistantMessage, ResponsesMessage, ToolCall


class FakeCapabilityLLM:
    cfg = SimpleNamespace(
        base_url="http://example.test/v1",
        api_key="fake-key",
        model="fake-gpt",
    )

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        role: str | None = None,
    ) -> AssistantMessage:
        if tools:
            return AssistantMessage(
                content="",
                tool_calls=[
                    ToolCall(id="call_1", name="search_notes", arguments={"query": "ping"})
                ],
            )
        return AssistantMessage(content="pong")

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        role: str | None = None,
    ):
        yield ReplyChunkEvent(text="ok")
        yield ReplyDoneEvent(final_text="ok")

    def responses(
        self,
        input_text: str,
        *,
        tools: list[dict[str, Any]] | None = None,
        max_output_tokens: int | None = None,
        role: str | None = None,
    ) -> ResponsesMessage:
        if tools:
            return ResponsesMessage(
                content="https://github.com/openai/codex",
                raw={"output": [{"type": "web_search_call"}, {"type": "message"}]},
            )
        return ResponsesMessage(content="ok", raw={"output": [{"type": "message"}]})


class FailingCapabilityLLM(FakeCapabilityLLM):
    cfg = SimpleNamespace(
        base_url="http://example.test/v1",
        api_key="fake-key",
        model="fake-gpt",
    )

    def chat(self, *args: Any, **kwargs: Any) -> AssistantMessage:
        raise AssertionError("capability profile should have been served from cache")


def test_probe_capabilities_builds_runtime_profile() -> None:
    profile = probe_capabilities(
        FakeCapabilityLLM(),  # type: ignore[arg-type]
        include_hosted_web_search=True,
        use_cache=False,
    )

    assert profile.model == "fake-gpt"
    assert profile.supported == {
        "responses_chat": True,
        "responses_streaming": True,
        "responses_tools": True,
        "responses_api": True,
        "hosted_web_search": True,
    }
    web = next(check for check in profile.checks if check.name == "hosted_web_search")
    assert "web_search" in web.detail


def test_probe_capabilities_caches_by_endpoint_and_model() -> None:
    first = probe_capabilities(
        FakeCapabilityLLM(),  # type: ignore[arg-type]
        include_hosted_web_search=True,
    )
    second = probe_capabilities(
        FailingCapabilityLLM(),  # type: ignore[arg-type]
        include_hosted_web_search=True,
    )

    assert second is first
