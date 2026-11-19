"""SplitResult 的 pydantic v2 数据定义。

本模块是输出 JSON 的唯一数据定义；JSON Schema 由
``SplitResult.model_json_schema()`` 导出，不另维护 schema 文件。
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

TaskId = Annotated[
    str,
    Field(pattern=r"^T[0-9]+$", description="任务 id，格式为 T1、T2……"),
]
TestPointId = Annotated[
    str,
    Field(pattern=r"^TP[0-9]+$", description="测试点 id，格式为 TP1、TP2……"),
]
QuestionId = Annotated[
    str,
    Field(pattern=r"^Q[0-9]+$", description="问题 id，格式为 Q1、Q2……"),
]


class StrictModel(BaseModel):
    """所有模型都禁止多余字段（additionalProperties: false）。"""

    model_config = ConfigDict(extra="forbid")


class InputType(str, Enum):
    FEATURE = "feature"
    BUG = "bug"
    MIXED = "mixed"
    OTHER = "other"


class Priority(str, Enum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


class Category(str, Enum):
    FRONTEND = "frontend"
    BACKEND = "backend"
    DATA = "data"
    INFRA = "infra"
    TEST = "test"
    DOC = "doc"
    OTHER = "other"


class Estimate(str, Enum):
    S = "S"
    M = "M"
    L = "L"


class TestType(str, Enum):
    FUNCTIONAL = "functional"
    EDGE_CASE = "edge_case"
    ERROR_HANDLING = "error_handling"
    REGRESSION = "regression"
    PERFORMANCE = "performance"
    SECURITY = "security"
    UX = "ux"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Understanding(StrictModel):
    goal: str = Field(description="核心目标/要解决的问题")
    in_scope: list[str]
    out_of_scope: list[str]
    assumptions: list[str] = Field(description="为继续拆解而做的假设，需用户确认")


class Task(StrictModel):
    id: TaskId
    title: str = Field(max_length=60, description="动词开头")
    description: str = Field(description="做什么、怎么算完成")
    priority: Priority = Field(description="P0 必须/阻塞，P1 重要，P2 可延后")
    category: Category | None = None
    estimate: Estimate | None = Field(
        default=None, description="S≤0.5天 M≤1天 L≤2天"
    )
    depends_on: list[TaskId] = Field(description="依赖的任务 id，可为空列表")
    acceptance_criteria: list[str] | None = None


class TestPoint(StrictModel):
    id: TestPointId
    task_ids: list[TaskId] = Field(min_length=1)
    type: TestType
    scenario: str = Field(description="测什么/前置条件")
    steps: list[str] | None = None
    expected_result: str
    priority: Priority | None = None


class Question(StrictModel):
    id: QuestionId
    question: str
    why: str = Field(description="为什么要问：原文哪里含糊/冲突")
    impact: str = Field(description="不问清楚会影响什么")
    affected_task_ids: list[TaskId] | None = None
    blocking: bool | None = Field(default=None, description="是否阻塞开工")
    suggested_default: str | None = Field(
        default=None, description="若无人回答，建议的默认做法"
    )


class SelfCheck(StrictModel):
    coverage_ok: bool = Field(description="原文每个诉求是否都有任务覆盖")
    issues: list[str] = Field(description="自检发现的遗漏/风险")
    confidence: Confidence


class SplitResult(StrictModel):
    input_type: InputType = Field(description="输入是需求、bug、还是混合")
    summary: str = Field(max_length=200, description="一两句话概括要做什么")
    understanding: Understanding
    tasks: list[Task] = Field(min_length=1)
    test_points: list[TestPoint] = Field(min_length=1)
    questions: list[Question]
    self_check: SelfCheck

    # 软规则 warning 属于校验过程的附加信息，不参与 JSON Schema/序列化。
    _warnings: list[str] = PrivateAttr(default_factory=list)

    @property
    def warnings(self) -> list[str]:
        """返回业务软规则产生的 warning（只读副本）。"""
        return list(self._warnings)

    def _set_warnings(self, warnings: list[str]) -> None:
        self._warnings = list(warnings)
