"""Stable assistant contracts."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel, Field

from modules.assistant.forecast.contracts import (
    DecisionRequest as DecisionRequest,
)
from modules.assistant.forecast.contracts import (
    EvaluateRequest as EvaluateRequest,
)
from modules.assistant.forecast.contracts import (
    EvidenceRef,
    FocusRequest,
    ResolvedScope,
)
from modules.assistant.forecast.contracts import (
    FeedRequest as FeedRequest,
)
from modules.assistant.forecast.contracts import (
    Horizon as Horizon,
)
from modules.assistant.schemas import NoticeDecision as NoticeDecision
from modules.assistant.schemas import NoticeDisposition as NoticeDisposition
from modules.assistant.schemas import NoticeRecheck as NoticeRecheck
from modules.assistant.schemas import ProactivePolicy as ProactivePolicy
from modules.assistant.schemas import RunResponse as RunResponse
from modules.assistant.schemas import WorkContext
from modules.assistant.session_contracts import (
    WorldCocreationAction as WorldCocreationAction,
)
from modules.assistant.session_contracts import (
    WorldCocreationCheckpointAdvanceRequest as WorldCocreationCheckpointAdvanceRequest,
)
from modules.assistant.session_contracts import (
    WorldCocreationMessageCreateRequest as WorldCocreationMessageCreateRequest,
)
from modules.assistant.session_contracts import (
    WorldCocreationMessageListResponse as WorldCocreationMessageListResponse,
)
from modules.assistant.session_contracts import (
    WorldCocreationMessageResponse as WorldCocreationMessageResponse,
)
from modules.assistant.session_contracts import (
    WorldCocreationSessionCreateRequest as WorldCocreationSessionCreateRequest,
)
from modules.assistant.session_contracts import (
    WorldCocreationSessionDetailResponse as WorldCocreationSessionDetailResponse,
)
from modules.assistant.session_contracts import (
    WorldCocreationSessionListResponse as WorldCocreationSessionListResponse,
)
from modules.assistant.session_contracts import (
    WorldCocreationSessionResponse as WorldCocreationSessionResponse,
)
from modules.assistant.session_contracts import (
    WorldCocreationSessionUpdateRequest as WorldCocreationSessionUpdateRequest,
)
from modules.assistant.session_contracts import (
    WorldCocreationSourceRef as WorldCocreationSourceRef,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class AssistantOperationContext:
    run_id: str
    owner_id: str
    work: WorkContext
    operation_id: str | None = None
    llm_snapshot: dict | None = None
    internal_meta: dict | None = None


@dataclass(frozen=True)
class AssistantOperation:
    """A real domain operation registered by the app, not chosen by an LLM."""

    label: str
    schema: type[BaseModel]
    prepare: Callable[..., Awaitable[dict[str, Any]]]
    apply: Callable[..., Awaitable[dict[str, Any]]]
    permission: str = "confirm"
    read_result: Callable[..., Awaitable[dict[str, Any]]] | None = None
    revision: str = "1"


class ForecastDomainFact(BaseModel):
    """Code-owned read projection. Text is evidence, never execution authority."""

    capability_id: str
    subject: str
    title: str
    summary: str
    source: dict[str, Any]
    scope_label: str
    unknowns: list[str] = []
    target: dict[str, Any] | None = None
    actionable: bool = True
    preparations: list[dict[str, Any]] = Field(default_factory=list, max_length=4)


@dataclass
class ForecastContext:
    scope: ResolvedScope
    focus: FocusRequest
    sources: list[dict]
    evidence: list[EvidenceRef]
    dependencies: list[dict]
    chapter_index: int | None
    excluded_targets: list[str] = field(default_factory=list)
    facts: list = field(default_factory=list)
    saved_draft_hash: str | None = None
    understanding: dict = field(default_factory=dict)

    @property
    def text(self):
        text = json.dumps(self.sources, ensure_ascii=False, sort_keys=True)
        if self.understanding.get("records"):
            text += "\n派生理解（可修订，非独立事实；核对所引原文）：\n" + json.dumps(
                {key: self.understanding.get(key) for key in ("records", "source_map")},
                ensure_ascii=False,
                sort_keys=True,
            )
        return text


# ============================================================
# 插件 SPI（AO-3）— 领域插件文件经组合根注册的 DI port 消费运行期服务，
# 不再 import modules.assistant.facade。签名与实现保持一致。
# ============================================================


class AssistantOperationScopePort(Protocol):
    """在领域准备可编辑预览前套用作者阅读范围；实现在 assistant/operation_scope。"""

    async def __call__(
        self,
        db: AsyncSession,
        novel_id: str,
        context: AssistantOperationContext | None,
        targets: list[tuple[str, Any]],
        *,
        aggregate: bool = False,
    ) -> None: ...


class AssistantDiscussionScopePort(Protocol):
    """解析一次可继续讨论的会话范围与证据指纹；实现经 AssistantService。"""

    async def __call__(
        self,
        db: AsyncSession,
        novel_id: str,
        run_id: str,
        owner_id: str,
        *,
        lock: bool = False,
    ) -> dict: ...


class AssistantSessionPort(Protocol):
    """共创会话指针推进与生成结果回写；实现是 AssistantSessionService。"""

    async def advance_checkpoint(
        self,
        db: AsyncSession,
        novel_id: str,
        session_id: str,
        data: WorldCocreationCheckpointAdvanceRequest,
    ) -> WorldCocreationSessionResponse: ...

    async def record_generation_outcome(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        session_id: str,
        action: str | None,
        author_content: str | None,
        task_id: str | None,
        context_confirmation_id: str | None,
        outcome_suggestion_id: str,
        outcome_label: str,
        outcome_kind: str = "candidate",
    ) -> None: ...
