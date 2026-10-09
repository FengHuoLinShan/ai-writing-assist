"""引导流程的作者输入与公开视图 schema；不含任何运行私有状态。"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from modules.assistant.schemas import StrictModel


class GuidedFlowSettings(StrictModel):
    """流程级设置；启动时冻结。"""

    semantic_review: bool = True


class GuidedFlowStartRequest(StrictModel):
    novel_id: str = Field(min_length=1, max_length=64)
    flow_id: str = Field(default="continue_writing", min_length=1, max_length=64)
    chapter_index: int = Field(ge=1, le=2147483647)
    settings: GuidedFlowSettings = Field(default_factory=GuidedFlowSettings)


class GuidedFlowAdvanceRequest(StrictModel):
    """推进一次流程；输入只承载当前停点要求的作者决定。"""

    novel_id: str = Field(min_length=1, max_length=64)
    context_confirmation_id: UUID | None = None


class GuidedFlowSettingsUpdate(StrictModel):
    novel_id: str = Field(min_length=1, max_length=64)
    semantic_review: bool


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
    """公开流程视图：步骤状态、停点原因与作者可执行动作，均为作者语言。"""

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
    settings: dict[str, Any] = Field(default_factory=dict)
