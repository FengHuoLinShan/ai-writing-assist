from __future__ import annotations

import uuid
from unittest import mock

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.repositories import (
    PlotThreadRepository,
    SceneFusionSuggestionRepository,
    SceneRepository,
)
from modules.outline.scene_workbench import SceneWorkbenchService
from modules.outline.schemas import (
    PlotThreadCreate,
    SceneCreate,
    SceneFusionSaveRequest,
)
from modules.outline.structure_dedup import (
    OutlineStructureDedupService,
    _asset_fingerprints,
)

pytestmark = [pytest.mark.asyncio]


async def test_apply_isolates_database_failure_per_suggestion(
    db_session: AsyncSession,
    test_project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = OutlineStructureDedupService(
        llm_client=mock.MagicMock(model_name="test-model")
    )
    calls = 0

    async def apply_one(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            await db_session.execute(
                text("INSERT INTO plot_threads (id) VALUES (:id)"),
                {"id": str(uuid.uuid4())},
            )
        return {
            "asset_type": "plot_thread",
            "action": "deprecate_duplicate",
            "source_asset_id": "source-2",
            "target_asset_id": "target-2",
        }

    monkeypatch.setattr(service, "_apply_one", apply_one)
    result = await service.apply(
        db_session,
        novel_id=test_project_id,
        confirmed=True,
        suggestions=[
            {
                "asset_type": "plot_thread",
                "action": "deprecate_duplicate",
                "source_asset_id": "source-1",
                "target_asset_id": "target-1",
            },
            {
                "asset_type": "plot_thread",
                "action": "deprecate_duplicate",
                "source_asset_id": "source-2",
                "target_asset_id": "target-2",
            },
        ],
    )

    assert result["applied"] == 1
    assert result["skipped"] == 1
    assert len(result["warnings"]) == 1
    assert await db_session.scalar(select(1)) == 1


async def _create_thread(
    db: AsyncSession,
    novel_id: str,
    *,
    name: str,
    status: str = "draft",
    start_chapter: int = 1,
) -> str:
    thread = await PlotThreadRepository().create(
        db,
        uuid.UUID(hex=novel_id),
        PlotThreadCreate(
            name=name,
            thread_type="main",
            summary=f"{name} 的主线",
            visible_goal="查明真相",
            start_chapter=start_chapter,
            status=status,
        ),
    )
    return str(thread.id)


async def _create_scene(
    db: AsyncSession,
    novel_id: str,
    *,
    scene_index: int,
    title: str,
) -> str:
    scene = await SceneRepository().create(
        db,
        uuid.UUID(hex=novel_id),
        SceneCreate(
            scene_index=scene_index,
            title=title,
            goal=f"{title} 的目标",
            core_conflict=f"{title} 的冲突",
            emotional_beat="紧张",
            must_happen="推进剧情",
            must_not_happen="泄露真相",
            chapter_ids=[str(scene_index + 1)],
            status="draft",
        ),
    )
    return str(scene.id)


async def _persist_phase1c_pair(
    db: AsyncSession,
    novel_id: str,
    source_scene_ids: list[str],
) -> str:
    stored_ids = await SceneWorkbenchService().persist_fusion_suggestions(
        db,
        novel_id=novel_id,
        source_workflow_id="wf-phase1c",
        suggestions=[
            {
                "suggestion_kind": "cross_chapter",
                "proposed_action": "merge",
                "source_scene_ids": source_scene_ids,
                "chapter_span": [1, 2],
                "confidence": 0.8,
                "reason": "同一导入边界的延续 Scene",
            }
        ],
    )
    assert len(stored_ids) == 1
    return stored_ids[0]


async def test_structure_dedup_suggests_exact_duplicate_thread(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    await _create_thread(db_session, test_project_id, name="旧日调查线", status="draft")
    await _create_thread(
        db_session,
        test_project_id,
        name="旧日调查线",
        status="candidate",
        start_chapter=2,
    )

    result = await OutlineStructureDedupService(
        llm_client=mock.MagicMock(model_name="test-model")
    ).suggest(
        db_session,
        novel_id=test_project_id,
        asset_types=["plot_thread"],
    )

    assert result["suggestion_count"] == 1
    suggestion = result["suggestions"][0]
    assert suggestion["asset_type"] == "plot_thread"
    assert suggestion["action"] == "merge"
    assert suggestion["target_status"] == "draft"
    assert suggestion["source_status"] == "candidate"


async def test_structure_dedup_apply_deprecates_duplicate_thread(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    target_id = await _create_thread(
        db_session,
        test_project_id,
        name="王都暗线",
        status="draft",
    )
    source_id = await _create_thread(
        db_session,
        test_project_id,
        name="王都暗线",
        status="candidate",
        start_chapter=2,
    )

    result = await OutlineStructureDedupService().apply(
        db_session,
        novel_id=test_project_id,
        confirmed=True,
        suggestions=[
            {
                "asset_type": "plot_thread",
                "action": "deprecate_duplicate",
                "source_asset_id": source_id,
                "target_asset_id": target_id,
            }
        ],
    )

    assert result["applied"] == 1
    source = await PlotThreadRepository().get(db_session, uuid.UUID(hex=source_id))
    assert source is not None
    assert source.status == "deprecated"
    assert source.provenance_meta["merged_into_asset_id"] == target_id
    assert source.provenance_meta["dedup_source"] == "smart_dedup"


async def test_scene_group_requires_confirmed_current_preview(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    source_id = await _create_scene(
        db_session,
        test_project_id,
        scene_index=0,
        title="追击上",
    )
    target_id = await _create_scene(
        db_session,
        test_project_id,
        scene_index=1,
        title="追击下",
    )
    service = OutlineStructureDedupService()
    scenes = await service._load_assets(
        db_session,
        novel_id=test_project_id,
        limit=10,
    )
    by_id = {item.asset_id: item for item in scenes["scene"]}
    source_fp = _asset_fingerprints(by_id[source_id])
    target_fp = _asset_fingerprints(by_id[target_id])
    operation = {
        "source_asset_id": source_id,
        "action": "merge",
        "expected_source_execution_fingerprint": source_fp["execution_fingerprint"],
        "expected_target_execution_fingerprint": target_fp["execution_fingerprint"],
    }

    with pytest.raises(ValueError, match="confirmation_required"):
        await service.apply_group(
            db_session,
            novel_id=test_project_id,
            primary_asset_id=target_id,
            asset_type="scene",
            operations=[operation],
        )

    result = await service.apply_group(
        db_session,
        novel_id=test_project_id,
        primary_asset_id=target_id,
        asset_type="scene",
        operations=[{**operation, "scene_preview_confirmed": True}],
    )

    source = await SceneRepository().get(db_session, uuid.UUID(source_id))
    assert result[0]["action"] == "merge"
    assert source is not None and source.status == "deprecated"


async def test_scene_group_ai_fusion_creates_review_queue_without_mutation(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    source_id = await _create_scene(
        db_session,
        test_project_id,
        scene_index=0,
        title="追击上",
    )
    target_id = await _create_scene(
        db_session,
        test_project_id,
        scene_index=1,
        title="追击下",
    )
    service = OutlineStructureDedupService()
    scenes = await service._load_assets(
        db_session,
        novel_id=test_project_id,
        limit=10,
    )
    by_id = {item.asset_id: item for item in scenes["scene"]}
    source_fp = _asset_fingerprints(by_id[source_id])
    target_fp = _asset_fingerprints(by_id[target_id])

    result = await service.apply_group(
        db_session,
        novel_id=test_project_id,
        primary_asset_id=target_id,
        asset_type="scene",
        operations=[
            {
                "source_asset_id": source_id,
                "action": "ai_fusion",
                "expected_source_execution_fingerprint": source_fp[
                    "execution_fingerprint"
                ],
                "expected_target_execution_fingerprint": target_fp[
                    "execution_fingerprint"
                ],
            }
        ],
    )

    source = await SceneRepository().get(db_session, uuid.UUID(source_id))
    target = await SceneRepository().get(db_session, uuid.UUID(target_id))
    pending = await SceneFusionSuggestionRepository().list_by_status(
        db_session,
        uuid.UUID(test_project_id),
    )
    assert result[0]["action"] == "ai_fusion_suggestion"
    assert source is not None and source.status == "draft"
    assert target is not None and target.status == "draft"
    assert len(pending) == 1
    assert pending[0].source_scene_ids == [target_id, source_id]
    assert pending[0].proposed_scene["resolution_mode"] == "ai_fusion_review"


async def test_structure_dedup_group_validates_keep_separate_current_fingerprint(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    source_id = await _create_scene(
        db_session,
        test_project_id,
        scene_index=0,
        title="旧场景",
    )
    target_id = await _create_scene(
        db_session,
        test_project_id,
        scene_index=1,
        title="主场景",
    )
    service = OutlineStructureDedupService()
    assets = await service._load_assets(
        db_session,
        novel_id=test_project_id,
        limit=10,
    )
    by_id = {item.asset_id: item for item in assets["scene"]}
    source_fp = _asset_fingerprints(by_id[source_id])
    target_fp = _asset_fingerprints(by_id[target_id])
    source = await SceneRepository().get(db_session, uuid.UUID(source_id))
    assert source is not None
    source.goal = "扫描后改变的场景目标"
    await db_session.flush()

    with pytest.raises(ValueError, match="stale_suggestion"):
        await service.apply_group(
            db_session,
            novel_id=test_project_id,
            primary_asset_id=target_id,
            asset_type="scene",
            operations=[
                {
                    "source_asset_id": source_id,
                    "action": "keep_separate",
                    "expected_source_execution_fingerprint": source_fp[
                        "execution_fingerprint"
                    ],
                    "expected_target_execution_fingerprint": target_fp[
                        "execution_fingerprint"
                    ],
                }
            ],
        )


@pytest.mark.parametrize("decision_status", ["pending", "dismissed", "adopted"])
async def test_structure_dedup_skips_current_phase1c_scene_decision_pair(
    db_session: AsyncSession,
    test_project_id: str,
    decision_status: str,
) -> None:
    managed_left = await _create_scene(
        db_session,
        test_project_id,
        scene_index=0,
        title="边界追击",
    )
    managed_right = await _create_scene(
        db_session,
        test_project_id,
        scene_index=1,
        title="边界追击",
    )
    visible_left = await _create_scene(
        db_session,
        test_project_id,
        scene_index=2,
        title="仍需扫描",
    )
    visible_right = await _create_scene(
        db_session,
        test_project_id,
        scene_index=3,
        title="仍需扫描",
    )
    suggestion_id = await _persist_phase1c_pair(
        db_session,
        test_project_id,
        [managed_left, managed_right],
    )
    if decision_status != "pending":
        suggestion = await SceneFusionSuggestionRepository().get_for_novel(
            db_session,
            uuid.UUID(hex=test_project_id),
            uuid.UUID(suggestion_id),
        )
        assert suggestion is not None
        await SceneFusionSuggestionRepository().mark_status(
            db_session,
            suggestion,
            status=decision_status,
        )

    result = await OutlineStructureDedupService(
        llm_client=mock.MagicMock(model_name="test-model")
    ).suggest(
        db_session,
        novel_id=test_project_id,
        asset_types=["scene"],
    )

    suggested_pairs = {
        frozenset((item["source_asset_id"], item["target_asset_id"]))
        for item in result["suggestions"]
    }
    assert suggested_pairs == {frozenset((visible_left, visible_right))}


async def test_structure_dedup_rescans_phase1c_pair_after_source_changes(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    left_id = await _create_scene(
        db_session,
        test_project_id,
        scene_index=0,
        title="来源更新后仍重复",
    )
    right_id = await _create_scene(
        db_session,
        test_project_id,
        scene_index=1,
        title="来源更新后仍重复",
    )
    await _persist_phase1c_pair(db_session, test_project_id, [left_id, right_id])

    left = await SceneRepository().get(db_session, uuid.UUID(left_id))
    assert left is not None
    left.emotional_beat = "作者已调整的节奏"
    await db_session.flush()

    result = await OutlineStructureDedupService(
        llm_client=mock.MagicMock(model_name="test-model")
    ).suggest(
        db_session,
        novel_id=test_project_id,
        asset_types=["scene"],
    )

    assert {
        frozenset((item["source_asset_id"], item["target_asset_id"]))
        for item in result["suggestions"]
    } == {frozenset((left_id, right_id))}


async def test_structure_dedup_skips_adopted_fusion_result_pairs(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    left_id = await _create_scene(
        db_session,
        test_project_id,
        scene_index=0,
        title="追击上",
    )
    right_id = await _create_scene(
        db_session,
        test_project_id,
        scene_index=1,
        title="追击下",
    )
    suggestion_id = await _persist_phase1c_pair(
        db_session,
        test_project_id,
        [left_id, right_id],
    )
    saved = await SceneWorkbenchService().save_llm_fusion(
        db_session,
        test_project_id,
        SceneFusionSaveRequest(
            source_scene_ids=[left_id, right_id],
            suggestion_id=suggestion_id,
            mode="keep_originals",
        ),
    )
    assert saved.fused_scene is not None

    result = await OutlineStructureDedupService(
        llm_client=mock.MagicMock(model_name="test-model")
    ).suggest(
        db_session,
        novel_id=test_project_id,
        asset_types=["scene"],
    )

    assert result["suggestions"] == []


async def test_current_fusion_decision_pairs_batch_load_sources(
    db_session: AsyncSession,
    test_project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_pairs: set[frozenset[str]] = set()
    for index in range(3):
        left_id = await _create_scene(
            db_session,
            test_project_id,
            scene_index=index * 2,
            title=f"批量来源 {index} 上",
        )
        right_id = await _create_scene(
            db_session,
            test_project_id,
            scene_index=index * 2 + 1,
            title=f"批量来源 {index} 下",
        )
        await _persist_phase1c_pair(db_session, test_project_id, [left_id, right_id])
        expected_pairs.add(frozenset((left_id, right_id)))

    get_many_calls: list[list[uuid.UUID]] = []
    list_status_calls: list[tuple[str, ...]] = []
    original_get_many = SceneRepository.get_many_for_novel
    original_list_by_statuses = SceneFusionSuggestionRepository.list_by_statuses

    async def spy_get_many(self, db, novel_id, scene_ids):
        get_many_calls.append(list(scene_ids))
        return await original_get_many(self, db, novel_id, scene_ids)

    async def spy_list_by_statuses(self, db, novel_id, *, statuses, skip=0, limit=None):
        list_status_calls.append(statuses)
        return await original_list_by_statuses(
            self,
            db,
            novel_id,
            statuses=statuses,
            skip=skip,
            limit=limit,
        )

    monkeypatch.setattr(SceneRepository, "get_many_for_novel", spy_get_many)
    monkeypatch.setattr(
        SceneFusionSuggestionRepository,
        "list_by_statuses",
        spy_list_by_statuses,
    )

    pairs = await SceneWorkbenchService().get_current_fusion_decision_pairs(
        db_session,
        test_project_id,
    )

    assert pairs == expected_pairs
    assert list_status_calls == [("pending", "dismissed", "adopted")]
    assert len(get_many_calls) == 1
    assert set(get_many_calls[0]) == {
        uuid.UUID(scene_id) for pair in expected_pairs for scene_id in pair
    }


async def test_structure_dedup_keeps_phase1c_decisions_novel_scoped(
    db_session: AsyncSession,
    test_project_id: str,
    other_novel_id: str,
) -> None:
    first_left = await _create_scene(
        db_session,
        test_project_id,
        scene_index=0,
        title="项目内重复",
    )
    first_right = await _create_scene(
        db_session,
        test_project_id,
        scene_index=1,
        title="项目内重复",
    )
    await _persist_phase1c_pair(
        db_session,
        test_project_id,
        [first_left, first_right],
    )
    other_left = await _create_scene(
        db_session,
        other_novel_id,
        scene_index=0,
        title="项目内重复",
    )
    other_right = await _create_scene(
        db_session,
        other_novel_id,
        scene_index=1,
        title="项目内重复",
    )

    result = await OutlineStructureDedupService(
        llm_client=mock.MagicMock(model_name="test-model")
    ).suggest(
        db_session,
        novel_id=other_novel_id,
        asset_types=["scene"],
    )

    assert {
        frozenset((item["source_asset_id"], item["target_asset_id"]))
        for item in result["suggestions"]
    } == {frozenset((other_left, other_right))}


async def test_structure_dedup_only_loads_fusion_decisions_for_scene_scope(
    db_session: AsyncSession,
    test_project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _create_thread(db_session, test_project_id, name="重复剧情线")
    await _create_thread(
        db_session,
        test_project_id,
        name="重复剧情线",
        status="candidate",
        start_chapter=2,
    )

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("non-scene scan must not load Scene fusion decisions")

    monkeypatch.setattr(
        SceneWorkbenchService,
        "get_current_fusion_decision_pairs",
        fail_if_called,
    )
    result = await OutlineStructureDedupService(
        llm_client=mock.MagicMock(model_name="test-model")
    ).suggest(
        db_session,
        novel_id=test_project_id,
        asset_types=["plot_thread"],
    )

    assert result["suggestion_count"] == 1
