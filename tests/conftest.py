"""测试隔离：确保配置只受当前用例 monkeypatch 的环境变量影响。"""

from __future__ import annotations

import importlib

import dotenv
import pytest

from splitter import config

CONFIG_ENV_VARS = (
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "DEEPSEEK_TEMPERATURE",
    "DEEPSEEK_MAX_TOKENS",
    "DEEPSEEK_TIMEOUT",
    "DEEPSEEK_MAX_RETRIES",
    "MAX_INPUT_CHARS",
    "RATE_LIMIT_RETRY_WAIT_SECONDS",
)


@pytest.fixture
def isolated_config(monkeypatch: pytest.MonkeyPatch):
    """清空相关环境变量并禁用真实 ``.env`` 加载，然后重载 config。"""

    for name in CONFIG_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    # reload 时 ``config.py`` 会执行 ``from dotenv import load_dotenv``，
    # 因此这里 patch dotenv 模块本身，避免读到本机真实 ``.env``。
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    return importlib.reload(config)
