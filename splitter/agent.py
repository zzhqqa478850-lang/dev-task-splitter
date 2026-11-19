"""拆分主流程：预处理 → 拼 prompt → 调用 → 校验 → 按失败类型重试。

本模块不打印日志、不读写 ``.env``、不调用 Streamlit；所有对外失败都
通过 :class:`AgentResult` 返回，方便 CLI / UI 各自展示。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from pydantic import ValidationError

from . import config, llm_client, prompts
from .schema import SplitResult
from .validator import SplitterValidationError, parse_and_validate

__all__ = ["AgentResult", "run"]

_PARSE_RETRY_TEMPLATE = (
    "上次输出不合法：{error}。请修正后重新输出完整 JSON。"
)
_MAX_DETAIL_CHARS = 300
_TRUNCATED_DETAIL = "输出被截断（finish_reason=length），JSON 不完整"


@dataclass
class AgentResult:
    """一次 ``run`` 的结构化结果；失败时不抛异常。"""

    ok: bool
    result: SplitResult | None = None
    error: str | None = None
    raw_output: str | None = None
    details: str | None = None
    warnings: list[str] = field(default_factory=list)
    attempts: int = 0
    retried: bool = False


def run(raw_text: str) -> AgentResult:
    """拆分用户原文，返回结构化结果。

    ``attempts`` 是实际调用 ``llm_client.chat`` 的次数；预处理失败（空
    输入、超长、缺 key）不会产生调用，因此为 0。
    """

    text = (raw_text or "").strip()
    if not text:
        return _failure(config.MSG_EMPTY_INPUT, attempts=0)

    settings = config.get_settings()
    length = len(text)
    if length > settings.max_input_chars:
        return _failure(
            config.MSG_INPUT_TOO_LONG.format(n=length), attempts=0
        )

    # 必须在任何 chat / OpenAI 调用之前检查，缺失时 attempts 保持 0。
    try:
        config.get_api_key()
    except config.MissingAPIKeyError:
        return _failure(config.MSG_MISSING_API_KEY, attempts=0)

    messages = prompts.build_messages(text)
    max_retries = max(0, settings.max_retries)
    attempts = 0

    while True:
        attempts += 1
        try:
            raw = llm_client.chat(messages)
        except config.MissingAPIKeyError:
            # 预检之后 key 被移除的极端情况；不再重试。
            return _failure(config.MSG_MISSING_API_KEY, attempts=attempts)
        except llm_client.LLMAuthError:
            return _failure(config.MSG_AUTH, attempts=attempts)
        except llm_client.LLMTimeoutError as exc:
            if _can_retry(attempts, max_retries):
                continue
            return _failure(
                config.MSG_TIMEOUT,
                attempts=attempts,
                details=_short_error(exc),
            )
        except llm_client.LLMRateLimitError as exc:
            if _can_retry(attempts, max_retries):
                time.sleep(settings.rate_limit_retry_wait_seconds)
                continue
            return _failure(
                config.MSG_RATE_LIMIT,
                attempts=attempts,
                details=_short_error(exc),
            )
        except llm_client.LLMUnavailableError as exc:
            if _can_retry(attempts, max_retries):
                continue
            return _failure(
                config.MSG_UNAVAILABLE,
                attempts=attempts,
                details=_short_error(exc),
            )
        except llm_client.LLMParseError as exc:
            # 响应结构异常，没有可用的原始文本；按解析失败处理。
            details = _short_error(exc)
            if _can_retry(attempts, max_retries):
                messages = _append_parse_retry(messages, "", details)
                continue
            return _failure(
                config.MSG_PARSE_FAILED,
                attempts=attempts,
                raw_output="",
                details=details,
            )
        except llm_client.LLMError as exc:
            # 未细分的接口错误按服务不可用处理，保留一次重试。
            if _can_retry(attempts, max_retries):
                continue
            return _failure(
                config.MSG_UNAVAILABLE,
                attempts=attempts,
                details=_short_error(exc),
            )

        # 新接口返回 ChatResult；为兼容仍返回普通 str 的调用方/mock，
        # 非 ChatResult 一律按“未截断的原文”处理。
        if isinstance(raw, llm_client.ChatResult):
            finish_reason = raw.finish_reason
            raw = raw.content
        else:
            finish_reason = None

        if not isinstance(raw, str):
            raw = "" if raw is None else str(raw)

        # 即使 content 看起来像完整 JSON，finish_reason=length 也视为截断
        # 并走现有 JSON 失败重试路径。
        if finish_reason == "length":
            details = _TRUNCATED_DETAIL
            if _can_retry(attempts, max_retries):
                messages = _append_parse_retry(messages, raw, details)
                continue
            return _failure(
                config.MSG_PARSE_FAILED,
                attempts=attempts,
                raw_output=raw,
                details=details,
            )

        try:
            result = parse_and_validate(raw)
        except (ValidationError, SplitterValidationError, ValueError, TypeError) as exc:
            details = _short_error(exc)
            if _can_retry(attempts, max_retries):
                messages = _append_parse_retry(messages, raw, details)
                continue
            return _failure(
                config.MSG_PARSE_FAILED,
                attempts=attempts,
                raw_output=raw,
                details=details,
            )

        return AgentResult(
            ok=True,
            result=result,
            raw_output=raw,
            warnings=result.warnings,
            attempts=attempts,
            retried=attempts > 1,
        )


def _failure(
    error: str,
    *,
    attempts: int,
    raw_output: str | None = None,
    details: str | None = None,
) -> AgentResult:
    return AgentResult(
        ok=False,
        result=None,
        error=error,
        raw_output=raw_output,
        details=details,
        warnings=[],
        attempts=attempts,
        retried=attempts > 1,
    )


def _can_retry(attempts: int, max_retries: int) -> bool:
    """已进行 ``attempts`` 次调用后，是否还允许再试一次。"""

    return attempts <= max_retries


def _append_parse_retry(
    messages: list[dict[str, str]], raw: str, error: str
) -> list[dict[str, str]]:
    """追加 assistant 原始输出和纠错 user 消息，返回新的 messages。"""

    return [
        *messages,
        {"role": "assistant", "content": raw},
        {
            "role": "user",
            "content": _PARSE_RETRY_TEMPLATE.format(error=error),
        },
    ]


def _short_error(exc: BaseException) -> str:
    """把校验/接口异常压缩成适合回传模型的一段短文本。"""

    if isinstance(exc, ValidationError):
        parts: list[str] = []
        for error in exc.errors()[:3]:
            location = ".".join(str(item) for item in error.get("loc", ()))
            message = str(error.get("msg", "")).strip()
            parts.append(f"{location}: {message}" if location else message)
        text = "；".join(part for part in parts if part)
    else:
        text = str(exc).strip()

    text = " ".join(text.split())
    if len(text) > _MAX_DETAIL_CHARS:
        text = f"{text[:_MAX_DETAIL_CHARS]}…"
    return text or exc.__class__.__name__
