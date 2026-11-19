"""配置模块测试：不依赖真实 ``.env``，也不需要真实 API key。"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from splitter import config

pytestmark = pytest.mark.usefixtures("isolated_config")


def test_default_config_values() -> None:
    """默认配置与架构文档一致。"""

    assert config.DEEPSEEK_BASE_URL == "https://api.deepseek.com"
    assert config.DEEPSEEK_MODEL == "deepseek-chat"
    assert config.DEEPSEEK_TEMPERATURE == 0.3
    assert config.DEEPSEEK_MAX_TOKENS == 4000
    assert config.DEEPSEEK_TIMEOUT == 60
    assert config.DEEPSEEK_MAX_RETRIES == 1
    assert config.MAX_INPUT_CHARS == 3000
    assert config.RATE_LIMIT_RETRY_WAIT_SECONDS == 2

    settings = config.get_settings()
    assert settings.base_url == "https://api.deepseek.com"
    assert settings.model == "deepseek-chat"
    assert settings.temperature == 0.3
    assert settings.max_tokens == 4000
    assert settings.timeout == 60
    assert settings.max_retries == 1
    assert settings.max_input_chars == 3000
    assert settings.rate_limit_retry_wait_seconds == 2


def test_environment_overrides_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """环境变量可以覆盖默认值。"""

    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "unit-test-model")
    monkeypatch.setenv("DEEPSEEK_TEMPERATURE", "0.7")
    monkeypatch.setenv("DEEPSEEK_MAX_TOKENS", "1234")
    monkeypatch.setenv("DEEPSEEK_TIMEOUT", "12.5")
    monkeypatch.setenv("DEEPSEEK_MAX_RETRIES", "4")
    monkeypatch.setenv("MAX_INPUT_CHARS", "500")
    monkeypatch.setenv("RATE_LIMIT_RETRY_WAIT_SECONDS", "0.01")

    settings = config.get_settings()
    assert settings.base_url == "https://example.test/v1"
    assert settings.model == "unit-test-model"
    assert settings.temperature == 0.7
    assert settings.max_tokens == 1234
    assert settings.timeout == 12.5
    assert settings.max_retries == 4
    assert settings.max_input_chars == 500
    assert settings.rate_limit_retry_wait_seconds == 0.01


def test_product_messages_are_exact() -> None:
    """产品文案逐字比对，避免 UI 与测试各写一份。"""

    assert config.MSG_EMPTY_INPUT == "请先粘贴需求或 bug 描述。"
    assert (
        config.MSG_INPUT_TOO_LONG
        == "当前 {n} 字，超过 3000 字上限，请删减后再试。"
    )
    assert config.MSG_INPUT_TOO_LONG.format(n=3001) == (
        "当前 3001 字，超过 3000 字上限，请删减后再试。"
    )
    assert config.MSG_MISSING_API_KEY == (
        "未配置 DeepSeek API Key，请在 .env 或 Streamlit secrets 中设置 "
        "DEEPSEEK_API_KEY。"
    )
    assert config.MSG_TIMEOUT == "请求超时（已重试 1 次），请稍后再试。"
    assert (
        config.MSG_UNAVAILABLE
        == "服务暂时不可用（已重试 1 次），请稍后再试。"
    )
    assert config.MSG_AUTH == "API Key 无效或无权限，请检查配置。"
    assert config.MSG_PARSE_FAILED == "结果格式异常，请重试。"
    assert config.MSG_RATE_LIMIT == (
        "请求太频繁（已重试 1 次），请稍后再试。"
    )
    assert (
        config.MSG_UNCLEAR_HINT
        == "描述不够清楚，建议先确认下面的问题。"
    )
    assert config.MSG_NO_QUESTIONS == "暂无需要澄清的问题。"


def test_priority_labels_are_exact() -> None:
    expected = {"P0": "高", "P1": "中", "P2": "低"}
    assert config.PRIORITY_LABELS == expected
    assert config.PRIORITY_MAP == expected
    assert config.PRIORITY_TEXT == expected


def test_get_api_key_missing_raises_fixed_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(config.MissingAPIKeyError) as exc_info:
        config.get_api_key()

    assert str(exc_info.value) == config.MSG_MISSING_API_KEY
    assert str(exc_info.value) == (
        "未配置 DeepSeek API Key，请在 .env 或 Streamlit secrets 中设置 "
        "DEEPSEEK_API_KEY。"
    )


def test_get_api_key_whitespace_raises_fixed_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "   \t ")

    with pytest.raises(config.MissingAPIKeyError) as exc_info:
        config.get_api_key()

    assert str(exc_info.value) == config.MSG_MISSING_API_KEY


def test_get_api_key_returns_stripped_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "  unit-test-key  ")

    assert config.get_api_key() == "unit-test-key"


def test_get_api_key_falls_back_to_streamlit_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    fake_streamlit = SimpleNamespace(
        secrets={"DEEPSEEK_API_KEY": "  streamlit-test-key  "}
    )
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)

    assert config.get_api_key() == "streamlit-test-key"


def test_get_api_key_environment_takes_precedence_over_streamlit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-test-key")
    fake_streamlit = SimpleNamespace(
        secrets={"DEEPSEEK_API_KEY": "streamlit-test-key"}
    )
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)

    assert config.get_api_key() == "env-test-key"
