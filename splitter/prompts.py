"""提示词读取与 messages 拼装。

system prompt 来自 ``prompts/system.md``，few-shot 示例来自
``prompts/examples/example_1.json``。user prompt 只放用户原文，不拼接
任何额外指令，保持与架构文档一致。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = [
    "EXAMPLE_PATH",
    "PROMPTS_DIR",
    "SYSTEM_PROMPT_PATH",
    "build_messages",
    "load_example",
    "load_system_prompt",
]

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system.md"
EXAMPLE_PATH = PROMPTS_DIR / "examples" / "example_1.json"

_USER_TEMPLATE = '以下是用户原文：\n"""{raw_input}"""'


def load_example() -> dict[str, Any]:
    """读取并返回 few-shot 示例（包含 ``input`` 与 ``output``）。"""

    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def load_system_prompt() -> str:
    """返回 system prompt：system.md 正文 + 一条短 few-shot 示例。"""

    system = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
    example = json.dumps(load_example(), ensure_ascii=False, indent=2)
    return (
        f"{system}\n\n"
        "# few-shot 示例（输入 → 输出，仅一条短示例）\n\n"
        f"{example}\n"
    )


def build_messages(raw_input: str) -> list[dict[str, str]]:
    """拼装一次 DeepSeek 调用所需的 messages。

    返回 ``[system, user]``；user 正文固定为架构文档要求的格式，只替换
    用户原文，不追加其他内容。
    """

    return [
        {"role": "system", "content": load_system_prompt()},
        {
            "role": "user",
            "content": _USER_TEMPLATE.format(raw_input=raw_input),
        },
    ]
