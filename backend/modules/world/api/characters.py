"""人物路由。"""

from __future__ import annotations

from fastapi import Query

from core.dependencies import DbSession
from modules.world.api._shared import (
    ActiveNovelIdQuery,
    _character_service,
    router,
)
from modules.world.schemas import (
    CharacterCreate,
    CharacterListResponse,
    CharacterResponse,
    CharacterUpdate,
)
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


@router.get("/characters", response_model=CharacterListResponse)
async def list_characters(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> CharacterListResponse:
    items, total = await _character_service.list(
        db,
        novel_id,
        skip=skip,
        limit=limit,
    )
    return CharacterListResponse(items=items, total=total)


@router.post("/characters", response_model=CharacterResponse, status_code=201)
async def create_character(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    data: CharacterCreate = ...,
) -> CharacterResponse:
    return await _character_service.create(db, novel_id, data)


@router.get("/characters/{character_id}", response_model=CharacterResponse)
async def get_character(
    db: DbSession,
    character_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> CharacterResponse:
    return await _character_service.get(
        db,
        character_id,
        novel_id=novel_id,
    )


@router.put("/characters/{character_id}", response_model=CharacterResponse)
async def update_character(
    db: DbSession,
    character_id: str,
    data: CharacterUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> CharacterResponse:
    return await _character_service.update(
        db,
        character_id,
        data,
        novel_id=novel_id,
        expected_updated_at=data.expected_updated_at,
        require_edit_baseline=True,
    )


@router.delete("/characters/{character_id}", status_code=204)
async def delete_character(
    db: DbSession,
    character_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> None:
    await _character_service.delete(db, character_id, novel_id=novel_id)
