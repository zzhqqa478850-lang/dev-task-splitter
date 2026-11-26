"""Streamlit 页面行为测试。

全部使用 mock 的 ``agent.run``，不访问网络，也不读取 API key。
计数、预校验、会话锁和结果展示都以设计规范里的文案为准。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import streamlit as st
from streamlit.runtime.media_file_manager import MediaFileManager
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.element_tree import Expander

from splitter import agent, config
from splitter.render import to_markdown
from splitter.schema import SplitResult

ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"
SAMPLES = ROOT / "samples"

# 与页面 session_state 约定一致。锁只表示当前脚本会话里有一次尚未画完的请求。
LOCK = "request_lock"
PENDING = "pending_submission"
ARMED = "pending_ui_armed"
RESULT = "split_result"
ERROR = "split_error"
SUBMITTED = "submitted_text"
PREVALIDATION = "prevalidation_message"

ATTRIBUTION_CURRENT = "以下结果对应本次提交的输入。"
ATTRIBUTION_STALE = "以下结果对应上次提交，当前输入已修改，尚未重新拆解。"
EXAMPLE_HINT = "点击后会覆盖当前输入，并清除上次结果与错误。"
FALLBACK = "拆解失败，请稍后重试。"


def _task(task_id: str = "T1", **extra: object) -> dict:
    data = {
        "id": task_id,
        "title": "补齐优惠券列表错误处理",
        "description": "定位列表接口 500 并给出可验证的修复。",
        "priority": "P0",
        "category": "backend",
        "estimate": "M",
        "depends_on": [],
        "acceptance_criteria": ["列表接口不再返回 500"],
    }
    data.update(extra)
    return data


def _point(point_id: str = "TP1", **extra: object) -> dict:
    data = {
        "id": point_id,
        "task_ids": ["T1"],
        "type": "functional",
        "scenario": "打开优惠券列表",
        "steps": ["打开页面", "等待列表返回"],
        "expected_result": "页面展示券列表而不是 500",
        "priority": "P0",
    }
    data.update(extra)
    return data


def _question(question_id: str = "Q1", **extra: object) -> dict:
    data = {
        "id": question_id,
        "question": "500 是全量用户还是单个活动？",
        "why": "原文没有说明影响范围。",
        "impact": "会影响修复优先级和回归范围。",
        "affected_task_ids": ["T1"],
        "blocking": True,
        "suggested_default": "先按全量故障处理。",
    }
    data.update(extra)
    return data


def _payload(**overrides: object) -> dict:
    data = {
        "input_type": "bug",
        "summary": "优惠券列表接口返回 500，需要定位并修复。",
        "understanding": {
            "goal": "让优惠券列表恢复可用。",
            "in_scope": ["定位 500", "补回归测试"],
            "out_of_scope": ["重做券样式"],
            "assumptions": ["网关日志可以查到"],
        },
        "tasks": [
            _task(),
            _task(
                "T2",
                title="补列表页错误提示",
                description="接口失败时给出可理解的提示。",
                priority="P1",
                category="frontend",
                estimate="S",
                depends_on=["T1"],
                acceptance_criteria=["失败时不展示空白页"],
            ),
            _task(
                "T3",
                title="补充监控告警",
                description="为列表接口增加错误率告警。",
                priority="P2",
                category=None,
                estimate="L",
                depends_on=[],
                acceptance_criteria=None,
            ),
        ],
        "test_points": [
            _point(),
            _point(
                "TP2",
                task_ids=["T2"],
                type="error_handling",
                scenario="接口持续 500",
                steps=None,
                expected_result="页面提示加载失败",
                priority="P2",
            ),
        ],
        "questions": [
            _question(),
            _question(
                "Q2",
                question="是否要先降级隐藏入口？",
                why="原文没有给出临时措施。",
                impact="会影响是否阻塞上线。",
                affected_task_ids=None,
                blocking=False,
                suggested_default=None,
            ),
        ],
        "self_check": {
            "coverage_ok": False,
            "issues": ["还缺一条空列表的回归"],
            "confidence": "low",
        },
    }
    data.update(overrides)
    return data


def _result(warning: str | None = None, **overrides: object) -> SplitResult:
    result = SplitResult.model_validate(_payload(**overrides))
    if warning:
        result._set_warnings([warning])
    return result


def _ok(result: SplitResult) -> agent.AgentResult:
    return agent.AgentResult(
        ok=True,
        result=result,
        warnings=result.warnings,
        attempts=1,
    )


def _fail(
    message: str,
    *,
    raw_output: str | None = None,
    details: str | None = None,
) -> agent.AgentResult:
    return agent.AgentResult(
        ok=False,
        error=message,
        raw_output=raw_output,
        details=details,
        attempts=1,
    )


def _visible(value: str) -> str:
    """去掉样式和标签，得到用户实际能读到的文字。"""

    without_style = re.sub(r"<style[\s\S]*?</style>", "", value)
    return re.sub(r"<[^>]+>", "", without_style)


def _page_text(at: AppTest) -> str:
    chunks: list[str] = []
    for group in (
        at.title,
        at.header,
        at.subheader,
        at.markdown,
        at.caption,
        at.text,
        at.error,
        at.warning,
        at.info,
        at.success,
    ):
        for element in group:
            value = getattr(element, "value", "")
            if not isinstance(value, str):
                continue
            if "<style" in value:
                continue
            chunks.append(_visible(value))
    chunks.extend(button.label for button in at.button)
    return "\n".join(chunks)


def _disarm(at: AppTest) -> None:
    """清掉测试里残留的按钮触发，避免下一次 run 被当成又点了一次。"""

    for button in at.button:
        button._value = False


def _new_app(monkeypatch: pytest.MonkeyPatch, responder) -> tuple[AppTest, list[str]]:
    calls: list[str] = []

    def _run(text: str):
        calls.append(text)
        return responder(text)

    monkeypatch.setattr(agent, "run", _run)
    app = AppTest.from_file(APP_PATH, default_timeout=20)
    app.run()
    return app, calls


def _finish_request(at: AppTest) -> AppTest:
    """点「拆解」并走完「先画出禁用态，再执行一次」的两拍。"""

    at.button(key="split_button").click().run()
    _disarm(at)
    if at.session_state.get(LOCK):
        at.run()
        _disarm(at)
    return at


def _finish_retry(at: AppTest) -> AppTest:
    at.button(key="retry_button").click().run()
    _disarm(at)
    if at.session_state.get(LOCK):
        at.run()
        _disarm(at)
    return at


def _sample(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8")


def test_empty_page_shows_count_and_keeps_submit_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at, calls = _new_app(monkeypatch, lambda text: _ok(_result()))

    assert at.title[0].value == "dev-task-splitter"
    text = _page_text(at)
    assert "把杂乱的需求 / bug 描述拆成要做的任务、要测的点和要问清楚的问题。" in text
    assert EXAMPLE_HINT in text
    assert "字数：0 / 3000" in text
    assert at.button(key="split_button").label == "拆解"
    assert at.button(key="split_button").disabled is False
    assert at.error.len == 0
    assert "设计提案" not in text
    assert "待用户审阅" not in text
    assert "非运行截图" not in text
    assert calls == []


def test_empty_and_whitespace_submit_do_not_call_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at, calls = _new_app(monkeypatch, lambda text: _ok(_result()))

    _finish_request(at)
    assert calls == []
    assert config.MSG_EMPTY_INPUT in _page_text(at)
    assert at.button(key="split_button").disabled is False
    with pytest.raises(KeyError):
        at.button(key="retry_button")

    at.text_area[0].set_value(" \n\t  ").run()
    _finish_request(at)
    assert calls == []
    assert config.MSG_EMPTY_INPUT in _page_text(at)
    assert at.session_state.get(LOCK) is not True


def test_examples_fill_repository_text_and_clear_previous_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at, calls = _new_app(monkeypatch, lambda text: _ok(_result()))
    at.text_area[0].set_value("需要先被覆盖的旧输入").run()
    _finish_request(at)
    assert calls
    assert "优惠券列表接口返回 500" in _page_text(at)

    at.session_state[ERROR] = "旧错误不该留下"
    at.session_state[PREVALIDATION] = config.MSG_EMPTY_INPUT

    for key, filename, stripped_len in (
        ("example_S01", "S01_feature_coupon_redemption.txt", 622),
        ("example_S04", "S04_feature_vague_unclear.txt", 147),
        ("example_S06", "S06_bug_coupon_list_500.txt", 742),
    ):
        original = _sample(filename)
        at.button(key=key).click().run()
        _disarm(at)
        assert at.text_area[0].value == original
        assert len(original.strip()) == stripped_len
        assert f"字数：{stripped_len} / 3000" in _page_text(at)
        assert "优惠券列表接口返回 500" not in _page_text(at)
        assert "旧错误不该留下" not in _page_text(at)
        assert config.MSG_EMPTY_INPUT not in _page_text(at)
        assert at.session_state.get(RESULT) is None
        assert at.session_state.get(ERROR) is None


def test_count_uses_stripped_length_on_each_rerun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at, calls = _new_app(monkeypatch, lambda text: _ok(_result()))

    at.text_area[0].set_value("  abc \n").run()
    assert "字数：3 / 3000" in _page_text(at)
    at.text_area[0].set_value("\n字字  ").run()
    assert "字数：2 / 3000" in _page_text(at)
    assert calls == []


def test_exactly_3000_submits_and_3001_is_blocked_without_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at, calls = _new_app(monkeypatch, lambda text: _ok(_result(summary="边界结果")))
    exactly = "字" * 3000
    at.text_area[0].set_value("\n" + exactly + " \n").run()

    assert "字数：3000 / 3000" in _page_text(at)
    assert at.button(key="split_button").disabled is False
    assert at.text_area[0].max_chars in (0, None)
    _finish_request(at)
    assert calls == [exactly]
    assert "边界结果" in _page_text(at)

    too_long = "字" * 3001
    at.text_area[0].set_value(too_long).run()
    _disarm(at)
    assert at.text_area[0].value == too_long
    assert len(at.text_area[0].value) == 3001
    assert config.MSG_INPUT_TOO_LONG.format(n=3001) in _page_text(at)
    assert at.button(key="split_button").disabled is True
    assert at.button(key="example_S01").disabled is False
    with pytest.raises(Exception):
        at.button(key="split_button").click()
    assert calls == [exactly]


def test_pending_frame_disables_controls_and_clears_old_result_before_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, object]] = []

    def responder(text: str):
        seen.append(
            {
                "lock": bool(st.session_state.get(LOCK)),
                "result": st.session_state.get(RESULT),
                "error": st.session_state.get(ERROR),
            }
        )
        if "第二次" in text:
            return _ok(_result(summary="新结果摘要标记-BETA"))
        return _ok(_result(summary="旧结果摘要标记-ALPHA"))

    at, calls = _new_app(monkeypatch, responder)
    at.text_area[0].set_value("第一次需求").run()
    _finish_request(at)
    assert "旧结果摘要标记-ALPHA" in _page_text(at)

    at.text_area[0].set_value("第二次需求").run()
    _disarm(at)
    # AppTest 会在同一次 run() 里把 st.rerun() 接着跑完，所以这里直接看到最终页。
    # 请求进行中的禁用态由「锁已置上但还没有待执行正文」的那一拍单独断言。
    # 调用发生时的会话状态证明：旧结果在 agent.run 之前已经清掉，且锁仍然持有。
    at.button(key="split_button").click().run()
    _disarm(at)

    assert calls == ["第一次需求", "第二次需求"]
    assert seen[1]["lock"] is True
    assert seen[1]["result"] is None
    assert seen[1]["error"] is None
    assert at.session_state.get(LOCK) is not True
    finished = _page_text(at)
    assert "新结果摘要标记-BETA" in finished
    assert "旧结果摘要标记-ALPHA" not in finished
    at.run()
    _disarm(at)
    assert calls == ["第一次需求", "第二次需求"]


def test_armed_lock_runs_once_and_reentry_does_not_call_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app as app_module

    def responder(text: str):
        again = getattr(app_module, "_execute_locked_request", None)
        if again is not None and calls_box[0] == 0:
            calls_box[0] += 1
            again()
            return _ok(_result(summary="只应调用一次"))
        calls_box[0] += 1
        return _ok(_result(summary="只应调用一次"))

    calls_box = [0]
    at, calls = _new_app(monkeypatch, responder)
    # _new_app 的 calls 只记录进入 responder 的次数；重入不应增加它。
    at.session_state["input_text"] = "已锁定的输入"
    at.session_state[LOCK] = True
    at.session_state[PENDING] = "已锁定的输入"
    at.session_state[ARMED] = True
    at.run()
    _disarm(at)

    assert calls == ["已锁定的输入"]
    assert calls_box[0] == 1
    assert at.session_state.get(LOCK) is not True
    assert "只应调用一次" in _page_text(at)


def test_locked_session_disables_controls_without_calling_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """锁为真、但没有排进执行队列时，控件按锁重建为禁用，且不会调用 agent。

    Streamlit 会在同一次脚本线程里立刻接着跑 ``st.rerun()``，所以「正在拆解」
    那一拍在真实浏览器里会盖住旧结果，测试这里用已经置上的锁来核对禁用态。
    """

    at, calls = _new_app(monkeypatch, lambda text: _ok(_result()))
    at.session_state["input_text"] = "不要发出去"
    at.session_state[LOCK] = True
    at.session_state[PENDING] = None
    at.session_state[ARMED] = False
    at.run()

    assert calls == []
    assert at.session_state.get(LOCK) is True
    assert at.button(key="split_button").disabled is True
    assert at.button(key="split_button").label == "正在拆解…"
    assert at.text_area[0].disabled is True
    for key in ("example_S01", "example_S04", "example_S06"):
        assert at.button(key=key).disabled is True
    # 请求中只保留 pending 提示；失败后的手动「重试」不应在这一拍出现。
    with pytest.raises(KeyError):
        at.button(key="retry_button")


def test_exception_unlocks_and_keeps_manual_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def responder(text: str):
        raise RuntimeError("boom-marker-not-a-secret")

    at, calls = _new_app(monkeypatch, responder)
    at.session_state["input_text"] = "会抛异常的输入"
    at.session_state[LOCK] = True
    at.session_state[PENDING] = "会抛异常的输入"
    at.session_state[ARMED] = True
    at.run()
    _disarm(at)

    assert calls == ["会抛异常的输入"]
    assert at.session_state.get(LOCK) is not True
    text = _page_text(at)
    assert FALLBACK in text
    assert "boom-marker-not-a-secret" not in text
    assert at.button(key="retry_button").disabled is False

    _finish_retry(at)
    assert calls == ["会抛异常的输入", "会抛异常的输入"]
    assert at.session_state.get(LOCK) is not True
    assert FALLBACK in _page_text(at)


@pytest.mark.parametrize(
    "message",
    [
        config.MSG_MISSING_API_KEY,
        config.MSG_AUTH,
        config.MSG_TIMEOUT,
        config.MSG_UNAVAILABLE,
        config.MSG_RATE_LIMIT,
        config.MSG_PARSE_FAILED,
        FALLBACK,
    ],
)
def test_agent_failures_keep_original_text_and_manual_retry(
    monkeypatch: pytest.MonkeyPatch, message: str
) -> None:
    at, calls = _new_app(monkeypatch, lambda text: _fail(message))
    at.text_area[0].set_value("请拆这条").run()
    _finish_request(at)

    assert calls == ["请拆这条"]
    assert message in _page_text(at)
    assert at.button(key="retry_button").disabled is False
    assert "正在拆解…" not in at.button(key="split_button").label

    _finish_retry(at)
    assert calls == ["请拆这条", "请拆这条"]
    assert message in _page_text(at)


def test_parse_failure_folds_details_and_raw_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = "{这不是合法 JSON"
    details = "解析细节标记"

    at, calls = _new_app(
        monkeypatch,
        lambda text: _fail(
            config.MSG_PARSE_FAILED, raw_output=raw, details=details
        ),
    )
    at.text_area[0].set_value("格式会失败").run()
    _finish_request(at)

    assert calls == ["格式会失败"]
    assert config.MSG_PARSE_FAILED in _page_text(at)
    detail_box = _expander(at, "错误详情")
    raw_box = _expander(at, "原始输出")
    assert detail_box.proto.expanded is False
    assert raw_box.proto.expanded is False
    assert any(details in code.value for code in detail_box.code)
    assert any(raw in code.value for code in raw_box.code)
    assert at.button(key="retry_button").disabled is False


def test_success_attribution_follows_stripped_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at, calls = _new_app(
        monkeypatch, lambda text: _ok(_result(summary="归属测试摘要"))
    )
    at.text_area[0].set_value("  同一条需求  \n").run()
    _finish_request(at)

    assert calls == ["同一条需求"]
    assert ATTRIBUTION_CURRENT in _page_text(at)
    assert "归属测试摘要" in _page_text(at)

    at.text_area[0].set_value("同一条需求已经改了").run()
    _disarm(at)
    edited = _page_text(at)
    assert ATTRIBUTION_STALE in edited
    assert ATTRIBUTION_CURRENT not in edited
    assert "归属测试摘要" in edited
    assert calls == ["同一条需求"]

    at.text_area[0].set_value("\n同一条需求\n").run()
    _disarm(at)
    assert ATTRIBUTION_CURRENT in _page_text(at)
    assert ATTRIBUTION_STALE not in _page_text(at)


def test_over_limit_keeps_previous_result_and_empty_submit_does_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at, calls = _new_app(
        monkeypatch, lambda text: _ok(_result(summary="仍应留在页面上"))
    )
    at.text_area[0].set_value("原始需求").run()
    _finish_request(at)

    at.text_area[0].set_value("字" * 3001).run()
    _disarm(at)
    text = _page_text(at)
    assert "仍应留在页面上" in text
    assert ATTRIBUTION_STALE in text
    assert config.MSG_INPUT_TOO_LONG.format(n=3001) in text
    assert at.button(key="split_button").disabled is True
    assert calls == ["原始需求"]

    at.text_area[0].set_value("   ").run()
    _finish_request(at)
    text = _page_text(at)
    assert calls == ["原始需求"]
    assert config.MSG_EMPTY_INPUT in text
    assert "仍应留在页面上" in text
    assert ATTRIBUTION_STALE in text
    with pytest.raises(KeyError):
        at.button(key="retry_button")


def test_success_renders_full_fields_hides_estimate_and_exports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warning = "任务 T1 未被任何测试点覆盖"
    stored: dict[str, SplitResult] = {}

    def responder(text: str):
        result = _result(warning)
        stored["result"] = result
        return _ok(result)

    captured: list[dict[str, object]] = []
    original_add = MediaFileManager.add

    def spy_add(self, path_or_data, mimetype, coordinates, file_name=None, is_for_static_download=False):
        captured.append(
            {
                "data": path_or_data,
                "mime": mimetype,
                "file_name": file_name,
            }
        )
        return original_add(
            self,
            path_or_data,
            mimetype,
            coordinates,
            file_name,
            is_for_static_download,
        )

    monkeypatch.setattr(MediaFileManager, "add", spy_add)
    at, calls = _new_app(monkeypatch, responder)
    at.text_area[0].set_value("完整字段需求").run()
    _finish_request(at)

    assert calls == ["完整字段需求"]
    text = _page_text(at)
    assert config.MSG_UNCLEAR_HINT not in text
    assert "优惠券列表接口返回 500" in text
    assert "输入类型：缺陷" in text
    assert "让优惠券列表恢复可用。" in text
    assert "定位 500" in text
    assert "重做券样式" in text
    assert "网关日志可以查到" in text
    assert "T1" in text and "补齐优惠券列表错误处理" in text
    assert "优先级：高" in text
    assert "分类：后端" in text
    assert "依赖：无" in text
    assert "列表接口不再返回 500" in text
    assert "T2" in text and "优先级：中" in text
    assert "分类：前端" in text
    assert "依赖：T1" in text
    assert "T3" in text and "优先级：低" in text
    assert "分类：未分类" in text
    assert "验收标准" in text
    assert "TP1" in text and "打开优惠券列表" in text
    assert "类型：功能" in text
    assert "打开页面" in text
    assert "页面展示券列表而不是 500" in text
    assert "TP2" in text and "类型：错误处理" in text
    assert "Q1" in text and "为什么要问" in text
    assert "原文没有说明影响范围。" in text
    assert "是否阻塞：是" in text
    assert "先按全量故障处理。" in text
    assert "Q2" in text and "是否阻塞：否" in text
    assert "诉求覆盖完整：否" in text
    assert "置信度：低" in text
    assert "还缺一条空列表的回归" in text
    assert "estimate" not in text
    assert "工时" not in text

    warning_box = _expander(at, "校验提示")
    assert warning in _page_text(at)
    assert any(warning in item.value for item in warning_box.markdown)

    copy_box = _expander(at, "一键复制 Markdown")
    assert copy_box.proto.expanded is False
    assert "点击下方代码块右上角的复制图标即可复制。" in _page_text(at)
    markdown = to_markdown(stored["result"])
    shown = next(code.value for code in copy_box.code)
    # st.code 会丢掉末尾那一个换行；下载文件仍是 to_markdown 的完整文本。
    assert shown == markdown or shown + "\n" == markdown
    assert "estimate" not in markdown

    downloads = {item["file_name"]: item for item in captured}
    assert downloads["split_result.md"]["mime"] == "text/markdown"
    assert downloads["split_result.json"]["mime"] == "application/json"
    md_data = downloads["split_result.md"]["data"]
    json_data = downloads["split_result.json"]["data"]
    assert bytes(md_data).decode("utf-8") == markdown
    parsed = json.loads(bytes(json_data).decode("utf-8"))
    assert parsed["tasks"][0]["estimate"] == "M"
    assert parsed["tasks"][1]["estimate"] == "S"
    assert "warnings" not in parsed
    assert at.download_button(key="download_markdown").label == "下载 Markdown"
    assert at.download_button(key="download_json").label == "下载 JSON"


def test_unclear_hint_and_absent_warnings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at, _calls = _new_app(
        monkeypatch,
        lambda text: _ok(_result(input_type="unclear", summary="需求还说不清")),
    )
    at.text_area[0].set_value("弄好一点").run()
    _finish_request(at)
    text = _page_text(at)
    assert config.MSG_UNCLEAR_HINT in text
    assert "输入类型：描述不清楚" in text
    assert all(box.label != "校验提示" for box in at.expander)


def test_empty_lists_use_spec_wording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _payload(
        input_type="feature",
        summary="只有一个很小的任务。",
        understanding={
            "goal": "把一件事做完。",
            "in_scope": [],
            "out_of_scope": [],
            "assumptions": [],
        },
        tasks=[
            _task(
                category=None,
                acceptance_criteria=None,
                depends_on=[],
                estimate="M",
            )
        ],
        test_points=[
            _point(steps=None, priority=None, type="edge_case")
        ],
        questions=[],
        self_check={"coverage_ok": True, "issues": [], "confidence": "high"},
    )

    at, _calls = _new_app(
        monkeypatch,
        lambda text: _ok(SplitResult.model_validate(payload)),
    )
    at.text_area[0].set_value("小需求").run()
    _finish_request(at)
    text = _page_text(at)
    assert "输入类型：需求" in text
    assert "无" in text
    assert config.MSG_NO_QUESTIONS in text
    assert "发现的问题：无" in text
    assert "诉求覆盖完整：是" in text
    assert "置信度：高" in text
    assert "分类：未分类" in text
    assert "依赖：无" in text
    assert "验收标准" not in text
    assert "步骤" not in text
    assert "类型：边界" in text
    assert "estimate" not in text


def test_user_and_model_text_is_html_escaped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hostile = "<script>alert(1)</script>"
    payload = _payload(
        summary=hostile,
        understanding={
            "goal": hostile,
            "in_scope": [hostile],
            "out_of_scope": [],
            "assumptions": [],
        },
        tasks=[_task(title=hostile, description=hostile, acceptance_criteria=[hostile])],
        test_points=[_point(scenario=hostile, steps=[hostile], expected_result=hostile)],
        questions=[_question(question=hostile, why=hostile, impact=hostile)],
    )
    result = SplitResult.model_validate(payload)
    result._set_warnings([hostile])

    at, _calls = _new_app(monkeypatch, lambda text: _ok(result))
    at.text_area[0].set_value(hostile).run()
    _finish_request(at)

    for element in list(at.markdown) + list(at.error) + list(at.warning) + list(at.info):
        assert "<script" not in element.value.lower()
    assert "alert(1)" in _page_text(at)
    # 导出的 Markdown 保留原文，供复制和下载，不在代码块里做 HTML 转义。
    assert any(hostile in code.value for code in at.code)


def test_paper_theme_tokens_do_not_use_hashed_classes() -> None:
    source = APP_PATH.read_text(encoding="utf-8")
    assert "#F7F4EE" in source
    assert "#1C1814" in source
    assert "Noto Sans CJK SC" in source
    assert "prefers-reduced-motion" in source
    assert "st-emotion-cache" not in source
    config_path = ROOT / ".streamlit" / "config.toml"
    assert config_path.is_file()
    theme = config_path.read_text(encoding="utf-8")
    assert "#F7F4EE" in theme
    assert "#1C1814" in theme


def _expander(at: AppTest, label: str) -> Expander:
    for box in at.expander:
        if box.label == label:
            return box
    raise AssertionError(f"找不到展开区：{label}")
