"""共创会话持久化路由（ADR-0021）。"""

from __future__ import annotations

from fastapi import HTTPException, Query

from core.dependencies import DbSession
from core.errors import ConflictError
from modules.assistant.contracts import RunResponse as AssistantRunResponse
from modules.assistant.facade import project_assistant_enabled
from modules.project.facade import require_active_project
from modules.world.api._shared import (
    ActiveNovelIdQuery,
    _cocreation_session_service,
    _require_generation_confirmation,
    _template_version_conflict,
    router,
)
from modules.world.schemas import (
    WorldCocreationChatRequest,
    WorldCocreationCheckpointAdvanceRequest,
    WorldCocreationMessageCreateRequest,
    WorldCocreationMessageListResponse,
    WorldCocreationMessageResponse,
    WorldCocreationSessionCreateRequest,
    WorldCocreationSessionDetailResponse,
    WorldCocreationSessionListResponse,
    WorldCocreationSessionResponse,
    WorldCocreationSessionUpdateRequest,
    WorldCocreationTurnTaskRequest,
    WorldGenerationChatResponse,
    WorldGenerationTaskResponse,
)
from modules.world.services.worldbuilding.generation_prompt_template_service import (
    TemplateVersionConflictError,
)


@router.post(
    "/cocreation-turns/task", response_model=WorldGenerationTaskResponse, status_code=202
)
async def enqueue_world_cocreation_turn(
    db: DbSession, data: WorldCocreationTurnTaskRequest
):
    await require_active_project(db, data.novel_id)
    try:
        return await _cocreation_session_service.enqueue_turn(db, data)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/cocreation-sessions",
    response_model=WorldCocreationSessionResponse,
    status_code=201,
)
async def create_world_cocreation_session(
    db: DbSession,
    data: WorldCocreationSessionCreateRequest,
) -> WorldCocreationSessionResponse:
    """Create one project-scoped co-creation session bound to its source."""
    await require_active_project(db, data.novel_id)
    return await _cocreation_session_service.create(db, data)


@router.get(
    "/cocreation-sessions",
    response_model=WorldCocreationSessionListResponse,
)
async def list_world_cocreation_sessions(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    include_archived: bool = Query(default=False),
    source_kind: str | None = Query(None),
    source_id: str | None = Query(None),
    workflow_preset: str | None = Query(None),
    target_kind: str | None = Query(None),
    search: str | None = Query(None, max_length=200),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> WorldCocreationSessionListResponse:
    items, total = await _cocreation_session_service.list_sessions(
        db,
        novel_id=novel_id,
        include_archived=include_archived,
        source_kind=source_kind,
        source_id=source_id,
        workflow_preset=workflow_preset,
        target_kind=target_kind,
        search=search,
        limit=limit,
        skip=skip,
    )
    return WorldCocreationSessionListResponse(items=items, total=total)


@router.get(
    "/cocreation-sessions/{session_id}",
    response_model=WorldCocreationSessionDetailResponse,
)
async def get_world_cocreation_session(
    db: DbSession,
    session_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldCocreationSessionDetailResponse:
    return await _cocreation_session_service.get_detail(
        db,
        novel_id,
        session_id,
    )


@router.patch(
    "/cocreation-sessions/{session_id}",
    response_model=WorldCocreationSessionResponse,
)
async def update_world_cocreation_session(
    db: DbSession,
    session_id: str,
    *,
    data: WorldCocreationSessionUpdateRequest,
) -> WorldCocreationSessionResponse:
    await require_active_project(db, data.novel_id)
    return await _cocreation_session_service.update_session(
        db,
        data.novel_id,
        session_id,
        data,
    )


@router.get(
    "/cocreation-sessions/{session_id}/messages",
    response_model=WorldCocreationMessageListResponse,
)
async def list_world_cocreation_messages(
    db: DbSession,
    session_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
    search: str | None = Query(None),
    around_message_id: str | None = Query(None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> WorldCocreationMessageListResponse:
    items, total, offset = await _cocreation_session_service.list_messages(
        db,
        novel_id=novel_id,
        session_id=session_id,
        limit=limit,
        skip=skip,
        search=search,
        around_message_id=around_message_id,
    )
    return WorldCocreationMessageListResponse(items=items, total=total, offset=offset)


@router.post(
    "/cocreation-sessions/{session_id}/messages",
    response_model=WorldCocreationMessageResponse,
    status_code=201,
)
async def append_world_cocreation_message(
    db: DbSession,
    session_id: str,
    *,
    data: WorldCocreationMessageCreateRequest,
) -> WorldCocreationMessageResponse:
    """Append one author message or decision; replies only come from generation."""
    await require_active_project(db, data.novel_id)
    return await _cocreation_session_service.create_message(
        db,
        data.novel_id,
        session_id,
        data,
    )


@router.post(
    "/cocreation-sessions/{session_id}/chat",
    response_model=WorldGenerationChatResponse | AssistantRunResponse,
)
async def chat_world_cocreation_session(
    db: DbSession,
    session_id: str,
    *,
    data: WorldCocreationChatRequest,
) -> WorldGenerationChatResponse:
    """Session-scoped chat; the completed turn is persisted atomically."""
    await require_active_project(db, data.novel_id)
    if not project_assistant_enabled():
        await _require_generation_confirmation(db, data, "world.generation.chat")
    try:
        return await _cocreation_session_service.chat(db, session_id, data)
    except TemplateVersionConflictError as exc:
        raise _template_version_conflict(exc) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/cocreation-sessions/{session_id}/checkpoint",
    response_model=WorldCocreationSessionResponse,
)
async def advance_world_cocreation_checkpoint(
    db: DbSession,
    session_id: str,
    *,
    data: WorldCocreationCheckpointAdvanceRequest,
) -> WorldCocreationSessionResponse:
    """Advance the session workspace pointer; drift keeps the proposal."""
    await require_active_project(db, data.novel_id)
    return await _cocreation_session_service.advance_checkpoint(
        db,
        data.novel_id,
        session_id,
        data,
    )
