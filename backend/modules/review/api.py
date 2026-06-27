"""
Review API 路由

提供结构复查的 RESTful API。
API 层不写复杂业务逻辑，仅做参数校验和路由分发。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from core.dependencies import DbSession
from modules.review.schemas import (
    ReviewListResponse,
    ReviewReportResponse,
    ReviewRequest,
)
from modules.review.services import ReviewService
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/api/review", tags=["review"])

_service = ReviewService()


@router.get("", response_model=ReviewListResponse)
async def list_reports(
    db: DbSession,
    novel_id: str = Query(..., description="项目 ID"),
    target_type: str | None = Query(None, description="按目标类型筛选"),
    decision: str | None = Query(None, description="按决策筛选"),
    skip: int = Query(0, ge=0, description="跳过的记录数"),
    limit: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="每页条数"),
) -> ReviewListResponse:
    """获取复查报告列表"""
    items, total = await _service.list_reports(
        db,
        novel_id,
        target_type=target_type,
        decision=decision,
        skip=skip,
        limit=limit,
    )
    return ReviewListResponse(
        items=[
            ReviewReportResponse(
                id=r.report_id,
                novel_id=r.novel_id,
                target_type=r.target_type,
                target_id=r.target_id,
                status=r.status,
                decision=r.decision,
                score=r.score,
                problems=r.problems,
                conflict_warnings=r.conflict_warnings,
                early_reveal_warnings=r.early_reveal_warnings,
                character_knowledge_warnings=r.character_knowledge_warnings,
                duplicate_entity_warnings=r.duplicate_entity_warnings,
                geo_warnings=r.geo_warnings,
                revision_instructions=r.revision_instructions,
            )
            for r in items
        ],
        total=total,
    )


@router.post("", response_model=ReviewReportResponse, status_code=201)
async def submit_review(
    db: DbSession,
    request: ReviewRequest,
) -> ReviewReportResponse:
    """提交结构化候选进行复查

    对传入的候选结构执行全维度复查：
    - Schema 校验
    - 实体引用检查
    - 提前揭示检查
    - 人物知识边界检查
    - 时间线冲突检查
    - 地理冲突检查
    - 对象重复检查

    返回复查报告，包含决策（pass/minor_revision/major_revision/reject）
    和各类警告及修改建议。
    """
    context = await _service.run_all_checks(
        db,
        request.novel_id,
        request.target_type,
        request.candidate_payload,
    )
    return ReviewReportResponse(
        id=context.report_id,
        novel_id=context.novel_id,
        target_type=context.target_type,
        target_id=context.target_id,
        status=context.status,
        decision=context.decision,
        score=context.score,
        problems=context.problems,
        conflict_warnings=context.conflict_warnings,
        early_reveal_warnings=context.early_reveal_warnings,
        character_knowledge_warnings=context.character_knowledge_warnings,
        duplicate_entity_warnings=context.duplicate_entity_warnings,
        geo_warnings=context.geo_warnings,
        revision_instructions=context.revision_instructions,
    )


@router.get("/{review_id}", response_model=ReviewReportResponse)
async def get_report(
    db: DbSession,
    review_id: str,
    novel_id: str = Query(..., description="项目 ID"),
) -> ReviewReportResponse:
    """获取指定 ID 的复查报告详情"""
    context = await _service.get_report(db, review_id, novel_id)
    return ReviewReportResponse(
        id=context.report_id,
        novel_id=context.novel_id,
        target_type=context.target_type,
        target_id=context.target_id,
        status=context.status,
        decision=context.decision,
        score=context.score,
        problems=context.problems,
        conflict_warnings=context.conflict_warnings,
        early_reveal_warnings=context.early_reveal_warnings,
        character_knowledge_warnings=context.character_knowledge_warnings,
        duplicate_entity_warnings=context.duplicate_entity_warnings,
        geo_warnings=context.geo_warnings,
        revision_instructions=context.revision_instructions,
    )
