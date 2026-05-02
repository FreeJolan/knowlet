"""Verify the catch-once-cache behavior for `temperature`-rejecting models.

Some newer providers (Anthropic Claude 4.x, etc.) reject the `temperature`
request param. Rather than maintain a curated substring list of model ids
(which ages with every release), the LLMClient learns from a single 400 and
caches the model id so it omits `temperature` on subsequent calls.
"""

from unittest import mock

from openai import BadRequestError

from knowlet.config import LLMConfig
from knowlet.core.llm import LLMClient, _no_temp_cache


def _temp_rejection() -> BadRequestError:
    return BadRequestError(
        message="temperature is deprecated for this model",
        response=mock.Mock(status_code=400, request=mock.Mock()),
        body=None,
    )


def _ok_response(content: str = "ok"):
    resp = mock.Mock()
    resp.choices = [mock.Mock(message=mock.Mock(content=content, tool_calls=None))]
    return resp


def setup_function():
    _no_temp_cache.clear()


def test_temperature_sent_on_first_call_for_unknown_model():
    cfg = LLMConfig(api_key="stub", model="gpt-4o-mini", temperature=0.3)
    client = LLMClient(cfg)
    fake_client = mock.Mock()
    fake_client.chat.completions.create.return_value = _ok_response()
    client._client = fake_client

    client.chat([{"role": "user", "content": "hi"}])
    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert kwargs["temperature"] == 0.3


def test_temperature_rejection_is_cached_and_retried_transparently():
    cfg = LLMConfig(api_key="stub", model="claude-opus-4-7", temperature=0.3)
    client = LLMClient(cfg)
    fake_client = mock.Mock()
    fake_client.chat.completions.create.side_effect = [
        _temp_rejection(),       # first attempt: rejected
        _ok_response("hello"),   # retry without temperature: succeeds
    ]
    client._client = fake_client

    msg = client.chat([{"role": "user", "content": "hi"}])
    assert msg.content == "hello"
    assert fake_client.chat.completions.create.call_count == 2
    # First call had temperature; retry did not.
    first_call = fake_client.chat.completions.create.call_args_list[0].kwargs
    second_call = fake_client.chat.completions.create.call_args_list[1].kwargs
    assert first_call["temperature"] == 0.3
    assert "temperature" not in second_call
    # Cache now holds this model.
    assert "claude-opus-4-7" in _no_temp_cache


def test_subsequent_call_skips_temperature_for_cached_model():
    cfg = LLMConfig(api_key="stub", model="claude-opus-4-7", temperature=0.3)
    client = LLMClient(cfg)
    _no_temp_cache.add("claude-opus-4-7")
    fake_client = mock.Mock()
    fake_client.chat.completions.create.return_value = _ok_response()
    client._client = fake_client

    client.chat([{"role": "user", "content": "hi"}])
    assert fake_client.chat.completions.create.call_count == 1
    kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert "temperature" not in kwargs


def test_default_config_temperature_is_none():
    """The default config must not force a temperature on Claude users.

    Setting temperature in cfg means *every* fresh process pays a 400 + retry
    before populating the cache; setting it to None lets the caller opt in.
    """
    cfg = LLMConfig(api_key="stub", model="claude-opus-4-7")
    assert cfg.temperature is None


def test_non_temperature_400_propagates():
    cfg = LLMConfig(api_key="stub", model="gpt-4o-mini", temperature=0.3)
    client = LLMClient(cfg)
    fake_client = mock.Mock()
    fake_client.chat.completions.create.side_effect = BadRequestError(
        message="some other validation error",
        response=mock.Mock(status_code=400, request=mock.Mock()),
        body=None,
    )
    client._client = fake_client

    try:
        client.chat([{"role": "user", "content": "hi"}])
    except BadRequestError:
        pass
    else:
        raise AssertionError("expected BadRequestError to propagate")
    # Did not retry; did not poison the cache.
    assert fake_client.chat.completions.create.call_count == 1
    assert "gpt-4o-mini" not in _no_temp_cache
