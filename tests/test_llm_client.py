"""llm_client 单元测试：全部 mock，不访问网络，不使用真实 key。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx2
import pytest
from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    InternalServerError,
    PermissionDeniedError,
    RateLimitError,
)

from splitter import config, llm_client

pytestmark = pytest.mark.usefixtures("isolated_config")


@pytest.fixture
def fake_openai(monkeypatch: pytest.MonkeyPatch):
    """替换 OpenAI 类，返回 (工厂 mock, 客户端 mock)。"""

    client = MagicMock()
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(llm_client, "OpenAI", factory)
    return factory, client


def make_response(
    content: str | None, finish_reason: str | None = "stop"
) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
        ]
    )


def make_status_error(exc_type, status_code: int):
    request = httpx2.Request(
        "POST", "https://api.deepseek.com/chat/completions"
    )
    response = httpx2.Response(status_code, request=request)
    return exc_type(f"HTTP {status_code}", response=response, body=None)


def test_chat_without_api_key_raises_before_client_creation(
    monkeypatch: pytest.MonkeyPatch, fake_openai
) -> None:
    factory, client = fake_openai
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(config.MissingAPIKeyError) as exc_info:
        llm_client.chat([{"role": "user", "content": "测试输入"}])

    assert str(exc_info.value) == config.MSG_MISSING_API_KEY
    assert factory.call_count == 0
    assert client.chat.completions.create.call_count == 0


def test_get_api_key_without_key_raises_fixed_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(config.MissingAPIKeyError) as exc_info:
        config.get_api_key()

    assert str(exc_info.value) == config.MSG_MISSING_API_KEY


@pytest.mark.parametrize(
    "make_exc",
    [
        lambda: APITimeoutError(request=object()),
        lambda: TimeoutError("timed out"),
    ],
    ids=["APITimeoutError", "TimeoutError"],
)
def test_chat_timeout_raises_timeout_error(
    monkeypatch: pytest.MonkeyPatch, fake_openai, make_exc
) -> None:
    _, client = fake_openai
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-key")
    client.chat.completions.create.side_effect = make_exc()

    with pytest.raises(llm_client.LLMTimeoutError) as exc_info:
        llm_client.chat([{"role": "user", "content": "测试输入"}])

    assert str(exc_info.value) == config.MSG_TIMEOUT


@pytest.mark.parametrize(
    "status_code, exc_type",
    [
        (401, AuthenticationError),
        (403, PermissionDeniedError),
    ],
)
def test_chat_auth_errors(
    monkeypatch: pytest.MonkeyPatch,
    fake_openai,
    status_code: int,
    exc_type,
) -> None:
    _, client = fake_openai
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-key")
    client.chat.completions.create.side_effect = make_status_error(
        exc_type, status_code
    )

    with pytest.raises(llm_client.LLMAuthError) as exc_info:
        llm_client.chat([{"role": "user", "content": "测试输入"}])

    assert str(exc_info.value) == config.MSG_AUTH
    assert "unit-test-key" not in str(exc_info.value)


def test_chat_rate_limit_error(
    monkeypatch: pytest.MonkeyPatch, fake_openai
) -> None:
    _, client = fake_openai
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-key")
    client.chat.completions.create.side_effect = make_status_error(
        RateLimitError, 429
    )

    with pytest.raises(llm_client.LLMRateLimitError) as exc_info:
        llm_client.chat([{"role": "user", "content": "测试输入"}])

    assert str(exc_info.value) == config.MSG_RATE_LIMIT


@pytest.mark.parametrize("status_code", [500, 502, 503])
def test_chat_server_errors_are_unavailable(
    monkeypatch: pytest.MonkeyPatch, fake_openai, status_code: int
) -> None:
    _, client = fake_openai
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-key")
    client.chat.completions.create.side_effect = make_status_error(
        InternalServerError, status_code
    )

    with pytest.raises(llm_client.LLMUnavailableError) as exc_info:
        llm_client.chat([{"role": "user", "content": "测试输入"}])

    assert str(exc_info.value) == config.MSG_UNAVAILABLE


@pytest.mark.parametrize(
    "make_exc",
    [
        lambda: APIConnectionError(request=object()),
        lambda: ConnectionError("connection refused"),
    ],
    ids=["APIConnectionError", "ConnectionError"],
)
def test_chat_network_errors_are_unavailable(
    monkeypatch: pytest.MonkeyPatch, fake_openai, make_exc
) -> None:
    _, client = fake_openai
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-key")
    client.chat.completions.create.side_effect = make_exc()

    with pytest.raises(llm_client.LLMUnavailableError) as exc_info:
        llm_client.chat([{"role": "user", "content": "测试输入"}])

    assert str(exc_info.value) == config.MSG_UNAVAILABLE


@pytest.mark.parametrize(
    "content, expected",
    [
        (None, ""),
        ("", ""),
    ],
    ids=["none", "empty-string"],
)
def test_chat_returns_empty_string_for_empty_content(
    monkeypatch: pytest.MonkeyPatch, fake_openai, content, expected
) -> None:
    _, client = fake_openai
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-key")
    client.chat.completions.create.return_value = make_response(content)

    result = llm_client.chat([{"role": "user", "content": "测试输入"}])

    assert isinstance(result, llm_client.ChatResult)
    assert result.content == expected
    assert result.finish_reason == "stop"


def test_chat_success_returns_content_and_passes_expected_params(
    monkeypatch: pytest.MonkeyPatch, fake_openai
) -> None:
    factory, client = fake_openai
    api_key_getter = MagicMock(return_value="unit-test-key")
    monkeypatch.setattr(config, "get_api_key", api_key_getter)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-key")

    raw_json = '{"summary": "测试输出", "tasks": []}'
    client.chat.completions.create.return_value = make_response(raw_json)
    messages = [{"role": "user", "content": "测试输入"}]

    result = llm_client.chat(messages)

    assert isinstance(result, llm_client.ChatResult)
    assert result.content == raw_json
    assert result.finish_reason == "stop"
    api_key_getter.assert_called_once_with()

    factory.assert_called_once()
    client_kwargs = factory.call_args.kwargs
    assert client_kwargs["base_url"] == "https://api.deepseek.com"
    assert client_kwargs["api_key"]  # 只确认传了 key，不输出其内容

    client.chat.completions.create.assert_called_once()
    create_kwargs = client.chat.completions.create.call_args.kwargs
    assert create_kwargs["model"] == "deepseek-chat"
    assert create_kwargs["messages"] == messages
    assert create_kwargs["response_format"] == {"type": "json_object"}
    assert create_kwargs["max_tokens"] == 8000
    assert create_kwargs["temperature"] == 0.3
    assert create_kwargs["timeout"] == 60


def test_chat_returns_finish_reason_length_for_truncated_output(
    monkeypatch: pytest.MonkeyPatch, fake_openai
) -> None:
    _, client = fake_openai
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-key")

    truncated_json = '{"summary": "被截断的输出", "tasks": ['
    client.chat.completions.create.return_value = make_response(
        truncated_json, finish_reason="length"
    )

    result = llm_client.chat([{"role": "user", "content": "测试输入"}])

    assert isinstance(result, llm_client.ChatResult)
    assert result.content == truncated_json
    assert result.finish_reason == "length"


def test_chat_missing_finish_reason_is_none(
    monkeypatch: pytest.MonkeyPatch, fake_openai
) -> None:
    _, client = fake_openai
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-key")
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))]
    )

    result = llm_client.chat([{"role": "user", "content": "测试输入"}])

    assert result.content == "{}"
    assert result.finish_reason is None


def test_chat_other_api_error_is_wrapped_without_key(
    monkeypatch: pytest.MonkeyPatch, fake_openai
) -> None:
    _, client = fake_openai
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-key")
    client.chat.completions.create.side_effect = APIError(
        "boom unit-test-key", request=object(), body=None
    )

    with pytest.raises(llm_client.LLMError) as exc_info:
        llm_client.chat([{"role": "user", "content": "测试输入"}])

    message = str(exc_info.value)
    assert message == llm_client.LLM_ERROR_MESSAGE
    assert "unit-test-key" not in message


def test_chat_malformed_response_raises_parse_error(
    monkeypatch: pytest.MonkeyPatch, fake_openai
) -> None:
    _, client = fake_openai
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-key")
    client.chat.completions.create.return_value = SimpleNamespace(choices=[])

    with pytest.raises(llm_client.LLMParseError) as exc_info:
        llm_client.chat([{"role": "user", "content": "测试输入"}])

    assert str(exc_info.value) == config.MSG_PARSE_FAILED
