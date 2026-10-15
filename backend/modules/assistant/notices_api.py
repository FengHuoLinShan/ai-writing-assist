"""Authenticated author-facing HTTP surface for unified notices."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Path

from core.container import get
from core.dependencies import DbSession
from core.errors import ValidationError
from core.service_keys import OUTLINE_SCENE_SERVICE
from modules.assistant.notice_contracts import (
    NoticeCategoryMuteRequest,
    NoticeDispositionRequest,
    NoticeScope,
)
from modules.assistant.notice_service import (
    apply_disposition,
    list_notices,
    set_category_mute,
)
from modules.project.facade import require_active_project

router = APIRouter(prefix="/api/assistant/unified-notices", tags=["assistant-notices"])


async def _authorize_scope(db, novel_id: UUID, scope: NoticeScope) -> None:
    await require_active_project(db, str(novel_id))
    if scope.scene_id is not None:
        # SceneService enforces both existence and novel ownership.
        await get(OUTLINE_SCENE_SERVICE).get(
            db, str(scope.scene_id), novel_id=str(novel_id)
        )


@router.get(
    "",
    openapi_extra={
        "x-novelcraft-operation-exemption": (
            "Read-only notice aggregation; no author state is changed."
        )
    },
)
async def get_unified_notices(
    db: DbSession,
    novel_id: UUID,
    scene_id: UUID | None = None,
    chapter_index: int | None = None,
):
    if scene_id is None and chapter_index is None:
        raise HTTPException(status_code=422, detail="需要选择场景或章节")
    await require_active_project(db, str(novel_id))
    scope = NoticeScope(scene_id=scene_id, chapter_index=chapter_index)
    await _authorize_scope(db, novel_id, scope)
    return await list_notices(db, str(novel_id), scope)


@router.post(
    "/dispositions",
    openapi_extra={"x-novelcraft-operation-id": "assistant.notice.set_disposition"},
)
async def update_notice_disposition(db: DbSession, data: NoticeDispositionRequest):
    await _authorize_scope(db, data.novel_id, data.scope)
    return await apply_disposition(db, data)


@router.put(
    "/category-mutes/{source_id}/{category}",
    openapi_extra={"x-novelcraft-operation-id": "assistant.notice.mute_category"},
)
async def mute_notice_category(
    db: DbSession,
    source_id: str = Path(pattern=r"^[a-z][a-z0-9_.]{1,80}$"),
    category: str = Path(min_length=1, max_length=80),
    data: NoticeCategoryMuteRequest = ...,
):
    await require_active_project(db, str(data.novel_id))
    if not category.strip():
        raise ValidationError("提醒类别不能为空")
    return await set_category_mute(
        db,
        str(data.novel_id),
        source_id,
        category,
        data.expected_row_version,
        muted=True,
    )


@router.delete(
    "/category-mutes/{source_id}/{category}",
    openapi_extra={"x-novelcraft-operation-id": "assistant.notice.unmute_category"},
)
async def unmute_notice_category(
    db: DbSession,
    source_id: str = Path(pattern=r"^[a-z][a-z0-9_.]{1,80}$"),
    category: str = Path(min_length=1, max_length=80),
    data: NoticeCategoryMuteRequest = ...,
):
    await require_active_project(db, str(data.novel_id))
    if not category.strip():
        raise ValidationError("提醒类别不能为空")
    return await set_category_mute(
        db,
        str(data.novel_id),
        source_id,
        category,
        data.expected_row_version,
        muted=False,
    )
