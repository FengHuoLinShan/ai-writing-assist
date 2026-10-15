"""Author-facing Story card/script APIs and deterministic task submissions."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, HTTPException, Query
from fastapi import status as http_status

from core.api_params import NovelIdQuery
from core.dependencies import DbSession
from modules.project.facade import require_active_project
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
    enqueue_confirmed_story_task,
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
    data: StoryTaskRequest | StoryCardTaskRequest | StoryOneClickTaskRequest,
    *,
    action: str,
    task_type: str,
    extra_meta: dict | None = None,
    llm_execution_snapshot: dict | None = None,
) -> StoryTaskResponse:
    try:
        return await enqueue_confirmed_story_task(
            db,
            data,
            action=action,
            task_type=task_type,
            extra_meta=extra_meta,
            llm_execution_snapshot=llm_execution_snapshot,
        )
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
    await require_active_project(db, data.novel_id, allow_demo_readonly=False)
    if data.simulation_protocol in {"rehearsal_v1", "observation_v2"}:
        raise HTTPException(
            status_code=409,
            detail="旧协议排演只读；请使用 simulation_v3 新建排演",
        )
    if data.simulation_protocol == "simulation_v3":
        from core.config import get_settings

        if not get_settings().story_rehearsal_enabled:
            raise HTTPException(status_code=409, detail="场景排演尚未开启")
        if data.rehearsal_rounds != 1:
            raise HTTPException(
                status_code=409,
                detail="当前一次只提交一回合；连续推进需新的预算与授权入口",
            )
    return await _enqueue_confirmed_task(
        db,
        data,
        action=STORY_ONE_CLICK_ACTION,
        task_type=STORY_ONE_CLICK_TASK,
        extra_meta={
            "submit_authorized": bool(data.submit_authorized),
            "authorization_scope": (
                "missing_or_stale_character_cards_only"
                if data.submit_authorized
                else "preview_only"
            ),
        },
    )


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


@router.post(
    "/scenes/{scene_id}/rehearsals", response_model=StoryTaskResponse, status_code=202
)
async def start_rehearsal(scene_id: str, data: StoryOneClickTaskRequest, db: DbSession):
    if data.scene_id != scene_id:
        raise HTTPException(status_code=422, detail="请选择当前场景的排演方式")
    if data.simulation_protocol in {"rehearsal_v1", "observation_v2"}:
        return await api_submit_one_click_task(data, db)
    if data.simulation_protocol != "simulation_v3":
        raise HTTPException(status_code=422, detail="请选择当前场景的排演方式")
    return await api_submit_one_click_task(data, db)


@router.get("/rehearsals/{run_id}")
async def get_rehearsal(
    run_id: uuid.UUID,
    db: DbSession,
    novel_id: NovelIdQuery,
    actor_id: uuid.UUID | None = None,
):
    from modules.account.facade import is_demo_readonly_principal
    from modules.story.rehearsals import read_rehearsal

    await require_active_project(db, novel_id)
    if is_demo_readonly_principal():
        raise HTTPException(status_code=404, detail="排演不存在")
    return await read_rehearsal(
        db, novel_id, str(run_id), str(actor_id) if actor_id else None
    )


@router.post("/rehearsals/{run_id}/replay")
async def replay_recorded_rehearsal(
    run_id: uuid.UUID, db: DbSession, novel_id: NovelIdQuery
):
    from modules.story.rehearsals import replay_rehearsal

    await require_active_project(db, novel_id, allow_demo_readonly=False)
    return await replay_rehearsal(db, novel_id, str(run_id))


@router.post(
    "/rehearsals/{run_id}/forks", response_model=StoryTaskResponse, status_code=202
)
async def fork_rehearsal(
    run_id: uuid.UUID, data: StoryOneClickTaskRequest, db: DbSession
):
    from modules.story.rehearsals import read_rehearsal

    await require_active_project(db, data.novel_id, allow_demo_readonly=False)
    parent = await read_rehearsal(db, data.novel_id, str(run_id))
    if parent["protocol"] != "simulation_v3":
        raise HTTPException(
            status_code=409,
            detail="旧协议历史只读；不能跨协议重解释或分叉",
        )
    if data.parent_rehearsal_id != run_id or data.simulation_protocol != "simulation_v3":
        raise HTTPException(status_code=422, detail="分叉必须绑定准确的原排演")
    return await api_submit_one_click_task(data, db)


# The author Scene Director has its own finite protocol and cumulative root
# ledger. Keep its router separate until app composition registers the matching
# assistant operations and trace policies; importing this legacy router must not
# expose unregistered writes or break the application registry at import time.
