"""世界改动记录与修订备注路由。"""

from __future__ import annotations

from typing import Literal

from fastapi import Query

from core.dependencies import DbSession
from modules.world.api._shared import (
    ActiveNovelIdQuery,
    _change_history_service,
    router,
)
from modules.world.revision_history_schemas import (
    RevisionNoteResponse,
    RevisionNoteUpdateRequest,
    WorldChangeHistoryResponse,
)
from modules.world.services.revision_notes import set_revision_note


@router.get("/change-history", response_model=WorldChangeHistoryResponse)
async def list_world_change_history(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    kinds: list[Literal["entity", "page", "map"]] | None = Query(
        default=None, description="按类型筛选，可重复传：entity/page/map"
    ),
    cursor: str | None = Query(default=None, description="翻页游标（不透明 base64）"),
    limit: int = Query(
        default=30,
        ge=1,
        le=50,
        description="每页条数（1–50，默认 30）",
    ),
) -> WorldChangeHistoryResponse:
    return await _change_history_service.list(
        db,
        novel_id=novel_id,
        kinds=kinds,
        cursor=cursor,
        limit=limit,
    )


@router.put("/revision-notes", response_model=RevisionNoteResponse)
async def put_revision_note(
    db: DbSession,
    data: RevisionNoteUpdateRequest,
    *,
    novel_id: ActiveNovelIdQuery,
) -> RevisionNoteResponse:
    return await set_revision_note(
        db,
        novel_id,
        data.target_kind,
        data.revision_id,
        data.note,
    )
