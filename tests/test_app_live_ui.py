"""用真实浏览器核对请求锁的可见行为。

AppTest 会在同一次 ``run()`` 里把 ``st.rerun()`` 接着跑完，看不到
「控件已禁用、旧结果已清掉、agent 还没返回」那一帧。这里另起一个
只属于测试进程的 Streamlit，假的 ``agent.run`` 由启动器替换，产品代码
没有测试开关。

覆盖两条路径：
1. 成功 → 再次提交：请求中不得残留上一轮结果、展开器和导出，也不得出现
   可被误认成可操作的「重试」。
2. 失败（异常）→ 手动重试：异常后锁必须打开、手动「重试」可点；点击重试
   进入 pending 时，旧错误条和旧结果同样必须从画面消失。
"""

from __future__ import annotations

import os
import shutil
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
ARTIFACTS = Path(
    os.environ.get("DTS_ARTIFACTS_DIR", "/opt/cursor/artifacts")
)

ALPHA = "旧结果摘要标记-ALPHA"
BETA = "新结果摘要标记-BETA"
FALLBACK = "拆解失败，请稍后重试。"
BOOM = "boom-marker-not-a-secret"

# 旧结果区里一旦在 pending 可见，就说明隐藏失败。
STALE_RESULT_TEXTS = (
    ALPHA,
    BETA,
    "摘要",
    "需求理解",
    "任务",
    "测试点",
    "问题",
    "自检",
    "验收标准",
    "校验提示",
    "一键复制 Markdown",
    "下载 Markdown",
    "下载 JSON",
    "导出",
    "以下结果对应本次提交的输入。",
    "以下结果对应上次提交，当前输入已修改，尚未重新拆解。",
    FALLBACK,
)


def _chrome_path() -> str:
    candidates = (
        os.environ.get("DTS_CHROME_PATH"),
        "/usr/local/bin/google-chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
    )
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise RuntimeError("找不到可用的 Chrome/Chromium 可执行文件")


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

    area = page.locator("textarea").filter(visible=True)
    area.fill(value)
    area.press("Tab")


def _shown(page: Page, text: str) -> int:
    """只数用户看得到的文字。Streamlit 会暂留零尺寸或 display:none 的旧节点。"""

    return page.get_by_text(text, exact=True).filter(visible=True).count()


def _overflow(page: Page) -> int:
    return int(
        page.evaluate(
            """() => document.documentElement.scrollWidth
            - document.documentElement.clientWidth"""
        )
    )


def _button_style(page: Page, selector: str) -> dict | None:
    """读当前可见按钮/输入框的禁用态，避开同一 key 的 stale 旧节点。"""

    return page.evaluate(
        """(selector) => {
            const visible = (el) => {
                if (!el) return false;
                const cs = getComputedStyle(el);
                const box = el.getBoundingClientRect();
                return cs.display !== 'none' && cs.visibility !== 'hidden'
                    && Number(cs.opacity) > 0 && box.width > 0 && box.height > 0;
            };
            const el = [...document.querySelectorAll(selector)].find(visible);
            if (!el) return null;
            const label = el.querySelector('p, [data-testid="stMarkdownContainer"] p') || el;
            const cs = getComputedStyle(el);
            const ls = getComputedStyle(label);
            const box = el.getBoundingClientRect();
            return {
                tag: el.tagName,
                disabled: Boolean(el.disabled),
                text: (el.innerText || '').trim(),
                bg: cs.backgroundColor,
                color: cs.color,
                textColor: ls.color,
                webkitTextFillColor: cs.webkitTextFillColor,
                cursor: cs.cursor,
                width: box.width,
                height: box.height,
            };
        }""",
        selector,
    )


def _rgb(value: str) -> tuple[int, int, int]:
    parts = value.removeprefix("rgb(").removesuffix(")").split(",")
    return tuple(int(part.strip()) for part in parts[:3])  # type: ignore[return-value]


def _contrast(foreground: str, background: str) -> float:
    def luminance(rgb: tuple[int, int, int]) -> float:
        channels = []
        for value in rgb:
            s = value / 255
            channels.append(
                s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4
            )
        return (
            0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
        )

    a = luminance(_rgb(foreground))
    b = luminance(_rgb(background))
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def _assert_contrast(style: dict | None, minimum: float = 4.5) -> None:
    assert style is not None, style
    ratio = _contrast(style["textColor"], style["bg"])
    assert ratio >= minimum, (ratio, style)


def _visible_clean_snapshot(page: Page) -> dict:
    """数当前真正占据画面、且属于结果区/导出区/旧的 pending 重试的节点。"""

    return page.evaluate(
        """() => {
            const visible = (el) => {
                if (!el) return false;
                const cs = getComputedStyle(el);
                const box = el.getBoundingClientRect();
                return cs.display !== 'none' && cs.visibility !== 'hidden'
                    && Number(cs.opacity) > 0 && box.width > 0 && box.height > 0;
            };
            const count = (selector) =>
                [...document.querySelectorAll(selector)].filter(visible).length;
            const borderedOutsideInput = [
                ...document.querySelectorAll(
                    '[data-testid="stVerticalBlock"], [data-testid="stVerticalBlockBorderWrapper"]'
                ),
            ].filter((el) => {
                if (!visible(el) || el.closest('.st-key-input_card')) return false;
                const cs = getComputedStyle(el);
                return parseFloat(cs.borderTopWidth) > 0
                    && cs.borderTopStyle !== 'none';
            }).length;
            return {
                expanders: count('[data-testid="stExpander"]'),
                downloads: count('[data-testid="stDownloadButton"]'),
                codeBlocks: count('[data-testid="stCode"]'),
                borderedOutsideInput,
                retryVisible: count('.st-key-retry_button'),
                retryTotal: document.querySelectorAll('.st-key-retry_button').length,
            };
        }"""
    )


def _assert_pending_clean(
    page: Page, fixture: Path, expected_calls: list[str]
) -> None:
    """pending 的任意时刻：旧结果区不可见、无 pending 重试、禁用态可感知。"""

    for text in STALE_RESULT_TEXTS:
        assert _shown(page, text) == 0, f"pending 仍看见旧结果文字：{text!r}"

    snap = _visible_clean_snapshot(page)
    assert snap["expanders"] == 0, snap
    assert snap["downloads"] == 0, snap
    assert snap["codeBlocks"] == 0, snap
    assert snap["borderedOutsideInput"] == 0, snap
    assert snap["retryVisible"] == 0, snap

    split = _button_style(page, ".st-key-split_button button")
    examples = [
        _button_style(page, f".st-key-example_{key} button")
        for key in ("S01", "S04", "S06")
    ]
    textarea = _button_style(page, "textarea")
    assert split is not None and split["disabled"] is True, split
    assert split["text"] == "正在拆解…", split
    assert split["bg"] == "rgb(241, 237, 228)", split
    assert split["textColor"] == "rgb(94, 86, 76)", split
    _assert_contrast(split)
    for example in examples:
        assert example is not None and example["disabled"] is True, example
        # 可用示例是 #F1EDE4。禁用必须换成更灰的 #E4DDD2，不能只改一个看不出来的字色。
        assert example["bg"] == "rgb(228, 221, 210)", example
        assert example["textColor"] == "rgb(94, 86, 76)", example
        _assert_contrast(example)
    assert textarea is not None and textarea["disabled"] is True, textarea
    assert textarea["bg"] == "rgb(241, 237, 228)", textarea
    assert textarea["color"] == "rgb(94, 86, 76)", textarea
    assert textarea["webkitTextFillColor"] == "rgb(94, 86, 76)", textarea

    # 多时点重复核对，别只看首帧。
    assert _calls(fixture) == expected_calls


def _sample_pending(
    page: Page, fixture: Path, expected_calls: list[str], *, samples: int = 5
) -> None:
    for _ in range(samples):
        _assert_pending_clean(page, fixture, expected_calls)
        time.sleep(0.15)


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


def _wait_for_pending(
    page: Page, fixture: Path, text: str, expected_call_count: int
) -> None:
    deadline = time.time() + 15
    while time.time() < deadline:
        calls = _calls(fixture)
        entered = (
            (fixture / "entered.log").read_text(encoding="utf-8")
            if (fixture / "entered.log").exists()
            else ""
        )
        pending = page.get_by_role("button", name="正在拆解…")
        if (
            len(calls) == expected_call_count
            and calls[-1] == text
            and text in entered
            and pending.count()
            and pending.is_disabled()
        ):
            return
        time.sleep(0.05)
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


def test_live_browser_pending_hides_old_result_and_retry_paths(
    live_app: dict,
) -> None:
    port = live_app["port"]
    fixture: Path = live_app["fixture"]
    url = f"http://127.0.0.1:{port}"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=_chrome_path(),
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(url, wait_until="domcontentloaded")
        # 先证明空态可用控件的视觉与禁用态不同。
        submit = page.get_by_role("button", name="拆解", exact=True)
        expect(submit).to_be_enabled()
        page.locator("textarea").first.wait_for()
        enabled_split = _button_style(page, ".st-key-split_button button")
        enabled_example = _button_style(page, ".st-key-example_S01 button")
        enabled_textarea = _button_style(page, "textarea")
        assert enabled_split is not None and enabled_split["disabled"] is False
        assert enabled_split["textColor"] == "rgb(247, 244, 238)", enabled_split
        assert enabled_split["height"] >= 44, enabled_split
        _assert_contrast(enabled_split)
        submit.hover()
        _assert_contrast(_button_style(page, ".st-key-split_button button"))
        submit.focus()
        _assert_contrast(_button_style(page, ".st-key-split_button button"))
        assert enabled_example is not None and enabled_example["disabled"] is False
        assert enabled_example["bg"] == "rgb(241, 237, 228)", enabled_example
        assert enabled_example["textColor"] == "rgb(28, 24, 20)", enabled_example
        assert enabled_example["height"] >= 44, enabled_example
        _assert_contrast(enabled_example)
        assert enabled_textarea is not None
        assert enabled_textarea["disabled"] is False
        assert enabled_textarea["bg"] == "rgb(253, 251, 247)", enabled_textarea
        expect(page.get_by_text("字数：0 / 3000")).to_be_visible()
        expect(page.get_by_text("设计提案")).to_have_count(0)
        assert _overflow(page) <= 1
        _shoot(page, "ui-desktop-1440-empty-no-model-call.png")

        # 空提交只做预校验，不调用 agent，不出现失败重试。
        submit.click()
        expect(page.get_by_text("请先粘贴需求或 bug 描述。")).to_be_visible()
        expect(page.get_by_role("button", name="重试")).to_have_count(0)
        assert _calls(fixture) == []

        _set_text(page, "字" * 3001)
        expect(
            page.get_by_text("当前 3001 字，超过 3000 字上限，请删减后再试。")
        ).to_be_visible()
        expect(page.get_by_role("button", name="拆解", exact=True)).to_be_disabled()
        assert page.locator("textarea").filter(visible=True).input_value() == "字" * 3001
        assert _calls(fixture) == []

        # ---- 路径 1：成功 → 再次提交 pending ----
        _set_text(page, "第一次需求")
        expect(page.get_by_text("字数：5 / 3000")).to_be_visible()
        page.get_by_role("button", name="拆解", exact=True).click()
        expect(page.get_by_text(ALPHA).filter(visible=True)).to_be_visible(
            timeout=15000
        )
        expect(page.get_by_text("以下结果对应本次提交的输入。")).to_be_visible()
        expect(page.locator('[data-testid="stExpander"]').filter(visible=True)).to_have_count(2)
        expect(
            page.locator('[data-testid="stDownloadButton"]').filter(visible=True)
        ).to_have_count(2)
        assert _calls(fixture) == ["第一次需求"]

        _write(fixture / "mode.txt", "slow")
        if (fixture / "release").exists():
            (fixture / "release").unlink()
        _set_text(page, "第二次需求")
        expect(
            page.get_by_text("以下结果对应上次提交，当前输入已修改，尚未重新拆解。")
        ).to_be_visible()
        page.get_by_role("button", name="拆解", exact=True).click()
        _wait_for_pending(page, fixture, "第二次需求", 2)

        expected = ["第一次需求", "第二次需求"]
        _sample_pending(page, fixture, expected)

        # 禁用控件被强行点击也不能再发请求；pending 不画重试。
        page.get_by_role("button", name="正在拆解…").click(force=True)
        page.get_by_role("button", name="S01 需求：优惠码兑换").click(force=True)
        expect(page.get_by_role("button", name="重试")).to_have_count(0)
        time.sleep(0.5)
        assert _calls(fixture) == expected
        _shoot(page, "ui-desktop-1440-loading-after-success-mock-fixture.png")

        _write(fixture / "release", "1")
        expect(page.get_by_text(BETA).filter(visible=True)).to_be_visible(timeout=15000)
        assert _shown(page, ALPHA) == 0
        expect(page.get_by_role("button", name="拆解", exact=True)).to_be_enabled()
        expect(page.get_by_text("以下结果对应本次提交的输入。")).to_be_visible()
        expect(page.get_by_text("验收标准").first).to_be_visible()
        expect(page.get_by_text("优先级：高").first).to_be_visible()
        expect(page.get_by_text("工时")).to_have_count(0)
        assert _calls(fixture) == expected
        assert _overflow(page) <= 1
        _shoot(page, "ui-desktop-1440-success-mock-fixture.png")

        # ---- 路径 2：异常失败 → 手动重试 pending ----
        _write(fixture / "mode.txt", "slow-raise")
        if (fixture / "release").exists():
            (fixture / "release").unlink()
        _set_text(page, "会失败的输入")
        page.get_by_role("button", name="拆解", exact=True).click()
        _wait_for_pending(page, fixture, "会失败的输入", 3)

        expected = ["第一次需求", "第二次需求", "会失败的输入"]
        _sample_pending(page, fixture, expected)
        page.get_by_role("button", name="正在拆解…").click(force=True)
        page.get_by_role("button", name="S01 需求：优惠码兑换").click(force=True)
        time.sleep(0.5)
        assert _calls(fixture) == expected

        _write(fixture / "release", "1")
        expect(page.get_by_text(FALLBACK).filter(visible=True)).to_be_visible(
            timeout=15000
        )
        assert _shown(page, BOOM) == 0
        assert _shown(page, BETA) == 0
        expect(page.get_by_role("button", name="拆解", exact=True)).to_be_enabled()
        expect(page.get_by_role("button", name="重试").filter(visible=True)).to_be_enabled()
        expect(page.locator("textarea").filter(visible=True)).to_be_enabled()
        assert _calls(fixture) == expected
        assert _overflow(page) <= 1
        _shoot(page, "ui-desktop-1440-error-mock-fixture.png")

        # 失败完成后手动重试：进入 pending 时旧错误条也必须消失。
        _write(fixture / "mode.txt", "slow")
        if (fixture / "release").exists():
            (fixture / "release").unlink()
        page.get_by_role("button", name="重试").filter(visible=True).click()
        _wait_for_pending(page, fixture, "会失败的输入", 4)

        expected = [
            "第一次需求",
            "第二次需求",
            "会失败的输入",
            "会失败的输入",
        ]
        _sample_pending(page, fixture, expected)
        page.get_by_role("button", name="正在拆解…").click(force=True)
        page.get_by_role("button", name="S01 需求：优惠码兑换").click(force=True)
        expect(page.get_by_role("button", name="重试")).to_have_count(0)
        time.sleep(0.5)
        assert _calls(fixture) == expected
        _shoot(page, "ui-desktop-1440-loading-after-retry-mock-fixture.png")

        _write(fixture / "release", "1")
        expect(page.get_by_text(ALPHA).filter(visible=True)).to_be_visible(timeout=15000)
        expect(page.get_by_role("button", name="拆解", exact=True)).to_be_enabled()
        expect(page.get_by_role("button", name="重试")).to_have_count(0)
        expect(page.get_by_text("以下结果对应本次提交的输入。")).to_be_visible()
        assert _calls(fixture) == expected
        assert _overflow(page) <= 1
        _shoot(page, "ui-desktop-1440-retry-success-mock-fixture.png")

        browser.close()
