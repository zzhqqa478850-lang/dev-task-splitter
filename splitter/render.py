"""把 :class:`~splitter.schema.SplitResult` 渲染为 Markdown。

本模块只依赖 ``schema`` 与 ``config``，不调用模型、不依赖 Streamlit，
因此既能用于页面下载，也能在测试或命令行里复用。

产品约定：

- 优先级对外只展示中文的 高 / 中 / 低，映射来自 ``config.PRIORITY_MAP``；
- ``questions`` 为空时展示固定文案；
- ``input_type`` 为 ``unclear`` 时，把提示放在 Markdown 最前面；
- 工时估算不是 v1 功能，因此不渲染 ``estimate``。
"""

from __future__ import annotations

from . import config
from .schema import (
    Category,
    Confidence,
    InputType,
    Priority,
    SplitResult,
    TestType,
)

__all__ = [
    "CATEGORY_LABELS",
    "CONFIDENCE_LABELS",
    "INPUT_TYPE_LABELS",
    "TEST_TYPE_LABELS",
    "category_label",
    "confidence_label",
    "input_type_label",
    "priority_label",
    "render_markdown",
    "test_type_label",
    "to_markdown",
]

INPUT_TYPE_LABELS = {
    InputType.FEATURE: "需求",
    InputType.BUG: "缺陷",
    InputType.MIXED: "需求 + 缺陷",
    InputType.UNCLEAR: "描述不清楚",
    InputType.OTHER: "其他",
}

CATEGORY_LABELS = {
    Category.FRONTEND: "前端",
    Category.BACKEND: "后端",
    Category.DATA: "数据",
    Category.INFRA: "基础设施",
    Category.TEST: "测试",
    Category.DOC: "文档",
    Category.CLARIFICATION: "澄清需求",
    Category.OTHER: "其他",
}

TEST_TYPE_LABELS = {
    TestType.FUNCTIONAL: "功能",
    TestType.EDGE_CASE: "边界",
    TestType.ERROR_HANDLING: "错误处理",
    TestType.REGRESSION: "回归",
    TestType.PERFORMANCE: "性能",
    TestType.SECURITY: "安全",
    TestType.UX: "体验",
}

CONFIDENCE_LABELS = {
    Confidence.HIGH: "高",
    Confidence.MEDIUM: "中",
    Confidence.LOW: "低",
}


def _value(item: object) -> str:
    """取出枚举/字符串的原始值，便于做映射查找。"""

    value = getattr(item, "value", item)
    return str(value)


def priority_label(priority: Priority | str | None) -> str:
    """返回优先级的中文展示文案（高 / 中 / 低）。"""

    if priority is None:
        return "未标注"
    value = _value(priority)
    return config.PRIORITY_MAP.get(value, value)


def input_type_label(input_type: InputType | str | None) -> str:
    """返回输入类型的中文展示文案。"""

    if input_type is None:
        return "未知"
    value = _value(input_type)
    for item, label in INPUT_TYPE_LABELS.items():
        if item.value == value:
            return label
    return value


def category_label(category: Category | str | None) -> str:
    """返回任务分类的中文展示文案。"""

    if category is None:
        return "未分类"
    value = _value(category)
    for item, label in CATEGORY_LABELS.items():
        if item.value == value:
            return label
    return value


def test_type_label(test_type: TestType | str | None) -> str:
    """返回测试点类型的中文展示文案。"""

    if test_type is None:
        return "未标注"
    value = _value(test_type)
    for item, label in TEST_TYPE_LABELS.items():
        if item.value == value:
            return label
    return value


def confidence_label(confidence: Confidence | str | None) -> str:
    """返回自检置信度的中文展示文案。"""

    if confidence is None:
        return "未知"
    value = _value(confidence)
    for item, label in CONFIDENCE_LABELS.items():
        if item.value == value:
            return label
    return value


def _bullets(items: list[str], empty: str = "无") -> str:
    """把字符串列表渲染成 Markdown 列表；为空时返回占位文本。"""

    if not items:
        return empty
    return "\n".join(f"- {item}" for item in items)


def _numbered(items: list[str], empty: str = "无") -> str:
    """把步骤列表渲染成有序列表；为空时返回占位文本。"""

    if not items:
        return empty
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, 1))


def _format_ids(ids: list[str] | None) -> str:
    """把 id 列表渲染成 ``T1、T2``；为空时返回「无」。"""

    if not ids:
        return "无"
    return "、".join(ids)


def _render_understanding(result: SplitResult) -> list[str]:
    understanding = result.understanding
    return [
        "## 需求理解",
        "",
        f"**目标**：{understanding.goal}",
        "",
        "**范围内**",
        "",
        _bullets(understanding.in_scope),
        "",
        "**范围外**",
        "",
        _bullets(understanding.out_of_scope),
        "",
        "**假设（待确认）**",
        "",
        _bullets(understanding.assumptions),
        "",
    ]


def _render_tasks(result: SplitResult) -> list[str]:
    lines = ["## 任务", ""]
    for task in result.tasks:
        meta = [f"优先级：{priority_label(task.priority)}"]
        if task.category is not None:
            meta.append(f"分类：{category_label(task.category)}")
        meta.append(f"依赖：{_format_ids(task.depends_on)}")

        lines.extend(
            [
                f"### {task.id} {task.title}",
                "",
                " ｜ ".join(meta),
                "",
                task.description,
                "",
            ]
        )
        if task.acceptance_criteria:
            lines.extend(
                [
                    "**验收标准**",
                    "",
                    _bullets(task.acceptance_criteria),
                    "",
                ]
            )
    return lines


def _render_test_points(result: SplitResult) -> list[str]:
    lines = ["## 测试点", ""]
    for point in result.test_points:
        meta = [
            f"关联任务：{_format_ids(point.task_ids)}",
            f"类型：{test_type_label(point.type)}",
        ]
        if point.priority is not None:
            meta.append(f"优先级：{priority_label(point.priority)}")

        lines.extend(
            [
                f"### {point.id}",
                "",
                " ｜ ".join(meta),
                "",
                f"**场景**：{point.scenario}",
                "",
            ]
        )
        if point.steps:
            lines.extend(["**步骤**", "", _numbered(point.steps), ""])
        lines.extend([f"**预期结果**：{point.expected_result}", ""])
    return lines


def _render_questions(result: SplitResult) -> list[str]:
    lines = ["## 问题", ""]
    if not result.questions:
        lines.extend([config.MSG_NO_QUESTIONS, ""])
        return lines

    for question in result.questions:
        lines.extend([f"### {question.id} {question.question}", ""])
        lines.append(f"**为什么要问**：{question.why}")
        lines.append("")
        lines.append(f"**影响**：{question.impact}")
        lines.append("")
        if question.affected_task_ids:
            lines.append(
                f"**影响任务**：{_format_ids(question.affected_task_ids)}"
            )
            lines.append("")
        if question.blocking is not None:
            lines.append(f"**是否阻塞**：{'是' if question.blocking else '否'}")
            lines.append("")
        if question.suggested_default:
            lines.append(f"**建议默认做法**：{question.suggested_default}")
            lines.append("")
    return lines


def _render_self_check(result: SplitResult) -> list[str]:
    self_check = result.self_check
    lines = [
        "## 自检",
        "",
        f"- 诉求覆盖完整：{'是' if self_check.coverage_ok else '否'}",
        f"- 置信度：{confidence_label(self_check.confidence)}",
    ]
    if self_check.issues:
        lines.append("- 发现的问题：")
        lines.extend(f"  - {item}" for item in self_check.issues)
    else:
        lines.append("- 发现的问题：无")
    lines.append("")
    return lines


def to_markdown(result: SplitResult) -> str:
    """把拆分结果渲染成完整的 Markdown 文本。

    ``unclear`` 输入会把提示放在文档最前面；空问题列表使用统一文案；
    优先级始终使用 ``config.PRIORITY_MAP`` 中的中文文案。
    """

    lines: list[str] = []

    if result.input_type == InputType.UNCLEAR:
        # 放在第一行，确保导出的 Markdown 打开就能看到。
        lines.extend([config.MSG_UNCLEAR_HINT, ""])

    lines.extend(
        [
            "# 拆解结果",
            "",
            f"**输入类型**：{input_type_label(result.input_type)}",
            "",
            f"**摘要**：{result.summary}",
            "",
        ]
    )

    lines.extend(_render_understanding(result))
    lines.extend(_render_tasks(result))
    lines.extend(_render_test_points(result))
    lines.extend(_render_questions(result))
    lines.extend(_render_self_check(result))

    if result.warnings:
        lines.extend(["## 校验提示", ""])
        lines.extend(f"- {warning}" for warning in result.warnings)
        lines.append("")

    # 去掉末尾多余空行，保证导出文本以单个换行结尾。
    return "\n".join(lines).rstrip() + "\n"


# 语义相同，保留两个名称方便调用方按习惯使用。
render_markdown = to_markdown
