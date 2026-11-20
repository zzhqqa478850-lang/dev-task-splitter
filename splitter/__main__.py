"""命令行入口：``python -m splitter --input <文件路径>``。"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import agent

__all__ = ["main"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m splitter",
        description="把杂乱的软件需求 / bug 描述拆成任务、测试点和待澄清问题。",
    )
    parser.add_argument(
        "--input",
        dest="input_path",
        required=True,
        metavar="PATH",
        help="包含需求或 bug 原文的 UTF-8 文本文件路径",
    )
    return parser


def _print_success(result: agent.AgentResult, elapsed: float) -> None:
    split = result.result
    if split is None:  # pragma: no cover - 成功结果必有 result
        print("运行失败：未返回结构化结果。", file=sys.stderr)
        return

    print(f"摘要：{split.summary}")
    print(
        f"任务：{len(split.tasks)} 个；"
        f"测试点：{len(split.test_points)} 个；"
        f"待澄清问题：{len(split.questions)} 个"
    )
    print(f"耗时：{elapsed:.2f} 秒")
    print(f"是否重试：{'是' if result.retried else '否'}")
    if result.warnings:
        print("提示：")
        for warning in result.warnings:
            print(f"- {warning}")


def _print_failure(result: agent.AgentResult) -> None:
    print(f"错误：{result.error}", file=sys.stderr)
    print(f"已调用接口：{result.attempts} 次", file=sys.stderr)
    if result.details:
        print(f"详细信息：{result.details}", file=sys.stderr)
    if result.raw_output is not None:
        print("原始输出：", file=sys.stderr)
        print(result.raw_output or "（空）", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    path = Path(args.input_path)

    try:
        raw_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        print(f"错误：无法读取输入文件 {path}：{exc}", file=sys.stderr)
        return 1

    started = time.perf_counter()
    try:
        result = agent.run(raw_text)
    except Exception as exc:  # 兜底：命令行不向用户抛 traceback
        elapsed = time.perf_counter() - started
        print(f"错误：运行失败：{exc}", file=sys.stderr)
        print(f"耗时：{elapsed:.2f} 秒", file=sys.stderr)
        return 1
    elapsed = time.perf_counter() - started

    if not result.ok:
        _print_failure(result)
        print(f"耗时：{elapsed:.2f} 秒", file=sys.stderr)
        return 1

    _print_success(result, elapsed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
