"""
Memory API 路由

提供长期记忆记录的 CRUD API 和记忆提案的管理 API。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from core.dependencies import DbSession

from modules.memory.schemas import (
    MemoryProposalDecision,
    MemoryProposalListResponse,
    MemoryProposalResponse,
    MemoryRecordCreate,
    MemoryRecordListResponse,
    MemoryRecordResponse,
    MemoryRecordUpdate,
)
from modules.memory.services import MemoryService
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from shared.utils import parse_uuid

router = APIRouter(prefix="/api/novels/{novel_id}/memories", tags=["memory"])
_service = MemoryService()


# ============================================================
# 记忆记录 CRUD
# ============================================================

@router.post("/records", response_model=MemoryRecordResponse, status_code=201)
async def create_memory_record(
    db: DbSession,
    novel_id: str,
    data: MemoryRecordCreate,
) -> MemoryRecordResponse:
    """创建新的记忆记录"""
    return await _service.create_memory_record(db, novel_id, data)


@router.get("/records", response_model=MemoryRecordListResponse)
async def list_memory_records(
    db: DbSession,
    novel_id: str,
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
    memory_type: str | None = Query(None, description="记忆类型过滤"),
    status: str | None = Query(None, description="状态过滤"),
    before_chapter: int | None = Query(None, description="只返回该章节之前的记录"),
) -> MemoryRecordListResponse:
    """获取记忆记录列表"""
    items, total = await _service.list_memory_records(
        db,
        novel_id,
        skip=skip,
        limit=limit,
        memory_type=memory_type,
        status=status,
        before_chapter_index=before_chapter,
    )
    return MemoryRecordListResponse(items=items, total=total)


@router.get("/records/{record_id}", response_model=MemoryRecordResponse)
async def get_memory_record(
    db: DbSession,
    novel_id: str,
    record_id: str,
) -> MemoryRecordResponse:
    """获取记忆记录详情"""
    return await _service.get_memory_record(db, record_id, novel_id)


@router.put("/records/{record_id}", response_model=MemoryRecordResponse)
async def update_memory_record(
    db: DbSession,
    novel_id: str,
    record_id: str,
    data: MemoryRecordUpdate,
) -> MemoryRecordResponse:
    """更新记忆记录"""
    return await _service.update_memory_record(db, record_id, data, novel_id)


@router.delete("/records/{record_id}", status_code=204)
async def delete_memory_record(
    db: DbSession,
    novel_id: str,
    record_id: str,
) -> None:
    """删除记忆记录"""
    await _service.delete_memory_record(db, record_id, novel_id)


# ============================================================
# 记忆提案管理
# ============================================================

@router.get("/proposals/pending", response_model=MemoryProposalListResponse)
async def list_pending_proposals(
    db: DbSession,
    novel_id: str,
    skip: int = Query(default=0, ge=0, description="跳过的记录数"),
    limit: int = Query(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description="每页条数",
    ),
) -> MemoryProposalListResponse:
    """获取待处理的记忆提案列表"""
    items, total = await _service.list_pending_proposals(
        db, novel_id, skip=skip, limit=limit
    )
    return MemoryProposalListResponse(items=items, total=total)


@router.post("/proposals/{proposal_id}/decide", response_model=MemoryProposalResponse)
async def decide_proposal(
    db: DbSession,
    novel_id: str,
    proposal_id: str,
    decision: MemoryProposalDecision,
) -> MemoryProposalResponse:
    """处理记忆提案（批准/拒绝）"""
    pid = parse_uuid(proposal_id, "proposal_id")

    if decision.decision == "approved":
        # 批准：创建正史记忆记录
        await _service.confirm_memory_proposal(
            db,
            proposal_id,
            novel_id,
            edited_payload=decision.edited_payload,
            decided_by=decision.decided_by,
        )
    else:
        # 拒绝：标记为 rejected
        await _service.decide_proposal(
            db,
            pid,
            decision="rejected",
            decided_by=decision.decided_by,
        )

    # 返回更新后的提案信息
    record = await _service.get_memory_proposal(db, proposal_id, novel_id)
    return MemoryProposalResponse.model_validate(record)
