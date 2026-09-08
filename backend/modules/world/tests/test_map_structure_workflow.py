from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from core.errors import ValidationError
from infrastructure.tasks.models import AsyncTask
from modules.evidence.compilation.services.compiled_context import (
    CompiledContext,
    ContextSection,
    Tier,
)
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasPage, MapAtlasRevision
from modules.world.map_atlas_schemas import MapAtlasRunCreate
from modules.world.map_atlas_service import MapAtlasService
from modules.world.map_structure_schemas import (
    MapDocument,
    MapNodeCreate,
    MapRelationBatch,
    MapSaveRequest,
    MapSource,
    SpatialConstraint,
)
from modules.world.map_structure_service import (
    MAP_TASK,
    MapStructureService,
    source_digest,
    source_payload,
)
from modules.world.map_structure_workflow import confirmed_spatial_sources, run_structure
from modules.world.models import CoreEntity


def prepared_context(entities):
    return SimpleNamespace(
        confirmation=SimpleNamespace(context_fingerprint="f" * 64),
        compiled=CompiledContext(
            sections=[
                ContextSection(
                    key="world_entities",
                    tier=Tier.P2,
                    status="canonical",
                    content="\n".join(
                        json.dumps(source_payload(entity), ensure_ascii=False)
                        for entity in entities
                    ),
                    sources=[
                        {"type": "entity", "id": str(entity.id), "status": "canonical"}
                        for entity in entities
                    ],
                )
            ]
        ),
    )


async def setup_task(db, novel_id):
    service = MapStructureService()
    node = await service.create_node(db, novel_id, MapNodeCreate(title="区域"))
    entities = [
        CoreEntity(
            novel_id=uuid.UUID(novel_id),
            name="甲城",
            entity_type="location",
            status="canonical",
            public_info="甲城",
            reveal_level="revealed",
        ),
        CoreEntity(
            novel_id=uuid.UUID(novel_id),
            name="乙城",
            entity_type="location",
            status="canonical",
            summary="乙城在甲城以北",
            public_info="乙城",
            reveal_level="revealed",
        ),
    ]
    db.add_all(entities)
    await db.flush()
    task = AsyncTask(
        novel_id=uuid.UUID(novel_id),
        task_type=MAP_TASK,
        status="running",
        attempt=1,
        lease_id=str(uuid.uuid4()),
        recovery_policy="manual_resume",
        meta={
            "node_id": node["id"],
            "base_revision_id": node["current_revision_id"],
            "location_ids": [str(entity.id) for entity in entities],
            "context_confirmation_id": str(uuid.uuid4()),
            "llm_execution_snapshot": {},
        },
    )
    db.add(task)
    await db.flush()
    model = await db.get(MapAtlasNode, uuid.UUID(node["id"]))
    model.structure_task_id = task.id
    await db.flush()
    db.task_checkpoint_enabled = True
    return node, entities, task


@pytest.mark.asyncio
async def test_text_only_task_creates_candidate_without_moving_current_head(
    db_session, test_project_id
):
    node, entities, task = await setup_task(db_session, test_project_id)
    prepared = prepared_context(entities)
    client = SimpleNamespace(
        generate_structured=AsyncMock(
            return_value=MapRelationBatch(
                relations=[
                    {
                        "subject": f"loc:{entities[1].id}",
                        "relation": "north",
                        "target": f"loc:{entities[0].id}",
                        "source_keys": [f"entity:{entities[1].id}"],
                        "quote": "乙城在甲城以北",
                    }
                ]
            )
        ),
        close=AsyncMock(),
    )
    with (
        patch(
            "modules.world.map_structure_workflow.prepare_confirmed_ai_action",
            autospec=True,
            return_value=prepared,
        ),
        patch(
            "modules.world.map_structure_workflow.require_fresh_confirmation",
            autospec=True,
        ),
        patch(
            "modules.world.map_structure_workflow.restore_project_llm_execution_settings",
            autospec=True,
            return_value={"llm": {"model": "text-flash"}},
        ),
        patch(
            "modules.world.map_structure_workflow.create_project_snapshot_llm_client",
            autospec=True,
            return_value=client,
        ),
    ):
        result = await run_structure(db_session, task)
    candidate = await db_session.scalar(
        select(MapAtlasRevision).where(
            MapAtlasRevision.id == uuid.UUID(result["revision_id"])
        )
    )
    assert candidate.status == "candidate"
    assert candidate.confirmation_id == uuid.UUID(task.meta["context_confirmation_id"])
    assert candidate.context_fingerprint == "f" * 64
    assert len(candidate.document["constraints"]) == 1
    assert not candidate.problems
    current = await db_session.get(MapAtlasNode, uuid.UUID(node["id"]))
    assert str(current.current_revision_id) == node["current_revision_id"]
    request = client.generate_structured.call_args.args[0]
    assert request.model == "text-flash"
    assert request.max_tokens == 4000
    assert all(isinstance(message.content, str) for message in request.messages)
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_excluded_location_is_not_reintroduced_from_world_table(
    db_session, test_project_id
):
    _, entities, task = await setup_task(db_session, test_project_id)
    with (
        patch(
            "modules.world.map_structure_workflow.prepare_confirmed_ai_action",
            autospec=True,
            return_value=prepared_context(entities[:1]),
        ),
        patch(
            "modules.world.map_structure_workflow.create_project_snapshot_llm_client",
            autospec=True,
        ) as factory,
    ):
        with pytest.raises(ValidationError, match="未全部进入"):
            await run_structure(db_session, task)
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_collector_does_not_rehydrate_excluded_items(db_session, test_project_id):
    _, entities, _ = await setup_task(db_session, test_project_id)
    prepared = prepared_context(entities)
    section = prepared.compiled.sections[0].materialize_items()
    section.items[1].selection_state = "excluded"
    prepared.compiled.sections = [section]
    sources = await confirmed_spatial_sources(db_session, test_project_id, prepared)
    assert set(sources) == {f"entity:{entities[0].id}"}


@pytest.mark.asyncio
async def test_reader_does_not_leak_geometry_derived_from_author_only_constraint(
    db_session, test_project_id
):
    node, entities, _ = await setup_task(db_session, test_project_id)
    source = MapSource(
        kind="entity",
        id=entities[1].id,
        source_hash=source_digest(source_payload(entities[1])),
        quote="乙城在甲城以北",
    )
    doc = MapDocument.model_validate(
        {
            "features": [
                {
                    "id": "a",
                    "kind": "location",
                    "label": "甲城",
                    "points": [{"x": 100, "y": 300}],
                    "reader_from_chapter": 1,
                },
                {
                    "id": "b",
                    "kind": "location",
                    "label": "乙城",
                    "points": [{"x": 100, "y": 100}],
                    "reader_from_chapter": 1,
                },
            ],
            "constraints": [
                SpatialConstraint(
                    id="north",
                    subject="b",
                    relation="north",
                    target="a",
                    sources=[source],
                ).model_dump(mode="json")
            ],
        }
    )
    service = MapStructureService()
    await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(base_revision_id=node["current_revision_id"], document=doc),
    )
    projection = await service.reader_preview(
        db_session, test_project_id, node["id"], chapter=1
    )
    assert projection["features"] == []
    assert "乙城在甲城以北" not in str(projection)


@pytest.mark.asyncio
async def test_structure_guided_image_does_not_require_a_second_text_model_plan(
    db_session, test_project_id
):
    service = MapStructureService()
    node = await service.create_node(
        db_session, test_project_id, MapNodeCreate(title="手绘区域")
    )
    with (
        patch(
            "modules.world.map_atlas_service.build_project_llm_execution_snapshot",
            autospec=True,
        ) as text_snapshot,
        patch(
            "modules.world.map_atlas_service.build_project_image_execution_snapshot",
            autospec=True,
            return_value={"image": "test"},
        ),
    ):
        run = await MapAtlasService().create_run(
            db_session,
            test_project_id,
            MapAtlasRunCreate(
                target_node_id=node["id"],
                source_map_revision_id=node["current_revision_id"],
                context_confirmation_id=str(uuid.uuid4()),
            ),
        )
    text_snapshot.assert_not_called()
    assert run["planned_page_count"] == 0
    from modules.world.map_atlas_models import MapAtlasRun

    model = await db_session.get(MapAtlasRun, uuid.UUID(run["id"]))
    assert model.context_snapshot["source_map_revision_id"] == node["current_revision_id"]


@pytest.mark.asyncio
async def test_structure_reference_counts_toward_eight_image_limit(
    db_session, test_project_id
):
    from modules.world.map_atlas_models import MapAtlasRun
    from modules.world.map_atlas_workflow import _reference_images

    service = MapStructureService()
    node = await service.create_node(
        db_session, test_project_id, MapNodeCreate(title="区域")
    )
    run = MapAtlasRun(
        novel_id=uuid.UUID(test_project_id), run_kind="initial", status="generating"
    )
    db_session.add(run)
    await db_session.flush()
    page = MapAtlasPage(
        novel_id=run.novel_id,
        run_id=run.id,
        node_id=uuid.UUID(node["id"]),
        title="画面",
        visual_brief="",
        prompt="",
        source_map_revision_id=uuid.UUID(node["current_revision_id"]),
        reference_page_ids=[str(uuid.uuid4()) for _ in range(8)],
    )
    db_session.add(page)
    await db_session.flush()
    with pytest.raises(ValueError, match="at most 8"):
        await _reference_images(db_session, SimpleNamespace(), page)
    page.reference_page_ids = []
    guide = await _reference_images(db_session, SimpleNamespace(), page)
    assert len(guide) == 1
    assert guide[0][0] == "structure.png"
    assert guide[0][1].startswith(b"\x89PNG")
