"""DeepSeek / OpenAI 兼容接口的最小封装。

只负责一次 ``chat`` 调用：JSON 模式、超时与错误分类。重试、提示词
拼装和结果校验都不在本模块内。
"""

from __future__ import annotations

from typing import Any

from openai import (
    APIConnectionError,
    APIError,
    APIStatusError,
    APITimeoutError,
    OpenAI,
)

from . import config

__all__ = [
    "LLM_AUTH_MESSAGE",
    "LLM_ERROR_MESSAGE",
    "LLM_PARSE_FAILED_MESSAGE",
    "LLM_RATE_LIMIT_MESSAGE",
    "LLM_TIMEOUT_MESSAGE",
    "LLM_UNAVAILABLE_MESSAGE",
    "LLMAuthError",
    "LLMError",
    "LLMParseError",
    "LLMRateLimitError",
    "LLMTimeoutError",
    "LLMUnavailableError",
    "chat",
]

# 文案统一来自 config，避免 UI 与本模块各写一份。
LLM_TIMEOUT_MESSAGE = config.MSG_TIMEOUT
LLM_UNAVAILABLE_MESSAGE = config.MSG_UNAVAILABLE
LLM_AUTH_MESSAGE = config.MSG_AUTH
LLM_PARSE_FAILED_MESSAGE = config.MSG_PARSE_FAILED
LLM_RATE_LIMIT_MESSAGE = config.MSG_RATE_LIMIT

# 兼容旧名称。
LLM_ERROR_MESSAGE = LLM_UNAVAILABLE_MESSAGE


class LLMError(RuntimeError):
    """调用 DeepSeek 接口失败。异常信息不包含 key 或请求头。"""


class LLMTimeoutError(LLMError):
    """调用 DeepSeek 接口超时。"""


class LLMAuthError(LLMError):
    """API key 无效或没有权限（401/403）。"""


class LLMRateLimitError(LLMError):
    """请求被限流（429）。"""


class LLMUnavailableError(LLMError):
    """网络错误、连接失败或服务端 5xx。"""


class LLMParseError(LLMError):
    """接口返回结构异常，无法取出文本内容。"""


def _load_http_exceptions() -> tuple[
    tuple[type[BaseException], ...], tuple[type[BaseException], ...]
]:
    """返回 (超时异常, 网络异常) 元组，兼容 httpx / httpx2。"""

    try:
        import httpx2 as httpx
    except ImportError:  # pragma: no cover - 取决于 openai 依赖版本
        try:
            import httpx  # type: ignore[no-redef]
        except ImportError:  # pragma: no cover
            return (), ()

    return (httpx.TimeoutException,), (httpx.NetworkError,)


_HTTP_TIMEOUT_ERRORS, _HTTP_NETWORK_ERRORS = _load_http_exceptions()
_TIMEOUT_ERRORS = (APITimeoutError, TimeoutError) + _HTTP_TIMEOUT_ERRORS
_NETWORK_ERRORS = (
    APIConnectionError,
    ConnectionError,
    OSError,
) + _HTTP_NETWORK_ERRORS


def _status_code(exc: Exception) -> int | None:
    """尽力从异常中取出 HTTP 状态码，失败返回 ``None``。"""

    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


def chat(messages: list[dict[str, str]]) -> str:
    """调用一次 chat completion，返回模型文本内容。

    - 缺少 API key 时由 :func:`config.get_api_key` 抛出
      :class:`config.MissingAPIKeyError`；该检查发生在创建 client 之前，
      因此不会产生任何请求。
    - ``content`` 为 ``None`` 或空字符串时返回 ``""``，由上层当作失败
      处理并重试。
    - 超时、401/403、429、网络错误/5xx 分别转换为对应的异常类型；
      异常信息固定，不包含 key 或请求头。
    """

    settings = config.get_settings()
    # 必须在创建 client / 发请求之前检查，缺失时直接抛异常。
    api_key = config.get_api_key()

    try:
        client = OpenAI(api_key=api_key, base_url=settings.base_url)
        response = client.chat.completions.create(
            model=settings.model,
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=settings.max_tokens,
            temperature=settings.temperature,
            timeout=settings.timeout,
        )
    except _TIMEOUT_ERRORS:
        raise LLMTimeoutError(config.MSG_TIMEOUT) from None
    except APIStatusError as exc:
        status = _status_code(exc)
        if status in (401, 403):
            raise LLMAuthError(config.MSG_AUTH) from None
        if status == 429:
            raise LLMRateLimitError(config.MSG_RATE_LIMIT) from None
        if status is not None and 500 <= status <= 599:
            raise LLMUnavailableError(config.MSG_UNAVAILABLE) from None
        raise LLMError(config.MSG_UNAVAILABLE) from None
    except _NETWORK_ERRORS:
        raise LLMUnavailableError(config.MSG_UNAVAILABLE) from None
    except APIError as exc:
        # 兜底：部分 SDK/测试桩只抛 APIError，但仍带 status_code。
        status = _status_code(exc)
        if status in (401, 403):
            raise LLMAuthError(config.MSG_AUTH) from None
        if status == 429:
            raise LLMRateLimitError(config.MSG_RATE_LIMIT) from None
        if status is not None and status >= 500:
            raise LLMUnavailableError(config.MSG_UNAVAILABLE) from None
        raise LLMError(config.MSG_UNAVAILABLE) from None

    try:
        content: Any = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError, KeyError):
        raise LLMParseError(config.MSG_PARSE_FAILED) from None

    if not content:
        return ""
    return content if isinstance(content, str) else str(content)
