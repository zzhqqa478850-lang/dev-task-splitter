"""agent 主流程单元测试：全部 mock，不访问网络，不使用真实 key。"""

from __future__ import annotations

import copy
import json
from unittest.mock import MagicMock

import pytest

from splitter import agent, config, llm_client

pytestmark = pytest.mark.usefixtures("isolated_config")


def make_payload() -> dict:
    """一份能通过当前 schema / validator 的完整结果。"""

    return {
        "input_type": "feature",
        "summary": "实现邮箱密码登录，并补齐基础安全校验。",
        "understanding": {
            "goal": "让已注册用户可以用邮箱和密码登录。",
            "in_scope": ["登录接口", "登录页面"],
            "out_of_scope": ["第三方登录"],
            "assumptions": ["用户体系已经存在"],
        },
        "tasks": [
            {
                "id": "T1",
                "title": "实现登录接口",
                "description": "提供邮箱密码校验并返回会话凭证。",
                "priority": "P0",
                "category": "backend",
                "estimate": "M",
                "depends_on": [],
                "acceptance_criteria": ["正确密码可以登录"],
            },
            {
                "id": "T2",
                "title": "实现登录页面",
                "description": "提供邮箱、密码输入框与提交交互。",
                "priority": "P1",
                "category": "frontend",
                "estimate": "S",
                "depends_on": ["T1"],
            },
        ],
        "test_points": [
            {
                "id": "TP1",
                "task_ids": ["T1"],
                "type": "functional",
                "scenario": "已注册用户使用正确邮箱和密码登录",
                "steps": ["打开登录页", "输入正确凭证并提交"],
                "expected_result": "登录成功并进入首页",
                "priority": "P0",
            },
            {
                "id": "TP2",
                "task_ids": ["T2"],
                "type": "edge_case",
                "scenario": "邮箱或密码为空时提交",
                "expected_result": "页面提示必填项，不发起请求",
            },
        ],
        "questions": [],
        "self_check": {
            "coverage_ok": True,
            "issues": [],
            "confidence": "high",
        },
    }


def as_raw(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def invalid_pydantic_raw() -> str:
    payload = make_payload()
    payload["tasks"] = []
    return as_raw(payload)


def unclear_empty_questions_raw() -> str:
    payload = make_payload()
    payload["input_type"] = "unclear"
    payload["questions"] = []
    return as_raw(payload)


@pytest.fixture
def mock_chat(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    chat = MagicMock()
    monkeypatch.setattr(agent.llm_client, "chat", chat)
    return chat


@pytest.fixture
def key_ok(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    getter = MagicMock(return_value="unit-test-key")
    monkeypatch.setattr(agent.config, "get_api_key", getter)
    return getter


@pytest.mark.parametrize("raw_text", ["", "   ", "\n\t  \r\n"])
def test_empty_or_whitespace_input_does_not_call_api(
    raw_text: str, mock_chat: MagicMock, key_ok: MagicMock
) -> None:
    result = agent.run(raw_text)

    assert result.ok is False
    assert result.result is None
    assert result.error == config.MSG_EMPTY_INPUT
    assert result.attempts == 0
    assert result.retried is False
    assert mock_chat.call_count == 0
    key_ok.assert_not_called()


def test_too_long_input_is_rejected_without_call(
    mock_chat: MagicMock, key_ok: MagicMock
) -> None:
    raw_text = "需" * 3001

    result = agent.run(raw_text)

    assert result.ok is False
    assert result.error == config.MSG_INPUT_TOO_LONG.format(n=3001)
    assert result.error == "当前 3001 字，超过 3000 字上限，请删减后再试。"
    assert result.attempts == 0
    assert result.retried is False
    assert mock_chat.call_count == 0
    key_ok.assert_not_called()


def test_exactly_3000_chars_is_allowed(
    mock_chat: MagicMock, key_ok: MagicMock
) -> None:
    raw_text = "需" * 3000
    mock_chat.return_value = as_raw(make_payload())

    result = agent.run(raw_text)

    assert result.ok is True
    assert result.attempts == 1
    assert result.retried is False
    assert result.warnings == []
    assert mock_chat.call_count == 1
    messages = mock_chat.call_args.args[0]
    assert messages[-1]["content"] == (
        f'以下是用户原文：\n"""{raw_text}"""'
    )


def test_missing_api_key_does_not_call_chat(
    monkeypatch: pytest.MonkeyPatch, mock_chat: MagicMock
) -> None:
    getter = MagicMock(
        side_effect=config.MissingAPIKeyError(config.MSG_MISSING_API_KEY)
    )
    monkeypatch.setattr(agent.config, "get_api_key", getter)

    result = agent.run("给登录页加记住我")

    assert result.ok is False
    assert result.error == config.MSG_MISSING_API_KEY
    assert result.attempts == 0
    assert result.retried is False
    assert mock_chat.call_count == 0
    getter.assert_called_once_with()


def test_timeout_retries_once_then_succeeds(
    mock_chat: MagicMock, key_ok: MagicMock
) -> None:
    mock_chat.side_effect = [
        llm_client.LLMTimeoutError(config.MSG_TIMEOUT),
        as_raw(make_payload()),
    ]

    result = agent.run("给登录页加记住我")

    assert result.ok is True
    assert result.attempts == 2
    assert result.retried is True
    assert result.error is None
    assert mock_chat.call_count == 2


def test_timeout_twice_returns_timeout_error(
    mock_chat: MagicMock, key_ok: MagicMock
) -> None:
    mock_chat.side_effect = [
        llm_client.LLMTimeoutError(config.MSG_TIMEOUT),
        llm_client.LLMTimeoutError(config.MSG_TIMEOUT),
    ]

    result = agent.run("给登录页加记住我")

    assert result.ok is False
    assert result.result is None
    assert result.error == config.MSG_TIMEOUT
    assert result.attempts == 2
    assert result.retried is True
    assert mock_chat.call_count == 2


def test_unavailable_retries_once_then_succeeds(
    mock_chat: MagicMock, key_ok: MagicMock
) -> None:
    mock_chat.side_effect = [
        llm_client.LLMUnavailableError(config.MSG_UNAVAILABLE),
        as_raw(make_payload()),
    ]

    result = agent.run("给登录页加记住我")

    assert result.ok is True
    assert result.attempts == 2
    assert result.retried is True
    assert mock_chat.call_count == 2


def test_unavailable_twice_returns_unavailable_error(
    mock_chat: MagicMock, key_ok: MagicMock
) -> None:
    mock_chat.side_effect = [
        llm_client.LLMUnavailableError(config.MSG_UNAVAILABLE),
        llm_client.LLMUnavailableError(config.MSG_UNAVAILABLE),
    ]

    result = agent.run("给登录页加记住我")

    assert result.ok is False
    assert result.error == config.MSG_UNAVAILABLE
    assert result.attempts == 2
    assert result.retried is True
    assert mock_chat.call_count == 2


@pytest.mark.parametrize("status_code", [401, 403])
def test_auth_errors_are_not_retried(
    status_code: int,
    mock_chat: MagicMock,
    key_ok: MagicMock,
) -> None:
    mock_chat.side_effect = llm_client.LLMAuthError(config.MSG_AUTH)

    result = agent.run("给登录页加记住我")

    assert result.ok is False
    assert result.error == config.MSG_AUTH
    assert result.attempts == 1
    assert result.retried is False
    assert mock_chat.call_count == 1


def test_rate_limit_sleeps_two_seconds_then_retries(
    monkeypatch: pytest.MonkeyPatch, mock_chat: MagicMock, key_ok: MagicMock
) -> None:
    sleep = MagicMock()
    monkeypatch.setattr(agent.time, "sleep", sleep)
    mock_chat.side_effect = [
        llm_client.LLMRateLimitError(config.MSG_RATE_LIMIT),
        as_raw(make_payload()),
    ]

    result = agent.run("给登录页加记住我")

    assert result.ok is True
    assert result.attempts == 2
    assert result.retried is True
    sleep.assert_called_once_with(2)
    assert mock_chat.call_count == 2


def test_rate_limit_twice_returns_rate_limit_error(
    monkeypatch: pytest.MonkeyPatch, mock_chat: MagicMock, key_ok: MagicMock
) -> None:
    sleep = MagicMock()
    monkeypatch.setattr(agent.time, "sleep", sleep)
    mock_chat.side_effect = [
        llm_client.LLMRateLimitError(config.MSG_RATE_LIMIT),
        llm_client.LLMRateLimitError(config.MSG_RATE_LIMIT),
    ]

    result = agent.run("给登录页加记住我")

    assert result.ok is False
    assert result.error == config.MSG_RATE_LIMIT
    assert result.error == "请求太频繁（已重试 1 次），请稍后再试。"
    assert result.attempts == 2
    assert result.retried is True
    sleep.assert_called_once_with(2)
    assert mock_chat.call_count == 2


@pytest.mark.parametrize(
    "bad_raw",
    [
        "{not valid json",
        "",
        invalid_pydantic_raw(),
        unclear_empty_questions_raw(),
    ],
    ids=["invalid-json", "empty-content", "pydantic", "unclear-empty"],
)
def test_parse_failures_retry_with_error_and_then_fail(
    bad_raw: str,
    mock_chat: MagicMock,
    key_ok: MagicMock,
) -> None:
    mock_chat.side_effect = [bad_raw, bad_raw]

    result = agent.run("给登录页加记住我")

    assert result.ok is False
    assert result.error == config.MSG_PARSE_FAILED
    assert result.raw_output == bad_raw
    assert result.attempts == 2
    assert result.retried is True
    assert result.details
    assert mock_chat.call_count == 2

    first_messages = mock_chat.call_args_list[0].args[0]
    second_messages = mock_chat.call_args_list[1].args[0]
    assert second_messages[: len(first_messages)] == first_messages
    assert second_messages[-2] == {
        "role": "assistant",
        "content": bad_raw,
    }
    retry_prompt = second_messages[-1]
    assert retry_prompt["role"] == "user"
    assert retry_prompt["content"].startswith("上次输出不合法：")
    assert retry_prompt["content"].endswith(
        "。请修正后重新输出完整 JSON。"
    )
    assert result.details in retry_prompt["content"]


def test_parse_failure_retries_once_then_succeeds(
    mock_chat: MagicMock, key_ok: MagicMock
) -> None:
    good_raw = as_raw(make_payload())
    mock_chat.side_effect = ["{not valid json", good_raw]

    result = agent.run("给登录页加记住我")

    assert result.ok is True
    assert result.attempts == 2
    assert result.retried is True
    assert result.raw_output == good_raw
    assert mock_chat.call_count == 2

    retry_messages = mock_chat.call_args_list[1].args[0]
    assert retry_messages[-2] == {
        "role": "assistant",
        "content": "{not valid json",
    }
    assert "JSON" in retry_messages[-1]["content"]


def test_soft_warning_succeeds_without_retry(
    mock_chat: MagicMock, key_ok: MagicMock
) -> None:
    payload = copy.deepcopy(make_payload())
    # 只保留覆盖 T1 的测试点，T2 未被覆盖只会产生 warning。
    payload["test_points"] = payload["test_points"][:1]
    mock_chat.return_value = as_raw(payload)

    result = agent.run("给登录页加记住我")

    assert result.ok is True
    assert result.attempts == 1
    assert result.retried is False
    assert mock_chat.call_count == 1
    assert any("T2" in warning and "覆盖" in warning for warning in result.warnings)
