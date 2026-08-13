from __future__ import annotations

import asyncio
import base64
import hashlib
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select

from core.errors import ConflictError
from infrastructure.llm.image_client import (
    OPENAI_IMAGE_MODEL,
    GeneratedImage,
    OpenAIImageClient,
)
from infrastructure.tasks.facade import enqueue_task
from infrastructure.tasks.models import AsyncTask
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasPage, MapAtlasRun
from modules.world.map_atlas_schemas import (
    AtlasPlan,
    MapAtlasDerivedRequest,
    MapAtlasEvidenceSummary,
    MapAtlasNodeUpdate,
    MapAtlasReviewRequest,
    MapAtlasRunCreate,
)
from modules.world.map_atlas_service import MapAtlasService
from modules.world.map_atlas_storage import (
    MapAtlasStorage,
    page_object_key,
    require_matching_mask,
    validate_png,
)
from modules.world.map_atlas_workflow import (
    _atlas_source_manifest,
    _attempt_object_key,
    _changed_spatial_location_keys,
    _compensate_uploaded_object,
    _generate_page,
    _new_source_identities,
    _plan,
    _plan_prompt,
    _previous_source_manifest,
    _reference_images,
    _require_attempt,
    _spatial_evidence,
    _spatial_fact_buckets,
    _spatial_fingerprint,
    _spatial_planning_context,
    _validate_plan_sources,
    _validate_update_targets,
    reconcile_map_atlas_task_owners,
)

OPAQUE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)


def test_evidence_summary_is_safe_and_old_runs_remain_null() -> None:
    snapshot = {
        "spatial_evidence": {
            "locations_checked": 1,
            "wiki_pages_used": 2,
            "rag_chunks_used": 3,
            "spatial_facts_used": 4,
            "conflicts": 1,
            "facts": ["private"],
            "source_key_refs": {"private": "private"},
            "prompt": "private",
            "token_count": 99,
            "location_ids": {"location:0": "private"},
        }
    }
    assert MapAtlasEvidenceSummary.from_snapshot({}) is None
    assert MapAtlasEvidenceSummary.from_snapshot(snapshot).model_dump() == {
        "locations_checked": 1,
        "wiki_pages_used": 2,
        "rag_chunks_used": 3,
        "spatial_facts_used": 4,
        "conflicts": 1,
        "degraded": False,
        "message": "",
    }


def test_spatial_facts_require_canonical_refs_and_conflicts_stay_ambiguous() -> None:
    spatial = {
        "facts": [
            {
                "location_key": "location:0",
                "basis": "explicit",
                "statement": "working",
                "source_keys": ["draft"],
            },
            {
                "location_key": "location:0",
                "basis": "conflicting",
                "statement": "uncertain",
                "source_keys": ["formal"],
            },
            {
                "location_key": "location:0",
                "basis": "explicit",
                "statement": "dropped",
                "source_keys": ["missing"],
            },
        ],
        "source_key_refs": {
            "draft": {
                "source_type": "world_bible_draft",
                "source_status": "working",
                "open_target": {"draft_id": "1"},
            },
            "formal": {
                "source_type": "rag",
                "source_status": "canonical",
                "open_target": {"chunk_id": "2"},
            },
        },
    }
    buckets, sources, invalid = _spatial_fact_buckets(spatial, {"location:0"})
    assert buckets == {
        "supported": [],
        "visual_fill": ["working"],
        "conflicts": ["uncertain"],
    }
    assert len(sources) == 2 and invalid == 1


def test_spatial_fingerprint_changes_with_selected_source_hash() -> None:
    spatial = {
        "location_ids": {"location:0": "a"},
        "location_names": {"location:0": "A"},
        "location_aliases": {"location:0": []},
        "location_source_hashes": {
            "location:0": [{"type": "rag", "id": "1", "status": "canonical", "hash": "a"}]
        },
    }
    changed = {
        **spatial,
        "location_source_hashes": {
            "location:0": [{"type": "rag", "id": "1", "status": "canonical", "hash": "b"}]
        },
    }
    assert _spatial_fingerprint(spatial) != _spatial_fingerprint(changed)


def test_spatial_location_changes_and_planner_context_are_bounded() -> None:
    prior = {
        "spatial_evidence": {
            "location_ids": {"location:0": "a"},
            "location_source_hashes": {"location:0": [{"hash": "old"}]},
        }
    }
    current = {
        "location_ids": {"location:0": "a", "location:1": "b"},
        "location_source_hashes": {
            "location:0": [{"hash": "new"}],
            "location:1": [{"hash": "new"}],
        },
    }
    assert _changed_spatial_location_keys(prior, current) == {"entity:a", "entity:b"}
    facts = [
        {
            "location_key": f"location:{index}",
            "basis": "explicit",
            "statement": "x" * 1000,
        }
        for index in range(20)
        for _ in range(12)
    ]
    context = _spatial_planning_context({"facts": facts})
    assert len(context) <= 40000


def test_map_plan_prompt_keeps_geometry_out_of_frontend_annotations() -> None:
    prompt = _plan_prompt(
        context="北门在王城以东三里",
        schema={},
        style_note=None,
        include_interiors=False,
        prior_atlas=[],
        source_manifest={},
        run_kind="initial",
    )
    assert "annotations 只用于地点或地标名称" in prompt
    assert "不得生成层级、方向、距离、比例或图例标注" in prompt


@pytest.mark.asyncio
async def test_spatial_evidence_batches_twenty_locations_and_marks_bad_sources_degraded(
    db_session, project_novel_id
) -> None:
    from modules.world.models import CoreEntity

    run = MapAtlasRun(
        novel_id=uuid.UUID(project_novel_id), run_kind="initial", status="planning"
    )
    db_session.add(run)
    db_session.add_all(
        [
            CoreEntity(
                novel_id=uuid.UUID(project_novel_id),
                entity_type="location",
                name=f"地点{index}",
                status="canonical",
            )
            for index in range(20)
        ]
    )
    await db_session.flush()

    client = MagicMock()
    client.generate_structured = AsyncMock(return_value=SimpleNamespace(facts=[]))
    bundle = SimpleNamespace(
        rag_chunks=[{"id": "chunk", "text": "证据", "chapter_index": 1}]
    )
    with (
        patch(
            "modules.context.facade.retrieve_planned_context_evidence",
            autospec=True,
            return_value=bundle,
        ),
        patch(
            "modules.world.map_atlas_workflow._require_attempt",
            autospec=True,
            return_value=run,
        ),
        patch("modules.world.map_atlas_workflow.require_active_project", autospec=True),
    ):
        spatial, _manifest = await _spatial_evidence(
            db_session, SimpleNamespace(), run, client
        )
    assert client.generate_structured.await_count == 4
    assert spatial["locations_checked"] == 20
    assert spatial["rag_chunks_used"] == 20
    prior = MapAtlasRun(
        novel_id=uuid.UUID(project_novel_id),
        run_kind="initial",
        status="completed",
        context_snapshot={"spatial_evidence": spatial},
    )
    next_run = MapAtlasRun(
        novel_id=uuid.UUID(project_novel_id), run_kind="update", status="planning"
    )
    db_session.add_all([prior, next_run])
    await db_session.flush()
    with (
        patch(
            "modules.context.facade.retrieve_planned_context_evidence",
            autospec=True,
            return_value=bundle,
        ),
        patch(
            "modules.world.map_atlas_workflow._require_attempt",
            autospec=True,
            return_value=next_run,
        ),
        patch("modules.world.map_atlas_workflow.require_active_project", autospec=True),
    ):
        reused, _manifest = await _spatial_evidence(
            db_session, SimpleNamespace(), next_run, client
        )
    assert client.generate_structured.await_count == 4
    assert reused["message"] == "已复用相同资料的空间线索。"
    prior.context_snapshot = {"spatial_evidence": {**spatial, "degraded": True}}
    fresh_run = MapAtlasRun(
        novel_id=uuid.UUID(project_novel_id), run_kind="update", status="planning"
    )
    db_session.add(fresh_run)
    await db_session.flush()
    with (
        patch(
            "modules.context.facade.retrieve_planned_context_evidence",
            autospec=True,
            return_value=bundle,
        ),
        patch(
            "modules.world.map_atlas_workflow._require_attempt",
            autospec=True,
            return_value=fresh_run,
        ),
        patch("modules.world.map_atlas_workflow.require_active_project", autospec=True),
    ):
        await _spatial_evidence(db_session, SimpleNamespace(), fresh_run, client)
    assert client.generate_structured.await_count == 8

    client.generate_structured.side_effect = RuntimeError("temporary")
    failed_run = MapAtlasRun(
        novel_id=uuid.UUID(project_novel_id), run_kind="update", status="planning"
    )
    db_session.add(failed_run)
    await db_session.flush()
    with (
        patch(
            "modules.context.facade.retrieve_planned_context_evidence",
            autospec=True,
            return_value=bundle,
        ),
        patch(
            "modules.world.map_atlas_workflow._require_attempt",
            autospec=True,
            return_value=failed_run,
        ),
        patch("modules.world.map_atlas_workflow.require_active_project", autospec=True),
    ):
        failed, _manifest = await _spatial_evidence(
            db_session, SimpleNamespace(), failed_run, client
        )
    assert failed["all_batches_failed"] is True
    assert failed["degraded"] is True
    assert failed["message"] == "空间资料提取暂时不可用。"


ALPHA_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DQAAAEgQGALFXOsAAAAABJRU5ErkJggg=="
)


def test_atlas_plan_requires_parent_first_and_twenty_pages() -> None:
    node = {
        "plan_key": "child",
        "parent_plan_key": "missing",
        "title": "北城",
        "level": "city",
        "summary": "城市",
        "visual_brief": "北城的全景地图",
    }
    with pytest.raises(PydanticValidationError):
        AtlasPlan(style_brief="羊皮纸", nodes=[node])
    with pytest.raises(PydanticValidationError):
        AtlasPlan(
            style_brief="羊皮纸",
            nodes=[
                {**node, "plan_key": f"city-{index}", "parent_plan_key": None}
                for index in range(21)
            ],
        )
    assert AtlasPlan(style_brief="羊皮纸", nodes=[]).nodes == []


def test_atlas_plan_rejects_duplicate_canonical_locations() -> None:
    location_id = str(uuid.uuid4())
    with pytest.raises(PydanticValidationError, match="locations must be unique"):
        AtlasPlan(
            style_brief="羊皮纸",
            nodes=[
                {
                    "plan_key": f"place-{index}",
                    "location_entity_id": location_id,
                    "title": f"地点 {index}",
                    "level": "city",
                    "summary": "城市",
                    "visual_brief": "城市地图",
                }
                for index in range(2)
            ],
        )


def test_review_cas_and_derived_reference_limits_are_required() -> None:
    with pytest.raises(PydanticValidationError):
        MapAtlasReviewRequest()
    with pytest.raises(PydanticValidationError):
        MapAtlasDerivedRequest(reference_page_ids=[str(uuid.uuid4()) for _ in range(8)])
    assert (
        len(
            MapAtlasDerivedRequest(
                reference_page_ids=[str(uuid.uuid4()) for _ in range(7)]
            ).reference_page_ids
        )
        == 7
    )


def test_atlas_sources_must_come_from_compiled_project_context() -> None:
    novel_id = str(uuid.uuid4())
    plan = AtlasPlan(
        style_brief="羊皮纸",
        nodes=[
            {
                "plan_key": "world",
                "title": "九州",
                "level": "world",
                "summary": "世界",
                "visual_brief": "九州世界地图",
                "sources": [
                    {
                        "source_type": "world_bible_page",
                        "title": "地理总览",
                        "summary": "九州分为三域",
                        "open_target": {
                            "kind": "world_bible_page",
                            "page_id": "page-1",
                            "novel_id": novel_id,
                        },
                    }
                ],
            }
        ],
    )

    manifest = _atlas_source_manifest(
        {
            "world_bible_page": [
                {
                    "source_id": "page-1",
                    "status": "canonical",
                    "label": "地理总览",
                    "summary": "九州分为三域",
                }
            ]
        }
    )
    _validate_plan_sources(plan, novel_id, manifest)
    assert len(plan.nodes[0].sources[0].source_hash or "") == 64

    plan.nodes[0].sources[0].open_target["page_id"] = "foreign-page"
    with pytest.raises(ValueError, match="compiled context"):
        _validate_plan_sources(plan, novel_id, manifest)


def test_atlas_sources_cannot_reuse_an_id_from_another_source_bucket() -> None:
    novel_id = str(uuid.uuid4())
    plan = AtlasPlan(
        style_brief="羊皮纸",
        nodes=[
            {
                "plan_key": "world",
                "title": "九州",
                "level": "world",
                "summary": "世界",
                "visual_brief": "九州世界地图",
                "sources": [
                    {
                        "source_type": "world_bible_page",
                        "title": "地理总览",
                        "summary": "九州分为三域",
                        "open_target": {
                            "kind": "world_bible_page",
                            "page_id": "shared-id",
                            "novel_id": novel_id,
                        },
                    }
                ],
            }
        ],
    )

    with pytest.raises(ValueError, match="compiled context"):
        _validate_plan_sources(
            plan,
            novel_id,
            _atlas_source_manifest(
                {"entity": [{"source_id": "shared-id", "status": "canonical"}]}
            ),
        )


def test_atlas_source_catalog_is_canonical_openable_and_marks_working() -> None:
    catalog = _atlas_source_manifest(
        {
            "world_bible_page": [
                {
                    "source_id": "page-1",
                    "label": "正式地理",
                    "summary": "正式摘要",
                    "status": "canonical",
                }
            ],
            "world_bible_draft": [
                {
                    "source_id": "draft-1",
                    "label": "港口工作稿",
                    "summary": "未发布内容",
                    "status": "working",
                }
            ],
            "rag": [
                {
                    "source_id": "chunk-1",
                    "label": "第七章正文",
                    "summary": "港口位于北岸",
                    "chapter_index": "7",
                    "status": "canonical",
                }
            ],
            "relation": [{"source_id": "relation-1", "status": "canonical"}],
            "character_knowledge": [{"source_id": "knowledge-1", "status": "canonical"}],
            "entity": [{"source_id": "candidate-1", "status": "candidate"}],
            "project": [{"source_id": "project-1"}],
        }
    )

    assert catalog["world_bible_page"][0]["open_target"] == {
        "kind": "world_bible_page",
        "page_id": "page-1",
    }
    assert catalog["world_bible_draft"][0]["status"] == "working"
    assert catalog["rag"][0]["open_target"] == {
        "kind": "writing",
        "chapter_index": "7",
        "chunk_id": "chunk-1",
    }
    assert not {"project", "relation", "character_knowledge", "entity"}.intersection(
        catalog
    )

    plan = AtlasPlan(
        style_brief="羊皮纸",
        nodes=[
            {
                "plan_key": "world",
                "title": "九州",
                "level": "world",
                "summary": "世界",
                "visual_brief": "九州世界地图",
                "evidence": {"supported": ["正式资料如此记载"]},
                "sources": [
                    {
                        "source_type": "world_bible_page",
                        "title": "伪造标题",
                        "summary": "伪造摘要",
                        "open_target": {
                            "kind": "world_bible_page",
                            "page_id": "page-1",
                        },
                    }
                ],
            }
        ],
    )
    _validate_plan_sources(plan, str(uuid.uuid4()), catalog)
    source = plan.nodes[0].sources[0]
    assert (source.title, source.summary) == ("正式地理", "正式摘要")


def test_formal_evidence_requires_formal_source_and_new_sources_use_prior_run() -> None:
    with pytest.raises(PydanticValidationError, match="retained source"):
        AtlasPlan(
            style_brief="atlas",
            nodes=[
                {
                    "plan_key": "world",
                    "title": "world",
                    "level": "world",
                    "summary": "world",
                    "visual_brief": "world map",
                    "evidence": {"supported": ["unsupported claim"]},
                }
            ],
        )

    working_catalog = _atlas_source_manifest(
        {
            "world_bible_draft": [
                {
                    "source_id": "draft-1",
                    "label": "工作稿",
                    "status": "working",
                }
            ]
        }
    )
    working_plan = AtlasPlan(
        style_brief="atlas",
        nodes=[
            {
                "plan_key": "world",
                "title": "world",
                "level": "world",
                "summary": "world",
                "visual_brief": "world map",
                "evidence": {"supported": ["working-only claim"]},
                "sources": [
                    {
                        "source_type": "world_bible_draft",
                        "title": "工作稿",
                        "summary": "未发布",
                        "open_target": {
                            "kind": "world_bible_draft",
                            "draft_id": "draft-1",
                        },
                    }
                ],
            }
        ],
    )
    with pytest.raises(ValueError, match="sole formal support"):
        _validate_plan_sources(working_plan, str(uuid.uuid4()), working_catalog)

    prior_manifest = _atlas_source_manifest(
        {
            "world_bible_page": [
                {
                    "source_id": "page-1",
                    "source_hash": "a" * 64,
                    "status": "canonical",
                }
            ]
        }
    )
    current_manifest = _atlas_source_manifest(
        {
            "world_bible_page": [
                {
                    "source_id": "page-1",
                    "source_hash": "b" * 64,
                    "status": "canonical",
                },
                {"source_id": "page-2", "status": "published"},
            ],
            "world_bible_draft": [{"source_id": "draft-2", "status": "working"}],
        }
    )
    assert _new_source_identities(prior_manifest, current_manifest) == {
        ("world_bible_page", "page-1"),
        ("world_bible_page", "page-2"),
    }

    new_path = AtlasPlan(
        style_brief="atlas",
        nodes=[
            {
                "plan_key": "new-region",
                "title": "new region",
                "level": "region",
                "summary": "new region",
                "visual_brief": "new region map",
                "sources": [
                    {
                        "source_type": "world_bible_page",
                        "title": "ignored",
                        "summary": "ignored",
                        "open_target": {
                            "kind": "world_bible_page",
                            "page_id": "page-2",
                        },
                    }
                ],
            }
        ],
    )
    _validate_plan_sources(new_path, str(uuid.uuid4()), current_manifest)
    _validate_update_targets(
        new_path,
        [],
        changed_semantic_keys=set(),
        missing_location_ids=set(),
        new_source_identities=_new_source_identities(prior_manifest, current_manifest),
    )
    new_path.nodes[0].sources[0].source_status = "working"
    with pytest.raises(ValueError, match="newly retained source"):
        _validate_update_targets(
            new_path,
            [],
            changed_semantic_keys=set(),
            missing_location_ids=set(),
            new_source_identities=_new_source_identities(
                prior_manifest, current_manifest
            ),
        )


def test_update_rejects_unchanged_existing_node() -> None:
    novel_id = str(uuid.uuid4())
    source_hash = "a" * 64
    source = {
        "source_type": "world_bible_page",
        "title": "地理总览",
        "summary": "九州分为三域",
        "open_target": {
            "kind": "world_bible_page",
            "page_id": "page-1",
            "novel_id": novel_id,
        },
        "source_hash": source_hash,
    }
    plan = AtlasPlan(
        style_brief="羊皮纸",
        nodes=[
            {
                "plan_key": "world",
                "title": "九州",
                "level": "world",
                "summary": "世界",
                "visual_brief": "九州世界地图",
                "sources": [source],
            }
        ],
    )
    prior = [
        {
            "semantic_key": (
                f"path:root:{hashlib.sha256('九州'.encode()).hexdigest()[:20]}"
            ),
            "sources": [source],
        }
    ]
    manifest = _atlas_source_manifest(
        {
            "world_bible_page": [
                {
                    "source_id": "page-1",
                    "source_hash": source_hash,
                    "status": "canonical",
                }
            ]
        }
    )
    _validate_plan_sources(plan, novel_id, manifest)
    with pytest.raises(ValueError, match="unchanged"):
        _validate_update_targets(
            plan,
            prior,
            changed_semantic_keys=set(),
            missing_location_ids=set(),
        )

    manifest["world_bible_page"][0]["source_hash"] = "b" * 64
    _validate_plan_sources(plan, novel_id, manifest)
    _validate_update_targets(
        plan,
        prior,
        changed_semantic_keys={prior[0]["semantic_key"]},
        missing_location_ids=set(),
    )


@pytest.mark.asyncio
async def test_previous_manifest_ignores_failed_planning_runs(
    db_session, test_project_id
) -> None:
    started_at = datetime(2026, 8, 12, tzinfo=UTC)
    previous = MapAtlasRun(
        novel_id=uuid.UUID(test_project_id),
        run_kind="initial",
        status="completed",
        source_manifest=[
            {
                "source_type": "world_bible_page",
                "source_id": "page-1",
                "status": "canonical",
            }
        ],
        created_at=started_at,
    )
    failed = MapAtlasRun(
        novel_id=uuid.UUID(test_project_id),
        run_kind="update",
        status="failed",
        source_manifest=[
            {
                "source_type": "world_bible_page",
                "source_id": "failed-page",
                "status": "canonical",
            }
        ],
        created_at=started_at + timedelta(minutes=1),
    )
    current = MapAtlasRun(
        novel_id=uuid.UUID(test_project_id),
        run_kind="update",
        status="planning",
        created_at=started_at + timedelta(minutes=2),
    )
    db_session.add_all([previous, failed, current])
    await db_session.flush()

    manifest = await _previous_source_manifest(db_session, current)

    assert manifest["world_bible_page"][0]["source_id"] == "page-1"


@pytest.mark.asyncio
async def test_initial_plan_fails_without_retained_atlas_sources(
    db_session, test_project_id
) -> None:
    run = MapAtlasRun(
        novel_id=uuid.UUID(test_project_id),
        run_kind="initial",
        status="planning",
    )
    db_session.add(run)
    await db_session.flush()
    background = {
        "rendered_context": "项目风格不是可引用地图资料",
        "context_usage": {"included_asset_manifest": {}},
    }

    with (
        patch(
            "modules.world.map_atlas_workflow._compile_context",
            autospec=True,
            return_value=background,
        ),
        patch(
            "modules.world.map_atlas_workflow._require_attempt",
            autospec=True,
            return_value=run,
        ),
        patch(
            "modules.world.map_atlas_workflow.restore_project_llm_execution_settings",
            autospec=True,
        ) as restore_settings,
    ):
        await _plan(db_session, SimpleNamespace(), run)

    await db_session.refresh(run)
    assert (run.status, run.error_code, run.planned_page_count) == (
        "failed",
        "insufficient_sources",
        0,
    )
    restore_settings.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "error_code"),
    [
        ("generating", None),
        ("paused", None),
        ("partial", "retry_requires_confirmation"),
        ("partial", "worker_interrupted"),
    ],
)
async def test_create_run_reuses_the_project_unresolved_run(
    db_session,
    test_project_id,
    status,
    error_code,
) -> None:
    active = MapAtlasRun(
        novel_id=uuid.UUID(test_project_id),
        run_kind="initial",
        status=status,
        error_code=error_code,
    )
    db_session.add(active)
    await db_session.flush()
    with (
        patch(
            "modules.world.map_atlas_service.build_project_image_execution_snapshot",
            autospec=True,
        ) as image_snapshot,
        patch(
            "modules.world.map_atlas_service.enqueue_coalesced_task",
            autospec=True,
        ) as enqueue,
    ):
        result = await MapAtlasService().create_run(
            db_session,
            test_project_id,
            MapAtlasRunCreate(),
        )
    assert result["id"] == str(active.id)
    image_snapshot.assert_not_awaited()
    enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_run_reuses_partial_run_with_recoverable_page(
    db_session, test_project_id
) -> None:
    run = MapAtlasRun(
        novel_id=uuid.UUID(test_project_id),
        run_kind="initial",
        status="partial",
        error_code="map_atlas_workflow_failed",
    )
    db_session.add(run)
    await db_session.flush()
    node = MapAtlasNode(
        novel_id=run.novel_id,
        created_by_run_id=run.id,
        semantic_key="world",
        title="世界",
        level="world",
    )
    db_session.add(node)
    await db_session.flush()
    db_session.add(
        MapAtlasPage(
            novel_id=run.novel_id,
            run_id=run.id,
            node_id=node.id,
            generation_status="retry_requires_confirmation",
            title="世界",
            visual_brief="世界地图",
            prompt="no text",
        )
    )
    await db_session.flush()

    with (
        patch(
            "modules.world.map_atlas_service.build_project_image_execution_snapshot",
            autospec=True,
        ) as image_snapshot,
        patch(
            "modules.world.map_atlas_service.enqueue_coalesced_task",
            autospec=True,
        ) as enqueue,
    ):
        result = await MapAtlasService().create_run(
            db_session, test_project_id, MapAtlasRunCreate()
        )

    assert result["id"] == str(run.id)
    image_snapshot.assert_not_awaited()
    enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_run_allows_new_run_after_ordinary_partial(
    db_session, test_project_id
) -> None:
    old = MapAtlasRun(
        novel_id=uuid.UUID(test_project_id),
        run_kind="initial",
        status="partial",
        error_code="moderation_blocked",
    )
    db_session.add(old)
    await db_session.flush()
    task_id = str(uuid.uuid4())
    with (
        patch(
            "modules.world.map_atlas_service.build_project_image_execution_snapshot",
            autospec=True,
            return_value={"snapshot_hash": "image"},
        ),
        patch(
            "modules.world.map_atlas_service.build_project_llm_execution_snapshot",
            autospec=True,
            return_value={"snapshot_hash": "llm"},
        ),
        patch(
            "modules.world.map_atlas_service.enqueue_coalesced_task",
            autospec=True,
            return_value=SimpleNamespace(task_id=task_id),
        ),
    ):
        result = await MapAtlasService().create_run(
            db_session, test_project_id, MapAtlasRunCreate()
        )

    assert result["id"] != str(old.id)
    assert result["status"] == "planning"


@pytest.mark.asyncio
async def test_reconciler_preserves_uploaded_page_and_fences_unknown_provider(
    db_session, test_project_id
) -> None:
    task_id = uuid.uuid4()
    run = MapAtlasRun(
        novel_id=uuid.UUID(test_project_id),
        task_id=task_id,
        run_kind="initial",
        status="generating",
    )
    db_session.add(run)
    await db_session.flush()
    node = MapAtlasNode(
        novel_id=run.novel_id,
        created_by_run_id=run.id,
        semantic_key="world",
        title="世界",
        level="world",
    )
    db_session.add(node)
    await db_session.flush()
    uploaded = MapAtlasPage(
        novel_id=run.novel_id,
        run_id=run.id,
        node_id=node.id,
        generation_status="uploaded",
        title="世界",
        visual_brief="世界地图",
        prompt="no text",
        object_key=page_object_key(test_project_id, str(uuid.uuid4())),
    )
    unknown = MapAtlasPage(
        novel_id=run.novel_id,
        run_id=run.id,
        node_id=node.id,
        generation_status="provider_in_flight",
        title="北境",
        visual_brief="北境地图",
        prompt="no text",
    )
    db_session.add_all([uploaded, unknown])
    await db_session.flush()
    with patch(
        "modules.world.map_atlas_workflow.list_task_lifecycle_contracts",
        autospec=True,
        return_value={},
    ):
        assert await reconcile_map_atlas_task_owners(db_session) == 1
    assert uploaded.generation_status == "review_ready"
    assert unknown.generation_status == "retry_requires_confirmation"
    assert run.status == "partial"
    assert run.completed_page_count == 1


@pytest.mark.asyncio
async def test_review_tree_and_history_expose_manual_retry_and_rejections(
    db_session, test_project_id
) -> None:
    novel_id = uuid.UUID(test_project_id)
    run = MapAtlasRun(
        novel_id=novel_id,
        run_kind="initial",
        status="partial",
    )
    db_session.add(run)
    await db_session.flush()
    node = MapAtlasNode(
        novel_id=novel_id,
        created_by_run_id=run.id,
        semantic_key="world",
        title="世界",
        level="world",
    )
    db_session.add(node)
    await db_session.flush()
    unknown = MapAtlasPage(
        novel_id=novel_id,
        run_id=run.id,
        node_id=node.id,
        generation_status="retry_requires_confirmation",
        title="世界",
        visual_brief="世界地图",
        prompt="no text",
    )
    rejected = MapAtlasPage(
        novel_id=novel_id,
        run_id=run.id,
        node_id=node.id,
        generation_status="review_ready",
        review_status="rejected",
        title="旧候选",
        visual_brief="世界地图",
        prompt="no text",
    )
    db_session.add_all([unknown, rejected])
    await db_session.flush()

    service = MapAtlasService()
    tree = await service.get_tree(
        db_session,
        test_project_id,
        run_id=str(run.id),
    )
    assert tree["total_pages"] == 2
    history = await service.get_archived_pages(db_session, test_project_id)
    assert [item["id"] for item in history] == [str(rejected.id)]


@pytest.mark.asyncio
async def test_page_history_keeps_unresolved_candidates_from_older_runs(
    db_session, test_project_id, async_client
) -> None:
    novel_id = uuid.UUID(test_project_id)
    started_at = datetime(2026, 8, 12, tzinfo=UTC)
    old_run = MapAtlasRun(
        novel_id=novel_id,
        run_kind="initial",
        status="partial",
        created_at=started_at,
    )
    latest_run = MapAtlasRun(
        novel_id=novel_id,
        run_kind="update",
        status="review_ready",
        created_at=started_at + timedelta(minutes=1),
    )
    db_session.add_all([old_run, latest_run])
    await db_session.flush()
    node = MapAtlasNode(
        novel_id=novel_id,
        created_by_run_id=old_run.id,
        semantic_key="world",
        title="世界",
        level="world",
    )
    db_session.add(node)
    await db_session.flush()
    old_pages = [
        MapAtlasPage(
            novel_id=novel_id,
            run_id=old_run.id,
            node_id=node.id,
            generation_status=status,
            title=status,
            visual_brief="世界地图",
            prompt="no text",
        )
        for status in (
            "review_ready",
            "failed",
            "retry_requires_confirmation",
            "prepared",
        )
    ]
    latest_page = MapAtlasPage(
        novel_id=novel_id,
        run_id=latest_run.id,
        node_id=node.id,
        generation_status="review_ready",
        title="latest",
        visual_brief="世界地图",
        prompt="no text",
    )
    db_session.add_all([*old_pages, latest_page])
    await db_session.flush()

    history = await MapAtlasService().get_archived_pages(db_session, test_project_id)

    assert {item["id"] for item in history} == {str(page.id) for page in old_pages[:3]}
    assert {item["run_id"] for item in history} == {str(old_run.id)}

    response = await async_client.get(
        f"/api/world/map-atlas/{test_project_id}/pages/history"
    )
    assert response.status_code == 200
    assert {item["id"] for item in response.json()} == {
        str(page.id) for page in old_pages[:3]
    }


def test_attempt_object_key_is_unique_per_task_attempt() -> None:
    novel_id = uuid.uuid4()
    run = SimpleNamespace(novel_id=novel_id)
    page = SimpleNamespace(id=uuid.uuid4())
    first = _attempt_object_key(run, page, SimpleNamespace(id=uuid.uuid4(), attempt=1))
    second = _attempt_object_key(run, page, SimpleNamespace(id=uuid.uuid4(), attempt=1))
    assert first != second
    assert first.endswith("/image.png")
    assert "/attempts/" in first


@pytest.mark.asyncio
async def test_parent_reference_does_not_overflow_eight_explicit_references() -> None:
    db = AsyncMock()
    db.scalar.side_effect = [uuid.uuid4(), SimpleNamespace(id=uuid.uuid4())]
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db.execute.return_value = result
    page = SimpleNamespace(
        node_id=uuid.uuid4(),
        novel_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        reference_page_ids=[str(uuid.uuid4()) for _ in range(8)],
    )

    assert await _reference_images(db, MagicMock(spec=MapAtlasStorage), page) == []
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_workflow_rejects_more_than_eight_stored_references() -> None:
    db = AsyncMock()
    db.scalar.return_value = None
    page = SimpleNamespace(
        node_id=uuid.uuid4(),
        novel_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        reference_page_ids=[str(uuid.uuid4()) for _ in range(9)],
    )

    with pytest.raises(ValueError, match="at most 8 references"):
        await _reference_images(db, MagicMock(spec=MapAtlasStorage), page)

    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_workflow_attempt_must_still_own_the_run(
    db_session, test_project_id
) -> None:
    stale_id = enqueue_task(
        db_session,
        "map_atlas_generate",
        meta={"run_id": str(uuid.uuid4())},
        novel_id=test_project_id,
    )
    current_id = enqueue_task(
        db_session,
        "map_atlas_generate",
        meta={"run_id": str(uuid.uuid4())},
        novel_id=test_project_id,
    )
    await db_session.flush()
    stale = await db_session.get(AsyncTask, uuid.UUID(stale_id))
    assert stale is not None
    stale.mark_running()
    run = MapAtlasRun(
        novel_id=uuid.UUID(test_project_id),
        task_id=uuid.UUID(current_id),
        run_kind="initial",
        status="generating",
    )
    db_session.add(run)
    await db_session.flush()

    with pytest.raises(asyncio.CancelledError):
        await _require_attempt(
            db_session,
            stale,
            test_project_id,
            str(run.id),
        )


@pytest.mark.asyncio
async def test_adopt_is_additive_and_adopts_ancestors(
    db_session, test_project_id
) -> None:
    novel_id = uuid.UUID(test_project_id)
    run = MapAtlasRun(novel_id=novel_id, run_kind="initial", status="review_ready")
    db_session.add(run)
    await db_session.flush()
    parent = MapAtlasNode(
        novel_id=novel_id,
        created_by_run_id=run.id,
        semantic_key="world",
        title="世界",
        level="world",
        status="provisional",
    )
    db_session.add(parent)
    await db_session.flush()
    child = MapAtlasNode(
        novel_id=novel_id,
        created_by_run_id=run.id,
        parent_id=parent.id,
        semantic_key="world/city",
        title="北城",
        level="city",
        status="provisional",
    )
    db_session.add(child)
    await db_session.flush()
    pages = [
        MapAtlasPage(
            novel_id=novel_id,
            run_id=run.id,
            node_id=child.id,
            generation_status="review_ready",
            title="北城",
            visual_brief="城市地图",
            prompt="no text",
            evidence={"conflicts": ["两处道路记载不一致"]},
            object_key=page_object_key(test_project_id, str(uuid.uuid4())),
        )
        for _ in range(2)
    ]
    db_session.add_all(pages)
    await db_session.flush()

    service = MapAtlasService()
    with pytest.raises(ConflictError):
        await service.review_page(
            db_session,
            test_project_id,
            str(pages[0].id),
            "adopt",
            MapAtlasReviewRequest(expected_updated_at=pages[0].updated_at),
        )
    await service.review_page(
        db_session,
        test_project_id,
        str(pages[0].id),
        "adopt",
        MapAtlasReviewRequest(
            expected_updated_at=pages[0].updated_at,
            confirm_conflicts=True,
        ),
    )
    pages[1].evidence = {}
    await db_session.flush()
    await service.review_page(
        db_session,
        test_project_id,
        str(pages[1].id),
        "adopt",
        MapAtlasReviewRequest(expected_updated_at=pages[1].updated_at),
    )
    assert parent.status == child.status == "adopted"
    tree = await service.get_tree(db_session, test_project_id)
    assert tree["total_pages"] == 2

    await service.review_page(
        db_session,
        test_project_id,
        str(pages[0].id),
        "archive",
        MapAtlasReviewRequest(expected_updated_at=pages[0].updated_at),
    )
    tree = await service.get_tree(db_session, test_project_id)
    assert tree["total_pages"] == 1
    history = await service.get_archived_pages(db_session, test_project_id)
    assert [item["id"] for item in history] == [str(pages[0].id)]


async def _node_proposal_scenario(db_session, test_project_id):
    novel_id = uuid.UUID(test_project_id)
    original_run = MapAtlasRun(
        novel_id=novel_id,
        run_kind="initial",
        status="completed",
    )
    update_run = MapAtlasRun(
        novel_id=novel_id,
        run_kind="update",
        status="review_ready",
    )
    db_session.add_all([original_run, update_run])
    await db_session.flush()
    root = MapAtlasNode(
        novel_id=novel_id,
        created_by_run_id=original_run.id,
        semantic_key="world",
        title="世界",
        level="world",
        status="adopted",
    )
    old_parent = MapAtlasNode(
        novel_id=novel_id,
        created_by_run_id=original_run.id,
        semantic_key="west",
        title="西境",
        level="region",
        status="adopted",
        parent_id=None,
    )
    new_parent = MapAtlasNode(
        novel_id=novel_id,
        created_by_run_id=original_run.id,
        semantic_key="east",
        title="东境",
        level="region",
        status="adopted",
        parent_id=root.id,
        summary="旧东境",
        sort_order=1,
    )
    db_session.add_all([root, old_parent, new_parent])
    await db_session.flush()
    old_parent.parent_id = root.id
    new_parent.parent_id = root.id
    city = MapAtlasNode(
        novel_id=novel_id,
        created_by_run_id=original_run.id,
        semantic_key="entity:city",
        title="旧城",
        level="city",
        status="adopted",
        parent_id=old_parent.id,
        summary="旧摘要",
        sort_order=2,
    )
    db_session.add(city)
    await db_session.flush()
    parent_page = MapAtlasPage(
        novel_id=novel_id,
        run_id=update_run.id,
        node_id=new_parent.id,
        generation_status="review_ready",
        title="新东境",
        visual_brief="更新后的东境",
        prompt="no text",
        node_proposal={
            "node_id": str(new_parent.id),
            "parent_id": str(root.id),
            "title": "新东境",
            "level": "region",
            "summary": "新东境摘要",
            "sort_order": 4,
        },
    )
    city_page = MapAtlasPage(
        novel_id=novel_id,
        run_id=update_run.id,
        node_id=city.id,
        generation_status="review_ready",
        title="新城",
        visual_brief="更新后的城市",
        prompt="no text",
        node_proposal={
            "node_id": str(city.id),
            "parent_id": str(new_parent.id),
            "title": "新城",
            "level": "city",
            "summary": "新摘要",
            "sort_order": 7,
        },
    )
    db_session.add_all([parent_page, city_page])
    await db_session.flush()
    return SimpleNamespace(
        root=root,
        old_parent=old_parent,
        new_parent=new_parent,
        city=city,
        parent_page=parent_page,
        city_page=city_page,
    )


@pytest.mark.asyncio
async def test_reject_keeps_reused_node_metadata_and_parent_unchanged(
    db_session,
    test_project_id,
) -> None:
    scenario = await _node_proposal_scenario(db_session, test_project_id)

    await MapAtlasService().review_page(
        db_session,
        test_project_id,
        str(scenario.city_page.id),
        "reject",
        MapAtlasReviewRequest(expected_updated_at=scenario.city_page.updated_at),
    )

    assert scenario.city.parent_id == scenario.old_parent.id
    assert (scenario.city.title, scenario.city.summary, scenario.city.sort_order) == (
        "旧城",
        "旧摘要",
        2,
    )
    assert (
        scenario.new_parent.title,
        scenario.new_parent.summary,
        scenario.new_parent.sort_order,
    ) == ("东境", "旧东境", 1)


@pytest.mark.asyncio
async def test_adopt_applies_reused_node_and_run_ancestor_proposals(
    db_session,
    test_project_id,
) -> None:
    scenario = await _node_proposal_scenario(db_session, test_project_id)

    await MapAtlasService().review_page(
        db_session,
        test_project_id,
        str(scenario.city_page.id),
        "adopt",
        MapAtlasReviewRequest(expected_updated_at=scenario.city_page.updated_at),
    )

    assert scenario.city.parent_id == scenario.new_parent.id
    assert (scenario.city.title, scenario.city.summary, scenario.city.sort_order) == (
        "新城",
        "新摘要",
        0,
    )
    assert (
        scenario.new_parent.title,
        scenario.new_parent.summary,
        scenario.new_parent.sort_order,
    ) == ("新东境", "新东境摘要", 1)
    assert scenario.parent_page.review_status == "candidate"
    assert scenario.city_page.review_status == "adopted"


@pytest.mark.asyncio
async def test_adopting_child_bases_remaining_provisional_parent_proposal(
    db_session, test_project_id
) -> None:
    novel_id = uuid.UUID(test_project_id)
    run = MapAtlasRun(novel_id=novel_id, run_kind="initial", status="review_ready")
    db_session.add(run)
    await db_session.flush()
    root = MapAtlasNode(
        novel_id=novel_id,
        created_by_run_id=run.id,
        semantic_key="world:existing",
        title="世界",
        level="world",
        status="adopted",
    )
    db_session.add(root)
    await db_session.flush()
    sibling = MapAtlasNode(
        novel_id=novel_id,
        created_by_run_id=run.id,
        semantic_key="region:existing",
        title="已有地区",
        level="region",
        status="adopted",
        parent_id=root.id,
        sort_order=0,
    )
    parent = MapAtlasNode(
        novel_id=novel_id,
        created_by_run_id=run.id,
        semantic_key="path:parent",
        title="新地区",
        level="region",
        status="provisional",
        parent_id=root.id,
        sort_order=1,
    )
    db_session.add_all([sibling, parent])
    await db_session.flush()
    child = MapAtlasNode(
        novel_id=novel_id,
        created_by_run_id=run.id,
        semantic_key="path:parent:child",
        title="新城",
        level="city",
        status="provisional",
        parent_id=parent.id,
    )
    db_session.add(child)
    await db_session.flush()

    def proposal(node, parent_id, order):
        return {
            "node_id": str(node.id),
            "parent_id": str(parent_id),
            "title": node.title,
            "level": node.level,
            "sort_order": order,
        }

    parent_page = MapAtlasPage(
        novel_id=novel_id,
        run_id=run.id,
        node_id=parent.id,
        generation_status="review_ready",
        title=parent.title,
        visual_brief="brief",
        prompt="prompt",
        node_proposal=proposal(parent, root.id, 0),
    )
    child_page = MapAtlasPage(
        novel_id=novel_id,
        run_id=run.id,
        node_id=child.id,
        generation_status="review_ready",
        title=child.title,
        visual_brief="brief",
        prompt="prompt",
        node_proposal=proposal(child, parent.id, 0),
    )
    db_session.add_all([parent_page, child_page])
    await db_session.flush()
    service = MapAtlasService()
    await service.review_page(
        db_session,
        test_project_id,
        str(child_page.id),
        "adopt",
        MapAtlasReviewRequest(expected_updated_at=child_page.updated_at),
    )
    assert parent_page.node_proposal["base_node_updated_at"]
    await service.update_node(
        db_session,
        test_project_id,
        str(parent.id),
        MapAtlasNodeUpdate(before_node_id=None, expected_updated_at=parent.updated_at),
    )
    moved_order = parent.sort_order
    with pytest.raises(ConflictError, match="层级已变化"):
        await service.review_page(
            db_session,
            test_project_id,
            str(parent_page.id),
            "adopt",
            MapAtlasReviewRequest(expected_updated_at=parent_page.updated_at),
        )
    assert parent.sort_order == moved_order


@pytest.mark.asyncio
async def test_adopt_rejects_proposed_parent_cycle(
    db_session,
    test_project_id,
) -> None:
    scenario = await _node_proposal_scenario(db_session, test_project_id)
    scenario.city_page.node_proposal = {
        **scenario.city_page.node_proposal,
        "parent_id": str(scenario.city.id),
    }
    await db_session.flush()

    with pytest.raises(ConflictError, match="循环"):
        await MapAtlasService().review_page(
            db_session,
            test_project_id,
            str(scenario.city_page.id),
            "adopt",
            MapAtlasReviewRequest(expected_updated_at=scenario.city_page.updated_at),
        )

    assert scenario.city.parent_id == scenario.old_parent.id
    assert scenario.city_page.review_status == "candidate"


@pytest.mark.asyncio
async def test_review_page_enforces_cas_and_exact_state_transitions(
    db_session, test_project_id
) -> None:
    novel_id = uuid.UUID(test_project_id)
    run = MapAtlasRun(novel_id=novel_id, run_kind="initial", status="review_ready")
    db_session.add(run)
    await db_session.flush()
    node = MapAtlasNode(
        novel_id=novel_id,
        created_by_run_id=run.id,
        semantic_key="world",
        title="世界",
        level="world",
    )
    db_session.add(node)
    await db_session.flush()
    candidate = MapAtlasPage(
        novel_id=novel_id,
        run_id=run.id,
        node_id=node.id,
        generation_status="review_ready",
        title="世界",
        visual_brief="世界地图",
        prompt="no text",
    )
    failed_candidate = MapAtlasPage(
        novel_id=novel_id,
        run_id=run.id,
        node_id=node.id,
        generation_status="failed",
        title="世界备选",
        visual_brief="世界地图",
        prompt="no text",
    )
    db_session.add_all([candidate, failed_candidate])
    await db_session.flush()
    stale_version = candidate.updated_at
    candidate.review_note = "other writer"
    await db_session.flush()
    service = MapAtlasService()

    with pytest.raises(ConflictError, match="已在别处更新"):
        await service.review_page(
            db_session,
            test_project_id,
            str(candidate.id),
            "adopt",
            MapAtlasReviewRequest(expected_updated_at=stale_version),
        )

    await service.review_page(
        db_session,
        test_project_id,
        str(candidate.id),
        "adopt",
        MapAtlasReviewRequest(expected_updated_at=candidate.updated_at),
    )
    for action in ("adopt", "reject"):
        with pytest.raises(ConflictError):
            await service.review_page(
                db_session,
                test_project_id,
                str(candidate.id),
                action,
                MapAtlasReviewRequest(expected_updated_at=candidate.updated_at),
            )
    await service.review_page(
        db_session,
        test_project_id,
        str(candidate.id),
        "archive",
        MapAtlasReviewRequest(expected_updated_at=candidate.updated_at),
    )
    await service.review_page(
        db_session,
        test_project_id,
        str(candidate.id),
        "restore",
        MapAtlasReviewRequest(expected_updated_at=candidate.updated_at),
    )
    with pytest.raises(ConflictError):
        await service.review_page(
            db_session,
            test_project_id,
            str(candidate.id),
            "restore",
            MapAtlasReviewRequest(expected_updated_at=candidate.updated_at),
        )

    with pytest.raises(ConflictError):
        await service.review_page(
            db_session,
            test_project_id,
            str(failed_candidate.id),
            "reject",
            MapAtlasReviewRequest(expected_updated_at=failed_candidate.updated_at),
        )
    failed_candidate.generation_status = "review_ready"
    await db_session.flush()
    await service.review_page(
        db_session,
        test_project_id,
        str(failed_candidate.id),
        "reject",
        MapAtlasReviewRequest(expected_updated_at=failed_candidate.updated_at),
    )
    with pytest.raises(ConflictError):
        await service.review_page(
            db_session,
            test_project_id,
            str(failed_candidate.id),
            "adopt",
            MapAtlasReviewRequest(expected_updated_at=failed_candidate.updated_at),
        )


@pytest.mark.asyncio
async def test_mismatched_page_keys_never_reach_s3_or_create_a_derived_page(
    db_session,
    test_project_id,
) -> None:
    novel_id = uuid.UUID(test_project_id)
    run = MapAtlasRun(novel_id=novel_id, run_kind="initial", status="review_ready")
    db_session.add(run)
    await db_session.flush()
    node = MapAtlasNode(
        novel_id=novel_id,
        created_by_run_id=run.id,
        semantic_key="world",
        title="世界",
        level="world",
    )
    db_session.add(node)
    await db_session.flush()
    source_id, reference_id = uuid.uuid4(), uuid.uuid4()
    source = MapAtlasPage(
        id=source_id,
        novel_id=novel_id,
        run_id=run.id,
        node_id=node.id,
        generation_status="review_ready",
        title="世界",
        visual_brief="世界地图",
        prompt="no text",
        object_key=page_object_key(test_project_id, str(source_id)),
    )
    mismatched = MapAtlasPage(
        id=reference_id,
        novel_id=novel_id,
        run_id=run.id,
        node_id=node.id,
        generation_status="review_ready",
        title="异常参考",
        visual_brief="参考地图",
        prompt="no text",
        object_key=page_object_key(str(uuid.uuid4()), str(reference_id)),
    )
    db_session.add_all([source, mismatched])
    await db_session.flush()
    storage = MagicMock(spec=MapAtlasStorage)
    storage.get_png = AsyncMock()

    service = MapAtlasService(storage=storage)
    with pytest.raises(ValueError, match="owner mismatch"):
        await service.read_page_image(
            db_session,
            test_project_id,
            str(reference_id),
        )
    storage.iter_png_chunks.assert_not_called()

    run_count = await db_session.scalar(select(func.count(MapAtlasRun.id)))
    page_count = await db_session.scalar(select(func.count(MapAtlasPage.id)))
    with pytest.raises(ValueError, match="owner mismatch"):
        await service.create_derived_page(
            db_session,
            test_project_id,
            str(source_id),
            MapAtlasDerivedRequest(
                instruction="保持风格",
                reference_page_ids=[str(reference_id)],
            ),
            mode="edit",
        )
    assert await db_session.scalar(select(func.count(MapAtlasRun.id))) == run_count
    assert await db_session.scalar(select(func.count(MapAtlasPage.id))) == page_count

    candidate = MapAtlasPage(
        novel_id=novel_id,
        run_id=run.id,
        node_id=node.id,
        title="派生候选",
        visual_brief="候选地图",
        prompt="no text",
        reference_page_ids=[str(reference_id)],
    )
    db_session.add(candidate)
    await db_session.flush()
    with pytest.raises(ValueError, match="owner mismatch"):
        await _reference_images(db_session, storage, candidate)
    storage.get_png.assert_not_awaited()


@pytest.mark.asyncio
async def test_compensation_keeps_a_mask_key_referenced_after_commit(
    db_session,
    test_project_id,
) -> None:
    novel_id = uuid.UUID(test_project_id)
    run = MapAtlasRun(novel_id=novel_id, run_kind="edit", status="generating")
    db_session.add(run)
    await db_session.flush()
    node = MapAtlasNode(
        novel_id=novel_id,
        created_by_run_id=run.id,
        semantic_key="world",
        title="世界",
        level="world",
    )
    db_session.add(node)
    await db_session.flush()
    page_id = uuid.uuid4()
    key = page_object_key(test_project_id, str(page_id), mask=True)
    db_session.add(
        MapAtlasPage(
            id=page_id,
            novel_id=novel_id,
            run_id=run.id,
            node_id=node.id,
            title="世界",
            visual_brief="世界地图",
            prompt="no text",
            mask_object_key=key,
        )
    )
    await db_session.commit()
    storage = MagicMock(spec=MapAtlasStorage)
    storage.delete_object = AsyncMock()

    with patch(
        "modules.world.map_atlas_workflow.enqueue_task",
        autospec=True,
    ) as enqueue_cleanup:
        await _compensate_uploaded_object(db_session, storage, key)

    storage.delete_object.assert_not_awaited()
    enqueue_cleanup.assert_not_called()


@pytest.mark.asyncio
async def test_compensation_queues_cleanup_when_reference_check_is_unknown(
    db_session,
) -> None:
    key = page_object_key(str(uuid.uuid4()), str(uuid.uuid4()))
    storage = MagicMock(spec=MapAtlasStorage)
    storage.delete_object = AsyncMock()

    with (
        patch(
            "modules.world.map_atlas_workflow.delete_unreferenced_page_object",
            autospec=True,
            side_effect=RuntimeError("reference check unavailable"),
        ),
        patch(
            "modules.world.map_atlas_workflow.enqueue_task",
            autospec=True,
            return_value=str(uuid.uuid4()),
        ) as enqueue_cleanup,
    ):
        await _compensate_uploaded_object(db_session, storage, key)

    storage.delete_object.assert_not_awaited()
    assert enqueue_cleanup.call_args.kwargs["meta"]["object_key"] == key


@pytest.mark.asyncio
async def test_uploaded_attempt_recovers_after_final_commit_failure_without_provider(
    db_session,
    test_project_id,
    monkeypatch,
) -> None:
    novel_id = uuid.UUID(test_project_id)
    first_task = AsyncTask(
        task_type="map_atlas_generate",
        novel_id=novel_id,
        status="running",
        attempt=1,
        lease_id=str(uuid.uuid4()),
        recovery_policy="manual_resume",
        meta={},
    )
    db_session.add(first_task)
    await db_session.flush()
    run = MapAtlasRun(
        novel_id=novel_id,
        task_id=first_task.id,
        run_kind="initial",
        status="generating",
    )
    db_session.add(run)
    await db_session.flush()
    first_task.meta = {"novel_id": test_project_id, "run_id": str(run.id)}
    node = MapAtlasNode(
        novel_id=novel_id,
        created_by_run_id=run.id,
        semantic_key="world",
        title="世界",
        level="world",
    )
    db_session.add(node)
    await db_session.flush()
    page = MapAtlasPage(
        novel_id=novel_id,
        run_id=run.id,
        node_id=node.id,
        generation_status="prepared",
        title="世界",
        visual_brief="世界地图",
        prompt="no text",
    )
    db_session.add(page)
    await db_session.commit()
    db_session.expunge(first_task)

    objects: dict[str, bytes] = {}
    storage = MagicMock(spec=MapAtlasStorage)

    async def get_if_exists(key: str) -> bytes | None:
        return objects.get(key)

    async def put_png(key: str, payload: bytes):
        objects[key] = payload
        return validate_png(payload)

    storage.get_png_if_exists = AsyncMock(side_effect=get_if_exists)
    storage.put_png = AsyncMock(side_effect=put_png)
    storage.delete_object = AsyncMock(side_effect=lambda key: objects.pop(key, None))
    image_client = SimpleNamespace(
        generate=AsyncMock(return_value=GeneratedImage(OPAQUE_PNG, "request-1")),
        edit=AsyncMock(return_value=GeneratedImage(OPAQUE_PNG, "request-1")),
    )

    @asynccontextmanager
    async def image_client_context(*_args, **_kwargs):
        yield image_client

    original_commit = db_session.commit
    commit_count = 0

    async def fail_final_commit() -> None:
        nonlocal commit_count
        commit_count += 1
        if commit_count == 3:
            raise RuntimeError("commit acknowledgement lost")
        await original_commit()

    monkeypatch.setattr(db_session, "commit", fail_final_commit)
    with (
        patch(
            "modules.world.map_atlas_workflow.MapAtlasStorage",
            autospec=True,
            return_value=storage,
        ),
        patch(
            "modules.world.map_atlas_workflow.open_project_image_client",
            autospec=True,
        ) as open_client,
    ):
        open_client.side_effect = image_client_context
        assert not await _generate_page(db_session, first_task, run, page)

    monkeypatch.setattr(db_session, "commit", original_commit)
    await db_session.refresh(page)
    assert page.generation_status == "retry_requires_confirmation"
    assert page.object_key in objects
    storage.delete_object.assert_not_awaited()

    second_task = AsyncTask(
        task_type="map_atlas_generate",
        novel_id=novel_id,
        status="running",
        attempt=1,
        lease_id=str(uuid.uuid4()),
        recovery_policy="manual_resume",
        meta={"novel_id": test_project_id, "run_id": str(run.id)},
    )
    db_session.add(second_task)
    await db_session.flush()
    page.generation_status = "prepared"
    run.task_id = second_task.id
    await db_session.commit()

    with (
        patch(
            "modules.world.map_atlas_workflow.MapAtlasStorage",
            autospec=True,
            return_value=storage,
        ),
        patch(
            "modules.world.map_atlas_workflow.open_project_image_client",
            autospec=True,
        ) as open_client,
    ):
        open_client.side_effect = image_client_context
        assert await _generate_page(db_session, second_task, run, page)

    await db_session.refresh(page)
    assert page.generation_status == "review_ready"
    assert page.sha256 == validate_png(OPAQUE_PNG).sha256
    assert run.completed_page_count == 1
    assert image_client.generate.await_count == 1
    open_client.assert_not_called()


@pytest.mark.asyncio
async def test_failed_mask_enqueue_compensates_or_schedules_global_cleanup(
    db_session, test_project_id
) -> None:
    novel_id = uuid.UUID(test_project_id)
    run = MapAtlasRun(novel_id=novel_id, run_kind="initial", status="review_ready")
    db_session.add(run)
    await db_session.flush()
    node = MapAtlasNode(
        novel_id=novel_id,
        created_by_run_id=run.id,
        semantic_key="world",
        title="世界",
        level="world",
    )
    db_session.add(node)
    await db_session.flush()
    source_id = uuid.uuid4()
    source = MapAtlasPage(
        id=source_id,
        novel_id=novel_id,
        run_id=run.id,
        node_id=node.id,
        generation_status="review_ready",
        title="世界",
        visual_brief="世界地图",
        prompt="no text",
        object_key=page_object_key(test_project_id, str(source_id)),
        width=1,
        height=1,
    )
    db_session.add(source)
    await db_session.flush()

    storage = MagicMock(spec=MapAtlasStorage)
    storage.get_png = AsyncMock(return_value=OPAQUE_PNG)
    storage.put_png = AsyncMock()
    storage.delete_object = AsyncMock(side_effect=RuntimeError("delete failed"))
    cleanup_task_id = str(uuid.uuid4())
    with (
        patch(
            "modules.world.map_atlas_service.build_project_image_execution_snapshot",
            autospec=True,
            return_value={"snapshot_hash": "test"},
        ),
        patch(
            "modules.world.map_atlas_service.enqueue_coalesced_task",
            autospec=True,
            side_effect=RuntimeError("enqueue failed"),
        ),
        patch(
            "modules.world.map_atlas_service.enqueue_task",
            autospec=True,
            return_value=cleanup_task_id,
        ) as cleanup_task_mock,
        pytest.raises(RuntimeError, match="enqueue failed"),
    ):
        await MapAtlasService(storage=storage).create_derived_page(
            db_session,
            test_project_id,
            str(source.id),
            MapAtlasDerivedRequest(instruction="去掉西侧道路"),
            mode="edit",
            mask=ALPHA_PNG,
        )

    storage.delete_object.assert_awaited_once()
    cleanup_call = cleanup_task_mock.call_args
    assert cleanup_call.args[1] == "map_atlas_storage_cleanup"
    assert cleanup_call.kwargs["novel_id"] is None
    assert cleanup_call.kwargs["meta"]["cleanup_kind"] == "object"
    assert cleanup_call.kwargs["meta"]["object_key"].endswith("/mask.png")


def test_png_contract_and_deterministic_keys() -> None:
    source = validate_png(OPAQUE_PNG)
    mask = validate_png(ALPHA_PNG, require_alpha=True)
    assert (source.width, source.height) == (mask.width, mask.height) == (1, 1)
    require_matching_mask(OPAQUE_PNG, ALPHA_PNG)
    novel_id, page_id = uuid.uuid4(), uuid.uuid4()
    assert (
        page_object_key(str(novel_id), str(page_id))
        == f"map-atlas/{novel_id}/pages/{page_id}/image.png"
    )
    with pytest.raises(ValueError, match="alpha"):
        require_matching_mask(OPAQUE_PNG, OPAQUE_PNG)


@pytest.mark.asyncio
async def test_storage_uses_private_png_contract_and_idempotent_prefix_cleanup() -> None:
    chunks = [OPAQUE_PNG, b""]
    body = SimpleNamespace(read=lambda _size: chunks.pop(0), close=lambda: None)
    client = MagicMock()
    client.get_object.return_value = {"Body": body, "ContentLength": len(OPAQUE_PNG)}
    client.list_objects_v2.side_effect = [
        {"Contents": [{"Key": "map-atlas/n/pages/a/image.png"}], "IsTruncated": False},
        {"Contents": [], "IsTruncated": False},
        {"Contents": [], "IsTruncated": False},
        {"Contents": [], "IsTruncated": False},
        {"Contents": [], "IsTruncated": False},
    ]
    client.delete_objects.return_value = {}
    storage = MapAtlasStorage(client=client, bucket="private")
    await storage.put_png("map-atlas/n/pages/a/image.png", OPAQUE_PNG)
    assert await storage.get_png("map-atlas/n/pages/a/image.png") == OPAQUE_PNG
    assert await storage.delete_prefix("map-atlas/n/") == 1
    assert await storage.delete_prefix("map-atlas/n/") == 0
    client.put_object.assert_called_once()
    client.delete_objects.assert_called_once()


@pytest.mark.asyncio
async def test_gpt_image_client_calls_generate_and_multi_reference_edit() -> None:
    encoded = base64.b64encode(OPAQUE_PNG).decode()
    sdk = MagicMock()
    sdk.models.list = AsyncMock(return_value=SimpleNamespace(data=[]))
    sdk.images.generate = AsyncMock(
        return_value=SimpleNamespace(
            data=[SimpleNamespace(b64_json=encoded)], _request_id="gen"
        )
    )
    sdk.images.edit = AsyncMock(
        return_value=SimpleNamespace(
            data=[SimpleNamespace(b64_json=encoded)], _request_id="edit"
        )
    )
    sdk.close = AsyncMock()
    with patch(
        "infrastructure.llm.image_client.AsyncOpenAI", autospec=True, return_value=sdk
    ):
        client = OpenAIImageClient(api_key="test-key")
        await client.verify_connection()
        generated = await client.generate(
            prompt="no text", size="2048x1152", quality="medium"
        )
        edited = await client.edit(
            prompt="keep geography",
            images=[
                ("one.png", OPAQUE_PNG, "image/png"),
                ("two.png", OPAQUE_PNG, "image/png"),
            ],
            mask=("mask.png", ALPHA_PNG, "image/png"),
            size="2048x1152",
            quality="medium",
        )
        await client.close()
    assert generated.data == edited.data == OPAQUE_PNG
    assert sdk.images.generate.await_args.kwargs["model"] == OPENAI_IMAGE_MODEL
    assert len(sdk.images.edit.await_args.kwargs["image"]) == 2
    assert sdk.images.edit.await_args.kwargs["mask"][0] == "mask.png"
