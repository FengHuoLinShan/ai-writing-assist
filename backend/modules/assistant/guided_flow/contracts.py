"""引导流程的作者输入与公开视图 schema；不含任何运行私有状态。"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from modules.assistant.schemas import StrictModel


class GuidedFlowSettings(StrictModel):
    """流程级设置；启动时冻结。

    ``rolling_planning``/``planning_window`` 只影响 ``continue_writing``
    的滚动规划段（BR-6）：关闭后采用即完成（流程 2 v1 行为）；窗口是
    "接下来几章"的章数，1-5 章，默认 3。
    """

    semantic_review: bool = True
    rolling_planning: bool = True
    planning_window: int = Field(default=3, ge=1, le=5)


class GuidedFlowStartRequest(StrictModel):
    novel_id: str = Field(min_length=1, max_length=64)
    flow_id: str = Field(default="continue_writing", min_length=1, max_length=64)
    chapter_index: int | None = Field(default=None, ge=1, le=2147483647)
    settings: GuidedFlowSettings = Field(default_factory=GuidedFlowSettings)
    input: dict[str, Any] = Field(default_factory=dict)


class GuidedFlowAdvanceRequest(StrictModel):
    """推进一次流程；输入只承载当前停点要求的作者决定。

    ``context_confirmation_id`` 是资料确认停点的输入；``choice`` 是作者
    选择停点的输入（选方向卡、采用骨架、选意见、触发滚动规划等），
    结构由各流程定义并在服务端校验。
    """

    novel_id: str = Field(min_length=1, max_length=64)
    context_confirmation_id: UUID | None = None
    choice: dict[str, Any] | None = None


class GuidedFlowSettingsUpdate(StrictModel):
    novel_id: str = Field(min_length=1, max_length=64)
    semantic_review: bool | None = None
    planning_window: int | None = Field(default=None, ge=1, le=5)


class GuidedFlowStepView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    title: str
    state: Literal["done", "active", "pending", "skipped", "blocked"]
    detail: str = ""


class GuidedFlowStopView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    kind: Literal["author_confirm", "author_choice", "blocked"]
    reason: str
    actions: list[dict[str, str]] = Field(default_factory=list)


class GuidedFlowView(BaseModel):
    """公开流程视图：步骤状态、停点原因与作者可执行动作，均为作者语言。

    ``panel`` 是当前停点的作者面向载荷（方向卡、骨架包引用、候选清单、
    滚动窗口进度等），由各流程推导填充；不含运行私有状态。
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    flow_id: str
    flow_version: int
    title: str
    status: str
    stop: GuidedFlowStopView | None = None
    steps: list[GuidedFlowStepView] = Field(default_factory=list)
    chapter_index: int | None = None
    candidate: dict[str, Any] | None = None
    panel: dict[str, Any] | None = None
    settings: dict[str, Any] = Field(default_factory=dict)
