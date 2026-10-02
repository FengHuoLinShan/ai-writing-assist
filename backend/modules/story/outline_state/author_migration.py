"""表格迁移 story 落库（ADR-0030，计划 §3.4/§4 L3）— outline_state 窄 seam。

映射：arc → OutlineArc、thread → PlotThread、foreshadowing → ForeshadowingPlan、
chapter_plan → planned/reference/link Scene；总纲经 create_revision 写入。
同名结构只补空字段，其他差异与卷章节范围重叠为 conflict；apply 前 重算指纹，
不符抛 ConflictError(code="migration_preview_stale")；所有路径只 flush 不 commit。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError
from infrastructure.stable_hash import stable_hash
from modules.story.outline_state.contracts import (
    AuthorMigrationStoryItem,
    AuthorMigrationStoryRequest,
    StoryMigrationItemPlan,
    StoryMigrationPlan,
    StoryMigrationReceipt,
)
from modules.story.outline_state.foreshadowing_repository import (
    ForeshadowingPlanRepository,
)
from modules.story.outline_state.models import (
    ForeshadowingPlan,
    OutlineArc,
    PlotThread,
    Scene,
    StoryOutlineHead,
    StoryOutlineRevision,
)
from modules.story.outline_state.repositories import (
    OutlineArcRepository,
    PlotThreadRepository,
    SceneRepository,
    _notify_structure_change,
)
from modules.story.outline_state.schemas import (
    ForeshadowingPlanCreate,
    OutlineArcCreate,
    PlotThreadCreate,
    SceneCreate,
)
from modules.story.outline_state.story_outline_schemas import (
    StoryOutlineCreativeCore,
    StoryOutlineProvenance,
    StoryOutlineRevisionApply,
    StoryOutlineRevisionCreate,
)
from modules.story.outline_state.story_outline_service import (
    StoryOutlineNotFoundError,
    StoryOutlineService,
)
from modules.world.contracts import (
    FieldConflict,
    MigrationAppliedChange,
    MigrationRollbackResult,
)
from shared.utils import parse_uuid

# ADR-0030 的来源标记字面量；与 imports.spreadsheet_migration.constants 保持一致，
# 但 story 侧不依赖 imports 实现模块。
MIGRATION_SOURCE = "spreadsheet_migration"

_ACTIVE_SCENE_STATUSES: tuple[str, ...] = ("candidate", "draft", "canonical")
_VALID_THREAD_TYPES = frozenset({"main", "sub", "background"})
_THREAD_TYPE_ALIASES = {
    "主线": "main",
    "支线": "sub",
    "副线": "sub",
    "辅线": "sub",
    "背景": "background",
    "暗线": "background",
    "世界观": "background",
    "subplot": "sub",
    "secondary": "sub",
    "relationship": "sub",
    "hidden": "background",
    "mystery": "background",
    "world": "background",
}
_OUTLINE_CORE_REQUIRED = ("premise", "tone_and_reader_promise", "story_engine")
# creative_core 不完整时用合成 item 暴露 conflict；回滚的 outline 判定也复用该键。
# L4 请求侧 item_key 由 sheet/行号生成，不会与该键冲突。
OUTLINE_ITEM_KEY = "__outline__"
_EXCERPT_LIMIT = 200

_KIND_CHANGE_TYPES = {
    "arc": "outline_arc",
    "thread": "plot_thread",
    "foreshadowing": "foreshadowing_plan",
    "scene": "outline_scene",
}


@dataclass
class _PlanContext:
    """plan/apply 共享的只读项目状态。"""

    novel_id: uuid.UUID
    threads: list[PlotThread] = field(default_factory=list)
    arcs: list[OutlineArc] = field(default_factory=list)
    foreshadowing_plans: list[ForeshadowingPlan] = field(default_factory=list)
    active_scenes: list[Scene] = field(default_factory=list)
    scene_chapters: dict[uuid.UUID, set[int]] = field(default_factory=dict)
    written_chapters: set[int] = field(default_factory=set)
    outline_head: StoryOutlineHead | None = None
    outline_revision: StoryOutlineRevision | None = None

    @property
    def threads_by_name(self) -> dict[str, PlotThread]:
        return {thread.name: thread for thread in self.threads}

    @property
    def arcs_by_title(self) -> dict[str, OutlineArc]:
        return {arc.title: arc for arc in self.arcs}

    @property
    def plans_by_name(self) -> dict[str, ForeshadowingPlan]:
        return {plan.name: plan for plan in self.foreshadowing_plans}


# ============================================================
# facade
# ============================================================


async def plan_author_migration_structures(
    db: AsyncSession,
    novel_id: str,
    request: AuthorMigrationStoryRequest,
    *,
    entity_refs: dict[str, str | None],
) -> StoryMigrationPlan:
    """只读计算故事结构迁移计划；entity_refs 值为 None 表示本次新建、尚无 id。

    计划输出不携带新实体 id（指纹也不含），entity_refs 仅供签名对齐 world 侧；
    实体 id 在 apply 时由 world 回执的 entity_ids 提供。
    """
    plan, _ctx = await _compute_plan(db, novel_id, request)
    return plan


async def apply_author_migration_structures(
    db: AsyncSession,
    novel_id: str,
    request: AuthorMigrationStoryRequest,
    *,
    entity_ids: dict[str, str],
    expected_fingerprint: str,
    authorized_by: str,
) -> StoryMigrationReceipt:
    """按已确认的计划写入；只 flush，不 commit。"""
    plan, ctx = await _compute_plan(db, novel_id, request)
    if plan.fingerprint != expected_fingerprint:
        raise ConflictError(
            "表格迁移预览已过期，请重新预览后再确认",
            code="migration_preview_stale",
        )
    nid = parse_uuid(novel_id, "novel_id")
    adopted_at = datetime.now(UTC).isoformat()
    plan_by_key = {item.item_key: item for item in plan.items}
    applied: list[MigrationAppliedChange] = []
    scene_repo = SceneRepository()

    needs_scene_write = any(
        plan_by_key.get(item.item_key) is not None
        and plan_by_key[item.item_key].action in {"planned_scene", "link_scene"}
        for item in request.items
    )
    next_scene_index = 0
    if needs_scene_write:
        await scene_repo.lock_scene_order(db, nid)
        maximum = await db.scalar(
            select(func.max(Scene.scene_index)).where(Scene.novel_id == nid)
        )
        next_scene_index = int(maximum) + 1 if maximum is not None else 0

    for item in request.items:
        item_plan = plan_by_key.get(item.item_key)
        if item_plan is None or item_plan.action not in {
            "create",
            "fill_empty",
            "planned_scene",
            "link_scene",
        }:
            continue
        meta = _migration_meta(request, item, authorized_by, adopted_at)
        related_ids = _resolve_entity_refs(item.related_entity_keys, entity_ids)
        if item.kind == "arc":
            await _apply_arc(
                db,
                nid,
                item,
                item_plan,
                meta,
                related_ids,
                applied,
            )
        elif item.kind == "thread":
            await _apply_thread(
                db,
                nid,
                item,
                item_plan,
                meta,
                related_ids,
                applied,
            )
        elif item.kind == "foreshadowing":
            await _apply_foreshadowing(
                db,
                nid,
                item,
                item_plan,
                meta,
                related_ids,
                applied,
            )
        elif item.kind == "chapter_plan":
            next_scene_index = await _apply_chapter_plan(
                db,
                nid,
                ctx,
                item,
                item_plan,
                meta,
                entity_ids,
                applied,
                next_scene_index=next_scene_index,
            )

    outline_change = None
    if plan.outline_action in {"create", "replace"}:
        outline_change = await _apply_outline(db, novel_id, request, ctx)

    return StoryMigrationReceipt(
        applied_changes=applied,
        outline_change=outline_change,
    )


async def rollback_author_migration_structures(
    db: AsyncSession,
    novel_id: str,
    receipt: StoryMigrationReceipt,
    *,
    dry_run: bool,
) -> MigrationRollbackResult:
    """按回执逆序回滚；已改动项保留。"""
    nid = parse_uuid(novel_id, "novel_id")
    reverted: list[str] = []
    kept: list[dict] = []
    now = datetime.now(UTC).isoformat()
    for change in reversed(receipt.applied_changes):
        model = _model_for_kind(change.kind)
        if model is None:
            kept.append({"item_key": change.item_key, "reason_code": "unknown_kind"})
            continue
        try:
            target_id = uuid.UUID(str(change.target_id))
        except (TypeError, ValueError):
            kept.append({"item_key": change.item_key, "reason_code": "invalid_target"})
            continue
        row = await db.scalar(
            select(model).where(model.id == target_id, model.novel_id == nid)
        )
        if row is None:
            kept.append({"item_key": change.item_key, "reason_code": "missing"})
            continue
        if stable_hash(_asset_state(row)) != change.after_hash:
            kept.append(
                {"item_key": change.item_key, "reason_code": "modified_after_migration"}
            )
            continue
        if change.operation == "create":
            if not _owns_migration_marker(row):
                kept.append(
                    {"item_key": change.item_key, "reason_code": "not_migration_owned"}
                )
                continue
            if not dry_run:
                row.status = "deprecated"
                _merge_row_meta(
                    row,
                    {"rolled_back_at": now, "rollback_source": MIGRATION_SOURCE},
                )
                db.add(row)
                await db.flush()
                await _notify_structure_change(
                    db,
                    row,
                    _KIND_CHANGE_TYPES[change.kind],
                    invalidate_context=True,
                )
            reverted.append(change.item_key)
        elif change.operation == "fill_empty":
            if not dry_run:
                for column, value in change.before.items():
                    if hasattr(row, column):
                        setattr(row, column, value)
                _merge_row_meta(row, {"spreadsheet_migration_rolled_back_at": now})
                db.add(row)
                await db.flush()
                await _notify_structure_change(
                    db,
                    row,
                    _KIND_CHANGE_TYPES[change.kind],
                    invalidate_context=True,
                )
            reverted.append(change.item_key)
        else:
            kept.append(
                {"item_key": change.item_key, "reason_code": "unsupported_operation"}
            )
    if receipt.outline_change:
        reverted_outline, reason = await _rollback_outline(
            db,
            novel_id,
            receipt.outline_change,
            dry_run=dry_run,
        )
        if reverted_outline:
            reverted.append(OUTLINE_ITEM_KEY)
        else:
            kept.append(
                {"item_key": OUTLINE_ITEM_KEY, "reason_code": reason or "outline_kept"}
            )
    return MigrationRollbackResult(reverted=reverted, kept=kept)


# ============================================================
# 计划计算
# ============================================================


async def _load_context(db: AsyncSession, novel_id: str) -> _PlanContext:
    from modules.writing.facade import list_chapter_indices

    nid = parse_uuid(novel_id, "novel_id")
    ctx = _PlanContext(novel_id=nid)
    ctx.threads = list(
        (
            await db.scalars(
                select(PlotThread).where(
                    PlotThread.novel_id == nid,
                    PlotThread.status != "deprecated",
                )
            )
        ).all()
    )
    ctx.arcs = list(
        (
            await db.scalars(
                select(OutlineArc).where(
                    OutlineArc.novel_id == nid,
                    OutlineArc.status != "deprecated",
                )
            )
        ).all()
    )
    ctx.foreshadowing_plans = list(
        (
            await db.scalars(
                select(ForeshadowingPlan).where(
                    ForeshadowingPlan.novel_id == nid,
                    ForeshadowingPlan.status != "deprecated",
                )
            )
        ).all()
    )
    scene_repo = SceneRepository()
    ctx.active_scenes = list(
        (
            await db.scalars(
                select(Scene)
                .where(
                    Scene.novel_id == nid,
                    Scene.status.in_(_ACTIVE_SCENE_STATUSES),
                )
                .order_by(Scene.scene_index, Scene.id)
            )
        ).all()
    )
    for scene in ctx.active_scenes:
        chapters = set(scene_repo.chapter_indices_for_scene(scene))
        chapters.update(_planned_range_chapters(scene))
        ctx.scene_chapters[scene.id] = chapters
    ctx.written_chapters = set(await list_chapter_indices(db, novel_id))
    outline_service = StoryOutlineService()
    ctx.outline_head = await outline_service.repository.get_head(db, nid)
    if ctx.outline_head is not None and ctx.outline_head.current_revision_id is not None:
        ctx.outline_revision = await outline_service.repository.get_revision(
            db,
            nid,
            ctx.outline_head.current_revision_id,
        )
    return ctx


async def _compute_plan(
    db: AsyncSession,
    novel_id: str,
    request: AuthorMigrationStoryRequest,
) -> tuple[StoryMigrationPlan, _PlanContext]:
    ctx = await _load_context(db, novel_id)
    items: list[StoryMigrationItemPlan] = []
    stamps: dict[str, str] = {}
    planned_names: set[tuple[str, str]] = set()
    planned_arc_ranges: list[tuple[int, int]] = []

    for item in request.items:
        if item.decision == "skip":
            items.append(StoryMigrationItemPlan(item_key=item.item_key, action="skip"))
        elif item.kind == "arc":
            items.append(
                _plan_arc_item(item, ctx, planned_names, planned_arc_ranges, stamps)
            )
        elif item.kind == "thread":
            items.append(_plan_thread_item(item, ctx, planned_names, stamps))
        elif item.kind == "foreshadowing":
            items.append(_plan_foreshadowing_item(item, ctx, planned_names, stamps))
        else:
            items.append(_plan_chapter_item(item, ctx, request, stamps))

    outline_action, outline_conflict = _outline_decision(request, ctx)
    if outline_conflict is not None:
        items.append(outline_conflict)
    outline_stamp = None
    if ctx.outline_revision is not None:
        outline_stamp = f"{ctx.outline_revision.id}|{_stamp(ctx.outline_revision)}"
    fingerprint = _fingerprint(request, items, stamps, outline_action, outline_stamp)
    return (
        StoryMigrationPlan(
            items=items,
            outline_action=outline_action,
            fingerprint=fingerprint,
        ),
        ctx,
    )


def _plan_arc_item(
    item: AuthorMigrationStoryItem,
    ctx: _PlanContext,
    planned_names: set[tuple[str, str]],
    planned_arc_ranges: list[tuple[int, int]],
    stamps: dict[str, str],
) -> StoryMigrationItemPlan:
    key = ("arc", item.title)
    if key in planned_names:
        return _conflict_item(item.item_key, "duplicate_in_migration")
    start, end = _item_range(item)
    if start is not None:
        overlapping = _find_overlapping_arc(item.title, start, end, ctx.arcs)
        if overlapping is not None or _overlaps_any(start, end, planned_arc_ranges):
            return _conflict_item(
                item.item_key,
                "arc_range_overlap",
                target_label=(
                    overlapping.title if overlapping is not None else item.title
                ),
            )
    match = ctx.arcs_by_title.get(item.title)
    if match is not None:
        return _match_item(item, match, _incoming_values(item), stamps)
    planned_names.add(key)
    if start is not None:
        planned_arc_ranges.append((start, end))
    return StoryMigrationItemPlan(
        item_key=item.item_key,
        action="create",
        target_label=item.title,
    )


def _plan_thread_item(
    item: AuthorMigrationStoryItem,
    ctx: _PlanContext,
    planned_names: set[tuple[str, str]],
    stamps: dict[str, str],
) -> StoryMigrationItemPlan:
    key = ("thread", item.title)
    if key in planned_names:
        return _conflict_item(item.item_key, "duplicate_in_migration")
    match = ctx.threads_by_name.get(item.title)
    if match is not None:
        return _match_item(item, match, _incoming_values(item), stamps)
    planned_names.add(key)
    return StoryMigrationItemPlan(
        item_key=item.item_key,
        action="create",
        target_label=item.title,
    )


def _plan_foreshadowing_item(
    item: AuthorMigrationStoryItem,
    ctx: _PlanContext,
    planned_names: set[tuple[str, str]],
    stamps: dict[str, str],
) -> StoryMigrationItemPlan:
    key = ("foreshadowing", item.title)
    if key in planned_names:
        return _conflict_item(item.item_key, "duplicate_in_migration")
    match = ctx.plans_by_name.get(item.title)
    if match is not None:
        return _match_item(item, match, _incoming_values(item), stamps)
    planned_names.add(key)
    return StoryMigrationItemPlan(
        item_key=item.item_key,
        action="create",
        target_label=item.title,
    )


def _plan_chapter_item(
    item: AuthorMigrationStoryItem,
    ctx: _PlanContext,
    request: AuthorMigrationStoryRequest,
    stamps: dict[str, str],
) -> StoryMigrationItemPlan:
    start, end = _item_range(item)
    if start is None:
        return _conflict_item(item.item_key, "chapter_range_missing")
    covered_scene = next(
        (
            scene
            for scene in ctx.active_scenes
            if any(start <= chapter <= end for chapter in ctx.scene_chapters[scene.id])
        ),
        None,
    )
    if covered_scene is not None:
        stamps[item.item_key] = _stamp(covered_scene)
        return StoryMigrationItemPlan(
            item_key=item.item_key,
            action="existing_ref",
            target_id=str(covered_scene.id),
            target_label=_scene_label(covered_scene),
        )
    written = [
        chapter for chapter in range(start, end + 1) if chapter in ctx.written_chapters
    ]
    if not written:
        return StoryMigrationItemPlan(item_key=item.item_key, action="planned_scene")
    if request.written_chapter_policy == "link_scene":
        return StoryMigrationItemPlan(item_key=item.item_key, action="link_scene")
    return StoryMigrationItemPlan(item_key=item.item_key, action="reference_only")


def _outline_decision(
    request: AuthorMigrationStoryRequest,
    ctx: _PlanContext,
) -> tuple[str | None, StoryMigrationItemPlan | None]:
    outline = request.outline
    if outline is None:
        return None, None
    if outline.policy == "skip":
        return "skip", None
    has_current = ctx.outline_revision is not None
    if outline.policy == "create_if_missing" and has_current:
        return "skip", None
    missing = [
        name
        for name in _OUTLINE_CORE_REQUIRED
        if not str(outline.creative_core.get(name) or "").strip()
    ]
    if missing:
        return "skip", _conflict_item(
            OUTLINE_ITEM_KEY,
            "outline_core_missing",
            conflicts=[
                FieldConflict(
                    field="creative_core",
                    current_excerpt="",
                    incoming_excerpt=f"缺失: {', '.join(missing)}",
                )
            ],
        )
    if not str(outline.outline_markdown or "").strip():
        return "skip", _conflict_item(
            OUTLINE_ITEM_KEY,
            "outline_markdown_missing",
        )
    return ("replace" if has_current else "create"), None


def _fingerprint(
    request: AuthorMigrationStoryRequest,
    items: list[StoryMigrationItemPlan],
    stamps: dict[str, str],
    outline_action: str | None,
    outline_stamp: str | None,
) -> str:
    payload = {
        "version": 1,
        "request": request.model_dump(mode="json"),
        "items": [
            {
                "item_key": item.item_key,
                "action": item.action,
                "target_id": item.target_id,
                "target_stamp": stamps.get(item.item_key),
                "fills": list(item.fills),
                "conflicts": [
                    conflict.model_dump(mode="json") for conflict in item.conflicts
                ],
                "reason_code": item.reason_code,
            }
            for item in items
        ],
        "outline_action": outline_action,
        "outline_stamp": outline_stamp,
    }
    return stable_hash(payload)


# ============================================================
# apply 写入
# ============================================================


async def _apply_arc(
    db: AsyncSession,
    nid: uuid.UUID,
    item: AuthorMigrationStoryItem,
    item_plan: StoryMigrationItemPlan,
    meta: dict[str, Any],
    related_ids: list[str],
    applied: list[MigrationAppliedChange],
) -> None:
    values = _incoming_values(item)
    if item_plan.action == "create":
        row = await OutlineArcRepository().create(
            db,
            nid,
            OutlineArcCreate(
                title=item.title,
                start_chapter=values.get("start_chapter"),
                end_chapter=values.get("end_chapter"),
                arc_goal=values.get("arc_goal"),
                core_conflict=values.get("core_conflict"),
                climax=values.get("climax"),
                result=values.get("result"),
                next_hook=values.get("next_hook"),
                related_entity_ids=related_ids,
                provenance_meta=meta,
                status="canonical",
            ),
        )
        applied.append(_change(item.item_key, "arc", row, "create", {}))
        return
    await _apply_fill(db, nid, item, item_plan, values, meta, applied)


async def _apply_thread(
    db: AsyncSession,
    nid: uuid.UUID,
    item: AuthorMigrationStoryItem,
    item_plan: StoryMigrationItemPlan,
    meta: dict[str, Any],
    related_ids: list[str],
    applied: list[MigrationAppliedChange],
) -> None:
    values = _incoming_values(item)
    if item_plan.action == "create":
        row = await PlotThreadRepository().create(
            db,
            nid,
            PlotThreadCreate(
                name=item.title,
                thread_type=values.get("thread_type") or "sub",
                summary=values.get("summary"),
                visible_goal=values.get("visible_goal"),
                hidden_truth=values.get("hidden_truth"),
                start_chapter=values.get("start_chapter"),
                planned_payoff_chapter=values.get("planned_payoff_chapter"),
                related_entity_ids=related_ids,
                provenance_meta=meta,
                status="canonical",
            ),
        )
        applied.append(_change(item.item_key, "thread", row, "create", {}))
        return
    await _apply_fill(db, nid, item, item_plan, values, meta, applied)


async def _apply_foreshadowing(
    db: AsyncSession,
    nid: uuid.UUID,
    item: AuthorMigrationStoryItem,
    item_plan: StoryMigrationItemPlan,
    meta: dict[str, Any],
    related_ids: list[str],
    applied: list[MigrationAppliedChange],
) -> None:
    values = _incoming_values(item)
    if item_plan.action == "create":
        payload = ForeshadowingPlanCreate(
            name=item.title,
            surface_meaning=values.get("surface_meaning"),
            hidden_meaning=values.get("hidden_meaning"),
            planned_seed_chapter=values.get("planned_seed_chapter"),
            planned_reinforce_chapters=values.get("planned_reinforce_chapters") or [],
            planned_payoff_chapter=values.get("planned_payoff_chapter"),
            related_entity_ids=related_ids,
            provenance_meta=meta,
            status="canonical",
        ).model_dump()
        row = await ForeshadowingPlanRepository().create(db, nid, payload)
        applied.append(_change(item.item_key, "foreshadowing", row, "create", {}))
        return
    await _apply_fill(db, nid, item, item_plan, values, meta, applied)


async def _apply_fill(
    db: AsyncSession,
    nid: uuid.UUID,
    item: AuthorMigrationStoryItem,
    item_plan: StoryMigrationItemPlan,
    values: dict[str, Any],
    meta: dict[str, Any],
    applied: list[MigrationAppliedChange],
) -> None:
    if item_plan.target_id is None or not item_plan.fills:
        return
    model = _model_for_kind(item.kind)
    if model is None:
        return
    row = await db.scalar(
        select(model).where(
            model.id == uuid.UUID(item_plan.target_id),
            model.novel_id == nid,
        )
    )
    if row is None:
        return
    before: dict[str, Any] = {}
    for column in item_plan.fills:
        before[column] = getattr(row, column)
        setattr(row, column, values[column])
    _merge_row_meta(
        row,
        {
            "spreadsheet_migration_fill": {
                "migration_id": meta["migration_id"],
                "source_refs": list(meta.get("source_refs") or []),
                "authorized_by": meta["authorized_by"],
                "adopted_at": meta["adopted_at"],
                "filled_fields": list(item_plan.fills),
            }
        },
    )
    db.add(row)
    await db.flush()
    await _notify_structure_change(
        db,
        row,
        _KIND_CHANGE_TYPES[item.kind],
        invalidate_context=True,
    )
    applied.append(_change(item.item_key, item.kind, row, "fill_empty", before))


async def _apply_chapter_plan(
    db: AsyncSession,
    nid: uuid.UUID,
    ctx: _PlanContext,
    item: AuthorMigrationStoryItem,
    item_plan: StoryMigrationItemPlan,
    meta: dict[str, Any],
    entity_ids: dict[str, str],
    applied: list[MigrationAppliedChange],
    *,
    next_scene_index: int,
) -> int:
    start, end = _item_range(item)
    if start is None:
        return next_scene_index
    fields = item.fields
    if item_plan.action == "link_scene":
        chapter_ids = [
            str(chapter)
            for chapter in range(start, end + 1)
            if chapter in ctx.written_chapters
        ]
    else:
        chapter_ids = []
    structure_meta = {
        **meta,
        "planning_state": "materialized" if chapter_ids else "planned",
        "planned_chapter_range": {"start": start, "end": end},
        "related_entity_ids": _resolve_entity_refs(item.related_entity_keys, entity_ids),
    }
    scene = await SceneRepository().create(
        db,
        nid,
        SceneCreate(
            scene_index=next_scene_index,
            title=item.title,
            goal=fields.get("goal"),
            core_conflict=fields.get("core_conflict"),
            emotional_beat=fields.get("emotional_beat"),
            must_happen=fields.get("must_happen"),
            must_not_happen=fields.get("must_not_happen"),
            source=MIGRATION_SOURCE,
            scene_chunks=[],
            chapter_ids=chapter_ids,
            pov_character_id=_resolve_entity_ref(item.pov_entity_key, entity_ids),
            structure_meta=structure_meta,
            status="canonical",
        ),
    )
    applied.append(_change(item.item_key, "scene", scene, "create", {}))
    return next_scene_index + 1


async def _apply_outline(
    db: AsyncSession,
    novel_id: str,
    request: AuthorMigrationStoryRequest,
    ctx: _PlanContext,
) -> dict[str, Any]:
    outline = request.outline
    if outline is None:
        raise ConflictError(
            "migration outline payload missing", code="migration_outline_missing"
        )
    core = outline.creative_core
    base_id = ctx.outline_revision.id if ctx.outline_revision is not None else None
    data = StoryOutlineRevisionCreate(
        base_revision_id=base_id,
        idempotency_key=f"spreadsheet-migration:{request.migration_id}",
        source="manual",
        provenance=StoryOutlineProvenance(
            actor="author",
            note="Adopted the author's original outline from a spreadsheet migration.",
            client_ref="spreadsheet-migration",
            source_refs=[f"migration:{request.migration_id}"],
        ),
        title=str(outline.title or "").strip() or "表格迁移导入的总纲",
        creative_core=StoryOutlineCreativeCore(
            premise=str(core["premise"]).strip(),
            tone_and_reader_promise=str(core["tone_and_reader_promise"]).strip(),
            story_engine=str(core["story_engine"]).strip(),
            ending_direction=(
                str(core["ending_direction"]).strip()
                if str(core.get("ending_direction") or "").strip()
                else None
            ),
        ),
        outline_markdown=outline.outline_markdown,
        major_storylines=[],
        macro_movements=[],
        open_decisions=[],
    )
    response = await StoryOutlineService().create_revision(db, novel_id, data)
    return {
        "revision_id": str(response.id),
        "base_revision_id": str(base_id) if base_id is not None else None,
    }


async def _rollback_outline(
    db: AsyncSession,
    novel_id: str,
    outline_change: dict[str, Any],
    *,
    dry_run: bool,
) -> tuple[bool, str | None]:
    if not isinstance(outline_change, dict):
        return False, "invalid_outline_change"
    try:
        revision_id = uuid.UUID(str(outline_change.get("revision_id")))
    except (TypeError, ValueError):
        return False, "invalid_outline_change"
    base_raw = outline_change.get("base_revision_id")
    service = StoryOutlineService()
    nid = parse_uuid(novel_id, "novel_id")
    head = await service.repository.get_head(db, nid)
    if head is None or head.current_revision_id != revision_id:
        return False, "outline_superseded"
    if base_raw:
        try:
            base_id = uuid.UUID(str(base_raw))
        except (TypeError, ValueError):
            return False, "invalid_outline_change"
        if dry_run:
            return True, None
        try:
            await service.apply_revision(
                db,
                novel_id,
                base_id,
                StoryOutlineRevisionApply(
                    base_revision_id=revision_id,
                    idempotency_key=f"spreadsheet-migration-rollback:{revision_id}",
                    confirmed=True,
                ),
            )
        except StoryOutlineNotFoundError:
            return False, "outline_base_missing"
        return True, None
    if dry_run:
        return True, None
    cleared = await service.clear_head_if_revision(db, novel_id, revision_id)
    if not cleared:
        return False, "outline_superseded"
    return True, None


# ============================================================
# 值映射与工具
# ============================================================


def _incoming_values(item: AuthorMigrationStoryItem) -> dict[str, Any]:
    """把迁移条目映射为各 model 列的待写值；仅包含实际提供的字段。"""
    fields = item.fields
    values: dict[str, Any] = {}
    if item.kind == "arc":
        for column in ("arc_goal", "core_conflict", "climax", "result", "next_hook"):
            if fields.get(column) is not None:
                values[column] = fields[column]
        if item.chapter_start is not None:
            values["start_chapter"] = item.chapter_start
        if item.chapter_end is not None:
            values["end_chapter"] = item.chapter_end
    elif item.kind == "thread":
        raw_type = str(fields.get("thread_type") or "").strip()
        if raw_type:
            values["thread_type"] = _normalize_thread_type(raw_type)
        for column in ("summary", "visible_goal", "hidden_truth"):
            if fields.get(column) is not None:
                values[column] = fields[column]
        if item.chapter_start is not None:
            values["start_chapter"] = item.chapter_start
        if item.chapter_end is not None:
            values["planned_payoff_chapter"] = item.chapter_end
    elif item.kind == "foreshadowing":
        for column in ("surface_meaning", "hidden_meaning"):
            if fields.get(column) is not None:
                values[column] = fields[column]
        seed = _to_int(fields.get("seed_chapter"))
        if seed is None:
            seed = item.chapter_start
        if seed is not None:
            values["planned_seed_chapter"] = seed
        payoff = _to_int(fields.get("payoff_chapter"))
        if payoff is None:
            payoff = item.chapter_end
        if payoff is not None:
            values["planned_payoff_chapter"] = payoff
        reinforce = _parse_int_list(fields.get("reinforce_chapters"))
        if reinforce:
            values["planned_reinforce_chapters"] = reinforce
    return values


def _normalize_thread_type(raw: str) -> str:
    lowered = raw.strip().lower()
    if lowered in _VALID_THREAD_TYPES:
        return lowered
    return (
        _THREAD_TYPE_ALIASES.get(raw.strip())
        or _THREAD_TYPE_ALIASES.get(lowered)
        or "sub"
    )


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_int_list(value: Any) -> list[int]:
    if value is None:
        return []
    text = str(value)
    numbers: list[int] = []
    current = ""
    for character in text:
        if character.isdigit():
            current += character
        elif current:
            numbers.append(int(current))
            current = ""
    if current:
        numbers.append(int(current))
    return numbers


def _item_range(item: AuthorMigrationStoryItem) -> tuple[int | None, int]:
    start = item.chapter_start
    end = item.chapter_end or item.chapter_start
    return start, end if end is not None else 0


def _find_overlapping_arc(
    title: str,
    start: int,
    end: int,
    arcs: list[OutlineArc],
) -> OutlineArc | None:
    for arc in arcs:
        if arc.title == title:
            continue
        arc_start, arc_end = arc.start_chapter, arc.end_chapter
        if arc_start is None or arc_end is None or arc_start > arc_end:
            continue
        if start <= arc_end and arc_start <= end:
            return arc
    return None


def _overlaps_any(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    return any(
        start <= range_end and range_start <= end for range_start, range_end in ranges
    )


def _match_item(
    item: AuthorMigrationStoryItem,
    row: Any,
    values: dict[str, Any],
    stamps: dict[str, str],
) -> StoryMigrationItemPlan:
    fills: list[str] = []
    conflicts: list[FieldConflict] = []
    for column, incoming in values.items():
        current = getattr(row, column)
        if _is_empty(current):
            fills.append(column)
        elif current != incoming:
            conflicts.append(
                FieldConflict(
                    field=column,
                    current_excerpt=_excerpt(current),
                    incoming_excerpt=_excerpt(incoming),
                )
            )
    stamps[item.item_key] = _stamp(row)
    target_id = str(row.id)
    target_label = _target_label(row)
    if conflicts:
        return StoryMigrationItemPlan(
            item_key=item.item_key,
            action="conflict",
            target_id=target_id,
            target_label=target_label,
            conflicts=conflicts,
        )
    if fills:
        return StoryMigrationItemPlan(
            item_key=item.item_key,
            action="fill_empty",
            target_id=target_id,
            target_label=target_label,
            fills=fills,
        )
    return StoryMigrationItemPlan(
        item_key=item.item_key,
        action="existing_ref",
        target_id=target_id,
        target_label=target_label,
    )


def _conflict_item(
    item_key: str,
    reason: str,
    *,
    target_label: str | None = None,
    conflicts: list[FieldConflict] | None = None,
) -> StoryMigrationItemPlan:
    return StoryMigrationItemPlan(
        item_key=item_key,
        action="conflict",
        target_label=target_label,
        conflicts=conflicts or [],
        reason_code=reason,
    )


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def _excerpt(value: Any) -> str:
    if value is None:
        return ""
    return str(value)[:_EXCERPT_LIMIT]


def _target_label(row: Any) -> str:
    for attribute in ("name", "title"):
        value = getattr(row, attribute, None)
        if value:
            return str(value)
    return str(getattr(row, "id"))


def _scene_label(scene: Scene) -> str:
    return scene.title or f"Scene {scene.scene_index}"


def _stamp(row: Any) -> str:
    marker = getattr(row, "updated_at", None) or getattr(row, "created_at", None)
    return marker.isoformat() if marker is not None else ""


def _planned_range_chapters(scene: Scene) -> set[int]:
    meta = scene.structure_meta if isinstance(scene.structure_meta, dict) else {}
    planned = meta.get("planned_chapter_range")
    if not isinstance(planned, dict):
        return set()
    start = _to_int(planned.get("start"))
    if start is None:
        return set()
    end = _to_int(planned.get("end"))
    if end is None or end < start:
        end = start
    return set(range(start, end + 1))


def _migration_meta(
    request: AuthorMigrationStoryRequest,
    item: AuthorMigrationStoryItem,
    authorized_by: str,
    adopted_at: str,
) -> dict[str, Any]:
    return {
        "source": MIGRATION_SOURCE,
        "migration_id": request.migration_id,
        "source_refs": list(item.source_refs),
        "authorized_by": authorized_by,
        "adopted_at": adopted_at,
    }


def _resolve_entity_refs(keys: list[str], refs: dict[str, str]) -> list[str]:
    resolved: list[str] = []
    for key in keys:
        value = _resolve_entity_ref(key, refs)
        if value and value not in resolved:
            resolved.append(value)
    return resolved


def _resolve_entity_ref(key: str | None, refs: dict[str, str]) -> str | None:
    if not key:
        return None
    if key in refs and refs[key]:
        return str(refs[key])
    try:
        # 契约允许 related_entity_keys / pov_entity_key 直接携带已有 entity_id。
        return str(uuid.UUID(key))
    except (ValueError, AttributeError, TypeError):
        return None


def _model_for_kind(
    kind: str,
) -> type[PlotThread | OutlineArc | ForeshadowingPlan | Scene] | None:
    return {
        "arc": OutlineArc,
        "thread": PlotThread,
        "foreshadowing": ForeshadowingPlan,
        "scene": Scene,
    }.get(kind)


def _asset_state(row: Any) -> dict[str, Any]:
    if isinstance(row, PlotThread):
        return {
            "status": row.status,
            "thread_type": row.thread_type,
            "summary": row.summary,
            "visible_goal": row.visible_goal,
            "hidden_truth": row.hidden_truth,
            "start_chapter": row.start_chapter,
            "planned_payoff_chapter": row.planned_payoff_chapter,
            "related_entity_ids": row.related_entity_ids or [],
            "provenance_meta": row.provenance_meta or {},
        }
    if isinstance(row, OutlineArc):
        return {
            "status": row.status,
            "start_chapter": row.start_chapter,
            "end_chapter": row.end_chapter,
            "arc_goal": row.arc_goal,
            "core_conflict": row.core_conflict,
            "climax": row.climax,
            "result": row.result,
            "next_hook": row.next_hook,
            "related_entity_ids": row.related_entity_ids or [],
            "provenance_meta": row.provenance_meta or {},
        }
    if isinstance(row, ForeshadowingPlan):
        return {
            "status": row.status,
            "surface_meaning": row.surface_meaning,
            "hidden_meaning": row.hidden_meaning,
            "planned_seed_chapter": row.planned_seed_chapter,
            "planned_payoff_chapter": row.planned_payoff_chapter,
            "planned_reinforce_chapters": row.planned_reinforce_chapters or [],
            "related_entity_ids": row.related_entity_ids or [],
            "provenance_meta": row.provenance_meta or {},
        }
    if isinstance(row, Scene):
        return {
            "status": row.status,
            "source": row.source,
            "title": row.title,
            "goal": row.goal,
            "core_conflict": row.core_conflict,
            "emotional_beat": row.emotional_beat,
            "must_happen": row.must_happen,
            "must_not_happen": row.must_not_happen,
            "chapter_ids": row.chapter_ids or [],
            "scene_chunks": row.scene_chunks or [],
            "structure_meta": row.structure_meta or {},
        }
    return {"status": getattr(row, "status", None)}


def _owns_migration_marker(row: Any) -> bool:
    if isinstance(row, Scene):
        meta = row.structure_meta
    else:
        meta = row.provenance_meta
    return isinstance(meta, dict) and meta.get("source") == MIGRATION_SOURCE


def _merge_row_meta(row: Any, extra: dict[str, Any]) -> None:
    if isinstance(row, Scene):
        meta = dict(row.structure_meta or {})
        meta.update(extra)
        row.structure_meta = meta
    else:
        meta = dict(row.provenance_meta or {})
        meta.update(extra)
        row.provenance_meta = meta


def _change(
    item_key: str,
    kind: str,
    row: Any,
    operation: str,
    before: dict[str, Any],
) -> MigrationAppliedChange:
    return MigrationAppliedChange(
        item_key=item_key,
        kind=kind,
        target_id=str(row.id),
        operation=operation,
        before=before,
        after_hash=stable_hash(_asset_state(row)),
    )
