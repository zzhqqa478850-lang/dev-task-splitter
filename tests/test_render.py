"""render 模块单元测试：固定 SplitResult，不访问网络、不启动浏览器。"""

from __future__ import annotations

import copy

import pytest

from splitter import config
from splitter.render import render_markdown, to_markdown
from splitter.schema import SplitResult


@pytest.fixture
def payload() -> dict:
    """一份覆盖三种优先级、空问题列表的完整结果。"""

    return {
        "input_type": "feature",
        "summary": "实现优惠码兑换，并补齐失败场景。",
        "understanding": {
            "goal": "让用户可以在结算页使用优惠码。",
            "in_scope": ["兑换接口", "结算页展示"],
            "out_of_scope": ["优惠码叠加"],
            "assumptions": ["优惠码数据已存在"],
        },
        "tasks": [
            {
                "id": "T1",
                "title": "实现兑换接口",
                "description": "校验优惠码并返回抵扣金额。",
                "priority": "P0",
                "category": "backend",
                "estimate": "M",
                "depends_on": [],
                "acceptance_criteria": ["成功时返回折扣金额"],
            },
            {
                "id": "T2",
                "title": "实现结算页展示",
                "description": "在 Order Summary 展示 Discount 行。",
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
                "scenario": "有效优惠码兑换",
                "steps": ["输入优惠码", "点击 Apply"],
                "expected_result": "展示折扣金额",
                "priority": "P0",
            },
            {
                "id": "TP2",
                "task_ids": ["T2"],
                "type": "edge_case",
                "scenario": "优惠码已使用",
                "expected_result": "提示优惠码已使用",
                "priority": "P2",
            },
        ],
        "questions": [],
        "self_check": {
            "coverage_ok": True,
            "issues": [],
            "confidence": "high",
        },
    }


def test_markdown_uses_chinese_priority_labels(payload: dict) -> None:
    markdown = to_markdown(SplitResult.model_validate(payload))

    assert "## 任务" in markdown
    assert "## 测试点" in markdown
    assert "## 问题" in markdown
    assert "## 自检" in markdown
    assert "优先级：高" in markdown
    assert "优先级：中" in markdown
    assert "优先级：低" in markdown


def test_empty_questions_uses_fixed_copy(payload: dict) -> None:
    markdown = render_markdown(SplitResult.model_validate(payload))

    assert config.MSG_NO_QUESTIONS in markdown


def test_unclear_hint_is_at_the_beginning(payload: dict) -> None:
    unclear_payload = copy.deepcopy(payload)
    unclear_payload["input_type"] = "unclear"
    unclear_payload["questions"] = [
        {
            "id": "Q1",
            "question": "具体要优化哪个页面？",
            "why": "原文没有说明页面。",
            "impact": "无法确定范围。",
            "affected_task_ids": ["T1"],
            "blocking": True,
            "suggested_default": "先按结算页处理。",
        }
    ]

    markdown = to_markdown(SplitResult.model_validate(unclear_payload))

    assert markdown.startswith(config.MSG_UNCLEAR_HINT)
    assert markdown.index(config.MSG_UNCLEAR_HINT) < markdown.index("## 任务")
    assert "具体要优化哪个页面？" in markdown


def test_render_markdown_is_alias(payload: dict) -> None:
    result = SplitResult.model_validate(payload)

    assert render_markdown is to_markdown
    assert render_markdown(result) == to_markdown(result)


def test_estimate_is_not_rendered(payload: dict) -> None:
    markdown = to_markdown(SplitResult.model_validate(payload))

    assert "估算" not in markdown
    assert "estimate" not in markdown
