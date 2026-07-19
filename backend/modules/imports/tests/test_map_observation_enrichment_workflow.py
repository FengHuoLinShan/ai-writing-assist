from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from modules.imports.adoption_policy import build_authorization_snapshot
from modules.imports.map_observation_enrichment_workflow import (
    MAP_OBSERVATION_ENRICHMENT_STAGE,
    MAP_OBSERVATION_ENRICHMENT_WORKFLOW_VERSION,
    MapObservationEnrichmentWorkflow,
)
from modules.outline.facade import bind_scene_spans_to_source, create_scene
from modules.world.facade import create_entity
from modules.world.map_models import MapObservation
from modules.writing.facade import create_published_draft_only


@pytest.mark.asyncio
async def test_map_enrichment_task_handler_is_a_thin_orchestrator_delegate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.imports import map_observation_enrichment_workflow as workflow_module
    from modules.imports.tasks import handle_map_observation_enrichment

    orchestrator = type(
        "FakeOrchestrator",
        (),
        {"run_task": AsyncMock(return_value={"status": "done"})},
    )()
    monkeypatch.setattr(
        workflow_module,
        "MapObservationEnrichmentTaskOrchestrator",
        lambda: orchestrator,
    )
    db = object()
    task = object()

    result = await handle_map_observation_enrichment(db, task)

    assert result == {"status": "done"}
    orchestrator.run_task.assert_awaited_once_with(db, task)


async def _create_exact_scene(
    db_session,
    novel_id: str,
    *,
    content: str = "克莱恩穿过地下通道，回到了圣赛琳娜教堂。",
    chapter_index: int = 1,
    scene_index: int = 0,
) -> dict:
    draft = await create_published_draft_only(
        db_session,
        novel_id,
        chapter_index,
        title=f"第{chapter_index}章",
        content=content,
    )
    scene = await create_scene(
        db_session,
        novel_id,
        {
            "scene_index": scene_index,
            "title": "回到教堂",
            "goal": "返回大祈祷厅",
            "chapter_ids": [str(chapter_index)],
            "scene_chunks": [
                {
                    "chapter_index": chapter_index,
                    "start_offset": 0,
                    "end_offset": len(content),
                }
            ],
            "status": "canonical",
        },
    )
    await bind_scene_spans_to_source(
        db_session,
        novel_id=novel_id,
        chapter_index=chapter_index,
        content_mode="canonical",
        source_draft_id=draft.id or "",
        source_content_hash=draft.content_hash,
        content=content,
    )
    return scene


async def _create_chunked_scenes(
    db_session,
    novel_id: str,
    *,
    content: str,
    chunks: list[tuple[int, int]],
) -> list[dict]:
    draft = await create_published_draft_only(
        db_session,
        novel_id,
        1,
        title="第1章",
        content=content,
    )
    scenes = []
    for scene_index, (start_offset, end_offset) in enumerate(chunks):
        scenes.append(
            await create_scene(
                db_session,
                novel_id,
                {
                    "scene_index": scene_index,
                    "title": f"Scene {scene_index}",
                    "goal": "测试 authoritative source",
                    "chapter_ids": ["1"],
                    "scene_chunks": [
                        {
                            "chapter_index": 1,
                            "start_offset": start_offset,
                            "end_offset": end_offset,
                        }
                    ],
                    "status": "canonical",
                },
            )
        )
    await bind_scene_spans_to_source(
        db_session,
        novel_id=novel_id,
        chapter_index=1,
        content_mode="canonical",
        source_draft_id=draft.id or "",
        source_content_hash=draft.content_hash,
        content=content,
    )
    return scenes


async def _create_scene_with_chunks(
    db_session,
    novel_id: str,
    *,
    content: str,
    chunks: list[tuple[int, int]],
) -> dict:
    draft = await create_published_draft_only(
        db_session,
        novel_id,
        1,
        title="第1章",
        content=content,
    )
    scene = await create_scene(
        db_session,
        novel_id,
        {
            "scene_index": 0,
            "title": "多片段 Scene",
            "goal": "验证证据边界",
            "chapter_ids": ["1"],
            "scene_chunks": [
                {
                    "chapter_index": 1,
                    "start_offset": start_offset,
                    "end_offset": end_offset,
                }
                for start_offset, end_offset in chunks
            ],
            "status": "canonical",
        },
    )
    await bind_scene_spans_to_source(
        db_session,
        novel_id=novel_id,
        chapter_index=1,
        content_mode="canonical",
        source_draft_id=draft.id or "",
        source_content_hash=draft.content_hash,
        content=content,
    )
    return scene


@pytest.mark.asyncio
async def test_map_enrichment_runtime_plan_keeps_each_scenes_source_chapters(
    db_session,
    sample_novel_id: str,
) -> None:
    first = await _create_exact_scene(
        db_session,
        sample_novel_id,
        content="第一章场景正文。",
        chapter_index=1,
        scene_index=0,
    )
    second = await _create_exact_scene(
        db_session,
        sample_novel_id,
        content="第二章场景正文。",
        chapter_index=2,
        scene_index=1,
    )

    _, runtime_plan = await MapObservationEnrichmentWorkflow()._build_runtime_plan(
        db_session,
        novel_id=sample_novel_id,
        start_chapter=1,
        end_chapter=2,
    )

    source_chapters = {
        item["scene_id"]: item["scene_card"]["source_chapters"]
        for item in runtime_plan["scenes"]
    }
    assert source_chapters == {first["id"]: [1], second["id"]: [2]}


@pytest.mark.asyncio
async def test_map_enrichment_runtime_plan_uses_exact_scene_source_only(
    db_session,
    sample_novel_id: str,
) -> None:
    scene = await _create_exact_scene(db_session, sample_novel_id)
    character = await create_entity(
        db_session,
        sample_novel_id,
        {
            "entity_type": "character",
            "name": "克莱恩",
            "content_json": {"aliases": ["克莱恩·莫雷蒂"]},
        },
    )
    location = await create_entity(
        db_session,
        sample_novel_id,
        {"entity_type": "location", "name": "圣赛琳娜教堂"},
    )
    await create_entity(
        db_session,
        sample_novel_id,
        {"entity_type": "location", "name": "未在当前 Scene 出现的地点"},
    )

    manifest, runtime_plan = await MapObservationEnrichmentWorkflow()._build_runtime_plan(
        db_session,
        novel_id=sample_novel_id,
        start_chapter=1,
        end_chapter=1,
    )

    assert manifest["coverage"] == {
        "selected_scene_count": 1,
        "skipped_scene_count": 0,
        "skipped_scenes": [],
        "overlap_conflict_scene_count": 0,
        "unassigned_range_count": 0,
        "unassigned_ranges": [],
    }
    assert manifest["scenes"][0]["scene_id"] == scene["id"]
    assert len(manifest["scenes"][0]["input_fingerprint"]) == 64
    plan = runtime_plan["scenes"][0]
    assert plan["scene_text"] == "克莱恩穿过地下通道，回到了圣赛琳娜教堂。"
    assert plan["source_parts"][0]["chapter_index"] == 1
    known = {item["name"]: item for item in plan["known_map_entities"]}
    assert known["克莱恩"]["terms"] == ["克莱恩", "克莱恩·莫雷蒂"]
    assert known["圣赛琳娜教堂"]["entity_type"] == "location"
    assert "未在当前 Scene 出现的地点" not in known
    refs = {
        (item["entity_type"], item["name"]): item["id"]
        for item in plan["canonical_entity_refs"]
    }
    assert refs[("character", "克莱恩")] == character["id"]
    assert refs[("location", "圣赛琳娜教堂")] == location["id"]


@pytest.mark.asyncio
async def test_map_enrichment_skips_both_scenes_when_exact_spans_overlap(
    db_session,
    sample_novel_id: str,
) -> None:
    scenes = await _create_chunked_scenes(
        db_session,
        sample_novel_id,
        content="ABCDEFGHIJ",
        chunks=[(0, 6), (4, 10)],
    )

    manifest, runtime_plan = await MapObservationEnrichmentWorkflow()._build_runtime_plan(
        db_session,
        novel_id=sample_novel_id,
        start_chapter=1,
        end_chapter=1,
    )

    assert runtime_plan["scenes"] == []
    assert manifest["coverage"]["overlap_conflict_scene_count"] == 2
    assert {item["scene_id"] for item in manifest["coverage"]["skipped_scenes"]} == {
        item["id"] for item in scenes
    }
    assert {item["reason"] for item in manifest["coverage"]["skipped_scenes"]} == {
        "scene_source_spans_overlap"
    }


@pytest.mark.asyncio
async def test_map_enrichment_reports_gap_without_assigning_it_to_neighbor_scenes(
    db_session,
    sample_novel_id: str,
) -> None:
    await _create_chunked_scenes(
        db_session,
        sample_novel_id,
        content="ABCDEFGHIJ",
        chunks=[(0, 3), (7, 10)],
    )

    manifest, runtime_plan = await MapObservationEnrichmentWorkflow()._build_runtime_plan(
        db_session,
        novel_id=sample_novel_id,
        start_chapter=1,
        end_chapter=1,
    )

    assert [item["scene_text"] for item in runtime_plan["scenes"]] == ["ABC", "HIJ"]
    assert manifest["coverage"]["unassigned_ranges"] == [
        {"chapter_index": 1, "start_offset": 3, "end_offset": 7}
    ]


@pytest.mark.asyncio
async def test_map_enrichment_skips_chapter_only_scene(
    db_session,
    sample_novel_id: str,
) -> None:
    scene = await _create_exact_scene(db_session, sample_novel_id, content="章节正文")
    from modules.outline.models import SceneSpan

    span = (
        await db_session.execute(
            select(SceneSpan).where(SceneSpan.scene_id == uuid.UUID(scene["id"]))
        )
    ).scalar_one()
    span.mapping_status = "chapter_only"
    span.start_offset = None
    span.end_offset = None
    await db_session.flush()

    manifest, runtime_plan = await MapObservationEnrichmentWorkflow()._build_runtime_plan(
        db_session,
        novel_id=sample_novel_id,
        start_chapter=1,
        end_chapter=1,
    )

    assert runtime_plan["scenes"] == []
    assert manifest["coverage"]["skipped_scenes"] == [
        {
            "scene_id": scene["id"],
            "scene_index": 0,
            "reason": "scene_span_is_not_exact",
        }
    ]


@pytest.mark.asyncio
async def test_map_enrichment_finalize_persists_review_candidate_with_own_provenance(
    db_session,
    sample_novel_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene = await _create_exact_scene(db_session, sample_novel_id)
    character = await create_entity(
        db_session,
        sample_novel_id,
        {"entity_type": "character", "name": "克莱恩"},
    )
    location = await create_entity(
        db_session,
        sample_novel_id,
        {"entity_type": "location", "name": "圣赛琳娜教堂"},
    )
    workflow = MapObservationEnrichmentWorkflow()
    manifest, _runtime_plan = await workflow._build_runtime_plan(
        db_session,
        novel_id=sample_novel_id,
        start_chapter=1,
        end_chapter=1,
    )

    async def restore_settings(_db, _novel_id, _snapshot):
        return {"llm": {"model": "fixture"}}

    monkeypatch.setattr(
        "modules.project.facade.restore_project_llm_execution_settings",
        restore_settings,
    )
    receipt = {
        "version": MAP_OBSERVATION_ENRICHMENT_WORKFLOW_VERSION,
        "scenes": [
            {
                "scene_id": scene["id"],
                "scene_index": 0,
                "input_fingerprint": manifest["scenes"][0]["input_fingerprint"],
                "output": {
                    "map_observation_proposals": [
                        {
                            "proposal_type": "character_location",
                            "character_name": "克莱恩",
                            "location_name": "圣赛琳娜教堂",
                            "movement_mode": "walk",
                            "state": "physical",
                            "quote": "克莱恩穿过地下通道，回到了圣赛琳娜教堂。",
                            "confidence": 0.95,
                        }
                    ],
                    "uncertain_items": [],
                },
                "diagnostics": [],
            }
        ],
    }
    task_id = str(uuid.uuid4())
    authorization = build_authorization_snapshot(
        novel_id=sample_novel_id,
        start_chapter=1,
        end_chapter=1,
        adoption_policy="user_authorized_pipeline",
        authorization_confirmed=True,
        stage=MAP_OBSERVATION_ENRICHMENT_STAGE,
    )

    result = await workflow.finalize(
        db_session,
        novel_id=sample_novel_id,
        task_id=task_id,
        start_chapter=1,
        end_chapter=1,
        authorization_snapshot=authorization,
        llm_execution_snapshot={"fixture": True},
        manifest=manifest,
        receipt=receipt,
    )

    assert result["candidate_created_count"] == 1
    assert result["uncertain_items"] == []
    observation = (await db_session.execute(select(MapObservation))).scalar_one()
    assert observation.review_state == "candidate"
    assert observation.scene_id == uuid.UUID(scene["id"])
    assert observation.source_chapter_index == 1
    assert observation.source_ref["source"] == ("map_enrichment_typed_map_proposal")
    assert observation.source_ref["source_workflow"] == "map_enrichment"
    assert str(observation.target_entity_id) == character["id"]
    assert observation.target_entity_type == "character"
    assert observation.value_json == {
        "schema_version": 1,
        "type": "location",
        "location_entity_id": location["id"],
        "movement_mode": "walk",
        "state": "physical",
    }
    assert observation.spatial_anchor == {"location_entity_id": location["id"]}
    assert observation.source_ref["resolved_location_entity_id"] == location["id"]
    assert observation.source_ref["deterministic_map_assignment"] == {
        "status": "location_has_no_unique_map_center"
    }
    assert observation.source_ref["scene_sequence"] == 0
    assert observation.source_ref["source_start_offset"] == 0
    assert observation.source_ref["source_end_offset"] == len(observation.evidence_text)
    assert observation.time_anchor["scene_sequence"] == 0
    assert observation.time_anchor["source_start_offset"] == 0
    assert observation.evidence_text == ("克莱恩穿过地下通道，回到了圣赛琳娜教堂。")


@pytest.mark.parametrize("receipt_scene_count", [0, 2])
@pytest.mark.asyncio
async def test_map_enrichment_finalize_requires_each_prepared_scene_exactly_once(
    db_session,
    sample_novel_id: str,
    monkeypatch: pytest.MonkeyPatch,
    receipt_scene_count: int,
) -> None:
    scene = await _create_exact_scene(db_session, sample_novel_id)
    workflow = MapObservationEnrichmentWorkflow()
    manifest, _runtime_plan = await workflow._build_runtime_plan(
        db_session,
        novel_id=sample_novel_id,
        start_chapter=1,
        end_chapter=1,
    )

    async def restore_settings(_db, _novel_id, _snapshot):
        return {"llm": {"model": "fixture"}}

    monkeypatch.setattr(
        "modules.project.facade.restore_project_llm_execution_settings",
        restore_settings,
    )
    scene_receipt = {
        "scene_id": scene["id"],
        "scene_index": 0,
        "input_fingerprint": manifest["scenes"][0]["input_fingerprint"],
        "output": {"map_observation_proposals": [], "uncertain_items": []},
        "diagnostics": [],
    }

    with pytest.raises(
        ValueError,
        match="every prepared Scene exactly once",
    ):
        await workflow.finalize(
            db_session,
            novel_id=sample_novel_id,
            task_id=str(uuid.uuid4()),
            start_chapter=1,
            end_chapter=1,
            authorization_snapshot=build_authorization_snapshot(
                novel_id=sample_novel_id,
                start_chapter=1,
                end_chapter=1,
                adoption_policy="user_authorized_pipeline",
                authorization_confirmed=True,
                stage=MAP_OBSERVATION_ENRICHMENT_STAGE,
            ),
            llm_execution_snapshot={"fixture": True},
            manifest=manifest,
            receipt={
                "version": MAP_OBSERVATION_ENRICHMENT_WORKFLOW_VERSION,
                "scenes": [dict(scene_receipt) for _ in range(receipt_scene_count)],
            },
        )

    assert list((await db_session.execute(select(MapObservation))).scalars().all()) == []


@pytest.mark.asyncio
async def test_map_enrichment_finalize_turns_cross_part_quote_into_uncertain_item(
    db_session,
    sample_novel_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene = await _create_scene_with_chunks(
        db_session,
        sample_novel_id,
        content="ABC---HIJ",
        chunks=[(0, 3), (6, 9)],
    )
    workflow = MapObservationEnrichmentWorkflow()
    manifest, runtime_plan = await workflow._build_runtime_plan(
        db_session,
        novel_id=sample_novel_id,
        start_chapter=1,
        end_chapter=1,
    )
    assert runtime_plan["scenes"][0]["scene_text"] == "ABC\nHIJ"

    async def restore_settings(_db, _novel_id, _snapshot):
        return {"llm": {"model": "fixture"}}

    monkeypatch.setattr(
        "modules.project.facade.restore_project_llm_execution_settings",
        restore_settings,
    )
    result = await workflow.finalize(
        db_session,
        novel_id=sample_novel_id,
        task_id=str(uuid.uuid4()),
        start_chapter=1,
        end_chapter=1,
        authorization_snapshot=build_authorization_snapshot(
            novel_id=sample_novel_id,
            start_chapter=1,
            end_chapter=1,
            adoption_policy="user_authorized_pipeline",
            authorization_confirmed=True,
            stage=MAP_OBSERVATION_ENRICHMENT_STAGE,
        ),
        llm_execution_snapshot={"fixture": True},
        manifest=manifest,
        receipt={
            "version": MAP_OBSERVATION_ENRICHMENT_WORKFLOW_VERSION,
            "scenes": [
                {
                    "scene_id": scene["id"],
                    "scene_index": 0,
                    "input_fingerprint": manifest["scenes"][0]["input_fingerprint"],
                    "output": {
                        "map_observation_proposals": [
                            {
                                "proposal_type": "route_state",
                                "path_name": "跨片段路线",
                                "state": "open",
                                "quote": "ABC\nHIJ",
                                "confidence": 0.9,
                            }
                        ],
                        "uncertain_items": [],
                    },
                    "diagnostics": [],
                }
            ],
        },
    )

    assert result["candidate_created_count"] == 0
    assert result["uncertain_count"] == 1
    assert result["uncertain_items"][0]["reason"] == (
        "evidence_not_found_in_current_scene"
    )


@pytest.mark.asyncio
async def test_map_enrichment_finalize_orders_same_scene_movements_by_source_offset(
    db_session,
    sample_novel_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = "克莱恩出现在黑荆棘安保公司内部。他沿着街道前行。克莱恩回到了圣赛琳娜教堂。"
    scene = await _create_exact_scene(
        db_session,
        sample_novel_id,
        content=content,
    )
    await create_entity(
        db_session,
        sample_novel_id,
        {"entity_type": "character", "name": "克莱恩"},
    )
    for name in ("黑荆棘安保公司", "圣赛琳娜教堂"):
        await create_entity(
            db_session,
            sample_novel_id,
            {"entity_type": "location", "name": name},
        )
    workflow = MapObservationEnrichmentWorkflow()
    manifest, _runtime_plan = await workflow._build_runtime_plan(
        db_session,
        novel_id=sample_novel_id,
        start_chapter=1,
        end_chapter=1,
    )

    async def restore_settings(_db, _novel_id, _snapshot):
        return {"llm": {"model": "fixture"}}

    monkeypatch.setattr(
        "modules.project.facade.restore_project_llm_execution_settings",
        restore_settings,
    )
    task_id = str(uuid.uuid4())
    result = await workflow.finalize(
        db_session,
        novel_id=sample_novel_id,
        task_id=task_id,
        start_chapter=1,
        end_chapter=1,
        authorization_snapshot=build_authorization_snapshot(
            novel_id=sample_novel_id,
            start_chapter=1,
            end_chapter=1,
            adoption_policy="user_authorized_pipeline",
            authorization_confirmed=True,
            stage=MAP_OBSERVATION_ENRICHMENT_STAGE,
        ),
        llm_execution_snapshot={"fixture": True},
        manifest=manifest,
        receipt={
            "version": MAP_OBSERVATION_ENRICHMENT_WORKFLOW_VERSION,
            "scenes": [
                {
                    "scene_id": scene["id"],
                    "scene_index": 0,
                    "input_fingerprint": manifest["scenes"][0]["input_fingerprint"],
                    "output": {
                        "map_observation_proposals": [
                            {
                                "proposal_type": "character_location",
                                "character_name": "克莱恩",
                                "location_name": "圣赛琳娜教堂",
                                "movement_mode": "walk",
                                "state": "physical",
                                "quote": "克莱恩回到了圣赛琳娜教堂。",
                                "confidence": 0.95,
                            },
                            {
                                "proposal_type": "character_location",
                                "character_name": "克莱恩",
                                "location_name": "黑荆棘安保公司",
                                "movement_mode": "walk",
                                "state": "present",
                                "quote": "克莱恩出现在黑荆棘安保公司内部。",
                                "confidence": 0.95,
                            },
                        ],
                        "uncertain_items": [],
                    },
                    "diagnostics": [],
                }
            ],
        },
    )

    assert result["candidate_created_count"] == 2
    observations = list(
        (await db_session.execute(select(MapObservation))).scalars().all()
    )
    ordered = sorted(
        observations,
        key=lambda item: item.time_anchor["scene_sequence"],
    )
    assert [item.evidence_text for item in ordered] == [
        "克莱恩出现在黑荆棘安保公司内部。",
        "克莱恩回到了圣赛琳娜教堂。",
    ]
    assert [item.time_anchor["scene_sequence"] for item in ordered] == [0, 1]
    assert [item.time_anchor["source_start_offset"] for item in ordered] == [
        content.index(item.evidence_text) for item in ordered
    ]
