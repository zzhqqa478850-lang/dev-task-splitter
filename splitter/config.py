"""应用配置：从 ``.env`` / 环境变量读取 DeepSeek 相关参数。

约定：

- 模块导入时调用一次 ``load_dotenv()``；已存在的环境变量优先，不会被
  ``.env`` 覆盖。
- 配置值既以模块常量暴露（便于直接读取默认值），也可通过
  :func:`get_settings` 在调用时重新读取环境变量。
- API key 不保存在 :class:`Settings` 中，也不参与日志或序列化；只在
  真正调用接口前通过 :func:`get_api_key` 获取。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

__all__ = [
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MAX_RETRIES",
    "DEEPSEEK_MAX_TOKENS",
    "DEEPSEEK_MODEL",
    "DEEPSEEK_TEMPERATURE",
    "DEEPSEEK_TIMEOUT",
    "MAX_INPUT_CHARS",
    "MISSING_API_KEY_MESSAGE",
    "MissingAPIKeyError",
    "Settings",
    "get_api_key",
    "get_settings",
]

load_dotenv()

MISSING_API_KEY_MESSAGE = "未配置 DEEPSEEK_API_KEY，请在 .env 中填写后重试。"

# 硬编码默认值；下面同名模块常量会在导入时被环境变量覆盖。
_DEFAULT_BASE_URL = "https://api.deepseek.com"
_DEFAULT_MODEL = "deepseek-chat"
_DEFAULT_TEMPERATURE = 0.3
_DEFAULT_MAX_TOKENS = 4000
_DEFAULT_TIMEOUT = 60.0
_DEFAULT_MAX_RETRIES = 2
_DEFAULT_MAX_INPUT_CHARS = 3000


class MissingAPIKeyError(RuntimeError):
    """缺少可用的 DeepSeek API key。"""


def _env_str(name: str, default: str) -> str:
    """读取非空字符串环境变量；空值或未设置时返回默认值。"""
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _env_float(name: str, default: float) -> float:
    """读取浮点环境变量；空值或未设置时返回默认值。"""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是数字") from exc


def _env_int(name: str, default: int) -> int:
    """读取整数环境变量；空值或未设置时返回默认值。"""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是整数") from exc


@dataclass(frozen=True)
class Settings:
    """一次调用所需的非敏感配置。"""

    base_url: str
    model: str
    temperature: float
    max_tokens: int
    timeout: float
    max_retries: int
    max_input_chars: int


# 导入时的配置快照：便于代码/测试直接读取当前环境下的模块级配置。
DEEPSEEK_BASE_URL = _env_str("DEEPSEEK_BASE_URL", _DEFAULT_BASE_URL)
DEEPSEEK_MODEL = _env_str("DEEPSEEK_MODEL", _DEFAULT_MODEL)
DEEPSEEK_TEMPERATURE = _env_float(
    "DEEPSEEK_TEMPERATURE", _DEFAULT_TEMPERATURE
)
DEEPSEEK_MAX_TOKENS = _env_int("DEEPSEEK_MAX_TOKENS", _DEFAULT_MAX_TOKENS)
DEEPSEEK_TIMEOUT = _env_float("DEEPSEEK_TIMEOUT", _DEFAULT_TIMEOUT)
DEEPSEEK_MAX_RETRIES = _env_int("DEEPSEEK_MAX_RETRIES", _DEFAULT_MAX_RETRIES)
MAX_INPUT_CHARS = _env_int("MAX_INPUT_CHARS", _DEFAULT_MAX_INPUT_CHARS)


def get_settings() -> Settings:
    """读取当前环境变量并返回配置。

    未设置的环境变量回退到导入时的模块常量，因此测试可以安全地
    monkeypatch 环境变量。
    """

    return Settings(
        base_url=_env_str("DEEPSEEK_BASE_URL", DEEPSEEK_BASE_URL),
        model=_env_str("DEEPSEEK_MODEL", DEEPSEEK_MODEL),
        temperature=_env_float(
            "DEEPSEEK_TEMPERATURE", DEEPSEEK_TEMPERATURE
        ),
        max_tokens=_env_int("DEEPSEEK_MAX_TOKENS", DEEPSEEK_MAX_TOKENS),
        timeout=_env_float("DEEPSEEK_TIMEOUT", DEEPSEEK_TIMEOUT),
        max_retries=_env_int("DEEPSEEK_MAX_RETRIES", DEEPSEEK_MAX_RETRIES),
        max_input_chars=_env_int("MAX_INPUT_CHARS", MAX_INPUT_CHARS),
    )


def get_api_key() -> str:
    """返回去除首尾空白后的 API key；缺失或空白时抛异常。

    异常信息是固定中文文案，不包含任何 key 内容。
    """

    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise MissingAPIKeyError(MISSING_API_KEY_MESSAGE)
    return api_key
