"""DeepSeek / OpenAI 兼容接口的最小封装。

只负责一次 ``chat`` 调用：JSON 模式、超时与错误转换。重试、提示词
拼装和结果校验都不在本模块内。
"""

from __future__ import annotations

from typing import Any

from openai import APIError, APITimeoutError, OpenAI

from . import config

__all__ = [
    "LLM_ERROR_MESSAGE",
    "LLM_TIMEOUT_MESSAGE",
    "LLMError",
    "LLMTimeoutError",
    "chat",
]

LLM_TIMEOUT_MESSAGE = "调用 DeepSeek 接口超时，请稍后重试。"
LLM_ERROR_MESSAGE = "调用 DeepSeek 接口失败，请稍后重试。"


class LLMError(RuntimeError):
    """调用 DeepSeek 接口失败。异常信息不包含 key 或请求头。"""


class LLMTimeoutError(LLMError):
    """调用 DeepSeek 接口超时。"""


def chat(messages: list[dict[str, str]]) -> str:
    """调用一次 chat completion，返回模型文本内容。

    - ``content`` 为 ``None`` 或空字符串时返回 ``""``，由上层当作失败
      处理并重试。
    - 超时转换为 :class:`LLMTimeoutError`，其他 API 错误转换为
      :class:`LLMError`。
    - 缺少 API key 时由 :func:`config.get_api_key` 抛出
      :class:`config.MissingAPIKeyError`，此时不会创建真实请求。
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
    except (APITimeoutError, TimeoutError) as exc:
        raise LLMTimeoutError(LLM_TIMEOUT_MESSAGE) from exc
    except APIError as exc:
        raise LLMError(LLM_ERROR_MESSAGE) from exc

    try:
        content: Any = response.choices[0].message.content
    except (AttributeError, IndexError, TypeError) as exc:
        raise LLMError("调用 DeepSeek 接口返回格式异常，请稍后重试。") from exc

    if not content:
        return ""
    return content if isinstance(content, str) else str(content)
