"""llm_client 单元测试：全部 mock，不访问网络，不使用真实 key。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from openai import APIError, APITimeoutError

from splitter import config, llm_client

pytestmark = pytest.mark.usefixtures("isolated_config")

MISSING_KEY_MESSAGE = "未配置 DEEPSEEK_API_KEY，请在 .env 中填写后重试。"
TIMEOUT_MESSAGE = "调用 DeepSeek 接口超时，请稍后重试。"


@pytest.fixture
def fake_openai(monkeypatch: pytest.MonkeyPatch):
    """替换 OpenAI 类，返回 (工厂 mock, 客户端 mock)。"""

    client = MagicMock()
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(llm_client, "OpenAI", factory)
    return factory, client


def make_response(content: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
            )
        ]
    )


def test_chat_without_api_key_raises_before_client_creation(
    monkeypatch: pytest.MonkeyPatch, fake_openai
) -> None:
    factory, _ = fake_openai
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(config.MissingAPIKeyError) as exc_info:
        llm_client.chat([{"role": "user", "content": "测试输入"}])

    assert str(exc_info.value) == MISSING_KEY_MESSAGE
    factory.assert_not_called()


def test_get_api_key_without_key_raises_fixed_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(config.MissingAPIKeyError) as exc_info:
        config.get_api_key()

    assert str(exc_info.value) == MISSING_KEY_MESSAGE


@pytest.mark.parametrize(
    "make_exc",
    [
        lambda: APITimeoutError(request=object()),
        lambda: TimeoutError("timed out"),
    ],
    ids=["APITimeoutError", "TimeoutError"],
)
def test_chat_timeout_raises_fixed_message(
    monkeypatch: pytest.MonkeyPatch, fake_openai, make_exc
) -> None:
    _, client = fake_openai
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-key")
    client.chat.completions.create.side_effect = make_exc()

    with pytest.raises(llm_client.LLMTimeoutError) as exc_info:
        llm_client.chat([{"role": "user", "content": "测试输入"}])

    assert str(exc_info.value) == TIMEOUT_MESSAGE


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

    assert (
        llm_client.chat([{"role": "user", "content": "测试输入"}])
        == expected
    )


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

    assert result == raw_json
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
    assert create_kwargs["max_tokens"] == 4000
    assert create_kwargs["temperature"] == 0.3
    assert create_kwargs["timeout"] == 60


def test_chat_other_api_error_is_wrapped_without_key(
    monkeypatch: pytest.MonkeyPatch, fake_openai
) -> None:
    _, client = fake_openai
    monkeypatch.setenv("DEEPSEEK_API_KEY", "unit-test-key")
    client.chat.completions.create.side_effect = APIError(
        "boom", request=object(), body=None
    )

    with pytest.raises(llm_client.LLMError) as exc_info:
        llm_client.chat([{"role": "user", "content": "测试输入"}])

    message = str(exc_info.value)
    assert message == llm_client.LLM_ERROR_MESSAGE
    assert "unit-test-key" not in message
