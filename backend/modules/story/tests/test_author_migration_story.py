"""表格迁移 story 落库（L3，ADR-0030）的行为测试。

覆盖：chapter_plan 的 planned/existing_ref/reference_only/link_scene 四分支、
同名补空与冲突、卷章节范围重叠、总纲三策略及回滚、跨 novel 隔离、
指纹过期、deep import 场景替换不清理表格迁移来源 Scene。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError
from modules.story.outline_state.author_migration import (
    OUTLINE_ITEM_KEY,
    apply_author_migration_structures,
    plan_author_migration_structures,
    rollback_author_migration_structures,
)
from modules.story.outline_state.contracts import (
    AuthorMigrationOutlineInput,
    AuthorMigrationStoryItem,
    AuthorMigrationStoryRequest,
)
from modules.story.outline_state.models import (
    ForeshadowingPlan,
    OutlineArc,
    PlotThread,
    Scene,
    SceneChapterLink,
    StoryOutlineRevision,
)
from modules.story.outline_state.repositories import (
    OutlineArcRepository,
    PlotThreadRepository,
    SceneRepository,
)
from modules.story.outline_state.scene_replacement import (
    DeepImportSceneCommitService,
    _is_cleanable,
)
from modules.story.outline_state.schemas import (
    OutlineArcCreate,
    PlotThreadCreate,
    SceneCreate,
)
from modules.story.outline_state.story_outline_schemas import (
    StoryOutlineCreativeCore,
    StoryOutlineRevisionCreate,
)
from modules.story.outline_state.story_outline_service import StoryOutlineService


def _item(**overrides) -> AuthorMigrationStoryItem:
    payload = {
        "item_key": "f0s0r1",
        "source_refs": ["f0s0:r1"],
        "source_hash": "a" * 64,
        "kind": "thread",
        "title": "主角复仇线",
    }
    payload.update(overrides)
    return AuthorMigrationStoryItem(**payload)


def _request(
    items: list[AuthorMigrationStoryItem],
    **overrides,
) -> AuthorMigrationStoryRequest:
    payload = {
        "migration_id": "m-20261002-0001",
        "items": items,
    }
    payload.update(overrides)
    return AuthorMigrationStoryRequest(**payload)


def _outline(
    policy: str = "create_if_missing",
    **overrides,
) -> AuthorMigrationOutlineInput:
    payload = {
        "title": "迁移总纲",
        "outline_markdown": "# 总纲\n\n作者原文，逐字保留。",
        "creative_core": {
            "premise": "被围城的城邦必须在冬天前找到新盟友。",
            "tone_and_reader_promise": "克制的权谋奇幻。",
            "story_engine": "每次谈判都暴露一个新的秘密。",
        },
        "policy": policy,
    }
    payload.update(overrides)
    return AuthorMigrationOutlineInput(**payload)


def _outline_revision_data(
    idempotency_key: str,
    *,
    markdown: str = "# 基线总纲\n\n基线正文。",
    title: str = "基线总纲",
    base_revision_id: uuid.UUID | None = None,
) -> StoryOutlineRevisionCreate:
    return StoryOutlineRevisionCreate(
        base_revision_id=base_revision_id,
        idempotency_key=idempotency_key,
        source="manual",
        title=title,
        creative_core=StoryOutlineCreativeCore(
            premise="基线前提",
            tone_and_reader_promise="基线基调",
            story_engine="基线引擎",
        ),
        outline_markdown=markdown,
        major_storylines=[],
        macro_movements=[],
        open_decisions=[],
    )


async def _make_thread(
    db: AsyncSession,
    novel_id: str,
    **overrides,
) -> PlotThread:
    payload = {"name": "旧线", "thread_type": "main"}
    payload.update(overrides)
    return await PlotThreadRepository().create(
        db,
        uuid.UUID(novel_id),
        PlotThreadCreate(**payload),
    )


async def _make_arc(db: AsyncSession, novel_id: str, **overrides) -> OutlineArc:
    payload = {"title": "第一卷", "start_chapter": 1, "end_chapter": 10}
    payload.update(overrides)
    return await OutlineArcRepository().create(
        db,
        uuid.UUID(novel_id),
        OutlineArcCreate(**payload),
    )


async def _make_scene(db: AsyncSession, novel_id: str, **overrides) -> Scene:
    payload = {
        "scene_index": 0,
        "title": "既有场景",
        "source": "manual",
        "status": "draft",
    }
    payload.update(overrides)
    return await SceneRepository().create(
        db,
        uuid.UUID(novel_id),
        SceneCreate(**payload),
    )


async def _write_chapter(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
) -> None:
    from modules.writing.models import WritingDraft

    db.add(
        WritingDraft(
            novel_id=uuid.UUID(novel_id),
            chapter_index=chapter_index,
            title=f"第{chapter_index}章",
            content="章节正文" * 20,
            content_hash="",
        )
    )
    await db.flush()


async def _plan(
    db: AsyncSession,
    novel_id: str,
    request: AuthorMigrationStoryRequest,
    entity_refs: dict[str, str | None] | None = None,
):
    return await plan_author_migration_structures(
        db,
        novel_id,
        request,
        entity_refs=entity_refs or {},
    )


async def _apply(
    db: AsyncSession,
    novel_id: str,
    request: AuthorMigrationStoryRequest,
    fingerprint: str,
    entity_ids: dict[str, str] | None = None,
):
    return await apply_author_migration_structures(
        db,
        novel_id,
        request,
        entity_ids=entity_ids or {},
        expected_fingerprint=fingerprint,
        authorized_by="owner-account-1",
    )


def _action_by_key(plan):
    return {item.item_key: item for item in plan.items}


# ============================================================
# chapter_plan：planned / existing_ref / reference_only / link_scene
# ============================================================


@pytest.mark.asyncio
async def test_chapter_plan_unwritten_chapter_becomes_planned_scene(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    request = _request(
        [
            _item(
                item_key="cp-1",
                kind="chapter_plan",
                title="第3章：夜袭",
                chapter_start=3,
                chapter_end=3,
                fields={
                    "goal": "守住城门",
                    "core_conflict": "守军内讧",
                    "must_happen": "夜袭开始",
                },
            )
        ]
    )
    plan = await _plan(db_session, test_project_id, request)
    assert _action_by_key(plan)["cp-1"].action == "planned_scene"

    receipt = await _apply(db_session, test_project_id, request, plan.fingerprint)
    assert [change.kind for change in receipt.applied_changes] == ["scene"]
    scene_id = uuid.UUID(receipt.applied_changes[0].target_id)
    scene = await db_session.get(Scene, scene_id)
    assert scene is not None
    assert scene.novel_id == uuid.UUID(test_project_id)
    # 形状与 P20 _apply_scenes 的 planned Scene 一致。
    assert scene.source == "spreadsheet_migration"
    assert scene.status == "canonical"
    assert scene.scene_chunks == []
    assert scene.chapter_ids == []
    assert scene.goal == "守住城门"
    assert scene.must_happen == "夜袭开始"
    meta = scene.structure_meta
    assert meta["planning_state"] == "planned"
    assert meta["planned_chapter_range"] == {"start": 3, "end": 3}
    assert meta["source"] == "spreadsheet_migration"
    assert meta["migration_id"] == request.migration_id
    assert meta["source_refs"] == ["f0s0:r1"]
    assert meta["authorized_by"] == "owner-account-1"
    assert meta["adopted_at"]


@pytest.mark.asyncio
async def test_chapter_plan_covered_by_active_scene_is_existing_ref(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    existing = await _make_scene(
        db_session,
        test_project_id,
        chapter_ids=["3"],
    )
    planned_range_scene = await _make_scene(
        db_session,
        test_project_id,
        scene_index=1,
        title="P20 计划场景",
        structure_meta={
            "planning_state": "planned",
            "planned_chapter_range": {"start": 8, "end": 9},
        },
    )
    request = _request(
        [
            _item(
                item_key="cp-covered",
                kind="chapter_plan",
                title="第3章",
                chapter_start=3,
            ),
            _item(
                item_key="cp-planned-range",
                kind="chapter_plan",
                title="第8章",
                chapter_start=8,
            ),
        ]
    )
    plan = await _plan(db_session, test_project_id, request)
    actions = _action_by_key(plan)
    assert actions["cp-covered"].action == "existing_ref"
    assert actions["cp-covered"].target_id == str(existing.id)
    assert actions["cp-planned-range"].action == "existing_ref"
    assert actions["cp-planned-range"].target_id == str(planned_range_scene.id)

    receipt = await _apply(db_session, test_project_id, request, plan.fingerprint)
    assert receipt.applied_changes == []
    scenes = (
        (
            await db_session.execute(
                select(Scene).where(Scene.novel_id == uuid.UUID(test_project_id))
            )
        )
        .scalars()
        .all()
    )
    assert {scene.id for scene in scenes} == {existing.id, planned_range_scene.id}


@pytest.mark.asyncio
async def test_chapter_plan_reference_only_writes_nothing(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    await _write_chapter(db_session, test_project_id, 5)
    request = _request(
        [_item(item_key="cp-5", kind="chapter_plan", title="第5章", chapter_start=5)]
    )
    plan = await _plan(db_session, test_project_id, request)
    assert _action_by_key(plan)["cp-5"].action == "reference_only"

    receipt = await _apply(db_session, test_project_id, request, plan.fingerprint)
    assert receipt.applied_changes == []
    assert (
        await db_session.scalar(
            select(Scene.id).where(Scene.novel_id == uuid.UUID(test_project_id))
        )
        is None
    )


@pytest.mark.asyncio
async def test_chapter_plan_link_scene_creates_scene_with_chapter_ids(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    await _write_chapter(db_session, test_project_id, 5)
    await _write_chapter(db_session, test_project_id, 6)
    request = _request(
        [
            _item(
                item_key="cp-5-7",
                kind="chapter_plan",
                title="第5-7章",
                chapter_start=5,
                chapter_end=7,
                fields={"must_happen": "联军进城"},
            )
        ],
        written_chapter_policy="link_scene",
    )
    plan = await _plan(db_session, test_project_id, request)
    assert _action_by_key(plan)["cp-5-7"].action == "link_scene"

    receipt = await _apply(db_session, test_project_id, request, plan.fingerprint)
    assert len(receipt.applied_changes) == 1
    scene = await db_session.get(
        Scene,
        uuid.UUID(receipt.applied_changes[0].target_id),
    )
    assert scene is not None
    assert scene.chapter_ids == ["5", "6"]
    assert scene.must_happen == "联军进城"
    assert scene.structure_meta["planning_state"] == "materialized"
    assert scene.structure_meta["planned_chapter_range"] == {"start": 5, "end": 7}
    links = (
        (
            await db_session.execute(
                select(SceneChapterLink).where(
                    SceneChapterLink.scene_id == scene.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert sorted(link.chapter_index for link in links) == [5, 6]


# ============================================================
# 同名与重叠
# ============================================================


@pytest.mark.asyncio
async def test_same_name_thread_only_fills_empty_fields(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    thread = await _make_thread(
        db_session,
        test_project_id,
        name="主角复仇线",
        summary=None,
        hidden_truth="复仇的代价是王座",
        start_chapter=None,
    )
    request = _request(
        [
            _item(
                item_key="th-1",
                kind="thread",
                title="主角复仇线",
                chapter_start=1,
                chapter_end=30,
                fields={
                    "summary": "复仇主线",
                    "hidden_truth": "复仇的代价是王座",
                    "visible_goal": "找到真凶",
                },
            )
        ]
    )
    plan = await _plan(db_session, test_project_id, request)
    item_plan = _action_by_key(plan)["th-1"]
    assert item_plan.action == "fill_empty"
    assert sorted(item_plan.fills) == [
        "planned_payoff_chapter",
        "start_chapter",
        "summary",
        "visible_goal",
    ]
    assert item_plan.target_id == str(thread.id)

    receipt = await _apply(db_session, test_project_id, request, plan.fingerprint)
    assert [change.operation for change in receipt.applied_changes] == ["fill_empty"]
    assert receipt.applied_changes[0].before == {
        "planned_payoff_chapter": None,
        "start_chapter": None,
        "summary": None,
        "visible_goal": None,
    }
    await db_session.refresh(thread)
    assert thread.summary == "复仇主线"
    assert thread.hidden_truth == "复仇的代价是王座"
    assert thread.start_chapter == 1
    assert thread.planned_payoff_chapter == 30
    assert thread.status == "draft"
    assert sorted(
        thread.provenance_meta["spreadsheet_migration_fill"]["filled_fields"]
    ) == [
        "planned_payoff_chapter",
        "start_chapter",
        "summary",
        "visible_goal",
    ]


@pytest.mark.asyncio
async def test_same_name_thread_conflicting_field_is_conflict(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    await _make_thread(
        db_session,
        test_project_id,
        name="主角复仇线",
        hidden_truth="原作真相",
    )
    request = _request(
        [
            _item(
                item_key="th-1",
                kind="thread",
                title="主角复仇线",
                fields={"hidden_truth": "表格里的另一个真相"},
            )
        ]
    )
    plan = await _plan(db_session, test_project_id, request)
    item_plan = _action_by_key(plan)["th-1"]
    assert item_plan.action == "conflict"
    assert [conflict.field for conflict in item_plan.conflicts] == ["hidden_truth"]
    assert item_plan.conflicts[0].current_excerpt == "原作真相"

    receipt = await _apply(db_session, test_project_id, request, plan.fingerprint)
    assert receipt.applied_changes == []


@pytest.mark.asyncio
async def test_arc_range_overlap_is_conflict(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    await _make_arc(
        db_session,
        test_project_id,
        title="第一卷",
        start_chapter=1,
        end_chapter=10,
    )
    request = _request(
        [
            _item(
                item_key="arc-1",
                kind="arc",
                title="第二卷",
                chapter_start=5,
                chapter_end=15,
                fields={"arc_goal": "反击"},
            )
        ]
    )
    plan = await _plan(db_session, test_project_id, request)
    item_plan = _action_by_key(plan)["arc-1"]
    assert item_plan.action == "conflict"
    assert item_plan.reason_code == "arc_range_overlap"

    receipt = await _apply(db_session, test_project_id, request, plan.fingerprint)
    assert receipt.applied_changes == []
    arcs = (
        (
            await db_session.execute(
                select(OutlineArc).where(
                    OutlineArc.novel_id == uuid.UUID(test_project_id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert [arc.title for arc in arcs] == ["第一卷"]


@pytest.mark.asyncio
async def test_duplicate_arc_titles_in_one_migration_conflict(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    request = _request(
        [
            _item(
                item_key="arc-a",
                kind="arc",
                title="第一卷",
                chapter_start=1,
                chapter_end=5,
            ),
            _item(
                item_key="arc-b",
                kind="arc",
                title="第一卷",
                chapter_start=1,
                chapter_end=5,
            ),
        ]
    )
    plan = await _plan(db_session, test_project_id, request)
    actions = _action_by_key(plan)
    assert actions["arc-a"].action == "create"
    assert actions["arc-b"].action == "conflict"
    assert actions["arc-b"].reason_code == "duplicate_in_migration"


@pytest.mark.asyncio
async def test_invalid_thread_type_falls_back_to_sub(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    request = _request(
        [
            _item(
                item_key="th-2",
                kind="thread",
                title="神秘暗流",
                fields={"thread_type": "mystery"},
            ),
            _item(
                item_key="th-3",
                kind="thread",
                title="无类型线",
            ),
        ]
    )
    plan = await _plan(db_session, test_project_id, request)
    assert all(item.action == "create" for item in plan.items)
    receipt = await _apply(db_session, test_project_id, request, plan.fingerprint)
    threads = (
        (
            await db_session.execute(
                select(PlotThread).where(
                    PlotThread.novel_id == uuid.UUID(test_project_id)
                )
            )
        )
        .scalars()
        .all()
    )
    by_name = {thread.name: thread for thread in threads}
    assert by_name["神秘暗流"].thread_type == "background"
    assert by_name["无类型线"].thread_type == "sub"
    assert by_name["神秘暗流"].status == "canonical"
    assert len(receipt.applied_changes) == 2


@pytest.mark.asyncio
async def test_foreshadowing_creates_plan_with_chapter_fields(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    request = _request(
        [
            _item(
                item_key="fs-1",
                kind="foreshadowing",
                title="古剑的来历",
                fields={
                    "surface_meaning": "一把旧剑",
                    "hidden_meaning": "封印魔神的钥匙",
                    "reinforce_chapters": "3、5,7",
                },
            )
        ]
    )
    plan = await _plan(db_session, test_project_id, request)
    assert _action_by_key(plan)["fs-1"].action == "create"
    await _apply(db_session, test_project_id, request, plan.fingerprint)
    created = (
        await db_session.execute(
            select(ForeshadowingPlan).where(
                ForeshadowingPlan.novel_id == uuid.UUID(test_project_id)
            )
        )
    ).scalar_one()
    assert created.surface_meaning == "一把旧剑"
    assert created.hidden_meaning == "封印魔神的钥匙"
    assert created.planned_reinforce_chapters == [3, 5, 7]
    assert created.status == "canonical"
    assert created.provenance_meta["source"] == "spreadsheet_migration"


# ============================================================
# 总纲三策略及回滚
# ============================================================


@pytest.mark.asyncio
async def test_outline_create_if_missing_and_rollback_clears_head(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    service = StoryOutlineService()
    current = await service.get_current(db_session, test_project_id)
    assert current.current_revision_id is None

    request = _request([], outline=_outline(policy="create_if_missing"))
    plan = await _plan(db_session, test_project_id, request)
    assert plan.outline_action == "create"

    receipt = await _apply(db_session, test_project_id, request, plan.fingerprint)
    assert receipt.outline_change is not None
    assert receipt.outline_change["base_revision_id"] is None
    revision_id = uuid.UUID(receipt.outline_change["revision_id"])
    current = await service.get_current(db_session, test_project_id)
    assert current.current_revision_id == revision_id
    revision = await db_session.get(StoryOutlineRevision, revision_id)
    assert revision is not None
    assert revision.outline_markdown == "# 总纲\n\n作者原文，逐字保留。"
    assert (
        revision.creative_core_json["premise"] == "被围城的城邦必须在冬天前找到新盟友。"
    )
    assert revision.provenance_json["client_ref"] == "spreadsheet-migration"

    rollback = await rollback_author_migration_structures(
        db_session,
        test_project_id,
        receipt,
        dry_run=False,
    )
    assert rollback.reverted == [OUTLINE_ITEM_KEY]
    current = await service.get_current(db_session, test_project_id)
    assert current.current_revision_id is None
    assert current.revision is None
    # 修订保留在历史中，不硬删。
    assert await db_session.get(StoryOutlineRevision, revision_id) is not None


@pytest.mark.asyncio
async def test_outline_create_if_missing_with_existing_head_skips(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    service = StoryOutlineService()
    baseline = await service.create_revision(
        db_session,
        test_project_id,
        _outline_revision_data("baseline-outline-0001"),
    )
    request = _request([], outline=_outline(policy="create_if_missing"))
    plan = await _plan(db_session, test_project_id, request)
    assert plan.outline_action == "skip"

    receipt = await _apply(db_session, test_project_id, request, plan.fingerprint)
    assert receipt.outline_change is None
    current = await service.get_current(db_session, test_project_id)
    assert current.current_revision_id == baseline.id


@pytest.mark.asyncio
async def test_outline_replace_appends_revision_and_rollback_restores_base(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    service = StoryOutlineService()
    baseline = await service.create_revision(
        db_session,
        test_project_id,
        _outline_revision_data(
            "baseline-outline-0002",
            markdown="# 基线总纲\n\n基线正文。",
        ),
    )
    request = _request([], outline=_outline(policy="replace"))
    plan = await _plan(db_session, test_project_id, request)
    assert plan.outline_action == "replace"

    receipt = await _apply(db_session, test_project_id, request, plan.fingerprint)
    assert receipt.outline_change == {
        "revision_id": receipt.outline_change["revision_id"],
        "base_revision_id": str(baseline.id),
    }
    current = await service.get_current(db_session, test_project_id)
    assert str(current.current_revision_id) == receipt.outline_change["revision_id"]
    assert current.revision.base_revision_id == baseline.id

    rollback = await rollback_author_migration_structures(
        db_session,
        test_project_id,
        receipt,
        dry_run=False,
    )
    assert rollback.reverted == [OUTLINE_ITEM_KEY]
    current = await service.get_current(db_session, test_project_id)
    assert current.revision is not None
    assert current.revision.outline_markdown == "# 基线总纲\n\n基线正文。"
    assert current.revision.restored_from_revision_id == baseline.id


@pytest.mark.asyncio
async def test_outline_skip_policy_writes_nothing(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    request = _request([], outline=_outline(policy="skip"))
    plan = await _plan(db_session, test_project_id, request)
    assert plan.outline_action == "skip"
    receipt = await _apply(db_session, test_project_id, request, plan.fingerprint)
    assert receipt.outline_change is None
    assert (
        await db_session.scalar(
            select(StoryOutlineRevision.id).where(
                StoryOutlineRevision.novel_id == uuid.UUID(test_project_id)
            )
        )
        is None
    )


@pytest.mark.asyncio
async def test_outline_missing_creative_core_is_conflict(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    request = _request(
        [],
        outline=_outline(
            policy="create_if_missing",
            creative_core={"premise": "只有前提"},
        ),
    )
    plan = await _plan(db_session, test_project_id, request)
    assert plan.outline_action == "skip"
    conflict = _action_by_key(plan)[OUTLINE_ITEM_KEY]
    assert conflict.action == "conflict"
    assert conflict.reason_code == "outline_core_missing"
    assert conflict.conflicts[0].field == "creative_core"

    receipt = await _apply(db_session, test_project_id, request, plan.fingerprint)
    assert receipt.outline_change is None
    assert receipt.applied_changes == []
    assert (
        await db_session.scalar(
            select(StoryOutlineRevision.id).where(
                StoryOutlineRevision.novel_id == uuid.UUID(test_project_id)
            )
        )
        is None
    )


# ============================================================
# 指纹与过期
# ============================================================


@pytest.mark.asyncio
async def test_stale_fingerprint_raises_conflict(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    request = _request([_item(item_key="th-stale", kind="thread", title="新线")])
    plan = await _plan(db_session, test_project_id, request)
    # 预览之后作者改了项目状态：出现同名线，动作从 create 变为 fill/conflict。
    await _make_thread(db_session, test_project_id, name="新线")
    with pytest.raises(ConflictError) as exc_info:
        await _apply(
            db_session,
            test_project_id,
            request,
            plan.fingerprint,
        )
    assert exc_info.value.code == "migration_preview_stale"
    # 失败关闭：不写任何结构。
    assert (
        await db_session.scalar(
            select(PlotThread.id).where(PlotThread.novel_id == uuid.UUID(test_project_id))
        )
        is not None  # 同名线本身存在，但迁移未新增。
    )
    assert (
        len(
            (
                await db_session.execute(
                    select(PlotThread.id).where(
                        PlotThread.novel_id == uuid.UUID(test_project_id),
                        PlotThread.provenance_meta["source"].as_string()
                        == "spreadsheet_migration",
                    )
                )
            ).all()
        )
        == 0
    )


@pytest.mark.asyncio
async def test_fingerprint_excludes_new_entity_ids(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    request = _request(
        [
            _item(
                item_key="th-ent",
                kind="thread",
                title="关联实体线",
                related_entity_keys=["ent-1"],
            )
        ]
    )
    plan_without_ids = await _plan(
        db_session,
        test_project_id,
        request,
        entity_refs={"ent-1": None},
    )
    entity_id = str(uuid.uuid4())
    plan_with_ids = await _plan(
        db_session,
        test_project_id,
        request,
        entity_refs={"ent-1": entity_id},
    )
    assert plan_without_ids.fingerprint == plan_with_ids.fingerprint

    receipt = await _apply(
        db_session,
        test_project_id,
        request,
        plan_with_ids.fingerprint,
        entity_ids={"ent-1": entity_id},
    )
    assert len(receipt.applied_changes) == 1
    thread = await db_session.get(
        PlotThread,
        uuid.UUID(receipt.applied_changes[0].target_id),
    )
    assert thread is not None
    assert thread.related_entity_ids == [entity_id]


# ============================================================
# 跨 novel 隔离
# ============================================================


@pytest.mark.asyncio
async def test_cross_novel_names_do_not_match(
    db_session: AsyncSession,
    test_project_id: str,
    project_factory,
) -> None:
    other_project_id = str(await project_factory.create_project(title="另一本书"))
    await _make_thread(db_session, other_project_id, name="主角复仇线")
    await _make_arc(
        db_session,
        other_project_id,
        title="第一卷",
        start_chapter=1,
        end_chapter=10,
    )
    request = _request(
        [
            _item(
                item_key="th-iso",
                kind="thread",
                title="主角复仇线",
                fields={"summary": "本书的线"},
            ),
            _item(
                item_key="arc-iso",
                kind="arc",
                title="第二卷",
                chapter_start=1,
                chapter_end=10,
            ),
        ]
    )
    plan = await _plan(db_session, test_project_id, request)
    actions = _action_by_key(plan)
    assert actions["th-iso"].action == "create"
    assert actions["arc-iso"].action == "create"

    receipt = await _apply(db_session, test_project_id, request, plan.fingerprint)
    assert len(receipt.applied_changes) == 2
    for change in receipt.applied_changes:
        row = await db_session.get(
            PlotThread if change.kind == "thread" else OutlineArc,
            uuid.UUID(change.target_id),
        )
        assert row is not None
        assert row.novel_id == uuid.UUID(test_project_id)
    other_thread = (
        await db_session.execute(
            select(PlotThread).where(PlotThread.novel_id == uuid.UUID(other_project_id))
        )
    ).scalar_one()
    assert other_thread.summary is None


# ============================================================
# 回滚
# ============================================================


@pytest.mark.asyncio
async def test_rollback_deprecates_created_assets_and_keeps_modified(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    request = _request(
        [
            _item(
                item_key="th-rb",
                kind="thread",
                title="将被回滚的线",
                fields={"summary": "临时摘要"},
            ),
            _item(
                item_key="cp-rb",
                kind="chapter_plan",
                title="第9章",
                chapter_start=9,
            ),
        ]
    )
    plan = await _plan(db_session, test_project_id, request)
    receipt = await _apply(db_session, test_project_id, request, plan.fingerprint)
    assert len(receipt.applied_changes) == 2
    thread = await db_session.get(
        PlotThread,
        uuid.UUID(
            next(
                change.target_id
                for change in receipt.applied_changes
                if change.kind == "thread"
            )
        ),
    )
    assert thread is not None
    # 作者在回滚前编辑了这条线 → 快照不一致，应保留。
    thread.summary = "作者改过的摘要"
    await db_session.flush()

    rollback = await rollback_author_migration_structures(
        db_session,
        test_project_id,
        receipt,
        dry_run=False,
    )
    kept_keys = {entry["item_key"] for entry in rollback.kept}
    assert "th-rb" in kept_keys
    assert {"cp-rb"} == set(rollback.reverted)
    scene = (
        await db_session.execute(
            select(Scene).where(Scene.novel_id == uuid.UUID(test_project_id))
        )
    ).scalar_one()
    assert scene.status == "deprecated"
    assert scene.structure_meta["rolled_back_at"]
    await db_session.refresh(thread)
    assert thread.status == "canonical"
    assert thread.summary == "作者改过的摘要"


@pytest.mark.asyncio
async def test_rollback_restores_filled_fields(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    thread = await _make_thread(
        db_session,
        test_project_id,
        name="补空后回滚",
        summary=None,
    )
    request = _request(
        [
            _item(
                item_key="th-fill-rb",
                kind="thread",
                title="补空后回滚",
                fields={"summary": "迁移补的摘要"},
            )
        ]
    )
    plan = await _plan(db_session, test_project_id, request)
    receipt = await _apply(db_session, test_project_id, request, plan.fingerprint)
    assert [change.operation for change in receipt.applied_changes] == ["fill_empty"]

    rollback = await rollback_author_migration_structures(
        db_session,
        test_project_id,
        receipt,
        dry_run=False,
    )
    assert rollback.reverted == ["th-fill-rb"]
    await db_session.refresh(thread)
    assert thread.summary is None
    assert thread.status == "draft"


@pytest.mark.asyncio
async def test_rollback_dry_run_does_not_write(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    request = _request(
        [
            _item(
                item_key="th-dry",
                kind="thread",
                title="dry run 线",
                fields={"summary": "摘要"},
            )
        ],
        outline=_outline(policy="create_if_missing"),
    )
    plan = await _plan(db_session, test_project_id, request)
    receipt = await _apply(db_session, test_project_id, request, plan.fingerprint)
    assert len(receipt.applied_changes) == 1
    assert receipt.outline_change is not None

    rollback = await rollback_author_migration_structures(
        db_session,
        test_project_id,
        receipt,
        dry_run=True,
    )
    assert rollback.reverted == ["th-dry", OUTLINE_ITEM_KEY]
    thread = (
        await db_session.execute(
            select(PlotThread).where(PlotThread.novel_id == uuid.UUID(test_project_id))
        )
    ).scalar_one()
    assert thread.status == "canonical"
    current = await StoryOutlineService().get_current(db_session, test_project_id)
    assert current.current_revision_id is not None


@pytest.mark.asyncio
async def test_rollback_keeps_outline_when_superseded(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    service = StoryOutlineService()
    await service.create_revision(
        db_session,
        test_project_id,
        _outline_revision_data("baseline-outline-0003"),
    )
    request = _request([], outline=_outline(policy="replace"))
    plan = await _plan(db_session, test_project_id, request)
    receipt = await _apply(db_session, test_project_id, request, plan.fingerprint)
    migration_revision_id = uuid.UUID(receipt.outline_change["revision_id"])
    # 作者在回滚前又保存了一个新修订 → head 不再指向迁移修订。
    await service.create_revision(
        db_session,
        test_project_id,
        _outline_revision_data(
            "author-newer-0001",
            markdown="# 作者更新\n\n新正文。",
            title="作者更新",
            base_revision_id=migration_revision_id,
        ),
    )
    rollback = await rollback_author_migration_structures(
        db_session,
        test_project_id,
        receipt,
        dry_run=False,
    )
    assert rollback.reverted == []
    assert rollback.kept == [
        {"item_key": OUTLINE_ITEM_KEY, "reason_code": "outline_superseded"}
    ]
    assert await db_session.get(StoryOutlineRevision, migration_revision_id) is not None
    current = await service.get_current(db_session, test_project_id)
    assert current.revision is not None
    assert current.revision.title == "作者更新"


# ============================================================
# deep import 场景替换回归
# ============================================================


@pytest.mark.asyncio
async def test_deep_import_replacement_keeps_migration_scenes(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    migration_scene = await _make_scene(
        db_session,
        test_project_id,
        scene_index=0,
        title="迁移场景",
        source="spreadsheet_migration",
        status="canonical",
        chapter_ids=["7"],
        structure_meta={
            "source": "spreadsheet_migration",
            "migration_id": "m-20261002-0001",
            "planning_state": "materialized",
            "planned_chapter_range": {"start": 7, "end": 7},
        },
    )
    deep_import_scene = await _make_scene(
        db_session,
        test_project_id,
        scene_index=1,
        title="深度导入场景",
        source="deep_import",
        status="draft",
        chapter_ids=["7"],
        structure_meta={
            "workflow_id": "wf-old-1",
            "auto_ingested": True,
        },
    )
    assert _is_cleanable(migration_scene) is False
    assert _is_cleanable(deep_import_scene) is True

    result = await DeepImportSceneCommitService().commit(
        db_session,
        novel_id=test_project_id,
        workflow_id="wf-new-1",
        start_chapter=7,
        end_chapter=7,
        candidates=[],
        fusion_suggestions=[],
    )
    await db_session.refresh(migration_scene)
    await db_session.refresh(deep_import_scene)
    assert migration_scene.status == "canonical"
    assert deep_import_scene.status == "deprecated"
    assert result["active_scene_changed"] is True
