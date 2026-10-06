"""生成中心对话与 Ask World 路由（Generate Center Chatbox）。"""

from __future__ import annotations

from fastapi import HTTPException

from core.dependencies import DbSession
from core.errors import ConflictError
from infrastructure.tasks.facade import (
    enqueue_task_with_optional_operation,
    get_operation_task,
)
from modules.assistant.contracts import RunResponse as AssistantRunResponse
from modules.assistant.facade import project_assistant_enabled
from modules.evidence.facade import attach_result_ref
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    require_active_project,
)
from modules.world.api._shared import (
    ActiveNovelIdQuery,
    _ask_world_service,
    _attach_manual_context_result,
    _require_generation_confirmation,
    _suggestion_service,
    _template_version_conflict,
    _world_generation_service,
    router,
)
from modules.world.schemas import (
    AskWorldCitationOpenRequest,
    AskWorldCitationOpenResponse,
    AskWorldQuestionRequest,
    AskWorldResponse,
    AskWorldSaveRequest,
    AskWorldSaveResponse,
    WorldGenerationApplyPageDraftRequest,
    WorldGenerationApplyPageDraftResponse,
    WorldGenerationChatRequest,
    WorldGenerationChatResponse,
    WorldGenerationConvergenceRequest,
    WorldGenerationConvergenceResponse,
    WorldGenerationExplorationRequest,
    WorldGenerationExplorationResponse,
    WorldGenerationSemanticInspectionRequest,
    WorldGenerationSemanticInspectionResponse,
    WorldGenerationSuggestionRequest,
    WorldGenerationSuggestionResponse,
    WorldGenerationSuggestionTaskRequest,
    WorldGenerationTaskResponse,
)
from modules.world.services.worldbuilding.generation_prompt_template_service import (
    TemplateVersionConflictError,
)
from modules.world.services.worldbuilding.worldbuilding_service import (
    SuggestionAlreadyProcessedError,
)


@router.post(
    "/generation-center/chat",
    response_model=WorldGenerationChatResponse | AssistantRunResponse,
)
async def chat_world_generation_center(
    db: DbSession,
    data: WorldGenerationChatRequest,
) -> WorldGenerationChatResponse:
    """World co-creation chat; never writes a business asset or suggestion."""
    await require_active_project(db, data.novel_id)
    if not project_assistant_enabled():
        await _require_generation_confirmation(db, data, "world.generation.chat")
    try:
        if project_assistant_enabled():
            from modules.assistant.facade import submit_cocreation

            return await submit_cocreation(db, data)
        result = await _world_generation_service.chat(db, data)
        await _attach_manual_context_result(db, data, result)
        return result
    except TemplateVersionConflictError as exc:
        raise _template_version_conflict(exc) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/generation-center/convergence",
    response_model=WorldGenerationConvergenceResponse,
)
async def converge_world_generation_center(
    db: DbSession,
    data: WorldGenerationConvergenceRequest,
) -> WorldGenerationConvergenceResponse:
    """Read-only convergence over the author-selected source window."""
    await require_active_project(db, data.novel_id)
    await _require_generation_confirmation(db, data, "world.generation.convergence")
    try:
        result = await _world_generation_service.converge(db, data)
        await _attach_manual_context_result(db, data, result)
        return result
    except TemplateVersionConflictError as exc:
        raise _template_version_conflict(exc) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/generation-center/exploration",
    response_model=WorldGenerationExplorationResponse,
)
async def explore_world_generation_center(
    db: DbSession,
    data: WorldGenerationExplorationRequest,
) -> WorldGenerationExplorationResponse:
    """Return at most three read-only, one-hop world gaps."""
    await require_active_project(db, data.novel_id)
    await _require_generation_confirmation(db, data, "world.generation.exploration")
    try:
        result = await _world_generation_service.explore(db, data)
        await _attach_manual_context_result(db, data, result)
        return result
    except TemplateVersionConflictError as exc:
        raise _template_version_conflict(exc) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/generation-center/semantic-inspection",
    response_model=WorldGenerationSemanticInspectionResponse,
)
async def inspect_world_generation_center_page(
    db: DbSession,
    data: WorldGenerationSemanticInspectionRequest,
) -> WorldGenerationSemanticInspectionResponse:
    """Inspect one exact current page; findings remain author-reviewable."""
    await require_active_project(db, data.novel_id)
    await _require_generation_confirmation(
        db,
        data,
        "world.generation.semantic_inspection",
    )
    try:
        result = await _world_generation_service.inspect_current_page(db, data)
        await _attach_manual_context_result(db, data, result)
        return result
    except TemplateVersionConflictError as exc:
        raise _template_version_conflict(exc) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/ask-world", response_model=AskWorldResponse)
async def ask_world(
    db: DbSession,
    data: AskWorldQuestionRequest,
) -> AskWorldResponse:
    """Answer from current author-visible evidence without writing assets."""
    await require_active_project(db, data.novel_id)
    await _require_generation_confirmation(db, data, "world.ask")
    try:
        result = await _ask_world_service.ask(db, data)
        await _attach_manual_context_result(db, data, result)
        return result
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/ask-world/citations/open",
    response_model=AskWorldCitationOpenResponse,
)
async def open_ask_world_citation(
    db: DbSession,
    data: AskWorldCitationOpenRequest,
) -> AskWorldCitationOpenResponse:
    """Re-open one citation inside the active project and report freshness."""
    await require_active_project(db, data.novel_id)
    return await _ask_world_service.open_citation(db, data.novel_id, data.citation)


@router.post(
    "/ask-world/suggestions",
    response_model=AskWorldSaveResponse,
    status_code=201,
)
async def save_ask_world_suggestion(
    db: DbSession,
    data: AskWorldSaveRequest,
) -> AskWorldSaveResponse:
    """Explicitly save an answer as a pending, reviewable suggestion."""
    await require_active_project(db, data.novel_id)
    try:
        return await _suggestion_service.save_ask_world_answer(db, data)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/generation-center/suggestions",
    response_model=WorldGenerationSuggestionResponse,
    status_code=201,
    deprecated=True,
)
async def generate_world_suggestion(
    db: DbSession,
    data: WorldGenerationSuggestionRequest,
) -> WorldGenerationSuggestionResponse:
    """Generate one typed, pending suggestion for the author-selected target."""
    await require_active_project(db, data.novel_id)
    action = (
        "world.generation.core_entity"
        if getattr(data.target, "kind", "") == "core_entity"
        else "world.generation.world_bible_page"
    )
    await _require_generation_confirmation(db, data, action)
    try:
        result = await _world_generation_service.generate_suggestion(db, data)
        await _attach_manual_context_result(db, data, result)
        return result
    except TemplateVersionConflictError as exc:
        raise _template_version_conflict(exc) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/generation-center/suggestions/task",
    response_model=WorldGenerationTaskResponse,
    status_code=202,
)
async def enqueue_world_suggestion(
    db: DbSession,
    data: WorldGenerationSuggestionTaskRequest,
) -> WorldGenerationTaskResponse:
    await require_active_project(db, data.novel_id)
    action = (
        "world.generation.core_entity"
        if getattr(data.target, "kind", "") == "core_entity"
        else "world.generation.world_bible_page"
    )
    await _require_generation_confirmation(db, data, action)
    payload = data.model_dump(mode="json", exclude={"operation_id"})
    try:
        existing = await get_operation_task(
            db,
            operation_id=str(data.operation_id),
            task_type="world_generation_suggestion",
            novel_id=data.novel_id,
            request_payload=payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if existing is not None:
        return WorldGenerationTaskResponse(
            task_id=existing.task_id,
            status=existing.status,
        )
    snapshot = await build_project_llm_execution_snapshot(db, data.novel_id)
    try:
        receipt = await enqueue_task_with_optional_operation(
            db,
            operation_id=str(data.operation_id),
            task_type="world_generation_suggestion",
            novel_id=data.novel_id,
            request_payload=payload,
            meta={
                **payload,
                "llm_execution_snapshot": snapshot,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.flush()
    if not receipt.reused and data.context_confirmation_id:
        await attach_result_ref(
            db,
            novel_id=data.novel_id,
            confirmation_id=data.context_confirmation_id,
            result_type="task",
            result_id=receipt.task_id,
            status="running",
        )
    return WorldGenerationTaskResponse(
        task_id=receipt.task_id,
        status=receipt.status,
    )


@router.post(
    "/generation-center/suggestions/{suggestion_id}/apply-page-draft",
    response_model=WorldGenerationApplyPageDraftResponse,
)
async def apply_world_generation_page_draft(
    db: DbSession,
    suggestion_id: str,
    data: WorldGenerationApplyPageDraftRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> WorldGenerationApplyPageDraftResponse:
    try:
        return await _suggestion_service.apply_world_generation_page_draft(
            db,
            novel_id,
            suggestion_id,
            data,
        )
    except SuggestionAlreadyProcessedError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "already_processed",
                "suggestion_status": exc.status,
            },
        ) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
