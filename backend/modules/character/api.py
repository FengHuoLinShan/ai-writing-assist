"""
Character API 路由

提供人物档案和人物知识边界的 REST API。
API 层不写复杂业务逻辑，仅做参数校验和路由分发。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

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


class TaskSubmitResponse(BaseModel):
    """任务提交响应"""
    task_id: str
    status: str = "pending"


class ApplySuggestionsRequest(BaseModel):
    """应用 AI 建议请求"""
    fields: list[str]
    """要应用的字段列表"""


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
    novel_id: str = Query(..., description="小说项目 ID"),
) -> CharacterResponse:
    """获取人物详情"""
    return await _service.get_character(db, character_id, novel_id=novel_id)


@router.put("/{character_id}", response_model=CharacterResponse)
async def update_character(
    db: DbSession,
    character_id: str,
    data: CharacterUpdate,
    novel_id: str = Query(..., description="小说项目 ID"),
) -> CharacterResponse:
    """更新人物信息"""
    return await _service.update_character(db, character_id, data, novel_id=novel_id)


@router.delete("/{character_id}", status_code=204)
async def delete_character(
    db: DbSession,
    character_id: str,
    novel_id: str = Query(..., description="小说项目 ID"),
) -> None:
    """删除人物"""
    await _service.delete_character(db, character_id, novel_id=novel_id)


# ============================================================
# AI 抽取
# ============================================================


@router.post("/{character_id}/extract", response_model=TaskSubmitResponse, status_code=201)
async def extract_character(
    db: DbSession,
    character_id: str,
    novel_id: str = Query(..., description="小说项目 ID"),
) -> TaskSubmitResponse:
    """提交单个人物的档案抽取任务

    用 RAG 检索章节正文中与该角色相关的内容，
    调用 LLM 抽取档案字段，写入 meta.ai_suggestions。
    """
    from infrastructure.tasks.models import AsyncTask

    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="character_extract",
        status="pending",
        meta={"novel_id": novel_id, "character_id": character_id},
        progress=0.0,
    )
    db.add(task)
    await db.flush()
    return TaskSubmitResponse(task_id=str(task.id))


@router.post("/extract-all", response_model=list[TaskSubmitResponse], status_code=201)
async def extract_all_characters(
    db: DbSession,
    novel_id: str = Query(..., description="小说项目 ID"),
) -> list[TaskSubmitResponse]:
    """提交所有人物档案的抽取任务"""
    from infrastructure.tasks.models import AsyncTask

    chars, _ = await _service.list_characters(db, novel_id, limit=999)
    tasks = []
    for char in chars:
        task = AsyncTask(
            id=uuid.uuid4(),
            task_type="character_extract",
            status="pending",
            meta={"novel_id": novel_id, "character_id": char.id},
            progress=0.0,
        )
        db.add(task)
        tasks.append(task)
    await db.flush()
    return [
        TaskSubmitResponse(task_id=str(t.id))
        for t in tasks
    ]


@router.get("/{character_id}/suggestions")
async def get_character_suggestions(
    db: DbSession,
    character_id: str,
    novel_id: str = Query(..., description="小说项目 ID"),
) -> dict:
    """获取人物的 AI 抽取建议（meta.ai_suggestions）"""
    char = await _service.get_character(db, character_id, novel_id=novel_id)
    meta = getattr(char, "meta", {}) or {}
    return {"suggestions": meta.get("ai_suggestions", {}), "updated_at": meta.get("ai_suggestions_at")}


@router.put("/{character_id}/apply-suggestions", response_model=CharacterResponse)
async def apply_character_suggestions(
    db: DbSession,
    character_id: str,
    novel_id: str = Query(..., description="小说项目 ID"),
    request: ApplySuggestionsRequest | None = None,
) -> CharacterResponse:
    """应用 AI 建议到人物字段

    将 ai_suggestions 中的指定字段应用到人物原型字段，
    并清除已应用的 suggestions。
    """
    char = await _service.get_character(db, character_id, novel_id=novel_id)

    meta = dict(getattr(char, "meta", {}) or {})
    suggestions = meta.get("ai_suggestions", {})

    if not suggestions:
        raise HTTPException(400, detail="没有待应用的 AI 建议")

    fields_to_apply = request.fields if request and request.fields else list(suggestions.keys())
    if not fields_to_apply:
        raise HTTPException(400, detail="请指定要应用的字段")

    # 构建更新数据
    updates: dict[str, object] = {}
    for field in fields_to_apply:
        if field in suggestions and suggestions[field]:
            raw_value = suggestions[field]
            # 移除 #包围的原始内容保留
            from modules.character.tasks import _EXTRACTABLE_FIELDS
            if field in _EXTRACTABLE_FIELDS:
                updates[field] = raw_value

    if not updates:
        raise HTTPException(400, detail="没有可应用的字段")

    # 清除已应用的 suggestions
    remaining_suggestions = {k: v for k, v in suggestions.items() if k not in fields_to_apply}
    meta["ai_suggestions"] = remaining_suggestions
    if not remaining_suggestions:
        meta.pop("ai_suggestions", None)
        meta.pop("ai_suggestions_at", None)
    updates["meta"] = meta

    update_data = CharacterUpdate(**updates)
    return await _service.update_character(db, character_id, update_data, novel_id=novel_id)


@router.patch("/{character_id}/state", response_model=CharacterResponse)
async def update_character_state(
    db: DbSession,
    character_id: str,
    novel_id: str = Query(..., description="小说项目 ID"),
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
        novel_id=novel_id,
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
    novel_id: str = Query(..., description="小说项目 ID"),
) -> CharacterKnowledgeResponse:
    """获取单条知识记录"""
    return await _service.get_knowledge(db, knowledge_id, novel_id=novel_id)


@router.put(
    "/knowledge/{knowledge_id}",
    response_model=CharacterKnowledgeResponse,
)
async def update_character_knowledge(
    db: DbSession,
    knowledge_id: str,
    data: CharacterKnowledgeUpdate,
    novel_id: str = Query(..., description="小说项目 ID"),
) -> CharacterKnowledgeResponse:
    """更新知识记录"""
    return await _service.update_knowledge(db, knowledge_id, data, novel_id=novel_id)


@router.delete(
    "/knowledge/{knowledge_id}",
    status_code=204,
)
async def delete_character_knowledge(
    db: DbSession,
    knowledge_id: str,
    novel_id: str = Query(..., description="小说项目 ID"),
) -> None:
    """删除知识记录"""
    await _service.delete_knowledge(db, knowledge_id, novel_id=novel_id)


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
