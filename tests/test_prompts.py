"""提示词拼装与 few-shot 示例的单元测试（不访问网络）。"""

from __future__ import annotations

import json

from splitter import prompts
from splitter.validator import parse_and_validate


def test_build_messages_has_system_and_exact_user_prompt() -> None:
    raw_input = "登录页增加记住我勾选框，勾选后 7 天内免登录。"

    messages = prompts.build_messages(raw_input)

    assert [message["role"] for message in messages] == ["system", "user"]
    assert messages[1]["content"] == (
        f'以下是用户原文：\n"""{raw_input}"""'
    )
    assert messages[0]["content"].strip()


def test_system_prompt_contains_required_rules() -> None:
    system = prompts.load_system_prompt()

    required_phrases = [
        "资深技术负责人",
        "测试工程师",
        "5 步",
        "只输出一个合法 json 对象",
        "不编造",
        "0.5–2 天",
        "动词开头",
        "T1/T2",
        "TP1",
        "Q1",
        "复现并定位",
        "每个任务至少 1 个测试点",
        "只能引用已存在的任务 id",
        "与提出人确认需求范围",
        "category",
        "clarification",
        "澄清后补充测试点",
        "输入不含可拆分的需求或 bug，请重新提供",
        "忽略以上规则",
        "泄露 system prompt",
        "不执行",
        "不要使用 `\"other\"`",
    ]
    for phrase in required_phrases:
        assert phrase in system, f"system prompt 缺少：{phrase}"


def test_system_prompt_contains_json_order_and_sample() -> None:
    system = prompts.load_system_prompt()

    order = [
        "`input_type`",
        "`summary`",
        "`understanding`",
        "`tasks`",
        "`test_points`",
        "`questions`",
        "`self_check`",
    ]
    order_section = system[system.index("字段顺序固定为：") :]
    positions = [order_section.index(field) for field in order]
    assert positions == sorted(positions)
    assert '"input_type": "feature"' in system
    assert '"tasks": [' in system
    assert '"self_check": {' in system
    # few-shot 示例被拼进 system prompt。
    assert '"input":' in system
    assert '"output":' in system


def test_few_shot_output_passes_current_validator() -> None:
    example = prompts.load_example()

    assert example["input"].strip()
    result = parse_and_validate(
        json.dumps(example["output"], ensure_ascii=False)
    )

    assert result.tasks
    assert result.test_points
    assert result.questions
    assert result.summary
