"""用真实浏览器核对请求锁的可见行为。

AppTest 会在同一次 ``run()`` 里把 ``st.rerun()`` 接着跑完，看不到
「控件已禁用、旧结果已清掉、agent 还没返回」那一帧。这里另起一个
只属于测试进程的 Streamlit，假的 ``agent.run`` 由启动器替换，产品代码
没有测试开关。
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HARNESS = Path(__file__).resolve().parent / "live_ui_harness.py"
ARTIFACTS = Path("/opt/cursor/artifacts")

ALPHA = "旧结果摘要标记-ALPHA"
BETA = "新结果摘要标记-BETA"
FALLBACK = "拆解失败，请稍后重试。"
BOOM = "boom-marker-not-a-secret"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_until_ready(port: int, proc: subprocess.Popen[bytes]) -> None:
    url = f"http://127.0.0.1:{port}/_stcore/health"
    deadline = time.time() + 40
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"Streamlit 提前退出，code={proc.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(0.2)
    raise RuntimeError("Streamlit 健康检查超时")


def _calls(fixture: Path) -> list[str]:
    path = fixture / "calls.log"
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line]


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode)


def _set_text(page: Page, value: str) -> None:
    """填入文本并让输入框失焦，Streamlit 才会把新值带回服务端。"""

    area = page.locator("textarea")
    area.fill(value)
    area.press("Tab")


def _shown(page: Page, text: str) -> int:
    """只数用户看得到的文字。Streamlit 在脚本结束前可能留着零尺寸的旧节点。"""

    return page.get_by_text(text).filter(visible=True).count()


def _overflow(page: Page) -> int:
    return int(
        page.evaluate(
            """() => document.documentElement.scrollWidth
            - document.documentElement.clientWidth"""
        )
    )


def _shoot(page: Page, name: str) -> None:
    """截整页。Streamlit 在内部容器里滚动，先放开再按内容高度截。"""

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    height = page.evaluate(
        """() => {
            const nodes = document.querySelectorAll(
                '.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"], [data-testid="stMainBlockContainer"]'
            );
            nodes.forEach((el) => {
                el.style.overflow = 'visible';
                el.style.height = 'auto';
                el.style.maxHeight = 'none';
            });
            const block = document.querySelector('[data-testid="stMainBlockContainer"]');
            const bottom = block
                ? Math.ceil(block.getBoundingClientRect().bottom + window.scrollY)
                : 0;
            return Math.max(bottom + 32, document.body.scrollHeight, 900);
        }"""
    )
    page.set_viewport_size({"width": 1440, "height": int(height)})
    page.screenshot(path=str(ARTIFACTS / name), full_page=False)


@pytest.fixture(scope="module")
def live_app(tmp_path_factory: pytest.TempPathFactory):
    fixture = tmp_path_factory.mktemp("live-ui")
    _write(fixture / "mode.txt", "fast")
    port = _free_port()
    log_path = fixture / "server.log"
    log_handle = log_path.open("wb")
    env = os.environ.copy()
    env["DTS_FIXTURE_DIR"] = str(fixture)
    env["DTS_PORT"] = str(port)
    env.pop("DEEPSEEK_API_KEY", None)
    proc = subprocess.Popen(
        [sys.executable, str(HARNESS)],
        cwd=str(ROOT),
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        _wait_until_ready(port, proc)
        yield {"port": port, "fixture": fixture, "log": log_path}
    finally:
        (fixture / "release").write_text("1", encoding="utf-8")
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
        log_handle.close()


def test_live_browser_shows_pending_lock_and_unlock(live_app: dict) -> None:
    port = live_app["port"]
    fixture: Path = live_app["fixture"]
    url = f"http://127.0.0.1:{port}"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path="/usr/local/bin/google-chrome",
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(url, wait_until="domcontentloaded")
        expect(page.get_by_role("button", name="拆解", exact=True)).to_be_enabled()
        expect(page.get_by_text("字数：0 / 3000")).to_be_visible()
        expect(page.get_by_text("设计提案")).to_have_count(0)
        assert _overflow(page) <= 1
        submit_box = page.get_by_role("button", name="拆解", exact=True).bounding_box()
        assert submit_box is not None and submit_box["height"] >= 44
        example_box = page.get_by_role(
            "button", name="S01 需求：优惠码兑换"
        ).bounding_box()
        assert example_box is not None and example_box["height"] >= 44
        _shoot(page, "ui-desktop-1440-empty-no-model-call.png")

        page.get_by_role("button", name="拆解", exact=True).click()
        expect(page.get_by_text("请先粘贴需求或 bug 描述。")).to_be_visible()
        expect(page.get_by_role("button", name="重试")).to_have_count(0)
        assert _calls(fixture) == []

        _set_text(page, "字" * 3001)
        expect(page.get_by_text("当前 3001 字，超过 3000 字上限，请删减后再试。")).to_be_visible()
        expect(page.get_by_role("button", name="拆解", exact=True)).to_be_disabled()
        assert page.locator("textarea").input_value() == "字" * 3001
        assert _calls(fixture) == []

        _set_text(page, "第一次需求")
        expect(page.get_by_text("字数：5 / 3000")).to_be_visible()
        expect(page.get_by_role("button", name="拆解", exact=True)).to_be_enabled()
        page.get_by_role("button", name="拆解", exact=True).click()
        expect(page.get_by_text(ALPHA)).to_be_visible(timeout=15000)
        expect(page.get_by_text("以下结果对应本次提交的输入。")).to_be_visible()
        assert _calls(fixture) == ["第一次需求"]

        _write(fixture / "mode.txt", "slow")
        if (fixture / "release").exists():
            (fixture / "release").unlink()
        _set_text(page, "第二次需求")
        expect(page.get_by_text("以下结果对应上次提交，当前输入已修改，尚未重新拆解。")).to_be_visible()
        page.get_by_role("button", name="拆解", exact=True).click()

        deadline = time.time() + 15
        while time.time() < deadline:
            entered = (
                (fixture / "entered.log").read_text(encoding="utf-8")
                if (fixture / "entered.log").exists()
                else ""
            )
            pending = page.get_by_role("button", name="正在拆解…")
            if "第二次需求" in entered and pending.count() and pending.is_disabled():
                break
            time.sleep(0.1)
        else:
            buttons = page.locator("button").all_inner_texts()
            entered = (
                (fixture / "entered.log").read_text(encoding="utf-8")
                if (fixture / "entered.log").exists()
                else ""
            )
            raise AssertionError(
                "没有看到请求中的禁用页。"
                f" calls={_calls(fixture)!r}"
                f" entered={entered!r}"
                f" buttons={buttons!r}"
            )

        assert _calls(fixture) == ["第一次需求", "第二次需求"]
        assert _shown(page, ALPHA) == 0
        assert _shown(page, BETA) == 0
        assert _shown(page, "需求理解") == 0
        assert _shown(page, "验收标准") == 0
        expect(page.get_by_text("正在拆解…").first).to_be_visible()
        expect(page.locator("textarea").filter(visible=True)).to_be_disabled()
        for name in (
            "S01 需求：优惠码兑换",
            "S04 模糊：系统弄好一点",
            "S06 Bug：优惠券页 500",
        ):
            expect(page.get_by_role("button", name=name)).to_be_disabled()
        expect(page.get_by_role("button", name="重试")).to_be_disabled()
        assert _overflow(page) <= 1
        _shoot(page, "ui-desktop-1440-loading-mock-fixture.png")

        page.get_by_role("button", name="正在拆解…").click(force=True)
        page.get_by_role("button", name="S01 需求：优惠码兑换").click(force=True)
        page.get_by_role("button", name="重试").click(force=True)
        time.sleep(0.6)
        assert _calls(fixture) == ["第一次需求", "第二次需求"]

        _write(fixture / "release", "1")
        expect(page.get_by_text(BETA).filter(visible=True)).to_be_visible(timeout=15000)
        assert _shown(page, ALPHA) == 0
        expect(page.get_by_role("button", name="拆解", exact=True)).to_be_enabled()
        expect(page.get_by_text("以下结果对应本次提交的输入。")).to_be_visible()
        expect(page.get_by_text("验收标准").first).to_be_visible()
        expect(page.get_by_text("优先级：高").first).to_be_visible()
        expect(page.get_by_text("工时")).to_have_count(0)
        assert _calls(fixture) == ["第一次需求", "第二次需求"]
        assert _overflow(page) <= 1
        _shoot(page, "ui-desktop-1440-success-mock-fixture.png")

        _set_text(page, "第二次需求已修改")
        expect(page.get_by_text("以下结果对应上次提交，当前输入已修改，尚未重新拆解。")).to_be_visible(
            timeout=10000
        )
        expect(page.get_by_text(BETA).first).to_be_visible()
        assert _calls(fixture) == ["第一次需求", "第二次需求"]

        _write(fixture / "mode.txt", "raise")
        _set_text(page, "会失败的输入")
        page.get_by_role("button", name="拆解", exact=True).click()
        expect(page.get_by_text(FALLBACK).filter(visible=True)).to_be_visible(timeout=15000)
        assert _shown(page, BOOM) == 0
        assert _shown(page, BETA) == 0
        expect(page.get_by_role("button", name="拆解", exact=True)).to_be_enabled()
        expect(page.get_by_role("button", name="重试")).to_be_enabled()
        expect(page.locator("textarea")).to_be_enabled()
        assert _calls(fixture) == ["第一次需求", "第二次需求", "会失败的输入"]
        assert _overflow(page) <= 1
        _shoot(page, "ui-desktop-1440-error-mock-fixture.png")

        page.get_by_role("button", name="重试").click()
        expected = [
            "第一次需求",
            "第二次需求",
            "会失败的输入",
            "会失败的输入",
        ]
        deadline = time.time() + 10
        while time.time() < deadline and _calls(fixture) != expected:
            time.sleep(0.1)
        expect(page.get_by_text(FALLBACK).first).to_be_visible()
        expect(page.get_by_role("button", name="重试")).to_be_enabled()
        expect(page.get_by_role("button", name="拆解", exact=True)).to_be_enabled()
        assert _calls(fixture) == expected
        browser.close()
