"""应用配置与产品文案。

约定：

- 模块导入时调用一次 ``load_dotenv()``；已存在的环境变量优先，不会被
  ``.env`` 覆盖。
- 数值配置既以模块常量暴露（便于直接读取默认值），也可通过
  :func:`get_settings` 在调用时重新读取环境变量。
- 产品文案统一放在本模块，UI 不硬编码，便于测试精确比对。
- API key 不保存在 :class:`Settings` 中，也不参与日志或序列化；只在
  真正调用接口前通过 :func:`get_api_key` 获取，且绝不回显。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

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
    "MSG_AUTH",
    "MSG_EMPTY_INPUT",
    "MSG_INPUT_TOO_LONG",
    "MSG_MISSING_API_KEY",
    "MSG_NO_QUESTIONS",
    "MSG_PARSE_FAILED",
    "MSG_RATE_LIMIT",
    "MSG_TIMEOUT",
    "MSG_UNAVAILABLE",
    "MSG_UNCLEAR_HINT",
    "MissingAPIKeyError",
    "PRIORITY_LABELS",
    "PRIORITY_MAP",
    "PRIORITY_TEXT",
    "RATE_LIMIT_RETRY_WAIT_SECONDS",
    "Settings",
    "get_api_key",
    "get_settings",
]

load_dotenv()

# 产品文案：测试会逐字比对，修改时必须同步更新测试与文档。
MSG_EMPTY_INPUT = "请先粘贴需求或 bug 描述。"
MSG_INPUT_TOO_LONG = "当前 {n} 字，超过 3000 字上限，请删减后再试。"
MSG_MISSING_API_KEY = (
    "未配置 DeepSeek API Key，请在 .env 或 Streamlit secrets 中设置 "
    "DEEPSEEK_API_KEY。"
)
MSG_TIMEOUT = "请求超时（已重试 1 次），请稍后再试。"
MSG_UNAVAILABLE = "服务暂时不可用（已重试 1 次），请稍后再试。"
MSG_AUTH = "API Key 无效或无权限，请检查配置。"
MSG_PARSE_FAILED = "结果格式异常，请重试。"
MSG_RATE_LIMIT = "请求太频繁（已重试 1 次），请稍后再试。"
MSG_UNCLEAR_HINT = "描述不够清楚，建议先确认下面的问题。"
MSG_NO_QUESTIONS = "暂无需要澄清的问题。"

# 向后兼容的旧名称。
MISSING_API_KEY_MESSAGE = MSG_MISSING_API_KEY

# 优先级展示文案。
PRIORITY_LABELS = {"P0": "高", "P1": "中", "P2": "低"}
PRIORITY_MAP = PRIORITY_LABELS
PRIORITY_TEXT = PRIORITY_LABELS

# 硬编码默认值；下面同名模块常量会在导入时被环境变量覆盖。
_DEFAULT_BASE_URL = "https://api.deepseek.com"
_DEFAULT_MODEL = "deepseek-chat"
_DEFAULT_TEMPERATURE = 0.3
# DeepSeek 官方输出上限为 384K（393216）tokens；8000 远低于上限。
_DEFAULT_MAX_TOKENS = 8000
_DEFAULT_TIMEOUT = 60.0
_DEFAULT_MAX_RETRIES = 1
_DEFAULT_MAX_INPUT_CHARS = 3000
_DEFAULT_RATE_LIMIT_RETRY_WAIT_SECONDS = 2.0


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
    rate_limit_retry_wait_seconds: float = (
        _DEFAULT_RATE_LIMIT_RETRY_WAIT_SECONDS
    )


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
RATE_LIMIT_RETRY_WAIT_SECONDS = _env_float(
    "RATE_LIMIT_RETRY_WAIT_SECONDS",
    _DEFAULT_RATE_LIMIT_RETRY_WAIT_SECONDS,
)


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
        rate_limit_retry_wait_seconds=_env_float(
            "RATE_LIMIT_RETRY_WAIT_SECONDS",
            RATE_LIMIT_RETRY_WAIT_SECONDS,
        ),
    )


def _get_streamlit_secret(name: str) -> str | None:
    """从 ``streamlit.secrets`` 读取配置；不可用或不存在时返回 ``None``。

    Streamlit 在非运行上下文、缺少 secrets 文件或格式错误时会抛出多种
    异常，这里统一吞掉，确保不会因此泄露内容或影响环境变量读取。
    """

    try:
        import streamlit as st
    except Exception:
        return None

    try:
        secrets: Any = st.secrets
    except Exception:
        return None

    value: Any = None
    try:
        value = secrets[name]
    except Exception:
        try:
            value = secrets.get(name)
        except Exception:
            return None

    if value is None:
        return None
    text = str(value).strip()
    return text or None


def get_api_key() -> str:
    """返回去除首尾空白后的 API key；缺失或空白时抛异常。

    读取顺序：环境变量（含模块导入时加载的 ``.env``）→
    ``streamlit.secrets``。异常信息是固定中文文案，不包含任何 key 内容。
    """

    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        api_key = _get_streamlit_secret("DEEPSEEK_API_KEY") or ""
    if not api_key:
        raise MissingAPIKeyError(MSG_MISSING_API_KEY)
    return api_key
