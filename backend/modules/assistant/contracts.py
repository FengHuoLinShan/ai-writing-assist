"""Stable assistant contracts."""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

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

    @property
    def text(self):
        return json.dumps(self.sources, ensure_ascii=False, sort_keys=True)
