"""Streamlit 页面：把杂乱需求 / bug 描述拆成任务、测试点和待澄清问题。

运行方式::

    streamlit run app.py

页面只负责输入、展示和导出；模型调用、校验与重试都在 ``splitter.agent``。
API key 只由 ``config.get_api_key`` 在真正请求前读取，页面不会展示它。
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from splitter import agent, config
from splitter.render import (
    category_label,
    confidence_label,
    input_type_label,
    priority_label,
    test_type_label,
    to_markdown,
)
from splitter.schema import InputType, SplitResult

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"

# 读取真实样例，避免把大段原文硬编码在页面里；只读，不修改 samples/。
EXAMPLE_FILES = (
    ("S01", "S01 需求：优惠码兑换", "S01_feature_coupon_redemption.txt"),
    ("S04", "S04 模糊：系统弄好一点", "S04_feature_vague_unclear.txt"),
    ("S06", "S06 Bug：优惠券页 500", "S06_bug_coupon_list_500.txt"),
)

_STATE_RESULT = "split_result"
_STATE_ERROR = "split_error"


def _load_examples() -> list[tuple[str, str, str]]:
    """读取 samples 中的示例文本；文件缺失时跳过，不影响页面启动。"""

    examples: list[tuple[str, str, str]] = []
    for key, label, filename in EXAMPLE_FILES:
        try:
            text = (SAMPLES_DIR / filename).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        examples.append((key, label, text))
    return examples


def _fill_example(text: str) -> None:
    """示例按钮回调：填入原文并清空上一次结果。"""

    st.session_state["input_text"] = text
    st.session_state[_STATE_RESULT] = None
    st.session_state[_STATE_ERROR] = None


def _run_agent(text: str) -> None:
    """调用 agent，并把成功/失败结果写入 session_state。"""

    st.session_state[_STATE_ERROR] = None
    try:
        result = agent.run(text)
    except Exception:
        # agent.run 正常情况下不抛异常；这里兜底，保证页面不崩溃，
        # 也避免把底层异常细节（可能包含配置信息）直接展示出来。
        st.session_state[_STATE_RESULT] = None
        st.session_state[_STATE_ERROR] = "拆解失败，请稍后重试。"
        return

    st.session_state[_STATE_RESULT] = result


def _priority_text(priority) -> str:
    return priority_label(priority)


def _render_understanding(result: SplitResult) -> None:
    st.subheader("需求理解")
    understanding = result.understanding
    st.markdown(f"**目标**：{understanding.goal}")

    in_scope, out_of_scope, assumptions = st.columns(3)
    with in_scope:
        st.markdown("**范围内**")
        if understanding.in_scope:
            for item in understanding.in_scope:
                st.markdown(f"- {item}")
        else:
            st.caption("无")
    with out_of_scope:
        st.markdown("**范围外**")
        if understanding.out_of_scope:
            for item in understanding.out_of_scope:
                st.markdown(f"- {item}")
        else:
            st.caption("无")
    with assumptions:
        st.markdown("**假设（待确认）**")
        if understanding.assumptions:
            for item in understanding.assumptions:
                st.markdown(f"- {item}")
        else:
            st.caption("无")


def _render_tasks(result: SplitResult) -> None:
    st.subheader("任务")
    for task in result.tasks:
        with st.container(border=True):
            st.markdown(f"#### {task.id} {task.title}")
            meta = [f"优先级：{_priority_text(task.priority)}"]
            if task.category is not None:
                meta.append(f"分类：{category_label(task.category)}")
            meta.append(
                "依赖："
                + ("、".join(task.depends_on) if task.depends_on else "无")
            )
            st.caption(" ｜ ".join(meta))
            st.markdown(task.description)
            if task.acceptance_criteria:
                st.markdown("**验收标准**")
                for item in task.acceptance_criteria:
                    st.markdown(f"- {item}")


def _render_test_points(result: SplitResult) -> None:
    st.subheader("测试点")
    for point in result.test_points:
        with st.container(border=True):
            st.markdown(f"#### {point.id}")
            meta = [
                f"关联任务：{'、'.join(point.task_ids)}",
                f"类型：{test_type_label(point.type)}",
            ]
            if point.priority is not None:
                meta.append(f"优先级：{_priority_text(point.priority)}")
            st.caption(" ｜ ".join(meta))
            st.markdown(f"**场景**：{point.scenario}")
            if point.steps:
                st.markdown("**步骤**")
                for index, step in enumerate(point.steps, 1):
                    st.markdown(f"{index}. {step}")
            st.markdown(f"**预期结果**：{point.expected_result}")


def _render_questions(result: SplitResult) -> None:
    st.subheader("问题")
    if not result.questions:
        st.info(config.MSG_NO_QUESTIONS)
        return

    for question in result.questions:
        with st.container(border=True):
            st.markdown(f"#### {question.id} {question.question}")
            st.markdown(f"**为什么要问**：{question.why}")
            st.markdown(f"**影响**：{question.impact}")
            if question.affected_task_ids:
                st.markdown(
                    f"**影响任务**：{'、'.join(question.affected_task_ids)}"
                )
            if question.blocking is not None:
                st.markdown(
                    f"**是否阻塞**：{'是' if question.blocking else '否'}"
                )
            if question.suggested_default:
                st.markdown(
                    f"**建议默认做法**：{question.suggested_default}"
                )


def _render_self_check(result: SplitResult) -> None:
    st.subheader("自检")
    self_check = result.self_check
    st.markdown(
        f"- 诉求覆盖完整：{'是' if self_check.coverage_ok else '否'}\n"
        f"- 置信度：{confidence_label(self_check.confidence)}"
    )
    if self_check.issues:
        st.markdown("**发现的问题**")
        for item in self_check.issues:
            st.markdown(f"- {item}")
    else:
        st.caption("发现的问题：无")


def _render_exports(result: SplitResult) -> None:
    markdown = to_markdown(result)
    json_text = json.dumps(
        result.model_dump(mode="json"), ensure_ascii=False, indent=2
    )

    st.subheader("导出")
    markdown_col, json_col = st.columns(2)
    with markdown_col:
        st.download_button(
            "下载 Markdown",
            data=markdown,
            file_name="split_result.md",
            mime="text/markdown",
            key="download_markdown",
        )
    with json_col:
        st.download_button(
            "下载 JSON",
            data=json_text,
            file_name="split_result.json",
            mime="application/json",
            key="download_json",
        )

    # Streamlit 的代码块右上角自带复制按钮，点击即可复制完整 Markdown。
    with st.expander("一键复制 Markdown"):
        st.caption("点击下方代码块右上角的复制图标即可复制。")
        st.code(markdown, language="markdown")


def _render_success(result: SplitResult, warnings: list[str]) -> None:
    if result.input_type == InputType.UNCLEAR:
        st.warning(config.MSG_UNCLEAR_HINT)

    st.subheader("摘要")
    st.write(result.summary)
    st.caption(f"输入类型：{input_type_label(result.input_type)}")

    _render_understanding(result)
    _render_tasks(result)
    _render_test_points(result)
    _render_questions(result)
    _render_self_check(result)

    if warnings:
        with st.expander("校验提示"):
            for warning in warnings:
                st.markdown(f"- {warning}")

    _render_exports(result)


def _render_failure(result: agent.AgentResult, current_text: str) -> None:
    st.error(result.error or "拆解失败，请稍后重试。")

    if result.details:
        with st.expander("错误详情"):
            st.code(result.details)

    if result.raw_output is not None:
        st.markdown("**原始输出**")
        st.code(result.raw_output or "（空）")

    if st.button("重试", key="retry_button"):
        with st.spinner("正在重试…"):
            _run_agent(current_text)
        st.rerun()


def main() -> None:
    st.set_page_config(
        page_title="dev-task-splitter",
        page_icon="🧩",
        layout="wide",
    )

    for key, default in (
        (_STATE_RESULT, None),
        (_STATE_ERROR, None),
    ):
        st.session_state.setdefault(key, default)
    st.session_state.setdefault("input_text", "")

    st.title("dev-task-splitter")
    st.caption(
        "把杂乱的需求 / bug 描述拆成要做的任务、要测的点和要问清楚的问题。"
    )

    examples = _load_examples()
    if examples:
        st.markdown("**示例一键填入**")
        columns = st.columns(len(examples))
        for column, (key, label, text) in zip(columns, examples):
            column.button(
                label,
                key=f"example_{key}",
                on_click=_fill_example,
                args=(text,),
            )

    text = st.text_area(
        "需求或 bug 描述",
        key="input_text",
        height=260,
        placeholder="粘贴需求或 bug 描述，例如：用户反馈打开优惠券页面直接 500……",
    )

    count = len(text.strip())
    limit = config.get_settings().max_input_chars
    if count > limit:
        st.error(config.MSG_INPUT_TOO_LONG.format(n=count))
    else:
        st.caption(f"字数：{count} / {limit}")

    if st.button("拆解", type="primary", key="split_button"):
        with st.spinner("正在拆解，请稍候…"):
            _run_agent(text)

    error = st.session_state.get(_STATE_ERROR)
    result = st.session_state.get(_STATE_RESULT)

    if error:
        st.error(error)
        if st.button("重试", key="retry_exception"):
            with st.spinner("正在重试…"):
                _run_agent(st.session_state.get("input_text", ""))
            st.rerun()
    elif result is not None:
        if result.ok and result.result is not None:
            _render_success(result.result, result.warnings)
        else:
            _render_failure(result, st.session_state.get("input_text", ""))


if __name__ == "__main__":
    main()
