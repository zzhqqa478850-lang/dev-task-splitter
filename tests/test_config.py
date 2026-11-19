"""配置模块测试：不依赖真实 ``.env``，也不需要真实 API key。"""

from __future__ import annotations

import pytest

from splitter import config

pytestmark = pytest.mark.usefixtures("isolated_config")

MISSING_KEY_MESSAGE = "未配置 DEEPSEEK_API_KEY，请在 .env 中填写后重试。"


def test_default_config_values() -> None:
    """默认配置与架构文档一致。"""

    assert config.DEEPSEEK_BASE_URL == "https://api.deepseek.com"
    assert config.DEEPSEEK_MODEL == "deepseek-chat"
    assert config.DEEPSEEK_TEMPERATURE == 0.3
    assert config.DEEPSEEK_MAX_TOKENS == 4000
    assert config.DEEPSEEK_TIMEOUT == 60
    assert config.DEEPSEEK_MAX_RETRIES == 2
    assert config.MAX_INPUT_CHARS == 3000

    settings = config.get_settings()
    assert settings.base_url == "https://api.deepseek.com"
    assert settings.model == "deepseek-chat"
    assert settings.temperature == 0.3
    assert settings.max_tokens == 4000
    assert settings.timeout == 60
    assert settings.max_retries == 2
    assert settings.max_input_chars == 3000


def test_environment_overrides_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """环境变量可以覆盖默认值。"""

    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "unit-test-model")
    monkeypatch.setenv("DEEPSEEK_TEMPERATURE", "0.7")
    monkeypatch.setenv("DEEPSEEK_MAX_TOKENS", "1234")
    monkeypatch.setenv("DEEPSEEK_TIMEOUT", "12.5")
    monkeypatch.setenv("DEEPSEEK_MAX_RETRIES", "4")
    monkeypatch.setenv("MAX_INPUT_CHARS", "500")

    settings = config.get_settings()
    assert settings.base_url == "https://example.test/v1"
    assert settings.model == "unit-test-model"
    assert settings.temperature == 0.7
    assert settings.max_tokens == 1234
    assert settings.timeout == 12.5
    assert settings.max_retries == 4
    assert settings.max_input_chars == 500


def test_get_api_key_missing_raises_fixed_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(config.MissingAPIKeyError) as exc_info:
        config.get_api_key()

    assert str(exc_info.value) == MISSING_KEY_MESSAGE


def test_get_api_key_whitespace_raises_fixed_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "   \t ")

    with pytest.raises(config.MissingAPIKeyError) as exc_info:
        config.get_api_key()

    assert str(exc_info.value) == MISSING_KEY_MESSAGE


def test_get_api_key_returns_stripped_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "  unit-test-key  ")

    assert config.get_api_key() == "unit-test-key"
