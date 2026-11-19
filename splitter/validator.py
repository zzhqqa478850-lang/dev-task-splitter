"""解析与校验模型输出。

校验顺序：

1. 空内容检查；
2. ``json.loads``（失败视为格式错误/截断）；
3. ``SplitResult.model_validate``（字段、类型、枚举、额外字段）；
4. 业务规则硬校验 + 软规则 warning。

本模块只做确定性校验，不调用 LLM。
"""

from __future__ import annotations

import json

from .schema import SplitResult, Task

__all__ = [
    "BusinessRuleError",
    "DuplicateIdError",
    "EmptyContentError",
    "InvalidJSONError",
    "RefError",
    "SplitterValidationError",
    "parse_and_validate",
    "validate_result",
]


class SplitterValidationError(ValueError):
    """校验相关异常的基类。"""


class EmptyContentError(SplitterValidationError):
    """模型返回空内容。"""


class InvalidJSONError(SplitterValidationError):
    """输出不是合法 JSON（格式错误或被截断）。"""


class BusinessRuleError(SplitterValidationError):
    """业务规则硬校验失败。"""


class DuplicateIdError(BusinessRuleError):
    """同一集合内 id 重复。"""


class RefError(BusinessRuleError):
    """引用了不存在的任务 id。"""


def parse_and_validate(raw: str) -> SplitResult:
    """把模型原始输出解析并校验为 ``SplitResult``。

    失败时抛出异常：

    - 空内容：:class:`EmptyContentError`
    - JSON 非法/截断：:class:`InvalidJSONError`
    - schema 不匹配：``pydantic.ValidationError``
    - 业务硬规则失败：:class:`BusinessRuleError`（或其子类）

    软规则 warning 会写入返回对象的 ``warnings`` 属性，不影响成功。
    """

    if not isinstance(raw, str):
        raise TypeError("raw 必须是字符串")
    if not raw.strip():
        raise EmptyContentError("模型输出为空")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InvalidJSONError(
            f"JSON 解析失败：第 {exc.lineno} 行第 {exc.colno} 列，{exc.msg}"
        ) from exc

    # 保留 pydantic.ValidationError，便于按 errors() 精简后回传模型重试。
    result = SplitResult.model_validate(data)
    validate_result(result)
    return result


def validate_result(result: SplitResult) -> list[str]:
    """执行业务规则校验，返回软规则 warning 列表。

    硬规则失败会抛异常；软规则只记录 warning，并同时挂到
    ``result.warnings`` 上。
    """

    warnings: list[str] = []

    # 硬规则 1：各集合内 id 唯一。
    _ensure_unique("任务", [task.id for task in result.tasks])
    _ensure_unique("测试点", [point.id for point in result.test_points])
    _ensure_unique("问题", [question.id for question in result.questions])

    task_ids = {task.id for task in result.tasks}

    # 硬规则 2：所有任务引用都必须指向已存在的任务。
    for task in result.tasks:
        _ensure_refs(f"任务 {task.id} 的 depends_on", task.depends_on, task_ids)
    for point in result.test_points:
        _ensure_refs(f"测试点 {point.id} 的 task_ids", point.task_ids, task_ids)
    for question in result.questions:
        _ensure_refs(
            f"问题 {question.id} 的 affected_task_ids",
            question.affected_task_ids or [],
            task_ids,
        )

    # 软规则：每个任务至少被 1 个测试点覆盖。
    covered_task_ids = {
        task_id for point in result.test_points for task_id in point.task_ids
    }
    for task in result.tasks:
        if task.id not in covered_task_ids:
            warnings.append(f"任务 {task.id} 未被任何测试点覆盖")

    # 软规则（可选）：任务依赖无环。有环只警告，不阻止成功。
    cycle = _find_dependency_cycle(result.tasks)
    if cycle:
        warnings.append(f"任务依赖存在环: {' -> '.join(cycle)}")

    result._set_warnings(warnings)
    return warnings


def _ensure_unique(label: str, ids: list[str]) -> None:
    """检查单个集合内 id 是否唯一。"""
    seen: set[str] = set()
    duplicates: list[str] = []
    for item_id in ids:
        if item_id in seen and item_id not in duplicates:
            duplicates.append(item_id)
        seen.add(item_id)
    if duplicates:
        raise DuplicateIdError(f"{label} id 重复: {', '.join(duplicates)}")


def _ensure_refs(owner: str, refs: list[str], task_ids: set[str]) -> None:
    """检查引用列表中的每个 id 都存在于任务集合中。"""
    missing = list(dict.fromkeys(ref for ref in refs if ref not in task_ids))
    if missing:
        raise RefError(f"{owner} 引用了不存在的任务 id: {', '.join(missing)}")


def _find_dependency_cycle(tasks: list[Task]) -> list[str] | None:
    """DFS 查找一条依赖环，返回形如 ``[T1, T2, T1]`` 的路径。"""
    graph = {task.id: task.depends_on for task in tasks}
    state: dict[str, int] = {}  # 0/未访问，1/访问中，2/已完成
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        state[node] = 1
        stack.append(node)
        for dependency in graph[node]:
            if state.get(dependency) == 1:
                start = stack.index(dependency)
                return stack[start:] + [dependency]
            if state.get(dependency, 0) == 0:
                cycle = visit(dependency)
                if cycle is not None:
                    return cycle
        stack.pop()
        state[node] = 2
        return None

    for task in tasks:
        if state.get(task.id, 0) == 0:
            cycle = visit(task.id)
            if cycle is not None:
                return cycle
    return None
