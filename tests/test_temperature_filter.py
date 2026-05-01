"""Verify that newer Claude 4.x models don't get a `temperature` kwarg."""

from unittest import mock

from knowlet.config import LLMConfig
from knowlet.core.llm import LLMClient, model_disallows_temperature


def test_known_no_temp_models():
    assert model_disallows_temperature("claude-opus-4-7")
    assert model_disallows_temperature("claude-opus-4-6")
    assert model_disallows_temperature("claude-sonnet-4-6")
    assert model_disallows_temperature("claude-haiku-4-5-20251001")
    # case-insensitive + tolerates suffixes
    assert model_disallows_temperature("CLAUDE-OPUS-4-7")
    assert model_disallows_temperature("claude-opus-4-7@my-proxy")


def test_older_models_still_accept_temperature():
    assert not model_disallows_temperature("gpt-4o-mini")
    assert not model_disallows_temperature("claude-3-7-sonnet-20250219")
    assert not model_disallows_temperature("claude-sonnet-4-20250514")
    assert not model_disallows_temperature("claude-opus-4-20250514")
    assert not model_disallows_temperature("")


def test_chat_omits_temperature_for_opus_4_7():
    cfg = LLMConfig(api_key="stub", model="claude-opus-4-7", temperature=0.3)
    client = LLMClient(cfg)
    fake_resp = mock.Mock()
    fake_resp.choices = [mock.Mock(message=mock.Mock(content="ok", tool_calls=None))]
    fake_client = mock.Mock()
    fake_client.chat.completions.create.return_value = fake_resp
    client._client = fake_client  # bypass real OpenAI() init

    client.chat([{"role": "user", "content": "hi"}], temperature=0.5)
    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert "temperature" not in kwargs
    assert kwargs["model"] == "claude-opus-4-7"


def test_chat_includes_temperature_for_older_model():
    cfg = LLMConfig(api_key="stub", model="gpt-4o-mini", temperature=0.3)
    client = LLMClient(cfg)
    fake_resp = mock.Mock()
    fake_resp.choices = [mock.Mock(message=mock.Mock(content="ok", tool_calls=None))]
    fake_client = mock.Mock()
    fake_client.chat.completions.create.return_value = fake_resp
    client._client = fake_client

    client.chat([{"role": "user", "content": "hi"}])
    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert kwargs["temperature"] == 0.3
