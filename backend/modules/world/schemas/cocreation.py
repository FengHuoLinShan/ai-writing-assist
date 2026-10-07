"""共创会话持久化 schema（ADR-0021）。"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field, model_validator

# ============================================================
# 共创会话持久化（ADR-0021）
# ============================================================
from modules.assistant.contracts import (  # noqa: E402, F401
    WorldCocreationAction,
    WorldCocreationCheckpointAdvanceRequest,
    WorldCocreationMessageCreateRequest,
    WorldCocreationMessageListResponse,
    WorldCocreationMessageResponse,
    WorldCocreationSessionCreateRequest,
    WorldCocreationSessionDetailResponse,
    WorldCocreationSessionListResponse,
    WorldCocreationSessionResponse,
    WorldCocreationSessionUpdateRequest,
    WorldCocreationSourceRef,
)
from modules.world.schemas.generation import WorldGenerationChatRequest


class WorldCocreationChatRequest(WorldGenerationChatRequest):
    """会话内聊天：LLM 成功后把作者消息与完成的模型回复原子落库。"""

    session_action: WorldCocreationAction | None = None


class WorldCocreationTurnTaskRequest(WorldCocreationChatRequest):
    operation_id: uuid.UUID
    session_id: str = Field(..., min_length=1, max_length=64)
    mode: Literal["chat", "design"] = "chat"
    parent_checkpoint_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def require_turn_scope(self) -> WorldCocreationTurnTaskRequest:
        if self.mode == "design" and (
            not self.parent_checkpoint_id or not self.session_action
        ):
            raise ValueError("design iteration requires parent and action")
        return self
