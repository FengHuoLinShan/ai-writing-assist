"""
Character API 路由

提供人物档案和人物知识边界的 REST API。
API 层不写复杂业务逻辑，仅做参数校验和路由分发。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from core.dependencies import DbSession
from modules.character.schemas import (
    CharacterCreate,
    CharacterKnowledgeCreate,
    CharacterKnowledgeListResponse,
    CharacterKnowledgeResponse,
    CharacterKnowledgeUpdate,
    CharacterListResponse,
    CharacterResponse,
    CharacterUpdate,
    FilterContextRequest,
    FilterContextResponse,
)
from modules.character.services import CharacterService
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/api/characters", tags=["characters"])
_service = CharacterService()


# ============================================================
# Characters CRUD
# ============================================================

@router.post("", response_model=CharacterResponse, status_code=201)
async def create_character(
    db: DbSession,
    data: CharacterCreate,
) -> CharacterResponse:
    """创建新人物"""
    return await _service.create_character(db, data)


@router.get("", response_model=CharacterListResponse)
async def list_characters(
    db: DbSession,
    novel_id: str = Query(..., description="小说项目 ID"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> CharacterListResponse:
    """获取人物列表"""
    items, total = await _service.list_characters(
        db, novel_id, skip=skip, limit=limit,
    )
    return CharacterListResponse(items=items, total=total)


@router.get("/{character_id}", response_model=CharacterResponse)
async def get_character(
    db: DbSession,
    character_id: str,
) -> CharacterResponse:
    """获取人物详情"""
    return await _service.get_character(db, character_id)


@router.put("/{character_id}", response_model=CharacterResponse)
async def update_character(
    db: DbSession,
    character_id: str,
    data: CharacterUpdate,
) -> CharacterResponse:
    """更新人物信息"""
    return await _service.update_character(db, character_id, data)


@router.delete("/{character_id}", status_code=204)
async def delete_character(
    db: DbSession,
    character_id: str,
) -> None:
    """删除人物"""
    await _service.delete_character(db, character_id)


@router.patch("/{character_id}/state", response_model=CharacterResponse)
async def update_character_state(
    db: DbSession,
    character_id: str,
    current_state: str | None = Query(None, description="当前状态"),
    current_emotion: str | None = Query(None, description="当前情绪"),
    current_goal: str | None = Query(None, description="当前目标"),
) -> CharacterResponse:
    """更新人物当前状态（状态变化时的便捷 API）"""
    return await _service.update_character_state(
        db,
        character_id,
        current_state=current_state,
        current_emotion=current_emotion,
        current_goal=current_goal,
    )


# ============================================================
# Character Knowledge API
# ============================================================

@router.post(
    "/{character_id}/knowledge",
    response_model=CharacterKnowledgeResponse,
    status_code=201,
)
async def create_character_knowledge(
    db: DbSession,
    character_id: str,
    data: CharacterKnowledgeCreate,
) -> CharacterKnowledgeResponse:
    """创建人物知识记录"""
    # 确保 URL 中的 character_id 与请求体一致
    data.character_id = character_id
    return await _service.create_knowledge(db, data)


@router.get(
    "/{character_id}/knowledge",
    response_model=CharacterKnowledgeListResponse,
)
async def list_character_knowledge(
    db: DbSession,
    character_id: str,
    novel_id: str = Query(..., description="小说项目 ID"),
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> CharacterKnowledgeListResponse:
    """获取人物知识列表"""
    items, total = await _service.list_knowledge(
        db, novel_id, character_id, skip=skip, limit=limit,
    )
    return CharacterKnowledgeListResponse(items=items, total=total)


@router.get(
    "/knowledge/{knowledge_id}",
    response_model=CharacterKnowledgeResponse,
)
async def get_character_knowledge(
    db: DbSession,
    knowledge_id: str,
) -> CharacterKnowledgeResponse:
    """获取单条知识记录"""
    return await _service.get_knowledge(db, knowledge_id)


@router.put(
    "/knowledge/{knowledge_id}",
    response_model=CharacterKnowledgeResponse,
)
async def update_character_knowledge(
    db: DbSession,
    knowledge_id: str,
    data: CharacterKnowledgeUpdate,
) -> CharacterKnowledgeResponse:
    """更新知识记录"""
    return await _service.update_knowledge(db, knowledge_id, data)


@router.delete(
    "/knowledge/{knowledge_id}",
    status_code=204,
)
async def delete_character_knowledge(
    db: DbSession,
    knowledge_id: str,
) -> None:
    """删除知识记录"""
    await _service.delete_knowledge(db, knowledge_id)


# ============================================================
# Filter Context API（核心功能）
# ============================================================

@router.post(
    "/{character_id}/filter-context",
    response_model=FilterContextResponse,
)
async def filter_context(
    db: DbSession,
    character_id: str,
    novel_id: str = Query(..., description="小说项目 ID"),
    request: FilterContextRequest | None = None,
) -> FilterContextResponse:
    """按人物知识过滤上下文项

    根据角色对上下文项中目标的了解程度，过滤掉角色不该知道的信息。
    """
    items = request.context_items if request else []
    filtered, removed, replaced = (
        await _service.filter_context_by_character_knowledge(
            db, novel_id, character_id, items,
        )
    )
    return FilterContextResponse(
        filtered_items=filtered,
        removed_count=removed,
        replaced_count=replaced,
    )
