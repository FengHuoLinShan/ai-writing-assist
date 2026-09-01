"""Browser API for isolated RP interaction journeys."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import StreamingResponse

from core.csrf import require_xhr_request
from core.dependencies import DbSession
from core.errors import ConflictError, ValidationError
from modules.account.facade import current_account_id
from modules.imports.contracts import MAX_IMPORT_FILE_SIZE
from modules.imports.facade import apply_source_update, preview_source_update
from modules.interaction.schemas import (
    InteractionArchiveRequest,
    InteractionAttemptResponse,
    InteractionBranchListResponse,
    InteractionContinueRequest,
    InteractionDeleteRequest,
    InteractionEditUserRequest,
    InteractionExportResponse,
    InteractionGenerationRecordListResponse,
    InteractionHeartbeatResponse,
    InteractionMessagePageResponse,
    InteractionMutationResponse,
    InteractionOverviewResponse,
    InteractionOverviewUpdateRequest,
    InteractionPathIndexResponse,
    InteractionPreferencesResponse,
    InteractionReferenceSummaryResponse,
    InteractionReferenceUpdateRequest,
    InteractionRegenerateRequest,
    InteractionSelectRequest,
    InteractionSendRequest,
    InteractionSourceAnchorListResponse,
    InteractionSourceAnchorMatchRequest,
    InteractionSourceFromProjectRequest,
    InteractionSourceImportPreviewResponse,
    InteractionSourceListResponse,
    InteractionSourceObjectListResponse,
    InteractionSourceResolveRequest,
    InteractionSourceRevisionResponse,
    InteractionSourceUpdateRequest,
    InteractionStopRequest,
    InteractionStopResponse,
    InteractionTreeResponse,
    JourneyCreateRequest,
    JourneyDetailResponse,
    JourneyListResponse,
    JourneyModeUpdateRequest,
    JourneyTitleUpdateRequest,
)
from modules.interaction.services import InteractionService
from modules.interaction.source_service import InteractionSourceService
from modules.interaction.streaming import stream_attempt_events
from modules.project.facade import create_author_project, require_active_project

router = APIRouter(prefix="/api/interactions", tags=["interactions"])
_service = InteractionService()
_source_service = InteractionSourceService()
_xhr = [Depends(require_xhr_request)]


async def _read_source_upload(file: UploadFile) -> tuple[str, bytes]:
    name = file.filename or ""
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > MAX_IMPORT_FILE_SIZE:
            raise ValidationError("文件不能超过 50MB")
        chunks.append(chunk)
    return name, b"".join(chunks)


def _source_preview_response(preview) -> InteractionSourceImportPreviewResponse:
    return InteractionSourceImportPreviewResponse(
        preview_hash=preview.preview_hash,
        mode=preview.mode,
        title=preview.title,
        project_id=preview.project_id,
        chapter_count=preview.chapter_count,
        changes=[
            {
                "chapter_index": item.chapter_index,
                "title": item.title,
                "change": item.change,
            }
            for item in preview.changes
        ],
        requires_destructive_confirmation=preview.requires_destructive_confirmation,
    )


@router.get("/sources", response_model=InteractionSourceListResponse)
async def list_sources(db: DbSession) -> InteractionSourceListResponse:
    return await _source_service.list_sources(db)


@router.post(
    "/sources/import-preview",
    response_model=InteractionSourceImportPreviewResponse,
    dependencies=_xhr,
)
async def preview_source_import(
    db: DbSession,
    file: UploadFile = File(...),
    title: str = Form(..., min_length=1, max_length=255),
    mode: Literal["full", "append"] = Form("full"),
    project_id: str | None = Form(default=None),
) -> InteractionSourceImportPreviewResponse:
    if project_id:
        await require_active_project(db, project_id)
        await _source_service.require_author_project(db, project_id)
    file_name, content = await _read_source_upload(file)
    preview, _chapters = await preview_source_update(
        db,
        project_id=project_id,
        title=title,
        file_name=file_name,
        file_content=content,
        mode=mode,
    )
    return _source_preview_response(preview)


@router.post(
    "/sources/import",
    response_model=InteractionSourceRevisionResponse,
    status_code=202,
    dependencies=_xhr,
)
async def import_source(
    db: DbSession,
    file: UploadFile = File(...),
    title: str = Form(..., min_length=1, max_length=255),
    expected_preview_hash: str = Form(..., min_length=64, max_length=64),
    mode: Literal["full", "append"] = Form("full"),
    project_id: str | None = Form(default=None),
    destructive_confirmed: bool = Form(False),
    authorization_confirmed: bool = Form(False),
) -> InteractionSourceRevisionResponse:
    if project_id:
        await require_active_project(db, project_id)
        await _source_service.require_author_project(db, project_id)
    if authorization_confirmed is not True:
        raise ValidationError("请先确认完整整理会使用模型额度")
    file_name, content = await _read_source_upload(file)
    preview, _chapters = await preview_source_update(
        db,
        project_id=project_id,
        title=title,
        file_name=file_name,
        file_content=content,
        mode=mode,
    )
    if preview.preview_hash != expected_preview_hash:
        raise ConflictError("文件或作品章节已变化，请重新预览")

    target_project_id = project_id
    apply_hash = expected_preview_hash
    if target_project_id is None:
        project = await create_author_project(db, title=preview.title)
        target_project_id = str(project.project_id)
        created_preview, _created_chapters = await preview_source_update(
            db,
            project_id=target_project_id,
            title=title,
            file_name=file_name,
            file_content=content,
            mode=mode,
        )
        apply_hash = created_preview.preview_hash
    applied = await apply_source_update(
        db,
        project_id=target_project_id,
        title=title,
        file_name=file_name,
        file_content=content,
        mode=mode,
        expected_preview_hash=apply_hash,
        destructive_confirmed=destructive_confirmed,
    )
    return await _source_service.create_from_project(
        db,
        project_id=target_project_id,
        import_record_id=applied.import_record_id,
        authorization_confirmed=True,
    )


@router.post(
    "/sources/from-project",
    response_model=InteractionSourceRevisionResponse,
    status_code=202,
    dependencies=_xhr,
)
async def create_source_from_project(
    db: DbSession,
    data: InteractionSourceFromProjectRequest,
) -> InteractionSourceRevisionResponse:
    await require_active_project(db, data.project_id)
    return await _source_service.create_from_project(
        db,
        project_id=data.project_id,
        authorization_confirmed=data.authorization_confirmed,
    )


@router.get(
    "/sources/{revision_id}",
    response_model=InteractionSourceRevisionResponse,
)
async def get_source(
    db: DbSession,
    revision_id: str,
) -> InteractionSourceRevisionResponse:
    return await _source_service.get_source(db, revision_id)


@router.post(
    "/sources/{revision_id}/ambiguities/{ambiguity_key}",
    response_model=InteractionSourceRevisionResponse,
    dependencies=_xhr,
)
async def resolve_source_ambiguity(
    db: DbSession,
    revision_id: str,
    ambiguity_key: str,
    data: InteractionSourceResolveRequest,
) -> InteractionSourceRevisionResponse:
    return await _source_service.resolve_ambiguity(
        db,
        revision_id=revision_id,
        ambiguity_key=ambiguity_key,
        choice_key=data.choice_key,
    )


@router.get(
    "/sources/{revision_id}/anchors",
    response_model=InteractionSourceAnchorListResponse,
)
async def list_source_anchors(
    db: DbSession,
    revision_id: str,
    chapter_index: int | None = Query(default=None, ge=1),
) -> InteractionSourceAnchorListResponse:
    return await _source_service.list_anchors(
        db,
        revision_id=revision_id,
        chapter_index=chapter_index,
    )


@router.post(
    "/sources/{revision_id}/anchors/match",
    response_model=InteractionSourceAnchorListResponse,
    dependencies=_xhr,
)
async def match_source_anchors(
    db: DbSession,
    revision_id: str,
    data: InteractionSourceAnchorMatchRequest,
) -> InteractionSourceAnchorListResponse:
    return await _source_service.match_anchors(
        db,
        revision_id=revision_id,
        chapter_index=data.chapter_index,
        description=data.description,
    )


@router.get(
    "/sources/{revision_id}/objects",
    response_model=InteractionSourceObjectListResponse,
)
async def list_source_objects(
    db: DbSession,
    revision_id: str,
    entity_type: str | None = Query(default=None, max_length=64),
    query: str | None = Query(default=None, max_length=100),
    chapter_index: int | None = Query(default=None, ge=1),
    end_offset: int | None = Query(default=None, ge=1),
) -> InteractionSourceObjectListResponse:
    return await _source_service.list_objects(
        db,
        revision_id=revision_id,
        entity_type=entity_type,
        query=query,
        chapter_index=chapter_index,
        end_offset=end_offset,
    )


@router.patch(
    "/journeys/{journey_id}/source",
    response_model=JourneyDetailResponse,
    dependencies=_xhr,
)
async def update_journey_source(
    db: DbSession,
    journey_id: str,
    data: InteractionSourceUpdateRequest,
) -> JourneyDetailResponse:
    return await _service.update_journey_source(
        db,
        journey_id=journey_id,
        data=data,
    )


@router.get(
    "/journeys/{journey_id}/references",
    response_model=InteractionReferenceSummaryResponse,
)
async def get_journey_references(
    db: DbSession,
    journey_id: str,
) -> InteractionReferenceSummaryResponse:
    return await _service.get_reference_summary(db, journey_id=journey_id)


@router.patch(
    "/journeys/{journey_id}/references",
    response_model=InteractionReferenceSummaryResponse,
    dependencies=_xhr,
)
async def update_journey_references(
    db: DbSession,
    journey_id: str,
    data: InteractionReferenceUpdateRequest,
) -> InteractionReferenceSummaryResponse:
    return await _service.update_references(
        db,
        journey_id=journey_id,
        data=data,
    )


@router.post(
    "/journeys",
    response_model=InteractionMutationResponse,
    status_code=201,
    dependencies=_xhr,
)
async def create_journey(
    db: DbSession,
    data: JourneyCreateRequest,
) -> InteractionMutationResponse:
    return await _service.create_journey(db, data)


@router.get("/journeys", response_model=JourneyListResponse)
async def list_journeys(
    db: DbSession,
    status: str = Query(default="active"),
    search: str | None = Query(default=None, max_length=100),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=50),
) -> JourneyListResponse:
    return await _service.list_journeys(
        db,
        status=status,
        search=search,
        offset=offset,
        limit=limit,
    )


@router.get(
    "/journeys/{journey_id}/messages",
    response_model=InteractionMessagePageResponse,
)
async def get_message_page(
    db: DbSession,
    journey_id: str,
    before_node_id: str | None = Query(default=None),
    around_node_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
) -> InteractionMessagePageResponse:
    return await _service.get_message_page(
        db,
        journey_id=journey_id,
        before_node_id=before_node_id,
        around_node_id=around_node_id,
        limit=limit,
    )


@router.get(
    "/journeys/{journey_id}/path-index",
    response_model=InteractionPathIndexResponse,
)
async def get_path_index(
    db: DbSession,
    journey_id: str,
) -> InteractionPathIndexResponse:
    return await _service.get_path_index(db, journey_id=journey_id)


@router.post(
    "/journeys/{journey_id}/messages",
    response_model=InteractionMutationResponse,
    dependencies=_xhr,
)
async def send_message(
    db: DbSession,
    journey_id: str,
    data: InteractionSendRequest,
) -> InteractionMutationResponse:
    return await _service.send_message(
        db,
        journey_id=journey_id,
        content=data.content,
        expected_selection_epoch=data.expected_selection_epoch,
        idempotency_key=data.idempotency_key,
    )


@router.post(
    "/journeys/{journey_id}/nodes/{node_id}/continue-from-here",
    response_model=InteractionMutationResponse,
    dependencies=_xhr,
)
async def continue_from_node(
    db: DbSession,
    journey_id: str,
    node_id: str,
    data: InteractionSendRequest,
) -> InteractionMutationResponse:
    return await _service.continue_from_node(
        db,
        journey_id=journey_id,
        node_id=node_id,
        content=data.content,
        expected_selection_epoch=data.expected_selection_epoch,
        idempotency_key=data.idempotency_key,
    )


@router.post(
    "/journeys/{journey_id}/nodes/{node_id}/regenerate",
    response_model=InteractionMutationResponse,
    dependencies=_xhr,
)
async def regenerate(
    db: DbSession,
    journey_id: str,
    node_id: str,
    data: InteractionRegenerateRequest,
) -> InteractionMutationResponse:
    return await _service.regenerate(
        db,
        journey_id=journey_id,
        assistant_node_id=node_id,
        expected_selection_epoch=data.expected_selection_epoch,
        idempotency_key=data.idempotency_key,
    )


@router.post(
    "/journeys/{journey_id}/nodes/{node_id}/edit",
    response_model=InteractionMutationResponse,
    dependencies=_xhr,
)
async def edit_user_message(
    db: DbSession,
    journey_id: str,
    node_id: str,
    data: InteractionEditUserRequest,
) -> InteractionMutationResponse:
    return await _service.edit_user_message(
        db,
        journey_id=journey_id,
        user_node_id=node_id,
        content=data.content,
        expected_selection_epoch=data.expected_selection_epoch,
        idempotency_key=data.idempotency_key,
    )


@router.post(
    "/journeys/{journey_id}/nodes/{node_id}/select",
    response_model=JourneyDetailResponse,
    dependencies=_xhr,
)
async def select_branch(
    db: DbSession,
    journey_id: str,
    node_id: str,
    data: InteractionSelectRequest,
) -> JourneyDetailResponse:
    return await _service.select_branch(
        db,
        journey_id=journey_id,
        node_id=node_id,
        expected_selection_epoch=data.expected_selection_epoch,
    )


@router.get(
    "/journeys/{journey_id}/nodes/{node_id}/branches",
    response_model=InteractionBranchListResponse,
)
async def list_branches(
    db: DbSession,
    journey_id: str,
    node_id: str,
) -> InteractionBranchListResponse:
    return await _service.list_branches(
        db,
        journey_id=journey_id,
        node_id=node_id,
    )


@router.get(
    "/journeys/{journey_id}/tree",
    response_model=InteractionTreeResponse,
)
async def get_tree(
    db: DbSession,
    journey_id: str,
) -> InteractionTreeResponse:
    return await _service.get_tree(db, journey_id=journey_id)


@router.get(
    "/journeys/{journey_id}/attempts/{attempt_id}",
    response_model=InteractionAttemptResponse,
)
async def get_attempt(
    db: DbSession,
    journey_id: str,
    attempt_id: str,
) -> InteractionAttemptResponse:
    return await _service.get_attempt_state(
        db,
        journey_id=journey_id,
        attempt_id=attempt_id,
    )


@router.get(
    "/journeys/{journey_id}/generation-records",
    response_model=InteractionGenerationRecordListResponse,
)
async def list_generation_records(
    db: DbSession,
    journey_id: str,
) -> InteractionGenerationRecordListResponse:
    return await _service.list_generation_records(
        db,
        journey_id=journey_id,
    )


@router.get("/journeys/{journey_id}/attempts/{attempt_id}/events")
async def stream_attempt(
    request: Request,
    db: DbSession,
    journey_id: str,
    attempt_id: str,
    offset: int = Query(default=0, ge=0),
) -> StreamingResponse:
    await _service.get_attempt_state(
        db,
        journey_id=journey_id,
        attempt_id=attempt_id,
    )
    header_offset = request.headers.get("last-event-id")
    if header_offset:
        try:
            offset = max(offset, int(header_offset))
        except ValueError:
            pass
    owner_id = current_account_id()
    return StreamingResponse(
        stream_attempt_events(
            owner_id=owner_id,
            journey_id=uuid.UUID(journey_id),
            attempt_id=uuid.UUID(attempt_id),
            offset=offset,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/journeys/{journey_id}/attempts/{attempt_id}/stop",
    response_model=InteractionStopResponse,
    dependencies=_xhr,
)
async def stop_attempt(
    db: DbSession,
    journey_id: str,
    attempt_id: str,
    data: InteractionStopRequest,
) -> InteractionStopResponse:
    return await _service.stop_attempt(
        db,
        journey_id=journey_id,
        attempt_id=attempt_id,
        expected_selection_epoch=data.expected_selection_epoch,
    )


@router.post(
    "/journeys/{journey_id}/attempts/{attempt_id}/keep",
    response_model=InteractionStopResponse,
    dependencies=_xhr,
)
async def keep_partial(
    db: DbSession,
    journey_id: str,
    attempt_id: str,
    data: InteractionStopRequest,
) -> InteractionStopResponse:
    return await _service.keep_partial(
        db,
        journey_id=journey_id,
        attempt_id=attempt_id,
        expected_selection_epoch=data.expected_selection_epoch,
    )


@router.post(
    "/journeys/{journey_id}/attempts/{attempt_id}/continue",
    response_model=InteractionMutationResponse,
    dependencies=_xhr,
)
async def continue_attempt(
    db: DbSession,
    journey_id: str,
    attempt_id: str,
    data: InteractionContinueRequest,
) -> InteractionMutationResponse:
    return await _service.continue_attempt(
        db,
        journey_id=journey_id,
        attempt_id=attempt_id,
        expected_selection_epoch=data.expected_selection_epoch,
        idempotency_key=data.idempotency_key,
    )


@router.post(
    "/journeys/{journey_id}/attempts/{attempt_id}/retry",
    response_model=InteractionMutationResponse,
    dependencies=_xhr,
)
async def retry_attempt(
    db: DbSession,
    journey_id: str,
    attempt_id: str,
    data: InteractionRegenerateRequest,
) -> InteractionMutationResponse:
    return await _service.retry_attempt(
        db,
        journey_id=journey_id,
        attempt_id=attempt_id,
        expected_selection_epoch=data.expected_selection_epoch,
        idempotency_key=data.idempotency_key,
    )


@router.patch(
    "/journeys/{journey_id}/modes",
    response_model=InteractionMutationResponse,
    dependencies=_xhr,
)
async def update_modes(
    db: DbSession,
    journey_id: str,
    data: JourneyModeUpdateRequest,
) -> InteractionMutationResponse:
    return await _service.update_modes(
        db,
        journey_id=journey_id,
        see_sea_enabled=data.see_sea_enabled,
        action_options_enabled=data.action_options_enabled,
        expected_selection_epoch=data.expected_selection_epoch,
    )


@router.post(
    "/journeys/{journey_id}/heartbeat",
    response_model=InteractionHeartbeatResponse,
    dependencies=_xhr,
)
async def heartbeat(
    db: DbSession,
    journey_id: str,
) -> InteractionHeartbeatResponse:
    return await _service.heartbeat(db, journey_id=journey_id)


@router.post(
    "/journeys/{journey_id}/leave",
    response_model=InteractionHeartbeatResponse,
    dependencies=_xhr,
)
async def leave_story_page(
    db: DbSession,
    journey_id: str,
) -> InteractionHeartbeatResponse:
    return await _service.leave_story_page(db, journey_id=journey_id)


@router.get("/preferences", response_model=InteractionPreferencesResponse)
async def get_preferences(db: DbSession) -> InteractionPreferencesResponse:
    return await _service.get_preferences(db)


@router.post(
    "/preferences/see-sea-notice",
    response_model=InteractionPreferencesResponse,
    dependencies=_xhr,
)
async def acknowledge_see_sea_notice(
    db: DbSession,
) -> InteractionPreferencesResponse:
    return await _service.acknowledge_see_sea_notice(db)


@router.patch(
    "/journeys/{journey_id}/title",
    response_model=JourneyDetailResponse,
    dependencies=_xhr,
)
async def update_title(
    db: DbSession,
    journey_id: str,
    data: JourneyTitleUpdateRequest,
) -> JourneyDetailResponse:
    return await _service.update_title(
        db,
        journey_id=journey_id,
        title=data.title,
    )


@router.get(
    "/journeys/{journey_id}/overview",
    response_model=InteractionOverviewResponse,
)
async def get_overview(
    db: DbSession,
    journey_id: str,
) -> InteractionOverviewResponse:
    return await _service.get_overview(db, journey_id=journey_id)


@router.put(
    "/journeys/{journey_id}/overview",
    response_model=InteractionOverviewResponse,
    dependencies=_xhr,
)
async def update_overview(
    db: DbSession,
    journey_id: str,
    data: InteractionOverviewUpdateRequest,
) -> InteractionOverviewResponse:
    return await _service.update_overview(
        db,
        journey_id=journey_id,
        sections=data.sections,
        expected_overview_epoch=data.expected_overview_epoch,
        expected_selection_epoch=data.expected_selection_epoch,
        base_revision_id=data.base_revision_id,
        base_selected_leaf_node_id=data.base_selected_leaf_node_id,
        base_selected_path_hash=data.base_selected_path_hash,
    )


@router.post(
    "/journeys/{journey_id}/overview/retry",
    response_model=InteractionOverviewResponse,
    dependencies=_xhr,
)
async def retry_overview(
    db: DbSession,
    journey_id: str,
) -> InteractionOverviewResponse:
    return await _service.retry_overview(db, journey_id=journey_id)


@router.post(
    "/journeys/{journey_id}/archive",
    response_model=JourneyDetailResponse,
    dependencies=_xhr,
)
async def archive_journey(
    db: DbSession,
    journey_id: str,
    data: InteractionArchiveRequest,
) -> JourneyDetailResponse:
    return await _service.archive_journey(
        db,
        journey_id=journey_id,
        confirmed=data.confirmed,
    )


@router.post(
    "/journeys/{journey_id}/restore",
    response_model=JourneyDetailResponse,
    dependencies=_xhr,
)
async def restore_journey(
    db: DbSession,
    journey_id: str,
) -> JourneyDetailResponse:
    return await _service.restore_journey(db, journey_id=journey_id)


@router.delete(
    "/journeys/{journey_id}",
    status_code=204,
    dependencies=_xhr,
)
async def delete_journey(
    db: DbSession,
    journey_id: str,
    data: InteractionDeleteRequest,
) -> None:
    await _service.delete_journey(
        db,
        journey_id=journey_id,
        title_confirmation=data.title_confirmation,
    )


@router.get(
    "/journeys/{journey_id}/export",
    response_model=InteractionExportResponse,
)
async def export_journey(
    db: DbSession,
    journey_id: str,
    format_name: str = Query(default="md", alias="format"),
    story_only: bool = Query(default=False),
    include_overview: bool = Query(default=True),
) -> InteractionExportResponse:
    filename, media_type, content = await _service.export_journey(
        db,
        journey_id=journey_id,
        format_name=format_name,
        story_only=story_only,
        include_overview=include_overview,
    )
    return InteractionExportResponse(
        filename=filename,
        media_type=media_type,
        content=content,
    )


@router.get("/journeys/{journey_id}", response_model=JourneyDetailResponse)
async def get_journey(
    db: DbSession,
    journey_id: str,
) -> JourneyDetailResponse:
    return await _service.get_journey(db, journey_id)
