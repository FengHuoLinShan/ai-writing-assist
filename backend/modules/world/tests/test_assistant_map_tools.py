from uuid import UUID, uuid4

import pytest

from app.assistant_operation_registry import world_map_operations
from core.errors import ConflictError
from modules.account.facade import current_account_id
from modules.assistant.contracts import AssistantOperationContext, WorkContext
from modules.world.assistant_map_tools import (
    AddKnownLocation,
    AssistantSpaceArrangement,
    EditFeatureLabel,
    EditMapStructure,
    MapStructureEdit,
    ReviewSpatialClues,
    SpatialClueDecisionSelector,
    UpdateMapNode,
)
from modules.world.map_atlas_schemas import MapAtlasNodeUpdate
from modules.world.map_structure_schemas import MapNodeCreate, MapSaveRequest
from modules.world.map_structure_service import MapStructureService
from modules.world.models import CoreEntity
from modules.world.tests.test_map_structure import document


@pytest.mark.asyncio
async def test_known_place_stays_unpositioned_and_label_edit_preserves_locked_geometry(
    db_session, test_project_id
):
    db, nid = db_session, test_project_id
    service = MapStructureService()
    node = await service.create_node(db, nid, MapNodeCreate(title="区域", level="region"))
    from modules.evidence.contracts import VisibilityContextContract
    from modules.evidence.facade import inspect_novel_target

    bounded = await inspect_novel_target(
        db,
        novel_id=nid,
        target_ref={"target_type": "map_atlas_node", "target_id": node["id"]},
        content_mode="canonical",
        visibility=VisibilityContextContract(mode="author", cutoff_chapter=1),
    )
    assert not bounded["visible"]
    first = await service.save(
        db,
        nid,
        node["id"],
        MapSaveRequest(
            base_revision_id=(
                await service.node(db, nid, node["id"])
            ).current_revision_id,
            document=document(),
        ),
    )
    entity = CoreEntity(
        novel_id=UUID(nid), entity_type="location", name="雾港", status="canonical"
    )
    db.add(entity)
    await db.flush()
    context = AssistantOperationContext(
        str(uuid4()), str(current_account_id()), WorkContext(page="map", scope="project")
    )
    args = AddKnownLocation(node_id=node["id"], entity_id=entity.id)
    op = world_map_operations["map.add_known_location"]
    preview = await op.prepare(db, nid, args, context=context)
    result = await op.apply(db, nid, args, preview, context=context)
    current = await service.revision(db, nid, node["id"], UUID(result["revision_id"]))
    assert current.document["features"][-1]["points"] == []
    assert (
        current.document["features"][0]["points"]
        == first.document.features[0].model_dump()["points"]
    )
    assert current.document["features"][0]["locked"]
    edit = EditFeatureLabel(
        node_id=node["id"], feature_id="harbor", note="作者补充的说明"
    )
    op = world_map_operations["map.edit_feature_label"]
    preview = await op.prepare(db, nid, edit, context=context)
    result = await op.apply(db, nid, edit, preview, context=context)
    edited = await service.revision(db, nid, node["id"], UUID(result["revision_id"]))
    assert (
        edited.document["features"][0]["points"]
        == current.document["features"][0]["points"]
    )
    assert edited.document["features"][0]["note"] == "作者补充的说明"
    with pytest.raises(ConflictError):
        await op.apply(db, nid, edit, preview, context=context)


async def test_create_node_preview_names_the_exact_pinned_level_type(
    db_session, test_project_id
):
    from core.errors import ValidationError
    from modules.world.project_vocabulary_schemas import (
        VocabularyTermCreate,
        VocabularyTermUpdate,
    )
    from modules.world.project_vocabulary_service import (
        create_project_vocabulary_term,
        update_project_vocabulary_term,
    )

    db, nid = db_session, test_project_id
    term = await create_project_vocabulary_term(
        db,
        nid,
        VocabularyTermCreate(kind="level", name="舱段", description="原有空间层级"),
    )
    await update_project_vocabulary_term(
        db,
        nid,
        str(term.id),
        VocabularyTermUpdate(expected_revision_id=term.revision_id, name="甲板"),
    )
    args = MapNodeCreate(
        title="第一舱段",
        level="interior",
        level_type_ref=term.id,
        level_type_revision_id=term.revision_id,
    )
    context = AssistantOperationContext(
        str(uuid4()), str(current_account_id()), WorkContext(page="map", scope="project")
    )
    operation = world_map_operations["map.create_node"]
    preview = await operation.prepare(db, nid, args, context=context)
    assert preview["after"]["level_type"] == {
        "type_ref": str(term.id),
        "type_revision_id": str(term.revision_id),
        "name": "舱段",
        "description": "原有空间层级",
        "status": "active",
    }
    wrong_kind = await create_project_vocabulary_term(
        db, nid, VocabularyTermCreate(kind="feature", name="空间标记")
    )
    with pytest.raises(ValidationError, match="层级类型"):
        await operation.prepare(
            db,
            nid,
            MapNodeCreate(
                title="非法层级",
                level_type_ref=wrong_kind.id,
                level_type_revision_id=wrong_kind.revision_id,
            ),
            context=context,
        )


@pytest.mark.asyncio
async def test_assistant_space_edit_saves_without_model_coordinates_or_provenance_fields(
    db_session, test_project_id
):
    db, nid = db_session, test_project_id
    service = MapStructureService()
    node = await service.create_node(db, nid, MapNodeCreate(title="主界域"))
    context = AssistantOperationContext(
        str(uuid4()), str(current_account_id()), WorkContext(page="map", scope="project")
    )
    context, author_message = await _persist_author_turn(db, nid)
    args = EditMapStructure(
        node_id=UUID(node["id"]),
        base_revision_id=UUID(node["current_revision_id"]),
        edits=[
            MapStructureEdit(
                kind="add_space",
                space=AssistantSpaceArrangement(id="dream", label="梦境"),
            )
        ],
    )
    operation = world_map_operations["map.edit_spatial_structure"]
    preview = await operation.prepare(db, nid, args, context=context)
    assert any(space["id"] == "dream" for space in preview["after"]["spaces"])
    assert "points" not in str(operation.schema.model_json_schema())
    assert "author_decision" not in str(operation.schema.model_json_schema())

    author_message.content = "作者已经更改安排"
    await db.flush()
    with pytest.raises(ConflictError, match="变化"):
        await operation.apply(db, nid, args, preview, context=context)
    author_message.content = "请建立梦境空间"
    await db.flush()
    result = await operation.apply(db, nid, args, preview, context=context)
    revision = await service.revision(
        db, nid, str(args.node_id), UUID(result["revision_id"])
    )
    assert any(space["id"] == "dream" for space in revision.document["spaces"])
    assert revision.document["author_decision"]["message_id"] == str(author_message.id)


@pytest.mark.asyncio
async def test_assistant_node_rename_preview_rolls_back_until_confirmed(
    db_session, test_project_id
):
    db, nid = db_session, test_project_id
    structure = MapStructureService()
    node = await structure.create_node(db, nid, MapNodeCreate(title="旧名"))
    current = await structure.node(db, nid, node["id"])
    context = AssistantOperationContext(
        str(uuid4()), str(current_account_id()), WorkContext(page="map", scope="project")
    )
    args = UpdateMapNode(
        node_id=UUID(node["id"]),
        update=MapAtlasNodeUpdate(expected_updated_at=current.updated_at, title="新名"),
    )
    operation = world_map_operations["map.update_node"]
    preview = await operation.prepare(db, nid, args, context=context)
    assert preview["before"]["title"] == "旧名"
    assert preview["after"]["title"] == "新名"
    assert (await structure.node(db, nid, node["id"])).title == "旧名"

    await operation.apply(db, nid, args, preview, context=context)
    assert (await structure.node(db, nid, node["id"])).title == "新名"


@pytest.mark.asyncio
async def test_assistant_clue_review_uses_exact_quote_and_rejects_ambiguous_selector(
    monkeypatch, test_project_id
):
    from types import SimpleNamespace

    from core.errors import ConflictError
    from modules.world import assistant_map_tools

    clues = [
        SimpleNamespace(
            id=uuid4(),
            quote="黑港在群岛东侧",
            scene_index=2,
            status="pending_review",
            fingerprint="a" * 64,
        ),
        SimpleNamespace(
            id=uuid4(),
            quote="黑港在群岛东侧",
            scene_index=3,
            status="pending_review",
            fingerprint="b" * 64,
        ),
    ]

    async def list_clues(*_args, **_kwargs):
        return SimpleNamespace(items=clues, total_count=len(clues))

    monkeypatch.setattr(assistant_map_tools, "list_spatial_clues", list_clues)
    context = AssistantOperationContext(
        str(uuid4()), str(current_account_id()), WorkContext(page="map", scope="project")
    )
    args = ReviewSpatialClues(
        decisions=[
            SpatialClueDecisionSelector(
                quote="黑港在群岛东侧", scene_index=2, action="adopt"
            )
        ]
    )
    preview = await assistant_map_tools._clue_review_preview(
        None, test_project_id, args, context=context
    )
    assert preview["decisions"][0]["clue_id"] == str(clues[0].id)
    ambiguous = ReviewSpatialClues(
        decisions=[SpatialClueDecisionSelector(quote="黑港在群岛东侧", action="adopt")]
    )
    with pytest.raises(ConflictError, match="无法唯一定位"):
        await assistant_map_tools._clue_review_preview(
            None, test_project_id, ambiguous, context=context
        )


async def _persist_author_turn(db, novel_id):
    from infrastructure.tasks.models import AsyncTask
    from modules.assistant.models import AssistantMessage, AssistantRun, AssistantSession

    task = AsyncTask(novel_id=UUID(novel_id), task_type="assistant_turn", status="done")
    session = AssistantSession(
        novel_id=UUID(novel_id), title="地图安排", source_kind="project"
    )
    db.add_all([task, session])
    await db.flush()
    run = AssistantRun(
        novel_id=UUID(novel_id),
        owner_id=current_account_id(),
        session_id=session.id,
        task_id=task.id,
        mode="author",
        request_hash="a" * 64,
    )
    db.add(run)
    await db.flush()
    message = AssistantMessage(
        novel_id=UUID(novel_id),
        session_id=session.id,
        task_id=task.id,
        role="author",
        kind="message",
        content="请建立梦境空间",
    )
    db.add(message)
    await db.flush()
    return AssistantOperationContext(
        str(run.id), str(current_account_id()), WorkContext(page="map", scope="project")
    ), message
