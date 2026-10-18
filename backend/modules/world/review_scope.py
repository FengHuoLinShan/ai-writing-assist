"""Freeze matching identities, inspect finite pages, record explicit author checks."""

from datetime import UTC
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.stable_hash import stable_hash
from modules.project.facade import require_active_project
from modules.world.models import CoreEntity, WorldEntityReviewScope
from modules.world.repositories import CoreEntityRepository

MAX_MEMBERS = 10_000
PAGE_SIZE = 20


class ScopeFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type: str | None = None
    status: str | None = None
    display_state: Literal["active", "review", "archived"] | None = None
    q: str | None = Field(default=None, max_length=500)
    source: str | None = None
    workflow_id: str | None = None
    needs_review: bool | None = None
    auto_ingested: bool | None = None
    suggested_action: str | None = None
    scene_id: str | None = None
    scene_index: int | None = None
    source_chapter_index: int | None = None
    confidence_min: float | None = Field(default=None, ge=0, le=1)
    confidence_max: float | None = Field(default=None, ge=0, le=1)


class ScopeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    filters: ScopeFilters


class ScopeDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    entity_ids: list[UUID] = Field(min_length=1, max_length=PAGE_SIZE)
    disposition: Literal["checked", "deferred", "pending"]


def stamp(value):
    return (
        value.replace(tzinfo=UTC).isoformat()
        if value and value.tzinfo is None
        else value.isoformat()
        if value
        else ""
    )


async def _scope(db, novel_id, scope_id, *, lock=False):
    await require_active_project(db, novel_id)
    stmt = select(WorldEntityReviewScope).where(
        WorldEntityReviewScope.novel_id == UUID(novel_id),
        WorldEntityReviewScope.id == UUID(str(scope_id)),
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    row = await db.scalar(stmt)
    if row is None:
        raise NotFoundError("这份整理范围不属于当前作品")
    return row


async def freeze(db, novel_id, data: ScopeCreate):
    await require_active_project(db, novel_id)
    filters = data.filters.model_dump(exclude_none=True)
    existing = await db.scalar(
        select(WorldEntityReviewScope).where(
            WorldEntityReviewScope.novel_id == UUID(novel_id),
            WorldEntityReviewScope.operation_id == str(data.operation_id),
        )
    )
    if existing:
        if existing.filters_json != filters:
            raise ConflictError("这次冻结请求的条件已变化，请重新准备")
        return await read_scope(db, novel_id, existing.id)
    entities, total = await CoreEntityRepository().get_by_novel(
        db, UUID(novel_id), **filters, limit=MAX_MEMBERS + 1
    )
    if total > MAX_MEMBERS or len(entities) > MAX_MEMBERS:
        raise ValidationError("一次整理最多冻结一万个对象，请缩小筛选范围后分次处理")
    row = WorldEntityReviewScope(
        novel_id=UUID(novel_id),
        operation_id=str(data.operation_id),
        revision=1,
        filters_json=filters,
        members_json=[
            {
                "entity_id": str(item.id),
                "name": item.name,
                "entity_type": item.entity_type,
                "updated_at": stamp(item.updated_at),
            }
            for item in entities
        ],
        decisions_json={},
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        # Concurrent retries share one membership list; never silently freeze a new one.
        existing = await db.scalar(
            select(WorldEntityReviewScope).where(
                WorldEntityReviewScope.novel_id == UUID(novel_id),
                WorldEntityReviewScope.operation_id == str(data.operation_id),
            )
        )
        if existing is None:
            raise
        if existing.filters_json != filters:
            raise ConflictError("这次冻结请求的条件已变化，请重新准备") from None
        row = existing
    return await read_scope(db, novel_id, row.id)


async def _versions(db, novel_id, members):
    # Query lightweight versions once; never preload world prose into the browser/model.
    rows = (
        await db.execute(
            select(CoreEntity.id, CoreEntity.updated_at).where(
                CoreEntity.novel_id == UUID(novel_id),
                CoreEntity.id.in_([UUID(item["entity_id"]) for item in members]),
            )
        )
    ).all()
    return {str(identity): stamp(version) for identity, version in rows}


async def read_scope(db, novel_id, scope_id, *, skip=0):
    row = await _scope(db, novel_id, scope_id)
    members = row.members_json
    versions = await _versions(db, novel_id, members)
    checked = stale = deferred = 0
    page = []
    for index, item in enumerate(members):
        changed = versions.get(item["entity_id"]) != item["updated_at"]
        disposition = row.decisions_json.get(item["entity_id"], "pending")
        stale += changed
        checked += not changed and disposition == "checked"
        deferred += not changed and disposition == "deferred"
        if skip <= index < skip + PAGE_SIZE:
            page.append({**item, "stale": changed, "disposition": disposition})
    return {
        "id": str(row.id),
        "revision": row.revision,
        "created_at": row.created_at,
        "filters": row.filters_json,
        "fingerprint": stable_hash(members),
        "total": len(members),
        "checked": checked,
        "deferred": deferred,
        "stale": stale,
        "remaining": len(members) - checked - deferred,
        "items": page,
        "skip": skip,
        "limit": PAGE_SIZE,
        "has_more": skip + PAGE_SIZE < len(members),
        "omission": (
            "只冻结对象身份与保存版本；新增对象不加入。"
            "人工核对不代表 AI 已检查；同名仅是查重线索。"
        ),
    }


async def decide(db, novel_id, scope_id, data: ScopeDecision):
    row = await _scope(db, novel_id, scope_id, lock=True)
    if row.revision != data.expected_revision:
        raise ConflictError("整理进度已变化，请刷新后再标记；当前输入仍可保留")
    ids = {str(item) for item in data.entity_ids}
    members = [item for item in row.members_json if item["entity_id"] in ids]
    if len(members) != len(ids):
        raise ValidationError("不能标记这份冻结范围之外的对象")
    versions = await _versions(db, novel_id, members)
    if data.disposition != "pending" and any(
        versions.get(item["entity_id"]) != item["updated_at"] for item in members
    ):
        raise ConflictError("对象已变化或移除，请保留待核对并重新冻结当前范围")
    row.decisions_json = {**row.decisions_json, **dict.fromkeys(ids, data.disposition)}
    row.revision += 1
    await db.flush()
    return {
        "id": str(row.id),
        "revision": row.revision,
        "disposition": data.disposition,
        "count": len(ids),
    }


async def recent(db, novel_id):
    await require_active_project(db, novel_id)
    rows = (
        await db.scalars(
            select(WorldEntityReviewScope)
            .where(WorldEntityReviewScope.novel_id == UUID(novel_id))
            .order_by(WorldEntityReviewScope.created_at.desc(), WorldEntityReviewScope.id)
            .limit(10)
        )
    ).all()
    return [
        {
            "id": str(row.id),
            "created_at": row.created_at,
            "total": len(row.members_json),
            "filters": row.filters_json,
        }
        for row in rows
    ]
