"""Streamlit 页面：把杂乱需求 / bug 描述拆成任务、测试点和待澄清问题。

运行方式::

    streamlit run app.py

页面只负责输入、展示和导出；模型调用、校验与重试都在 ``splitter.agent``。
API key 只由 ``config.get_api_key`` 在真正请求前读取，页面不会展示它。

请求锁只存在于当前浏览器标签的这一次 Streamlit 会话（``st.session_state``）。
它不能跨标签、跨进程或跨 worker 去重。同一次会话里，如果禁用态画出来之前
就有点击进了队列，并且这下点击直到解锁之后才被处理，仍可能再跑一次。
锁已经存在时，提交回调直接返回，不会发起第二次 ``agent.run``。
"""

from __future__ import annotations

import html
import json
import time
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
from splitter.schema import InputType, Priority, SplitResult

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"

# 读取真实样例，避免把大段原文硬编码在页面里；只读，不修改 samples/。
EXAMPLE_FILES = (
    ("S01", "S01 需求：优惠码兑换", "S01_feature_coupon_redemption.txt"),
    ("S04", "S04 模糊：系统弄好一点", "S04_feature_vague_unclear.txt"),
    ("S06", "S06 Bug：优惠券页 500", "S06_bug_coupon_list_500.txt"),
)

RESULT = "split_result"
ERROR = "split_error"
LOCK = "request_lock"
PENDING = "pending_submission"
ARMED = "pending_ui_armed"
SUBMITTED = "submitted_text"
PREVALIDATION = "prevalidation_message"

ATTRIBUTION_CURRENT = "以下结果对应本次提交的输入。"
ATTRIBUTION_STALE = "以下结果对应上次提交，当前输入已修改，尚未重新拆解。"
EXAMPLE_HINT = "点击后会覆盖当前输入，并清除上次结果与错误。"
FALLBACK_ERROR = "拆解失败，请稍后重试。"
PENDING_LABEL = "正在拆解…"

# 同一次脚本调用栈里的重入保护。会话状态里的锁负责跨 rerun；这个深度只防止
# 同一次 agent.run 进行中再次进入执行函数。
_EXEC_DEPTH = 0

THEME_CSS = """
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stHeader"] {
  background: #F7F4EE;
  color: #1C1814;
  font-family: "Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC",
    "PingFang SC", "Microsoft YaHei", sans-serif;
}
.stApp {
  overflow-x: hidden;
}
[data-testid="stMainBlockContainer"] {
  max-width: 1120px;
  padding-top: 48px;
  padding-left: 0;
  padding-right: 0;
}
@media (max-width: 1439px) {
  [data-testid="stMainBlockContainer"] {
    max-width: none;
    padding-left: 40px;
    padding-right: 40px;
  }
}
@media (max-width: 800px) {
  [data-testid="stMainBlockContainer"] {
    padding-left: 16px;
    padding-right: 16px;
    padding-top: 24px;
  }
}
.stApp h1 {
  font-size: 32px;
  line-height: 38px;
  font-weight: 400;
  letter-spacing: -0.02em;
  color: #1C1814;
}
@media (max-width: 800px) {
  .stApp h1 {
    font-size: 28px;
    line-height: 34px;
  }
}
.stApp h2,
.stApp h3 {
  font-size: 18px;
  line-height: 24px;
  font-weight: 700;
  letter-spacing: 0;
  color: #1C1814;
}
.stApp p,
.stApp li,
.stApp label,
.stApp textarea,
.stApp button,
.stApp input {
  font-family: "Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC",
    "PingFang SC", "Microsoft YaHei", sans-serif;
}
.stApp p,
.stApp li,
.stApp .dts-copy {
  font-size: 15px;
  line-height: 24px;
  color: #1C1814;
  overflow-wrap: anywhere;
}
.stApp [data-testid="stCaptionContainer"],
.stApp [data-testid="stCaptionContainer"] p {
  color: #5E564C;
  font-size: 13px;
  line-height: 18px;
}
.stApp [data-testid="stTextArea"] textarea {
  background: #FDFBF7;
  color: #1C1814;
  border: 1px solid #D6D0C6;
  border-radius: 12px;
  padding: 16px;
  font-size: 15px;
  line-height: 24px;
}
/* 请求中：输入区用 --raised 底与 --ink-3 字，和可编辑态明显区分。 */
.stApp [data-testid="stTextArea"] textarea:disabled {
  background: #F1EDE4;
  color: #5E564C;
  -webkit-text-fill-color: #5E564C;
  border-color: #D6D0C6;
  cursor: not-allowed;
}
.stApp [data-testid="stTextArea"]:has(textarea:disabled) label p {
  color: #5E564C;
}
.stApp [data-testid="stTextArea"] textarea:focus {
  border: 2px solid #1C1814;
  outline: 2px solid #1C1814;
  outline-offset: 2px;
}
@media (max-width: 800px) {
  .stApp [data-testid="stTextArea"] textarea {
    height: 220px !important;
    min-height: 220px !important;
  }
}
.stApp button {
  min-height: 44px;
  font-size: 15px;
  line-height: 20px;
  /* 不过渡字色和底色：黑底浅字切到浅底深字时，中间帧会看不清。 */
  transition: border-color 180ms cubic-bezier(0.22, 1, 0.36, 1);
}
.stApp button:focus,
.stApp button:focus-visible,
.stApp textarea:focus-visible,
.stApp a:focus-visible,
.stApp summary:focus-visible {
  outline: 2px solid #1C1814;
  outline-offset: 2px;
}
.stApp .st-key-split_button button,
.stApp .st-key-split_button button:hover,
.stApp .st-key-split_button button:focus,
.stApp .st-key-split_button button:focus-visible {
  background: #1C1814;
  color: #F7F4EE;
  border: 1px solid #1C1814;
  border-radius: 999px;
  min-height: 44px;
  padding: 0 22px;
  font-weight: 700;
}
/* 按钮文案是内部 p。上面的 .stApp p 会把这段字涂成墨色，必须单独盖回去。 */
.stApp .st-key-split_button button :is(p, span, div),
.stApp .st-key-split_button button:hover :is(p, span, div),
.stApp .st-key-split_button button:focus :is(p, span, div),
.stApp .st-key-split_button button:focus-visible :is(p, span, div) {
  color: #F7F4EE;
}
.stApp .st-key-example_S01 button,
.stApp .st-key-example_S04 button,
.stApp .st-key-example_S06 button,
.stApp .st-key-download_markdown button,
.stApp .st-key-download_json button,
.stApp .st-key-retry_button button {
  background: #F1EDE4;
  color: #1C1814;
  border: 1px solid #D6D0C6;
  border-radius: 10px;
  min-height: 44px;
}
.stApp .st-key-split_button button:disabled,
.stApp .st-key-split_button button:disabled:hover,
.stApp .st-key-split_button button:disabled:active,
.stApp .st-key-example_S01 button:disabled,
.stApp .st-key-example_S04 button:disabled,
.stApp .st-key-example_S06 button:disabled,
.stApp .st-key-download_markdown button:disabled,
.stApp .st-key-download_json button:disabled,
.stApp .st-key-retry_button button:disabled {
  background: #F1EDE4;
  color: #5E564C;
  border: 1px solid #D6D0C6;
}
.stApp .st-key-split_button button:disabled :is(p, span, div),
.stApp .st-key-split_button button:disabled:hover :is(p, span, div),
.stApp .st-key-split_button button:disabled:active :is(p, span, div),
.stApp .st-key-example_S01 button:disabled :is(p, span, div),
.stApp .st-key-example_S04 button:disabled :is(p, span, div),
.stApp .st-key-example_S06 button:disabled :is(p, span, div),
.stApp .st-key-download_markdown button:disabled :is(p, span, div),
.stApp .st-key-download_json button:disabled :is(p, span, div),
.stApp .st-key-retry_button button:disabled :is(p, span, div) {
  color: #5E564C;
  -webkit-text-fill-color: #5E564C;
}
/* 示例与下载各占满自己的列，避免同一行里被 fit-content 拉出大空隙。 */
.stApp .st-key-examples [data-testid="stColumn"] [data-testid="stElementContainer"],
.stApp .st-key-exports [data-testid="stColumn"] [data-testid="stElementContainer"] {
  width: 100%;
}
.stApp .st-key-examples [data-testid="stColumn"] button,
.stApp .st-key-exports [data-testid="stColumn"] button {
  width: 100%;
}
.stApp [data-testid="stVerticalBlockBorderWrapper"] {
  background: #FDFBF7;
  border: 1px solid #D6D0C6;
  border-radius: 12px;
}
.dts-count,
.dts-meta,
.dts-id {
  color: #5E564C;
  font-size: 13px;
  line-height: 18px;
}
.dts-count-over {
  color: #B42318;
  font-weight: 700;
}
.dts-id {
  font-family: "Noto Sans Mono CJK SC", "IBM Plex Mono", ui-monospace, monospace;
  color: #1C1814;
  margin-right: 8px;
}
.dts-card-title {
  margin: 0 0 4px;
}
.dts-card-name {
  font-size: 15px;
  line-height: 24px;
  font-weight: 700;
  color: #1C1814;
}
.dts-pri {
  border: 1px solid #D6D0C6;
  border-radius: 4px;
  padding: 0 6px;
}
.dts-pri-high {
  background: #1C1814;
  color: #F7F4EE;
  border-radius: 4px;
  padding: 0 6px;
}
.dts-tag {
  border: 1px solid #1C1814;
  border-radius: 4px;
  padding: 0 6px;
  margin-left: 8px;
}
.dts-list {
  margin: 0 0 8px;
  padding-left: 1.2em;
}
.dts-banner {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  border-radius: 10px;
  padding: 12px 16px;
  margin: 8px 0 12px;
}
.dts-banner-error {
  background: #FDECEA;
  color: #B42318;
  border: 1px solid #B42318;
}
.dts-banner-warn {
  background: #F8F0DC;
  color: #6B4E12;
  border: 1px solid #C4A35A;
}
.dts-banner-info {
  background: #F1EDE4;
  color: #1C1814;
  border: 1px solid #D6D0C6;
}
.dts-banner-kicker {
  font-weight: 700;
  flex: none;
}
.dts-status,
.dts-attribution {
  color: #4A433A;
  font-size: 15px;
  line-height: 24px;
  margin: 8px 0;
}
@media (max-width: 959px) {
  .st-key-understanding_grid [data-testid="stHorizontalBlock"] {
    flex-direction: column;
  }
  .st-key-understanding_grid [data-testid="stColumn"] {
    width: 100% !important;
    flex: 1 1 100% !important;
  }
}
@media (max-width: 800px) {
  .st-key-examples [data-testid="stHorizontalBlock"],
  .st-key-exports [data-testid="stHorizontalBlock"],
  .st-key-input_footer [data-testid="stHorizontalBlock"] {
    flex-direction: column;
  }
  .st-key-examples [data-testid="stColumn"],
  .st-key-exports [data-testid="stColumn"],
  .st-key-input_footer [data-testid="stColumn"] {
    width: 100% !important;
    flex: 1 1 100% !important;
  }
  .stApp .st-key-split_button button,
  .stApp .st-key-example_S01 button,
  .stApp .st-key-example_S04 button,
  .stApp .st-key-example_S06 button,
  .stApp .st-key-download_markdown button,
  .stApp .st-key-download_json button,
  .stApp .st-key-retry_button button {
    width: 100%;
  }
}
.stApp:has(.dts-pending-active) [data-stale="true"] {
  display: none !important;
}
/* Streamlit 只给叶子节点写 data-stale。展开器、导出按钮、代码块和带边框的
   结果卡外壳不是叶子，pending 时仍会留下空骨架；这些控件在 pending 里没有
   合法用途，按稳定的 testid / key 整块隐藏。 */
.stApp:has(.dts-pending-active) [data-testid="stExpander"],
.stApp:has(.dts-pending-active) [data-testid="stDownloadButton"],
.stApp:has(.dts-pending-active) [data-testid="stCode"],
.stApp:has(.dts-pending-active) [class*="st-key-result_card_"] {
  display: none !important;
}
@media (prefers-reduced-motion: reduce) {
  .stApp *,
  .stApp *::before,
  .stApp *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
"""


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


def _init_state() -> None:
    for key, default in (
        (RESULT, None),
        (ERROR, None),
        (LOCK, False),
        (PENDING, None),
        (ARMED, False),
        (SUBMITTED, None),
        (PREVALIDATION, None),
        ("input_text", ""),
    ):
        st.session_state.setdefault(key, default)


def _html_text(value: object) -> str:
    """转义模型或用户文本，并把换行变成安全的换行标签。"""

    return html.escape(str(value), quote=True).replace("\n", "<br>")


def _copy(value: object) -> None:
    st.markdown(
        f"<div class='dts-copy'>{_html_text(value)}</div>",
        unsafe_allow_html=True,
    )


def _labeled(label: str, value: object) -> None:
    st.markdown(
        "<p class='dts-copy'><strong>"
        f"{html.escape(label)}</strong>{_html_text(value)}</p>",
        unsafe_allow_html=True,
    )


def _bullets(items: list[str] | None, *, empty: str | None = "无") -> None:
    if not items:
        if empty is not None:
            _copy(empty)
        return
    body = "".join(
        f"<li>{html.escape(item, quote=True)}</li>" for item in items
    )
    st.markdown(f"<ul class='dts-list'>{body}</ul>", unsafe_allow_html=True)


def _numbered(items: list[str]) -> None:
    body = "".join(
        f"<li>{html.escape(item, quote=True)}</li>" for item in items
    )
    st.markdown(f"<ol class='dts-list'>{body}</ol>", unsafe_allow_html=True)


def _banner(kind: str, message: str) -> None:
    kicker = "错误" if kind == "error" else "提示"
    st.markdown(
        (
            f"<div class='dts-banner dts-banner-{kind}' role='alert'>"
            f"<span class='dts-banner-kicker'>{kicker}</span>"
            f"<span class='dts-banner-text'>{html.escape(message)}</span>"
            "</div>"
        ),
        unsafe_allow_html=True,
    )


def _fill_example(text: str) -> None:
    """示例按钮回调：填入原文并清空上一次结果。请求进行中不生效。"""

    if st.session_state.get(LOCK):
        return
    st.session_state["input_text"] = text
    st.session_state[RESULT] = None
    st.session_state[ERROR] = None
    st.session_state[PREVALIDATION] = None
    st.session_state[SUBMITTED] = None


def _on_submit() -> None:
    """拆解 / 重试共用。预校验失败不加锁、不调用 agent。"""

    if st.session_state.get(LOCK):
        return
    raw = st.session_state.get("input_text", "") or ""
    stripped = raw.strip()
    limit = config.get_settings().max_input_chars
    if not stripped:
        st.session_state[PREVALIDATION] = config.MSG_EMPTY_INPUT
        return
    if len(stripped) > limit:
        return
    st.session_state[LOCK] = True
    st.session_state[PENDING] = stripped
    st.session_state[ARMED] = False
    st.session_state[RESULT] = None
    st.session_state[ERROR] = None
    st.session_state[PREVALIDATION] = None


def _run_agent(text: str) -> None:
    """调用 agent，并把成功/失败结果写入 session_state。"""

    try:
        result = agent.run(text)
    except Exception:
        # agent.run 正常情况下不抛异常；这里兜底，保证页面不崩溃，
        # 也避免把底层异常细节（可能包含配置信息）直接展示出来。
        st.session_state[RESULT] = None
        st.session_state[ERROR] = FALLBACK_ERROR
        st.session_state[SUBMITTED] = None
        return

    st.session_state[ERROR] = None
    st.session_state[RESULT] = result
    if result.ok and result.result is not None:
        st.session_state[SUBMITTED] = text.strip()
    else:
        st.session_state[SUBMITTED] = None


def _execute_locked_request() -> None:
    """执行已经画过禁用态的那一次请求，并在 finally 里解锁。"""

    global _EXEC_DEPTH
    if not st.session_state.get(LOCK):
        return
    if _EXEC_DEPTH:
        return
    pending = st.session_state.get(PENDING)
    if not isinstance(pending, str):
        return
    _EXEC_DEPTH += 1
    st.session_state[PENDING] = None
    try:
        with st.spinner(PENDING_LABEL):
            _run_agent(pending)
    finally:
        _EXEC_DEPTH -= 1
        st.session_state[LOCK] = False
        st.session_state[ARMED] = False
        st.session_state[PENDING] = None


def _failure_message() -> str | None:
    error = st.session_state.get(ERROR)
    if error:
        return str(error)
    result = st.session_state.get(RESULT)
    if result is not None and not result.ok:
        return result.error or FALLBACK_ERROR
    return None


def _priority_html(priority: Priority | str | None) -> str:
    label = html.escape(priority_label(priority))
    value = getattr(priority, "value", priority)
    css = "dts-pri-high" if value == "P0" else "dts-pri"
    return f"<span class='{css}'>{label}</span>"


def _meta(parts: list[str]) -> None:
    st.markdown(
        f"<p class='dts-meta'>{' ｜ '.join(parts)}</p>",
        unsafe_allow_html=True,
    )


def _render_understanding(result: SplitResult) -> None:
    st.subheader("需求理解")
    understanding = result.understanding
    _labeled("目标：", understanding.goal)

    with st.container(key="understanding_grid"):
        columns = st.columns(3, gap="small")
        blocks = (
            ("范围内", understanding.in_scope),
            ("范围外", understanding.out_of_scope),
            ("假设（待确认）", understanding.assumptions),
        )
        for column, (title, items) in zip(columns, blocks):
            with column:
                st.markdown(f"**{title}**")
                _bullets(items)


def _render_tasks(result: SplitResult) -> None:
    st.subheader("任务")
    for index, task in enumerate(result.tasks, start=1):
        with st.container(key=f"result_card_task_{index}", border=True):
            st.markdown(
                "<p class='dts-card-title'>"
                f"<span class='dts-id'>{html.escape(task.id)}</span>"
                f"<span class='dts-card-name'>{html.escape(task.title)}</span>"
                "</p>",
                unsafe_allow_html=True,
            )
            depends = (
                "、".join(html.escape(item) for item in task.depends_on)
                if task.depends_on
                else "无"
            )
            _meta(
                [
                    f"优先级：{_priority_html(task.priority)}",
                    f"分类：{html.escape(category_label(task.category))}",
                    f"依赖：{depends}",
                ]
            )
            _copy(task.description)
            if task.acceptance_criteria:
                st.markdown("**验收标准**")
                _bullets(task.acceptance_criteria, empty=None)


def _render_test_points(result: SplitResult) -> None:
    st.subheader("测试点")
    for index, point in enumerate(result.test_points, start=1):
        with st.container(key=f"result_card_test_{index}", border=True):
            st.markdown(
                "<p class='dts-card-title'>"
                f"<span class='dts-id'>{html.escape(point.id)}</span>"
                "</p>",
                unsafe_allow_html=True,
            )
            meta = [
                "关联任务："
                + "、".join(html.escape(item) for item in point.task_ids),
                f"类型：{html.escape(test_type_label(point.type))}",
            ]
            if point.priority is not None:
                meta.append(f"优先级：{_priority_html(point.priority)}")
            _meta(meta)
            _labeled("场景：", point.scenario)
            if point.steps:
                st.markdown("**步骤**")
                _numbered(point.steps)
            _labeled("预期结果：", point.expected_result)


def _render_questions(result: SplitResult) -> None:
    st.subheader("问题")
    if not result.questions:
        _banner("info", config.MSG_NO_QUESTIONS)
        return

    for index, question in enumerate(result.questions, start=1):
        with st.container(key=f"result_card_question_{index}", border=True):
            st.markdown(
                "<p class='dts-card-title'>"
                f"<span class='dts-id'>{html.escape(question.id)}</span>"
                f"<span class='dts-card-name'>{html.escape(question.question)}</span>"
                "</p>",
                unsafe_allow_html=True,
            )
            _labeled("为什么要问：", question.why)
            _labeled("影响：", question.impact)
            if question.affected_task_ids:
                joined = "、".join(
                    html.escape(item) for item in question.affected_task_ids
                )
                st.markdown(
                    f"<p class='dts-copy'><strong>影响任务：</strong>{joined}</p>",
                    unsafe_allow_html=True,
                )
            if question.blocking is not None:
                answer = "是" if question.blocking else "否"
                tag = (
                    "<span class='dts-tag'>阻塞</span>" if question.blocking else ""
                )
                st.markdown(
                    "<p class='dts-copy'><strong>是否阻塞：</strong>"
                    f"{answer}{tag}</p>",
                    unsafe_allow_html=True,
                )
            if question.suggested_default:
                _labeled("建议默认做法：", question.suggested_default)


def _render_self_check(result: SplitResult) -> None:
    st.subheader("自检")
    self_check = result.self_check
    covered = "是" if self_check.coverage_ok else "否"
    confidence = html.escape(confidence_label(self_check.confidence))
    st.markdown(
        "<ul class='dts-list'>"
        f"<li>诉求覆盖完整：{covered}</li>"
        f"<li>置信度：{confidence}</li>"
        "</ul>",
        unsafe_allow_html=True,
    )
    if self_check.issues:
        st.markdown("**发现的问题**")
        _bullets(self_check.issues, empty=None)
    else:
        _copy("发现的问题：无")


def _render_exports(result: SplitResult) -> None:
    markdown = to_markdown(result)
    json_text = json.dumps(
        result.model_dump(mode="json"), ensure_ascii=False, indent=2
    )

    st.subheader("导出")
    with st.container(key="exports"):
        markdown_col, json_col = st.columns(2, gap="small")
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
        _banner("warn", config.MSG_UNCLEAR_HINT)

    st.subheader("摘要")
    _copy(result.summary)
    st.markdown(
        "<p class='dts-meta'>输入类型："
        f"{html.escape(input_type_label(result.input_type))}</p>",
        unsafe_allow_html=True,
    )

    _render_understanding(result)
    _render_tasks(result)
    _render_test_points(result)
    _render_questions(result)
    _render_self_check(result)

    if warnings:
        with st.expander("校验提示"):
            _bullets(list(warnings), empty=None)

    _render_exports(result)


def _render_failure(result: agent.AgentResult | None, message: str) -> None:
    _banner("error", message)

    if result is not None and result.details:
        with st.expander("错误详情"):
            st.code(result.details)

    if result is not None and result.raw_output is not None:
        with st.expander("原始输出"):
            st.code(result.raw_output or "（空）")


def _render_attribution(current_text: str) -> None:
    submitted = st.session_state.get(SUBMITTED)
    if not isinstance(submitted, str):
        return
    if current_text.strip() == submitted:
        st.markdown(
            f"<p class='dts-attribution'>{html.escape(ATTRIBUTION_CURRENT)}</p>",
            unsafe_allow_html=True,
        )
        return
    _banner("warn", ATTRIBUTION_STALE)


def _render_page() -> None:
    """画出当前会话对应的整页。"""

    locked = bool(st.session_state.get(LOCK))
    if locked:
        # 标记给样式用：请求进行中，把上一轮还没卸掉的节点藏起来。
        st.markdown(
            "<div class='dts-pending-active'></div>",
            unsafe_allow_html=True,
        )
    current_text = st.session_state.get("input_text", "") or ""
    if (
        current_text.strip()
        and st.session_state.get(PREVALIDATION) == config.MSG_EMPTY_INPUT
    ):
        st.session_state[PREVALIDATION] = None

    st.title("dev-task-splitter")
    st.caption(
        "把杂乱的需求 / bug 描述拆成要做的任务、要测的点和要问清楚的问题。"
    )

    examples = _load_examples()
    if examples:
        st.markdown("**示例一键填入**")
        st.caption(EXAMPLE_HINT)
        with st.container(key="examples"):
            columns = st.columns(len(examples), gap="small")
            for column, (key, label, text) in zip(columns, examples):
                column.button(
                    label,
                    key=f"example_{key}",
                    disabled=locked,
                    on_click=_fill_example,
                    args=(text,),
                )

    limit = config.get_settings().max_input_chars
    with st.container(key="input_card", border=True):
        text = st.text_area(
            "需求或 bug 描述",
            key="input_text",
            height=260,
            disabled=locked,
            placeholder="粘贴需求或 bug 描述，例如：用户反馈打开优惠券页面直接 500……",
        )
        count = len((text or "").strip())
        over_limit = count > limit
        count_class = "dts-count dts-count-over" if over_limit else "dts-count"
        with st.container(key="input_footer"):
            count_col, button_col = st.columns([5, 2], gap="small")
            with count_col:
                st.markdown(
                    f"<p class='{count_class}'>字数：{count} / {limit}</p>",
                    unsafe_allow_html=True,
                )
            with button_col:
                st.button(
                    PENDING_LABEL if locked else "拆解",
                    type="primary",
                    key="split_button",
                    disabled=locked or over_limit,
                    on_click=_on_submit,
                )

    if locked:
        st.markdown(
            f"<p class='dts-status'>{PENDING_LABEL}</p>",
            unsafe_allow_html=True,
        )
    elif over_limit:
        _banner("error", config.MSG_INPUT_TOO_LONG.format(n=count))
    elif st.session_state.get(PREVALIDATION):
        _banner("error", str(st.session_state[PREVALIDATION]))

    failure = None if locked else _failure_message()
    result = None if locked else st.session_state.get(RESULT)

    if not locked and result is not None and result.ok and result.result is not None:
        _render_attribution(text or "")
        _render_success(result.result, result.warnings)
    elif failure is not None and not locked:
        agent_result = result if isinstance(result, agent.AgentResult) else None
        _render_failure(agent_result, failure)

    # 请求中只保留 pending 提示；失败完成并解锁后才画手动「重试」。
    if failure is not None:
        st.button(
            "重试",
            key="retry_button",
            disabled=over_limit,
            on_click=_on_submit,
        )

    st.divider()
    st.caption(
        "示例来自仓库 samples/ 原文。字数按去掉首尾空白计算，在页面重新运行后更新。"
    )


def main() -> None:
    st.set_page_config(
        page_title="dev-task-splitter",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(f"<style>{THEME_CSS}</style>", unsafe_allow_html=True)
    _init_state()

    _render_page()

    pending = st.session_state.get(PENDING)
    if st.session_state.get(LOCK) and isinstance(pending, str):
        st.session_state[ARMED] = True
        # 把已经画出的禁用页让给浏览器，再进入阻塞调用。
        time.sleep(0.2)
        _execute_locked_request()
        st.rerun()


if __name__ == "__main__":
    main()
