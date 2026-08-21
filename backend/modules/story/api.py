"""Author-facing Story card/script APIs and deterministic task submissions."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException, Query
from fastapi import status as http_status

from core.api_params import NovelIdQuery
from core.dependencies import DbSession
from infrastructure.tasks.facade import (
    enqueue_task_with_optional_operation,
    get_operation_task,
)
from modules.evidence.facade import attach_result_ref, require_fresh_confirmation
from modules.project.facade import (
    build_project_llm_execution_snapshot,
    require_active_project,
)
from modules.story.facade import (
    STORY_CARD_TASK,
    STORY_CHARACTER_CARD_ACTION,
    STORY_ONE_CLICK_ACTION,
    STORY_ONE_CLICK_TASK,
    STORY_REACTION_ACTION,
    STORY_REACTION_TASK,
    STORY_SCRIPT_ACTION,
    STORY_SCRIPT_TASK,
    StoryConflictError,
    StoryNotFoundError,
    adopt_scene_script_revision,
    archive_character_card_revision,
    archive_scene_script_revision,
    create_manual_character_card,
    create_scene_script_file,
    create_scene_script_revision,
    get_character_card,
    get_scene_script_file,
    get_scene_story_context,
    list_character_card_revisions,
    list_character_cards,
    list_scene_script_files,
    list_scene_script_revisions,
    restore_character_card_revision,
    unadopt_scene_script_file,
)
from modules.story.schemas import (
    CardArchiveRequest,
    CardRestoreRequest,
    CardRevisionCreate,
    CharacterCardListResponse,
    CharacterCardResponse,
    CharacterCardRevisionResponse,
    SceneScriptAdoptRequest,
    SceneScriptArchiveRequest,
    SceneScriptFileCreate,
    SceneScriptFileListResponse,
    SceneScriptFileResponse,
    SceneScriptRevisionCreate,
    SceneScriptRevisionResponse,
    SceneScriptUnadoptRequest,
    StoryCardTaskRequest,
    StoryOneClickTaskRequest,
    StorySceneContextResponse,
    StoryTaskRequest,
    StoryTaskResponse,
)
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/story", tags=["story"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, StoryConflictError):
        detail = str(exc)
        if exc.latest is not None:
            detail = {"message": detail, "latest": exc.latest}
        return HTTPException(status_code=http_status.HTTP_409_CONFLICT, detail=detail)
    if isinstance(exc, StoryNotFoundError):
        return HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    logger.exception("story api operation failed")
    return HTTPException(
        status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="服务器内部错误，请稍后重试。",
    )


@router.get("/character-cards", response_model=CharacterCardListResponse)
async def api_list_character_cards(
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
    scene_id: str | None = Query(None),
    character_id: list[str] | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
) -> CharacterCardListResponse:
    await require_active_project(db, novel_id)
    try:
        items = await list_character_cards(
            db,
            novel_id,
            scene_id=scene_id,
            character_ids=character_id,
        )
    except Exception as exc:
        raise _error(exc) from exc
    return CharacterCardListResponse(items=items[skip : skip + limit], total=len(items))


@router.get("/character-cards/{card_id}", response_model=CharacterCardResponse)
async def api_get_character_card(
    card_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
) -> CharacterCardResponse:
    await require_active_project(db, novel_id)
    try:
        return await get_character_card(db, novel_id, card_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.get(
    "/character-cards/{card_id}/revisions",
    response_model=list[CharacterCardRevisionResponse],
)
async def api_list_character_card_revisions(
    card_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
) -> list[CharacterCardRevisionResponse]:
    await require_active_project(db, novel_id)
    try:
        return await list_character_card_revisions(db, novel_id, card_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.post(
    "/character-cards",
    response_model=CharacterCardResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def api_create_character_card(
    data: CardRevisionCreate,
    db: DbSession,
) -> CharacterCardResponse:
    await require_active_project(db, data.novel_id)
    try:
        return await create_manual_character_card(
            db,
            novel_id=data.novel_id,
            scene_id=data.scene_id,
            character_id=data.character_id,
            content=data.content,
            source_manifest=data.source_manifest,
            source_task_id=data.source_task_id,
            context_snapshot_id=data.context_snapshot_id,
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post(
    "/character-cards/{card_id}/revisions",
    response_model=CharacterCardResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def api_create_character_card_revision(
    card_id: str,
    data: CardRevisionCreate,
    db: DbSession,
) -> CharacterCardResponse:
    await require_active_project(db, data.novel_id)
    try:
        current = await get_character_card(db, data.novel_id, card_id)
        if (
            str(current.character_id) != data.character_id
            or str(current.scene_id) != data.scene_id
        ):
            raise StoryConflictError("card path does not match scene/character")
        return await create_manual_character_card(
            db,
            novel_id=data.novel_id,
            scene_id=data.scene_id,
            character_id=data.character_id,
            content=data.content,
            expected_revision_id=data.expected_revision_id,
            source_manifest=data.source_manifest,
            source_task_id=data.source_task_id,
            context_snapshot_id=data.context_snapshot_id,
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post(
    "/character-cards/{card_id}/restore",
    response_model=CharacterCardResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def api_restore_character_card(
    card_id: str,
    data: CardRestoreRequest,
    db: DbSession,
) -> CharacterCardResponse:
    await require_active_project(db, data.novel_id)
    try:
        return await restore_character_card_revision(
            db,
            novel_id=data.novel_id,
            card_id=card_id,
            revision_id=data.revision_id,
            expected_revision_id=data.expected_revision_id,
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post(
    "/character-cards/{card_id}/revisions/{revision_id}/archive",
    status_code=http_status.HTTP_204_NO_CONTENT,
)
async def api_archive_character_card_revision(
    card_id: str,
    revision_id: uuid.UUID,
    data: CardArchiveRequest,
    db: DbSession,
) -> None:
    await require_active_project(db, data.novel_id)
    try:
        await archive_character_card_revision(
            db,
            novel_id=data.novel_id,
            card_id=card_id,
            revision_id=revision_id,
            expected_revision_id=data.expected_revision_id,
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.get(
    "/scenes/{scene_id}/script-files",
    response_model=SceneScriptFileListResponse,
)
async def api_list_scene_script_files(
    scene_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
) -> SceneScriptFileListResponse:
    await require_active_project(db, novel_id)
    try:
        items = await list_scene_script_files(db, novel_id=novel_id, scene_id=scene_id)
    except Exception as exc:
        raise _error(exc) from exc
    return SceneScriptFileListResponse(items=items, total=len(items))


@router.post(
    "/scenes/{scene_id}/script-files",
    response_model=SceneScriptFileResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def api_create_scene_script_file(
    scene_id: str,
    data: SceneScriptFileCreate,
    db: DbSession,
) -> SceneScriptFileResponse:
    await require_active_project(db, data.novel_id)
    if data.scene_id != scene_id:
        raise HTTPException(status_code=400, detail="scene path does not match body")
    try:
        return await create_scene_script_file(
            db,
            novel_id=data.novel_id,
            scene_id=scene_id,
            file_key=data.file_key,
            title=data.title,
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/script-files/{file_id}", response_model=SceneScriptFileResponse)
async def api_get_scene_script_file(
    file_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
) -> SceneScriptFileResponse:
    await require_active_project(db, novel_id)
    try:
        return await get_scene_script_file(db, novel_id, file_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.get(
    "/script-files/{file_id}/revisions",
    response_model=list[SceneScriptRevisionResponse],
)
async def api_list_scene_script_revisions(
    file_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
) -> list[SceneScriptRevisionResponse]:
    await require_active_project(db, novel_id)
    try:
        return await list_scene_script_revisions(db, novel_id=novel_id, file_id=file_id)
    except Exception as exc:
        raise _error(exc) from exc


@router.post(
    "/scenes/{scene_id}/script-revisions",
    response_model=SceneScriptFileResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def api_create_scene_script_revision(
    scene_id: str,
    data: SceneScriptRevisionCreate,
    db: DbSession,
) -> SceneScriptFileResponse:
    await require_active_project(db, data.novel_id)
    if data.scene_id != scene_id:
        raise HTTPException(status_code=400, detail="scene path does not match body")
    try:
        return await create_scene_script_revision(
            db,
            novel_id=data.novel_id,
            scene_id=scene_id,
            file_key=data.file_key,
            content=data.content,
            content_json=data.content_json,
            expected_revision_id=data.expected_revision_id,
            adopt=data.adopt,
            provenance=data.provenance,
            expected_adopted_revision_id=None,
            source_task_id=data.source_task_id,
            context_snapshot_id=data.context_snapshot_id,
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post(
    "/script-files/{file_id}/revisions/{revision_id}/adopt",
    response_model=SceneScriptFileResponse,
)
async def api_adopt_scene_script_revision(
    file_id: str,
    revision_id: uuid.UUID,
    data: SceneScriptAdoptRequest,
    db: DbSession,
) -> SceneScriptFileResponse:
    await require_active_project(db, data.novel_id)
    try:
        return await adopt_scene_script_revision(
            db,
            novel_id=data.novel_id,
            file_id=file_id,
            revision_id=revision_id,
            expected_revision_id=data.expected_revision_id,
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post(
    "/script-files/{file_id}/revisions/{revision_id}/archive",
    status_code=http_status.HTTP_204_NO_CONTENT,
)
async def api_archive_scene_script_revision(
    file_id: str,
    revision_id: uuid.UUID,
    data: SceneScriptArchiveRequest,
    db: DbSession,
) -> None:
    await require_active_project(db, data.novel_id)
    try:
        await archive_scene_script_revision(
            db,
            novel_id=data.novel_id,
            file_id=file_id,
            revision_id=revision_id,
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post(
    "/script-files/{file_id}/unadopt",
    response_model=SceneScriptFileResponse,
)
async def api_unadopt_scene_script_file(
    file_id: str,
    data: SceneScriptUnadoptRequest,
    db: DbSession,
) -> SceneScriptFileResponse:
    await require_active_project(db, data.novel_id)
    try:
        return await unadopt_scene_script_file(
            db,
            novel_id=data.novel_id,
            file_id=file_id,
            expected_revision_id=data.expected_revision_id,
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/scenes/{scene_id}/story-context", response_model=StorySceneContextResponse)
async def api_get_story_scene_context(
    scene_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
) -> StorySceneContextResponse:
    await require_active_project(db, novel_id)
    try:
        context = await get_scene_story_context(
            db,
            novel_id=novel_id,
            scene_id=scene_id,
        )
        if context is None:
            raise StoryNotFoundError("scene not found")
        return context
    except Exception as exc:
        raise _error(exc) from exc


async def _enqueue_confirmed_task(
    db: DbSession,
    data: StoryTaskRequest | StoryCardTaskRequest,
    *,
    action: str,
    task_type: str,
) -> StoryTaskResponse:
    request_payload = data.model_dump(
        mode="json",
        exclude_none=True,
        exclude={"operation_id"},
    )
    try:
        existing = await get_operation_task(
            db,
            operation_id=str(data.operation_id) if data.operation_id else None,
            task_type=task_type,
            novel_id=data.novel_id,
            request_payload=request_payload,
        )
        if existing is not None:
            return StoryTaskResponse(task_id=existing.task_id, status=existing.status)
        await require_fresh_confirmation(
            db,
            novel_id=data.novel_id,
            action=action,
            confirmation_id=data.context_confirmation_id,
        )
        meta = {
            **request_payload,
            "action": action,
            "llm_execution_snapshot": await build_project_llm_execution_snapshot(
                db,
                data.novel_id,
            ),
        }
        receipt = await enqueue_task_with_optional_operation(
            db,
            operation_id=str(data.operation_id) if data.operation_id else None,
            task_type=task_type,
            novel_id=data.novel_id,
            request_payload=request_payload,
            meta=meta,
        )
        if not receipt.reused:
            await attach_result_ref(
                db,
                novel_id=data.novel_id,
                confirmation_id=data.context_confirmation_id,
                result_type="task",
                result_id=receipt.task_id,
                status="running",
            )
        await db.flush()
        return StoryTaskResponse(task_id=receipt.task_id, status=receipt.status)
    except Exception as exc:
        raise _error(exc) from exc


async def _enqueue_one_click_task(
    db: DbSession,
    data: StoryOneClickTaskRequest,
) -> StoryTaskResponse:
    request_payload = data.model_dump(
        mode="json",
        exclude_none=True,
        exclude={"operation_id"},
    )
    try:
        existing = await get_operation_task(
            db,
            operation_id=str(data.operation_id) if data.operation_id else None,
            task_type=STORY_ONE_CLICK_TASK,
            novel_id=data.novel_id,
            request_payload=request_payload,
        )
        if existing is not None:
            return StoryTaskResponse(task_id=existing.task_id, status=existing.status)
        meta = {
            **request_payload,
            "action": STORY_ONE_CLICK_ACTION,
            "submit_authorized": bool(data.submit_authorized),
            "authorization_scope": (
                "missing_or_stale_character_cards_only"
                if data.submit_authorized
                else "preview_only"
            ),
            "llm_execution_snapshot": await build_project_llm_execution_snapshot(
                db,
                data.novel_id,
            ),
        }
        receipt = await enqueue_task_with_optional_operation(
            db,
            operation_id=str(data.operation_id) if data.operation_id else None,
            task_type=STORY_ONE_CLICK_TASK,
            novel_id=data.novel_id,
            request_payload=request_payload,
            meta=meta,
        )
        await db.flush()
        return StoryTaskResponse(task_id=receipt.task_id, status=receipt.status)
    except Exception as exc:
        raise _error(exc) from exc


@router.post("/tasks/character-card", response_model=StoryTaskResponse, status_code=202)
async def api_submit_character_card_task(
    data: StoryCardTaskRequest,
    db: DbSession,
) -> StoryTaskResponse:
    await require_active_project(db, data.novel_id)
    return await _enqueue_confirmed_task(
        db,
        data,
        action=STORY_CHARACTER_CARD_ACTION,
        task_type=STORY_CARD_TASK,
    )


@router.post("/tasks/reaction", response_model=StoryTaskResponse, status_code=202)
async def api_submit_reaction_task(
    data: StoryTaskRequest,
    db: DbSession,
) -> StoryTaskResponse:
    await require_active_project(db, data.novel_id)
    return await _enqueue_confirmed_task(
        db,
        data,
        action=STORY_REACTION_ACTION,
        task_type=STORY_REACTION_TASK,
    )


@router.post("/tasks/script", response_model=StoryTaskResponse, status_code=202)
async def api_submit_script_task(
    data: StoryTaskRequest,
    db: DbSession,
) -> StoryTaskResponse:
    await require_active_project(db, data.novel_id)
    return await _enqueue_confirmed_task(
        db,
        data,
        action=STORY_SCRIPT_ACTION,
        task_type=STORY_SCRIPT_TASK,
    )


@router.post("/tasks/one-click", response_model=StoryTaskResponse, status_code=202)
async def api_submit_one_click_task(
    data: StoryOneClickTaskRequest,
    db: DbSession,
) -> StoryTaskResponse:
    await require_active_project(db, data.novel_id)
    return await _enqueue_one_click_task(db, data)


# Scene-centric aliases keep the workbench wire shape close to the author's
# mental model while the resource-centric paths above remain stable for API
# clients that already hold a file/card ID.
@router.get(
    "/scenes/{scene_id}/character-cards", response_model=CharacterCardListResponse
)
async def api_scene_character_cards(
    scene_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
) -> CharacterCardListResponse:
    await require_active_project(db, novel_id)
    try:
        items = await list_character_cards(db, novel_id, scene_id=scene_id)
        return CharacterCardListResponse(items=items, total=len(items))
    except Exception as exc:
        raise _error(exc) from exc


@router.post(
    "/scenes/{scene_id}/character-cards",
    response_model=CharacterCardResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def api_scene_character_card_create(
    scene_id: str,
    data: CardRevisionCreate,
    db: DbSession,
) -> CharacterCardResponse:
    if data.scene_id != scene_id:
        raise HTTPException(status_code=400, detail="scene path does not match body")
    return await api_create_character_card(data, db)


@router.post(
    "/scenes/{scene_id}/character-cards/{card_id}/revisions",
    response_model=CharacterCardResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def api_scene_character_card_revision(
    scene_id: str,
    card_id: str,
    data: CardRevisionCreate,
    db: DbSession,
) -> CharacterCardResponse:
    if data.scene_id != scene_id:
        raise HTTPException(status_code=400, detail="scene path does not match body")
    return await api_create_character_card_revision(card_id, data, db)


@router.post(
    "/scenes/{scene_id}/character-cards/generate",
    response_model=StoryTaskResponse,
    status_code=202,
)
async def api_scene_character_cards_generate(
    scene_id: str,
    data: StoryCardTaskRequest,
    db: DbSession,
) -> StoryTaskResponse:
    if data.scene_id != scene_id:
        raise HTTPException(status_code=400, detail="scene path does not match body")
    return await api_submit_character_card_task(data, db)


@router.get("/scenes/{scene_id}/scripts", response_model=SceneScriptFileListResponse)
async def api_scene_scripts(
    scene_id: str,
    db: DbSession,
    *,
    novel_id: NovelIdQuery,
) -> SceneScriptFileListResponse:
    return await api_list_scene_script_files(scene_id, db, novel_id=novel_id)


@router.post(
    "/scenes/{scene_id}/scripts",
    response_model=SceneScriptFileResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def api_scene_script_file_create(
    scene_id: str,
    data: SceneScriptFileCreate,
    db: DbSession,
) -> SceneScriptFileResponse:
    return await api_create_scene_script_file(scene_id, data, db)


@router.post(
    "/scenes/{scene_id}/scripts/{file_id}/revisions",
    response_model=SceneScriptFileResponse,
    status_code=http_status.HTTP_201_CREATED,
)
async def api_scene_script_revision_save(
    scene_id: str,
    file_id: str,
    data: SceneScriptRevisionCreate,
    db: DbSession,
) -> SceneScriptFileResponse:
    await require_active_project(db, data.novel_id)
    if data.scene_id != scene_id:
        raise HTTPException(status_code=400, detail="scene path does not match body")
    try:
        file = await get_scene_script_file(db, data.novel_id, file_id)
        if str(file.scene_id) != scene_id or file.file_key != data.file_key:
            raise StoryConflictError("script path does not match body")
        return await create_scene_script_revision(
            db,
            novel_id=data.novel_id,
            scene_id=scene_id,
            file_key=data.file_key,
            content=data.content,
            content_json=data.content_json,
            expected_revision_id=data.expected_revision_id,
            adopt=data.adopt,
            provenance=data.provenance,
            source_task_id=data.source_task_id,
            context_snapshot_id=data.context_snapshot_id,
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post(
    "/scenes/{scene_id}/scripts/{file_id}/revisions/{revision_id}/adopt",
    response_model=SceneScriptFileResponse,
)
async def api_scene_script_revision_adopt(
    scene_id: str,
    file_id: str,
    revision_id: uuid.UUID,
    data: SceneScriptAdoptRequest,
    db: DbSession,
) -> SceneScriptFileResponse:
    await require_active_project(db, data.novel_id)
    try:
        file = await get_scene_script_file(db, data.novel_id, file_id)
        if str(file.scene_id) != scene_id:
            raise StoryConflictError("script path does not match scene")
        return await adopt_scene_script_revision(
            db,
            novel_id=data.novel_id,
            file_id=file_id,
            revision_id=revision_id,
            expected_revision_id=data.expected_revision_id,
        )
    except Exception as exc:
        raise _error(exc) from exc


@router.post(
    "/scenes/{scene_id}/reactions/generate",
    response_model=StoryTaskResponse,
    status_code=202,
)
async def api_scene_reactions_generate(
    scene_id: str,
    data: StoryTaskRequest,
    db: DbSession,
) -> StoryTaskResponse:
    if data.scene_id != scene_id:
        raise HTTPException(status_code=400, detail="scene path does not match body")
    return await api_submit_reaction_task(data, db)


@router.post(
    "/scenes/{scene_id}/scripts/generate",
    response_model=StoryTaskResponse,
    status_code=202,
)
async def api_scene_scripts_generate(
    scene_id: str,
    data: StoryTaskRequest,
    db: DbSession,
) -> StoryTaskResponse:
    if data.scene_id != scene_id:
        raise HTTPException(status_code=400, detail="scene path does not match body")
    return await api_submit_script_task(data, db)


@router.post(
    "/scenes/{scene_id}/simulate", response_model=StoryTaskResponse, status_code=202
)
async def api_scene_simulate(
    scene_id: str,
    data: StoryOneClickTaskRequest,
    db: DbSession,
) -> StoryTaskResponse:
    if data.scene_id != scene_id:
        raise HTTPException(status_code=400, detail="scene path does not match body")
    return await api_submit_one_click_task(data, db)
