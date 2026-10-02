"""World object image generation candidates via the local CLI (ADR-0029).

The local CLI is only ever used behind our review wrapper: the server builds
the default prompt from the entity's already-confirmed data, the author may
edit it before submitting, and every result is a candidate the author must
explicitly adopt (via the existing ``WorldObjectImageService.upload`` path)
before it replaces the object's current image.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, NotFoundError
from infrastructure.llm.redaction import redact_diagnostic
from infrastructure.tasks.facade import (
    cancel_exact_task,
    enqueue_task,
    list_task_lifecycle_contracts,
)
from modules.local_agent.facade import (
    AgentExecutor,
    limit_edge,
    local_image_task_meta,
    run_local_image,
    selected_executor,
    task_awaiting_local_approval,
)
from modules.world.asset_state import display_state_for_status
from modules.world.image_request_reuse import (
    compute_request_hash,
    find_reusable_asset,
    invalidate_reusable_asset,
    record_reusable_asset,
)
from modules.world.models import CoreEntity
from modules.world.models.image_candidate import WorldObjectImageCandidate
from modules.world.world_object_images import WorldObjectImageService
from shared.constants import TASK_MAX_HEARTBEAT_GAP
from shared.utils import parse_uuid

TASK_TYPE = "world_object_image_generate"

_ENTITY_TYPE_LABELS = {
    "character": "人物",
    "faction": "阵营",
    "item": "物品",
    "location": "地点",
    "event": "事件",
}

MAX_PROMPT_CHARS = 4000
_LISTED_CANDIDATES = 5
_RETAINED_REVIEW_READY = 3
_GENERATION_WIDTH = 1024
_GENERATION_HEIGHT = 1024
_MAX_IMAGE_EDGE = 2048
_FALLBACK_IMAGE_EDGE = 1024
_MAX_UPLOAD_BYTES = 6 * 1024 * 1024


def _entity_type_label(entity_type: str) -> str:
    return _ENTITY_TYPE_LABELS.get(entity_type, entity_type or "对象")


def _confirmed_extra_lines(content_json: dict | None) -> list[str]:
    """Pick a few short plain-text attributes out of confirmed content_json.

    Only top-level string values are used; nested structures, internal
    ``_meta`` bookkeeping, and anything long-form are skipped so the prompt
    never leaks unrelated working data.
    """
    lines: list[str] = []
    for key, value in (content_json or {}).items():
        if key.startswith("_") or not isinstance(value, str):
            continue
        text = value.strip()
        if not text or len(text) > 200:
            continue
        lines.append(text)
        if len(lines) >= 4:
            break
    return lines


def default_image_prompt(entity: CoreEntity) -> str:
    """Build a prompt from the entity's CONFIRMED data only.

    Entities whose status is not in the confirmed/active projection (still a
    draft, candidate, conflicted, or archived) only contribute their name and
    type, never summary/content_json text, so an unconfirmed or retired fact
    never becomes part of an image request.
    """
    is_character = entity.entity_type == "character"
    label = _entity_type_label(entity.entity_type)
    segments = [f"{entity.name}，{label}。"]
    if display_state_for_status(entity.status) == "active":
        if entity.summary:
            summary = entity.summary.strip()
            if summary:
                segments.append(summary)
        segments.extend(_confirmed_extra_lines(entity.content_json))
    if is_character:
        segments.append("半身像构图，聚焦人物本身，背景简洁。")
    else:
        segments.append("单一主体的概念画面，背景简洁。")
    segments.append("画面中不要出现文字、水印或签名。")
    prompt = " ".join(part for part in segments if part)
    return prompt[:MAX_PROMPT_CHARS]


class WorldObjectImageCandidateView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    entity_id: str
    status: Literal[
        "queued",
        "generating",
        "review_ready",
        "adopted",
        "discarded",
        "failed",
        "cancelled",
    ]
    prompt: str
    error: str | None = None
    width: int | None = None
    height: int | None = None
    created_at: datetime
    updated_at: datetime | None = None
    task_id: str | None = None
    awaiting_approval: bool = False
    # B9：该候选为同参数复用命中（未调用生成服务）
    reused: bool = False


class WorldObjectImageGenerationInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool
    reason: str | None = None
    executor_kind: str | None = None
    default_prompt: str
    candidates: list[WorldObjectImageCandidateView]


class WorldObjectImageCandidateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: str
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    # B9：同参数默认复用已有本机生成结果（省时间）；「重新生成」传 True 绕过。
    force_refresh: bool = False

    @field_validator("prompt")
    @classmethod
    def _strip_prompt(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("请输入图片描述")
        return stripped


class WorldObjectImageCandidateAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: str


class WorldObjectImageCandidateAdoptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate: WorldObjectImageCandidateView
    image_version: str


class WorldObjectImageGenerationService:
    def __init__(self, *, image_service: WorldObjectImageService | None = None) -> None:
        self._image_service = image_service or WorldObjectImageService()

    # -- lookups ----------------------------------------------------------

    @staticmethod
    async def _entity(db: AsyncSession, novel_id: str, entity_id: str) -> CoreEntity:
        entity = (
            await db.execute(
                select(CoreEntity).where(
                    CoreEntity.id == parse_uuid(entity_id, "entity_id"),
                    CoreEntity.novel_id == parse_uuid(novel_id, "novel_id"),
                )
            )
        ).scalar_one_or_none()
        if entity is None:
            raise NotFoundError(f"CoreEntity {entity_id} not found")
        return entity

    @staticmethod
    async def _candidate(
        db: AsyncSession,
        novel_id: str,
        candidate_id: str,
        *,
        lock: bool = False,
    ) -> WorldObjectImageCandidate:
        stmt = select(WorldObjectImageCandidate).where(
            WorldObjectImageCandidate.id == parse_uuid(candidate_id, "candidate_id"),
            WorldObjectImageCandidate.novel_id == parse_uuid(novel_id, "novel_id"),
        )
        if lock:
            stmt = stmt.with_for_update()
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise NotFoundError(f"WorldObjectImageCandidate {candidate_id} not found")
        return row

    async def _converge_orphaned(
        self, db: AsyncSession, novel_id: str, row: WorldObjectImageCandidate
    ) -> WorldObjectImageCandidate:
        """Close a queued/generating candidate whose task died without the
        handler's own exception path running (lease loss, worker crash)."""
        if row.status not in {"queued", "generating"} or not row.task_id:
            return row
        lifecycle = (
            await list_task_lifecycle_contracts(
                db,
                task_ids=[str(row.task_id)],
                novel_id=novel_id,
                max_heartbeat_gap=TASK_MAX_HEARTBEAT_GAP,
            )
        ).get(str(row.task_id))
        if lifecycle is not None and lifecycle.status not in {"failed", "cancelled"}:
            return row
        row = await self._candidate(db, novel_id, str(row.id), lock=True)
        if row.status in {"queued", "generating"}:
            if lifecycle is not None and lifecycle.status == "cancelled":
                row.status = "cancelled"
            else:
                row.status = "failed"
                row.error = "生成任务已中断，可以重新生成"
            row.image_data = None
            await db.flush()
        return row

    async def _view(
        self,
        db: AsyncSession,
        row: WorldObjectImageCandidate,
        *,
        reused: bool = False,
    ) -> WorldObjectImageCandidateView:
        awaiting_approval = (
            bool(row.task_id)
            and row.status in {"queued", "generating"}
            and await task_awaiting_local_approval(db, str(row.task_id))
        )
        return WorldObjectImageCandidateView(
            id=str(row.id),
            entity_id=str(row.entity_id),
            status=row.status,
            prompt=row.prompt,
            error=row.error,
            width=row.width,
            height=row.height,
            created_at=row.created_at,
            updated_at=row.updated_at,
            task_id=str(row.task_id) if row.task_id else None,
            awaiting_approval=awaiting_approval,
            reused=reused,
        )

    # -- read views ---------------------------------------------------------

    async def generation_info(
        self, db: AsyncSession, *, novel_id: str, entity_id: str, owner_id: str
    ) -> WorldObjectImageGenerationInfo:
        entity = await self._entity(db, novel_id, entity_id)
        executor = await selected_executor(db, novel_id, owner_id)
        available = executor.kind != "gateway"
        reason = None if available else "请先在项目设置中配对本机 CLI，并选择用于生成图片"
        rows = list(
            (
                await db.execute(
                    select(WorldObjectImageCandidate)
                    .where(
                        WorldObjectImageCandidate.novel_id
                        == parse_uuid(novel_id, "novel_id"),
                        WorldObjectImageCandidate.entity_id
                        == parse_uuid(entity_id, "entity_id"),
                    )
                    .order_by(
                        WorldObjectImageCandidate.created_at.desc(),
                        WorldObjectImageCandidate.id.desc(),
                    )
                    .limit(_LISTED_CANDIDATES)
                )
            )
            .scalars()
            .all()
        )
        converged = [await self._converge_orphaned(db, novel_id, row) for row in rows]
        views = [await self._view(db, row) for row in converged]
        return WorldObjectImageGenerationInfo(
            available=available,
            reason=reason,
            executor_kind=executor.kind if available else None,
            default_prompt=default_image_prompt(entity),
            candidates=views,
        )

    async def get_candidate(
        self, db: AsyncSession, *, novel_id: str, candidate_id: str
    ) -> WorldObjectImageCandidateView:
        row = await self._candidate(db, novel_id, candidate_id)
        row = await self._converge_orphaned(db, novel_id, row)
        return await self._view(db, row)

    async def get_candidate_image(
        self, db: AsyncSession, *, novel_id: str, candidate_id: str
    ) -> bytes:
        row = await self._candidate(db, novel_id, candidate_id)
        if row.status != "review_ready" or not row.image_data:
            raise NotFoundError(
                f"WorldObjectImageCandidate {candidate_id} image not found"
            )
        return row.image_data

    # -- writes ---------------------------------------------------------

    async def create_candidate(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        entity_id: str,
        owner_id: str,
        data: WorldObjectImageCandidateCreate,
    ) -> WorldObjectImageCandidateView:
        entity = await self._entity(db, novel_id, entity_id)
        executor = await selected_executor(db, novel_id, owner_id)
        if executor.kind == "gateway":
            raise ConflictError(
                "请先在项目设置中配对本机 CLI，并选择用于生成图片",
                code="local_image_executor_required",
            )
        active = (
            await db.execute(
                select(WorldObjectImageCandidate.id).where(
                    WorldObjectImageCandidate.novel_id
                    == parse_uuid(novel_id, "novel_id"),
                    WorldObjectImageCandidate.entity_id == entity.id,
                    WorldObjectImageCandidate.status.in_(["queued", "generating"]),
                )
            )
        ).scalar_one_or_none()
        if active is not None:
            raise ConflictError(
                "该对象已有正在生成的图片，请先完成或放弃当前候选",
                code="image_generation_in_progress",
            )
        # B9 幂等复用：同参数（对象状态 + prompt + 执行器）命中时直接复制
        # 已有本机生成结果，跳过 CLI 调用（省时间，不省钱）。
        request_hash = _world_object_request_hash(
            novel_id=str(entity.novel_id),
            owner_id=owner_id,
            entity=entity,
            prompt=data.prompt,
            executor=executor,
        )
        if data.force_refresh:
            await invalidate_reusable_asset(
                db, novel_id=str(entity.novel_id), request_hash=request_hash
            )
        else:
            reused = await _reuse_world_object_candidate(
                db,
                novel_id=str(entity.novel_id),
                owner_id=owner_id,
                request_hash=request_hash,
            )
            if reused is not None:
                candidate = reused
                return await self._view(db, candidate, reused=True)
        candidate = WorldObjectImageCandidate(
            novel_id=entity.novel_id,
            entity_id=entity.id,
            owner_id=parse_uuid(owner_id, "owner_id"),
            status="queued",
            prompt=data.prompt,
            executor_json={"kind": executor.kind, "device_id": executor.device_id},
        )
        db.add(candidate)
        await db.flush()
        meta = {
            "candidate_id": str(candidate.id),
            "novel_id": str(candidate.novel_id),
            **local_image_task_meta(executor),
        }
        task_id = enqueue_task(
            db,
            TASK_TYPE,
            meta=meta,
            novel_id=novel_id,
        )
        candidate.task_id = parse_uuid(task_id, "task_id")
        await db.flush()
        return await self._view(db, candidate)

    async def adopt_candidate(
        self, db: AsyncSession, *, novel_id: str, candidate_id: str
    ) -> WorldObjectImageCandidateAdoptResponse:
        candidate = await self._candidate(db, novel_id, candidate_id, lock=True)
        if candidate.status != "review_ready" or not candidate.image_data:
            raise ConflictError("该候选图片尚不能采用", code="candidate_not_ready")
        response = await self._image_service.upload(
            db,
            novel_id=novel_id,
            entity_id=str(candidate.entity_id),
            payload=candidate.image_data,
        )
        candidate.status = "adopted"
        candidate.adopted_image_version = response.image_version
        candidate.image_data = None
        await db.flush()
        return WorldObjectImageCandidateAdoptResponse(
            candidate=await self._view(db, candidate),
            image_version=str(response.image_version),
        )

    async def discard_candidate(
        self, db: AsyncSession, *, novel_id: str, candidate_id: str
    ) -> WorldObjectImageCandidateView:
        candidate = await self._candidate(db, novel_id, candidate_id, lock=True)
        if candidate.status in {"review_ready", "failed"}:
            candidate.status = "discarded"
            candidate.image_data = None
            await db.flush()
            return await self._view(db, candidate)
        if candidate.status in {"queued", "generating"}:
            if candidate.task_id:
                await cancel_exact_task(
                    db,
                    task_id=str(candidate.task_id),
                    novel_id=novel_id,
                    task_types={TASK_TYPE},
                    transition_reason="world_object_image_candidate_discard",
                )
            candidate.status = "cancelled"
            candidate.image_data = None
            await db.flush()
            return await self._view(db, candidate)
        raise ConflictError("该候选无法放弃", code="candidate_not_discardable")

    # -- retention --------------------------------------------------------

    async def _retain_newest_review_ready(
        self, db: AsyncSession, *, novel_id: str, entity_id: uuid.UUID
    ) -> None:
        stale = list(
            (
                await db.execute(
                    select(WorldObjectImageCandidate)
                    .where(
                        WorldObjectImageCandidate.novel_id
                        == parse_uuid(novel_id, "novel_id"),
                        WorldObjectImageCandidate.entity_id == entity_id,
                        WorldObjectImageCandidate.status == "review_ready",
                    )
                    .order_by(
                        WorldObjectImageCandidate.created_at.desc(),
                        WorldObjectImageCandidate.id.desc(),
                    )
                    .offset(_RETAINED_REVIEW_READY)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for row in stale:
            row.status = "discarded"
            row.image_data = None
        if stale:
            await db.flush()


async def _lock_candidate_for_task(
    db: AsyncSession, *, candidate_id: str, task
) -> WorldObjectImageCandidate | None:
    row = (
        await db.execute(
            select(WorldObjectImageCandidate)
            .where(
                WorldObjectImageCandidate.id == parse_uuid(candidate_id, "candidate_id")
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None or row.task_id != task.id or row.status != "queued":
        return None
    return row


def _world_object_request_hash(
    *,
    novel_id: str,
    owner_id: str,
    entity: CoreEntity,
    prompt: str,
    executor: AgentExecutor,
) -> str:
    """B9 幂等键：对象设定状态变化后不复用旧图。"""
    import hashlib as _hashlib
    import json as _json

    state_snapshot = _hashlib.sha256(
        _json.dumps(
            entity.content_json or {},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return compute_request_hash(
        novel_id=novel_id,
        owner_id=owner_id,
        state_snapshot_hash=state_snapshot,
        prompt=prompt,
        model=executor.kind,
        params={
            # device_id 不进哈希：设备只是执行载体，换设备不应使已生成
            # 资产失效；「模型」维度由 executor kind 表达。
            "width": _GENERATION_WIDTH,
            "height": _GENERATION_HEIGHT,
        },
    )


async def _reuse_world_object_candidate(
    db: AsyncSession,
    *,
    novel_id: str,
    owner_id: str,
    request_hash: str,
) -> WorldObjectImageCandidate | None:
    """命中复用登记且来源候选资产仍完整时，复制出一个 review_ready 候选。"""

    async def _validate(row) -> tuple | None:
        if row.source_type != "world_object" or not row.created_from_id:
            return None
        source = await db.get(WorldObjectImageCandidate, row.created_from_id)
        if (
            source is None
            or str(source.novel_id) != str(row.novel_id)
            or not source.image_data
        ):
            return None
        import hashlib as _hashlib

        digest = _hashlib.sha256(source.image_data).hexdigest()
        if row.asset_sha256 and digest != row.asset_sha256:
            return None
        return source.image_data, digest, source.width, source.height

    reused = await find_reusable_asset(
        db,
        novel_id=novel_id,
        owner_id=owner_id,
        request_hash=request_hash,
        validate_asset=_validate,
    )
    if reused is None or not reused.get("created_from_id"):
        return None
    source = await db.get(
        WorldObjectImageCandidate, uuid.UUID(str(reused["created_from_id"]))
    )
    if source is None:
        return None
    candidate = WorldObjectImageCandidate(
        novel_id=source.novel_id,
        entity_id=source.entity_id,
        owner_id=source.owner_id,
        status="review_ready",
        prompt=source.prompt,
        executor_json=dict(source.executor_json or {}),
        image_data=source.image_data,
        width=source.width,
        height=source.height,
        sha256=reused["asset_sha256"],
    )
    db.add(candidate)
    await db.flush()
    return candidate


async def handle_world_object_image_generate(db: AsyncSession, task) -> dict:
    """Generate one world-object image candidate through the local CLI.

    Recovery policy is ``never_retry``: the local-agent host-approval gate
    only ever admits a fresh, unapproved task, so a retried attempt would
    silently skip approval. Any failure here terminates the candidate.
    """
    meta = dict(task.meta or {})
    candidate_id = str(meta.get("candidate_id") or "")
    novel_id = str(meta.get("novel_id") or task.novel_id or "")
    if (
        task.task_type != TASK_TYPE
        or task.status != "running"
        or not task.lease_id
        or not candidate_id
        or not novel_id
    ):
        raise ValueError("invalid world object image generate task identity")

    candidate = await _lock_candidate_for_task(db, candidate_id=candidate_id, task=task)
    if candidate is None:
        return {"skipped": True}
    executor_json = dict(candidate.executor_json or {})
    executor = AgentExecutor(
        kind=str(executor_json.get("kind") or ""),
        device_id=executor_json.get("device_id"),
    )
    candidate.status = "generating"
    # Keep identities as plain values: a rollback below expires ORM attributes.
    candidate_pk, task_pk = candidate.id, task.id
    await db.commit()

    service = WorldObjectImageGenerationService()
    try:
        reviewed = await run_local_image(
            db,
            task=task,
            novel_id=novel_id,
            owner_id=str(candidate.owner_id),
            executor=executor,
            prompt=candidate.prompt,
            width=_GENERATION_WIDTH,
            height=_GENERATION_HEIGHT,
        )
        reviewed = limit_edge(reviewed, _MAX_IMAGE_EDGE)
        if len(reviewed.data) > _MAX_UPLOAD_BYTES:
            reviewed = limit_edge(reviewed, _FALLBACK_IMAGE_EDGE)
        if len(reviewed.data) > _MAX_UPLOAD_BYTES:
            raise ConflictError("生成图片过大，无法保存", code="local_image_failed")
    except BaseException as exc:
        await db.rollback()
        locked = await db.execute(
            select(WorldObjectImageCandidate)
            .where(WorldObjectImageCandidate.id == candidate_pk)
            .with_for_update()
        )
        row = locked.scalar_one_or_none()
        owned = row is not None and row.task_id == task_pk
        if owned and row.status in {"queued", "generating"}:
            row.status = "failed"
            row.error = redact_diagnostic(exc, limit=300)
            row.image_data = None
            await db.commit()
        raise

    locked = (
        await db.execute(
            select(WorldObjectImageCandidate)
            .where(
                WorldObjectImageCandidate.id == candidate_pk,
                WorldObjectImageCandidate.task_id == task_pk,
                WorldObjectImageCandidate.status == "generating",
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if locked is None:
        # Discarded/cancelled concurrently while the local CLI was working;
        # the generated bytes have no candidate to attach to any more.
        await db.commit()
        return {"candidate_id": str(candidate_pk), "status": "skipped"}
    locked.image_data = reviewed.data
    locked.width = reviewed.width
    locked.height = reviewed.height
    locked.sha256 = reviewed.sha256
    locked.status = "review_ready"
    locked.error = None
    # B9：登记可复用资产（幂等键含对象设定状态快照）。
    context_owner = str(locked.owner_id)
    await record_reusable_asset(
        db,
        novel_id=str(locked.novel_id),
        owner_id=context_owner,
        request_hash=_world_object_request_hash(
            novel_id=str(locked.novel_id),
            owner_id=context_owner,
            entity=await WorldObjectImageGenerationService._entity(
                db, str(locked.novel_id), str(locked.entity_id)
            ),
            prompt=locked.prompt,
            executor=executor,
        ),
        source_type="world_object",
        object_key=f"world-object-candidate:{locked.id}",
        provider=str((locked.executor_json or {}).get("kind") or "local-cli"),
        model=str((locked.executor_json or {}).get("kind") or "local-cli"),
        asset_sha256=reviewed.sha256,
        byte_size=len(reviewed.data),
        width=reviewed.width,
        height=reviewed.height,
        created_from_id=locked.id,
    )
    await db.flush()
    await service._retain_newest_review_ready(
        db, novel_id=novel_id, entity_id=locked.entity_id
    )
    await db.commit()
    return {"candidate_id": str(locked.id), "status": "review_ready"}
