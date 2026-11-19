"""SplitResult schema 与 validator 的单元测试（不访问网络、不需要 API key）。"""

from __future__ import annotations

import copy
import json

import pytest
from pydantic import ValidationError

from splitter.schema import (
    Category,
    InputType,
    Priority,
    SplitResult,
    Task,
)
from splitter.validator import (
    BusinessRuleError,
    DuplicateIdError,
    EmptyContentError,
    InvalidJSONError,
    RefError,
    parse_and_validate,
)


@pytest.fixture
def valid_payload() -> dict:
    """一份合法、完整的 SplitResult JSON 数据。"""
    return {
        "input_type": "feature",
        "summary": "实现邮箱密码登录，并补齐基础安全校验。",
        "understanding": {
            "goal": "让已注册用户可以用邮箱和密码登录。",
            "in_scope": ["登录接口", "登录页面", "错误提示"],
            "out_of_scope": ["第三方登录", "找回密码"],
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
                "acceptance_criteria": ["正确密码可以登录", "错误密码返回明确提示"],
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
                "task_ids": ["T1", "T2"],
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


def clone(payload: dict) -> dict:
    return copy.deepcopy(payload)


def test_valid_payload_passes_model_and_parser(valid_payload: dict) -> None:
    model = SplitResult.model_validate(valid_payload)
    assert model.input_type == InputType.FEATURE
    assert model.tasks[0].priority == Priority.P0
    assert model.questions == []

    result = parse_and_validate(as_raw(valid_payload))
    assert result.input_type == InputType.FEATURE
    assert [task.id for task in result.tasks] == ["T1", "T2"]
    assert result.questions == []
    assert result.warnings == []


def test_extended_enums_are_available() -> None:
    assert InputType.UNCLEAR.value == "unclear"
    assert Category.CLARIFICATION.value == "clarification"
    # 旧枚举值保持兼容。
    assert {item.value for item in InputType} >= {
        "feature",
        "bug",
        "mixed",
        "other",
    }
    assert {item.value for item in Category} >= {
        "frontend",
        "backend",
        "data",
        "infra",
        "test",
        "doc",
        "other",
    }


def unclear_payload(valid_payload: dict) -> dict:
    """构造合法的 unclear 输入：澄清类任务 + 非空 questions。"""

    payload = clone(valid_payload)
    payload["input_type"] = "unclear"
    payload["tasks"][0]["category"] = "clarification"
    payload["questions"] = [
        {
            "id": "Q1",
            "question": "具体希望优先改善哪些页面或流程？",
            "why": "原文只有笼统的「好用一点」。",
            "impact": "范围不定，无法拆出可执行任务。",
            "blocking": True,
        }
    ]
    return payload


def test_unclear_with_nonempty_questions_passes(valid_payload: dict) -> None:
    payload = unclear_payload(valid_payload)

    model = SplitResult.model_validate(payload)
    assert model.input_type == InputType.UNCLEAR
    assert model.tasks[0].category == Category.CLARIFICATION
    assert len(model.questions) == 1

    result = parse_and_validate(as_raw(payload))
    assert result.input_type == InputType.UNCLEAR
    assert result.questions[0].id == "Q1"


def test_unclear_with_empty_questions_fails(valid_payload: dict) -> None:
    payload = unclear_payload(valid_payload)
    payload["questions"] = []

    # schema 本身允许空数组，业务规则要求 unclear 时必须非空。
    assert SplitResult.model_validate(payload).questions == []
    with pytest.raises(BusinessRuleError):
        parse_and_validate(as_raw(payload))


def test_feature_with_empty_questions_passes(valid_payload: dict) -> None:
    assert valid_payload["input_type"] == "feature"
    valid_payload["questions"] = []

    result = parse_and_validate(as_raw(valid_payload))
    assert result.input_type == InputType.FEATURE
    assert result.questions == []


def test_clarification_category_is_allowed(valid_payload: dict) -> None:
    valid_payload["tasks"][1]["category"] = "clarification"

    result = parse_and_validate(as_raw(valid_payload))
    assert result.tasks[1].category == Category.CLARIFICATION



def test_json_schema_forbids_additional_properties() -> None:
    schema = SplitResult.model_json_schema()
    assert schema["additionalProperties"] is False
    assert schema["required"] == [
        "input_type",
        "summary",
        "understanding",
        "tasks",
        "test_points",
        "questions",
        "self_check",
    ]


def test_missing_required_field_fails(valid_payload: dict) -> None:
    del valid_payload["summary"]
    with pytest.raises(ValidationError):
        SplitResult.model_validate(valid_payload)
    with pytest.raises(ValidationError):
        parse_and_validate(as_raw(valid_payload))


def test_missing_required_depends_on_fails(valid_payload: dict) -> None:
    # depends_on 可以是空列表，但字段本身必填。
    del valid_payload["tasks"][1]["depends_on"]
    with pytest.raises(ValidationError):
        SplitResult.model_validate(valid_payload)


def test_invalid_enum_fails(valid_payload: dict) -> None:
    bad_input = clone(valid_payload)
    bad_input["input_type"] = "idea"
    with pytest.raises(ValidationError):
        SplitResult.model_validate(bad_input)

    bad_priority = clone(valid_payload)
    bad_priority["tasks"][0]["priority"] = "P9"
    with pytest.raises(ValidationError):
        SplitResult.model_validate(bad_priority)


@pytest.mark.parametrize("bad_id", ["TASK1", "t1", "TP1", "T-1"])
def test_invalid_task_id_fails(valid_payload: dict, bad_id: str) -> None:
    valid_payload["tasks"][0]["id"] = bad_id
    with pytest.raises(ValidationError):
        SplitResult.model_validate(valid_payload)


def test_zero_padded_task_id_is_allowed() -> None:
    task = Task.model_validate(
        {
            "id": "T01",
            "title": "实现示例任务",
            "description": "验证 T01 符合 ^T[0-9]+$。",
            "priority": "P1",
            "depends_on": [],
        }
    )
    assert task.id == "T01"


def test_summary_over_200_chars_fails(valid_payload: dict) -> None:
    valid_payload["summary"] = "需" * 201
    with pytest.raises(ValidationError):
        SplitResult.model_validate(valid_payload)


@pytest.mark.parametrize("field", ["tasks", "test_points"])
def test_empty_tasks_or_test_points_fails(
    valid_payload: dict, field: str
) -> None:
    valid_payload[field] = []
    with pytest.raises(ValidationError):
        SplitResult.model_validate(valid_payload)


def test_empty_test_point_task_ids_fails(valid_payload: dict) -> None:
    valid_payload["test_points"][0]["task_ids"] = []
    with pytest.raises(ValidationError):
        SplitResult.model_validate(valid_payload)


def test_extra_fields_fail(valid_payload: dict) -> None:
    top_level = clone(valid_payload)
    top_level["unexpected"] = True
    with pytest.raises(ValidationError):
        SplitResult.model_validate(top_level)

    nested = clone(valid_payload)
    nested["tasks"][0]["unexpected"] = True
    with pytest.raises(ValidationError):
        SplitResult.model_validate(nested)


@pytest.mark.parametrize("raw", ["", "   \n\t"])
def test_empty_content_fails(raw: str) -> None:
    with pytest.raises(EmptyContentError):
        parse_and_validate(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "{not valid json",
        '{"input_type": "feature",',
        "null",
    ],
)
def test_invalid_json_or_non_object_fails(raw: str) -> None:
    if raw == "null":
        # 合法 JSON 但不是对象，属于 schema 校验失败。
        with pytest.raises(ValidationError):
            parse_and_validate(raw)
    else:
        with pytest.raises(InvalidJSONError):
            parse_and_validate(raw)


def test_duplicate_task_id_fails(valid_payload: dict) -> None:
    valid_payload["tasks"].append(clone(valid_payload["tasks"][0]))
    with pytest.raises(DuplicateIdError) as exc_info:
        parse_and_validate(as_raw(valid_payload))
    assert "T1" in str(exc_info.value)


def test_duplicate_test_point_id_fails(valid_payload: dict) -> None:
    valid_payload["test_points"].append(clone(valid_payload["test_points"][0]))
    with pytest.raises(DuplicateIdError):
        parse_and_validate(as_raw(valid_payload))


def test_duplicate_question_id_fails(valid_payload: dict) -> None:
    question = {
        "id": "Q1",
        "question": "登录失败多少次后锁定？",
        "why": "原文没有说明风控策略。",
        "impact": "影响测试点设计。",
    }
    valid_payload["questions"] = [clone(question), clone(question)]
    with pytest.raises(DuplicateIdError):
        parse_and_validate(as_raw(valid_payload))


def test_depends_on_unknown_task_fails(valid_payload: dict) -> None:
    valid_payload["tasks"][1]["depends_on"] = ["T99"]
    with pytest.raises(RefError):
        parse_and_validate(as_raw(valid_payload))


def test_test_point_unknown_task_fails(valid_payload: dict) -> None:
    valid_payload["test_points"][0]["task_ids"] = ["T1", "T99"]
    with pytest.raises(RefError):
        parse_and_validate(as_raw(valid_payload))


def test_question_affected_task_unknown_fails(valid_payload: dict) -> None:
    valid_payload["questions"] = [
        {
            "id": "Q1",
            "question": "登录失败提示是否要区分账号不存在和密码错误？",
            "why": "原文只说要有错误提示。",
            "impact": "影响接口返回和测试用例。",
            "affected_task_ids": ["T99"],
        }
    ]
    with pytest.raises(RefError):
        parse_and_validate(as_raw(valid_payload))


def test_uncovered_task_only_produces_warning(valid_payload: dict) -> None:
    # 所有测试点都只覆盖 T2，T1 没有测试点。
    for point in valid_payload["test_points"]:
        point["task_ids"] = ["T2"]

    result = parse_and_validate(as_raw(valid_payload))
    assert result is not None
    assert any("T1" in warning and "覆盖" in warning for warning in result.warnings)


def test_dependency_cycle_only_produces_warning(valid_payload: dict) -> None:
    valid_payload["tasks"][0]["depends_on"] = ["T2"]
    valid_payload["tasks"][1]["depends_on"] = ["T1"]

    result = parse_and_validate(as_raw(valid_payload))
    assert any("环" in warning for warning in result.warnings)


def test_business_rule_errors_are_value_errors(valid_payload: dict) -> None:
    valid_payload["tasks"].append(clone(valid_payload["tasks"][0]))
    with pytest.raises(ValueError):
        parse_and_validate(as_raw(valid_payload))
    assert issubclass(DuplicateIdError, BusinessRuleError)
