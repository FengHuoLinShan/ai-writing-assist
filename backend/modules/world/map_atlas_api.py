"""Thin HTTP adapter for the owner-only AI map atlas."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from core.csrf import require_xhr_request
from core.dependencies import DbSession
from modules.project.facade import require_active_project
from modules.world.map_atlas_schemas import (
    MapAtlasAnnotationResponse,
    MapAtlasAnnotationUpdate,
    MapAtlasConfirmPromptsRequest,
    MapAtlasDerivedRequest,
    MapAtlasNodeResponse,
    MapAtlasNodeUpdate,
    MapAtlasPageResponse,
    MapAtlasPromptResponse,
    MapAtlasPromptUpdate,
    MapAtlasRetryRequest,
    MapAtlasReviewRequest,
    MapAtlasRunCreate,
    MapAtlasRunResponse,
    MapAtlasStopResponse,
    MapAtlasTreeResponse,
)
from modules.world.map_atlas_service import MapAtlasService, parse_reference_page_ids
from modules.world.map_atlas_storage import MAX_IMAGE_BYTES

router = APIRouter(prefix="/api/world/map-atlas", tags=["world-map-atlas"])
_service = MapAtlasService()
_xhr = [Depends(require_xhr_request)]


async def _require_active_novel_id(db: DbSession, novel_id: str) -> str:
    await require_active_project(db, novel_id)
    return novel_id


ActiveNovelId = Annotated[str, Depends(_require_active_novel_id)]


async def _read_bounded_png(upload: UploadFile | None) -> bytes | None:
    if upload is None:
        return None
    payload = await upload.read(MAX_IMAGE_BYTES)
    if len(payload) >= MAX_IMAGE_BYTES or await upload.read(1):
        raise HTTPException(status_code=413, detail="PNG 必须小于 50MB")
    return payload


async def _read_bounded_image(upload: UploadFile) -> bytes:
    payload = await upload.read(MAX_IMAGE_BYTES)
    if len(payload) >= MAX_IMAGE_BYTES or await upload.read(1):
        raise HTTPException(status_code=413, detail="图片必须小于 50MB")
    return payload


@router.post(
    "/{novel_id}/runs",
    response_model=MapAtlasRunResponse,
    status_code=202,
    dependencies=_xhr,
)
async def create_run(
    db: DbSession,
    novel_id: ActiveNovelId,
    data: MapAtlasRunCreate,
):
    return await _service.create_run(db, novel_id, data)


@router.get(
    "/{novel_id}/runs/latest",
    response_model=MapAtlasRunResponse | None,
)
async def get_latest_run(db: DbSession, novel_id: ActiveNovelId):
    return await _service.get_latest_run(db, novel_id)


@router.get("/{novel_id}/runs/{run_id}", response_model=MapAtlasRunResponse)
async def get_run(db: DbSession, novel_id: ActiveNovelId, run_id: str):
    return await _service.get_run(db, novel_id, run_id)


@router.post(
    "/{novel_id}/runs/{run_id}/stop",
    response_model=MapAtlasStopResponse,
    dependencies=_xhr,
)
async def stop_run(db: DbSession, novel_id: ActiveNovelId, run_id: str):
    return await _service.stop_run(db, novel_id, run_id)


@router.post(
    "/{novel_id}/runs/{run_id}/resume",
    response_model=MapAtlasRunResponse,
    dependencies=_xhr,
)
async def resume_run(
    db: DbSession,
    novel_id: ActiveNovelId,
    run_id: str,
    data: MapAtlasRetryRequest,
):
    return await _service.resume_run(
        db,
        novel_id,
        run_id,
        confirm_possible_duplicate_charge=data.confirm_possible_duplicate_charge,
    )


@router.get(
    "/{novel_id}/runs/{run_id}/results",
    response_model=MapAtlasTreeResponse,
)
async def get_run_results(db: DbSession, novel_id: ActiveNovelId, run_id: str):
    return await _service.get_tree(db, novel_id, run_id=run_id)


@router.post(
    "/{novel_id}/runs/{run_id}/confirm-prompts",
    response_model=MapAtlasRunResponse,
    dependencies=_xhr,
)
async def confirm_prompts(
    db: DbSession,
    novel_id: ActiveNovelId,
    run_id: str,
    data: MapAtlasConfirmPromptsRequest,
):
    return await _service.confirm_prompts(db, novel_id, run_id, data)


@router.get("/{novel_id}/atlas", response_model=MapAtlasTreeResponse)
async def get_atlas(db: DbSession, novel_id: ActiveNovelId):
    return await _service.get_tree(db, novel_id)


@router.get(
    "/{novel_id}/pages/history",
    response_model=list[MapAtlasPageResponse],
)
async def get_page_history(db: DbSession, novel_id: ActiveNovelId):
    return await _service.get_archived_pages(db, novel_id)


@router.get(
    "/{novel_id}/pages/{page_id}/prompt",
    response_model=MapAtlasPromptResponse,
)
async def get_page_prompt(db: DbSession, novel_id: ActiveNovelId, page_id: str):
    return await _service.get_prompt(db, novel_id, page_id)


@router.patch(
    "/{novel_id}/pages/{page_id}/prompt",
    response_model=MapAtlasPromptResponse,
    dependencies=_xhr,
)
async def update_page_prompt(
    db: DbSession,
    novel_id: ActiveNovelId,
    page_id: str,
    data: MapAtlasPromptUpdate,
):
    return await _service.update_prompt(db, novel_id, page_id, data)


@router.post(
    "/{novel_id}/pages/upload",
    response_model=MapAtlasPageResponse,
    status_code=201,
    dependencies=_xhr,
)
async def upload_page(
    db: DbSession,
    novel_id: ActiveNovelId,
    image: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=255)] = None,
    level: Annotated[str | None, Form()] = None,
    parent_id: Annotated[str | None, Form()] = None,
    node_id: Annotated[str | None, Form()] = None,
):
    if level is not None and level not in {
        "cover",
        "world",
        "region",
        "city",
        "district",
        "street",
        "interior",
    }:
        raise HTTPException(status_code=422, detail="地图层级无效")
    return await _service.upload_page(
        db,
        novel_id,
        payload=await _read_bounded_image(image),
        title=title,
        level=level,
        parent_id=parent_id,
        node_id=node_id,
    )


@router.patch(
    "/{novel_id}/nodes/{node_id}",
    response_model=MapAtlasNodeResponse,
    dependencies=_xhr,
)
async def update_node(
    db: DbSession,
    novel_id: ActiveNovelId,
    node_id: str,
    data: MapAtlasNodeUpdate,
):
    return await _service.update_node(db, novel_id, node_id, data)


async def _review(
    db: DbSession,
    novel_id: ActiveNovelId,
    page_id: str,
    action: str,
    data: MapAtlasReviewRequest,
):
    return await _service.review_page(db, novel_id, page_id, action, data)


@router.post(
    "/{novel_id}/pages/{page_id}/adopt",
    response_model=MapAtlasPageResponse,
    dependencies=_xhr,
)
async def adopt_page(
    db: DbSession,
    novel_id: ActiveNovelId,
    page_id: str,
    data: MapAtlasReviewRequest,
):
    return await _review(db, novel_id, page_id, "adopt", data)


@router.post(
    "/{novel_id}/pages/{page_id}/reject",
    response_model=MapAtlasPageResponse,
    dependencies=_xhr,
)
async def reject_page(
    db: DbSession,
    novel_id: ActiveNovelId,
    page_id: str,
    data: MapAtlasReviewRequest,
):
    return await _review(db, novel_id, page_id, "reject", data)


@router.post(
    "/{novel_id}/pages/{page_id}/archive",
    response_model=MapAtlasPageResponse,
    dependencies=_xhr,
)
async def archive_page(
    db: DbSession,
    novel_id: ActiveNovelId,
    page_id: str,
    data: MapAtlasReviewRequest,
):
    return await _review(db, novel_id, page_id, "archive", data)


@router.post(
    "/{novel_id}/pages/{page_id}/restore",
    response_model=MapAtlasPageResponse,
    dependencies=_xhr,
)
async def restore_page(
    db: DbSession,
    novel_id: ActiveNovelId,
    page_id: str,
    data: MapAtlasReviewRequest,
):
    return await _review(db, novel_id, page_id, "restore", data)


@router.post(
    "/{novel_id}/pages/{page_id}/retry",
    response_model=MapAtlasPageResponse,
    dependencies=_xhr,
)
async def retry_page(
    db: DbSession,
    novel_id: ActiveNovelId,
    page_id: str,
    data: MapAtlasRetryRequest,
):
    return await _service.retry_page(
        db,
        novel_id,
        page_id,
        confirm_possible_duplicate_charge=data.confirm_possible_duplicate_charge,
    )


@router.post(
    "/{novel_id}/pages/{page_id}/regenerate",
    response_model=MapAtlasPageResponse,
    status_code=202,
    dependencies=_xhr,
)
async def regenerate_page(
    db: DbSession,
    novel_id: ActiveNovelId,
    page_id: str,
    data: MapAtlasDerivedRequest,
):
    return await _service.create_derived_page(
        db,
        novel_id,
        page_id,
        data,
        mode="regenerate",
    )


@router.post(
    "/{novel_id}/pages/{page_id}/edit",
    response_model=MapAtlasPageResponse,
    status_code=202,
    dependencies=_xhr,
)
async def edit_page(
    db: DbSession,
    novel_id: ActiveNovelId,
    page_id: str,
    instruction: Annotated[str, Form(min_length=1, max_length=4000)],
    reference_page_ids: Annotated[str | None, Form()] = None,
    mask: Annotated[UploadFile | None, File()] = None,
):
    data = MapAtlasDerivedRequest(
        instruction=instruction,
        reference_page_ids=parse_reference_page_ids(reference_page_ids),
    )
    mask_bytes = await _read_bounded_png(mask)
    return await _service.create_derived_page(
        db,
        novel_id,
        page_id,
        data,
        mode="edit",
        mask=mask_bytes,
    )


@router.patch(
    "/{novel_id}/annotations/{annotation_id}",
    response_model=MapAtlasAnnotationResponse,
    dependencies=_xhr,
)
async def update_annotation(
    db: DbSession,
    novel_id: ActiveNovelId,
    annotation_id: str,
    data: MapAtlasAnnotationUpdate,
):
    return await _service.update_annotation(db, novel_id, annotation_id, data)


@router.get("/{novel_id}/pages/{page_id}/image")
async def read_page_image(db: DbSession, novel_id: ActiveNovelId, page_id: str):
    chunks = await _service.read_page_image(db, novel_id, page_id)
    return StreamingResponse(
        chunks,
        media_type="image/png",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
