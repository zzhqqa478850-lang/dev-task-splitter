"""仅测试进程使用的启动器。

产品 ``app.py`` 不会读取这里的环境变量，也没有测试开关。
本进程先替换 ``splitter.agent.run``，再启动 Streamlit，因此页面走的是
真实前端，模型调用停在这个假的 ``agent.run``。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURE = Path(os.environ["DTS_FIXTURE_DIR"])


def _read_mode() -> str:
    path = FIXTURE / "mode.txt"
    if not path.exists():
        return "fast"
    return path.read_text(encoding="utf-8").strip() or "fast"


def _record(name: str, text: str) -> None:
    path = FIXTURE / name
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text.replace("\n", " ") + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _result_for(text: str):
    from splitter.agent import AgentResult
    from splitter.schema import SplitResult

    summary = (
        "新结果摘要标记-BETA"
        if "第二次" in text
        else "旧结果摘要标记-ALPHA"
    )
    payload = {
        "input_type": "bug",
        "summary": summary,
        "understanding": {
            "goal": "让优惠券列表恢复可用。",
            "in_scope": ["定位 500", "补回归测试"],
            "out_of_scope": ["重做券样式"],
            "assumptions": ["网关日志可以查到"],
        },
        "tasks": [
            {
                "id": "T1",
                "title": "补齐优惠券列表错误处理",
                "description": "定位列表接口 500 并给出可验证的修复。",
                "priority": "P0",
                "category": "backend",
                "estimate": "M",
                "depends_on": [],
                "acceptance_criteria": ["列表接口不再返回 500"],
            },
            {
                "id": "T2",
                "title": "补列表页错误提示",
                "description": "接口失败时给出可理解的提示。",
                "priority": "P1",
                "category": "frontend",
                "estimate": "S",
                "depends_on": ["T1"],
                "acceptance_criteria": ["失败时不展示空白页"],
            },
        ],
        "test_points": [
            {
                "id": "TP1",
                "task_ids": ["T1"],
                "type": "functional",
                "scenario": "打开优惠券列表",
                "steps": ["打开页面", "等待列表返回"],
                "expected_result": "页面展示券列表而不是 500",
                "priority": "P0",
            }
        ],
        "questions": [
            {
                "id": "Q1",
                "question": "500 是全量用户还是单个活动？",
                "why": "原文没有说明影响范围。",
                "impact": "会影响修复优先级和回归范围。",
                "affected_task_ids": ["T1"],
                "blocking": True,
                "suggested_default": "先按全量故障处理。",
            }
        ],
        "self_check": {
            "coverage_ok": False,
            "issues": ["还缺一条空列表的回归"],
            "confidence": "low",
        },
    }
    result = SplitResult.model_validate(payload)
    result._set_warnings(["任务 T1 未被任何测试点覆盖"])
    return AgentResult(ok=True, result=result, warnings=result.warnings, attempts=1)


def _install_fake() -> None:
    import splitter.agent as agent_module

    def fake(text: str):
        _record("calls.log", text)
        mode = _read_mode()
        if mode == "raise":
            raise RuntimeError("boom-marker-not-a-secret")
        if mode == "slow":
            _record("entered.log", text)
            deadline = time.time() + 30
            release = FIXTURE / "release"
            while time.time() < deadline and not release.exists():
                time.sleep(0.05)
        return _result_for(text)

    agent_module.run = fake


def main() -> None:
    _install_fake()
    port = os.environ["DTS_PORT"]
    sys.argv = [
        "streamlit",
        "run",
        str(ROOT / "app.py"),
        "--server.port",
        port,
        "--server.address",
        "127.0.0.1",
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
        "--server.fileWatcherType",
        "none",
        "--logger.level",
        "error",
    ]
    from streamlit.web.cli import main as streamlit_main

    streamlit_main()


if __name__ == "__main__":
    main()
