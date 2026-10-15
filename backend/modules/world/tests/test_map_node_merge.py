from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.assistant_operation_registry import world_map_operations
from core.errors import ConflictError, NotFoundError, ValidationError
from modules.account.facade import current_account_id
from modules.assistant.contracts import AssistantOperationContext, WorkContext
from modules.world.assistant_map_tools import PreviewMapNodeMerge
from modules.world.map_atlas_models import (
    MapAtlasNode,
    MapAtlasPage,
    MapAtlasRevision,
    MapAtlasRun,
)
from modules.world.map_atlas_service import MapAtlasService
from modules.world.map_node_merge import (
    MapNodeMergeApplyRequest,
    MapNodeMergePreviewRequest,
    MapNodeMergeService,
    MapNodeMergeUndoRequest,
)
from modules.world.map_structure_geometry import geometry_hash
from modules.world.map_structure_review import changed_items
from modules.world.map_structure_schemas import (
    MapAuthorDecision,
    MapDocument,
    MapNodeCreate,
    MapSaveRequest,
)
from modules.world.map_structure_service import (
    MapStructureService,
    source_digest,
    source_payload,
)
from modules.world.models import CoreEntity
from modules.world.project_vocabulary_schemas import VocabularyTermCreate
from modules.world.project_vocabulary_service import create_project_vocabulary_term


async def _saved_node(
    db,
    novel_id,
    title,
    document,
    *,
    level_type_ref=None,
    level_type_revision_id=None,
):
    service = MapStructureService()
    node = await service.create_node(
        db,
        novel_id,
        MapNodeCreate(
            title=title,
            level="region",
            level_type_ref=level_type_ref,
            level_type_revision_id=level_type_revision_id,
        ),
    )
    revision = await service.save(
        db,
        novel_id,
        node["id"],
        MapSaveRequest(
            base_revision_id=uuid.UUID(node["current_revision_id"]),
            document=document,
        ),
    )
    return node["id"], revision


async def _merge_documents(db, novel_id, *, source_entity=None):
    feature_type = await create_project_vocabulary_term(
        db, novel_id, VocabularyTermCreate(kind="feature", name="地图地点")
    )
    space_type = await create_project_vocabulary_term(
        db, novel_id, VocabularyTermCreate(kind="space", name="独立空间")
    )
    author_decision = MapAuthorDecision(origin="manual")
    target = MapDocument.model_validate(
        {
            "schema_version": 2,
            "author_decision": author_decision.model_dump(mode="json"),
            "spaces": [
                {
                    "id": "main",
                    "label": "目标主空间",
                    "type_ref": str(space_type.id),
                    "type_revision_id": str(space_type.revision_id),
                }
            ],
            "features": [
                {
                    "id": "shared",
                    "kind": "location",
                    "label": "目标地点",
                    "points": [{"x": 20, "y": 30}],
                    "type_ref": str(feature_type.id),
                    "type_revision_id": str(feature_type.revision_id),
                },
                {
                    "id": "target-side",
                    "kind": "landmark",
                    "label": "目标地标",
                    "points": [{"x": 40, "y": 50}],
                    "type_ref": str(feature_type.id),
                    "type_revision_id": str(feature_type.revision_id),
                },
            ],
            "constraints": [
                {
                    "id": "route",
                    "subject": "shared",
                    "relation": "adjacent",
                    "target": "target-side",
                }
            ],
            "journeys": [
                {
                    "id": "journey",
                    "origin": "shared",
                    "destination": "target-side",
                    "transport_label": "目标渡船",
                    "author_decision": {"origin": "manual"},
                }
            ],
        }
    )
    source_shared = {
        "id": "shared",
        "kind": "location",
        "label": "来源地点",
        "points": [{"x": 900, "y": 800}],
        "type_ref": str(feature_type.id),
        "type_revision_id": str(feature_type.revision_id),
    }
    if source_entity is not None:
        from modules.world.map_structure_service import MapSource

        source_shared["entity_id"] = str(source_entity.id)
        source_shared["sources"] = [
            MapSource(
                kind="entity",
                id=source_entity.id,
                source_hash=source_digest(source_payload(source_entity)),
                quote="来源记载",
            ).model_dump(mode="json")
        ]
    source = MapDocument.model_validate(
        {
            "schema_version": 2,
            "author_decision": author_decision.model_dump(mode="json"),
            "spaces": [
                {
                    "id": "main",
                    "label": "来源主空间",
                    "type_ref": str(space_type.id),
                    "type_revision_id": str(space_type.revision_id),
                },
                {
                    "id": "cave",
                    "label": "来源洞窟",
                    "type_ref": str(space_type.id),
                    "type_revision_id": str(space_type.revision_id),
                },
            ],
            "features": [
                source_shared,
                {
                    "id": "source-side",
                    "kind": "landmark",
                    "label": "来源地标",
                    "space_id": "main",
                    "points": [{"x": 1200, "y": 1400}],
                    "depends_on": ["shared"],
                    "type_ref": str(feature_type.id),
                    "type_revision_id": str(feature_type.revision_id),
                },
            ],
            "constraints": [
                {
                    "id": "route",
                    "subject": "shared",
                    "relation": "adjacent",
                    "target": "source-side",
                }
            ],
            "journeys": [
                {
                    "id": "journey",
                    "origin": "shared",
                    "destination": "source-side",
                    "transport_label": "来源渡船",
                    "author_decision": {"origin": "manual"},
                }
            ],
        }
    )
    return target, source


def _walk(nodes):
    for node in nodes:
        yield node
        yield from _walk(node["children"])


@pytest.mark.asyncio
async def test_node_merge_preserves_coordinates_history_and_undoes_with_new_revision(
    db_session, test_project_id
):
    novel_id = test_project_id
    entity = CoreEntity(
        novel_id=uuid.UUID(novel_id),
        entity_type="location",
        name="来源资料",
        summary="来源记载",
        status="canonical",
    )
    db_session.add(entity)
    await db_session.flush()
    target_document, source_document = await _merge_documents(
        db_session, novel_id, source_entity=entity
    )
    target_id, target_saved = await _saved_node(
        db_session, novel_id, "目标地图", target_document
    )
    source_id, source_saved = await _saved_node(
        db_session, novel_id, "来源地图", source_document
    )
    service = MapNodeMergeService()

    preview = await service.preview(db_session, novel_id, source_id, target_id)
    assert preview.can_execute
    assert preview.merged_document is not None
    assert preview.requires_source_disposition_confirmation
    merged = preview.merged_document
    assert preview.affected_count == len(changed_items(target_document, merged)) + 1
    assert preview.affected_count == 7
    feature_ids = [item.id for item in merged.features]
    assert len(feature_ids) == len(set(feature_ids))
    source_feature = next(item for item in merged.features if item.label == "来源地点")
    target_feature = next(item for item in merged.features if item.label == "目标地点")
    assert source_feature.id != target_feature.id
    assert source_feature.space_id != target_feature.space_id
    assert [(point.x, point.y) for point in source_feature.points] == [(900, 800)]
    assert source_feature.type_ref == target_feature.type_ref
    assert (
        source_feature.sources[0].source_hash
        == source_document.features[0].sources[0].source_hash
    )
    assert len(merged.spaces) == 3
    assert {item.label for item in merged.spaces} == {
        "目标主空间",
        "来源主空间",
        "来源洞窟",
    }
    source_constraint = next(item for item in merged.constraints if item.id != "route")
    assert source_constraint.subject == source_feature.id
    source_journey = next(item for item in merged.journeys if item.id != "journey")
    assert source_journey.origin == source_feature.id
    assert source_journey.author_decision == source_document.journeys[0].author_decision

    with pytest.raises(ValidationError, match="明确确认来源节点"):
        await service.apply(
            db_session,
            novel_id,
            MapNodeMergeApplyRequest(
                source_node_id=source_id,
                target_node_id=target_id,
                preview_fingerprint=preview.fingerprint,
                confirmed_source_disposition=False,
            ),
        )
    result = await service.apply(
        db_session,
        novel_id,
        MapNodeMergeApplyRequest(
            source_node_id=source_id,
            target_node_id=target_id,
            preview_fingerprint=preview.fingerprint,
            confirmed_source_disposition=True,
        ),
    )
    source = await db_session.get(MapAtlasNode, uuid.UUID(source_id))
    target = await db_session.get(MapAtlasNode, uuid.UUID(target_id))
    assert source is not None and source.merged_into_node_id == target.id
    assert source.current_revision_id == uuid.UUID(source_saved.id)
    assert target.current_revision_id == uuid.UUID(result["merged_revision_id"])
    assert await db_session.get(MapAtlasRevision, uuid.UUID(source_saved.id)) is not None
    with pytest.raises(ConflictError) as redirect:
        await MapStructureService().get_map(db_session, novel_id, source_id)
    assert redirect.value.context["redirect_node_id"] == target_id
    assert redirect.value.context["redirect_to"].endswith(f"/{target_id}/map")
    assert source_saved.id in {
        item.id
        for item in await MapStructureService().history(db_session, novel_id, source_id)
    }

    atlas = await MapAtlasService().get_tree(db_session, novel_id)
    assert {node["id"] for node in _walk(atlas["nodes"])} == {target_id}
    undo_preview = await service.preview_undo(db_session, novel_id, source_id, target_id)
    assert undo_preview.can_undo
    assert undo_preview.affected_count == len(changed_items(merged, target_document)) + 1
    assert undo_preview.affected_count == preview.affected_count
    undo = await service.undo(
        db_session,
        novel_id,
        MapNodeMergeUndoRequest(
            source_node_id=source_id,
            target_node_id=target_id,
            preview_fingerprint=undo_preview.fingerprint,
            confirmed=True,
        ),
    )
    await db_session.refresh(source)
    await db_session.refresh(target)
    restored = await db_session.get(
        MapAtlasRevision, uuid.UUID(undo["restored_revision_id"])
    )
    assert source.merged_into_node_id is None
    assert source.current_revision_id == uuid.UUID(source_saved.id)
    assert target.current_revision_id == restored.id
    assert restored.base_revision_id == uuid.UUID(result["merged_revision_id"])
    assert MapDocument.model_validate(restored.document) == target_document
    assert target_saved.id != restored.id


@pytest.mark.asyncio
async def test_node_merge_preview_blocks_children_candidates_and_image_pages(
    db_session, test_project_id
):
    target_document, source_document = await _merge_documents(db_session, test_project_id)
    target_id, _ = await _saved_node(
        db_session, test_project_id, "目标地图", target_document
    )
    source_id, source_saved = await _saved_node(
        db_session, test_project_id, "来源地图", source_document
    )
    child = await MapStructureService().create_node(
        db_session,
        test_project_id,
        MapNodeCreate(
            title="来源下级",
            level="city",
            parent_id=uuid.UUID(source_id),
        ),
    )
    preview = await MapNodeMergeService().preview(
        db_session, test_project_id, source_id, target_id
    )
    assert not preview.can_execute
    assert any("来源节点仍有子节点" in item for item in preview.blockers)
    child_row = await db_session.get(MapAtlasNode, uuid.UUID(child["id"]))
    await db_session.delete(child_row)
    await db_session.flush()

    candidate = MapAtlasRevision(
        novel_id=uuid.UUID(test_project_id),
        node_id=uuid.UUID(source_id),
        base_revision_id=uuid.UUID(source_saved.id),
        status="candidate",
        document=source_document.model_dump(mode="json"),
        geometry_hash=source_saved.geometry_hash,
        problems=[],
    )
    db_session.add(candidate)
    await db_session.flush()
    preview = await MapNodeMergeService().preview(
        db_session, test_project_id, source_id, target_id
    )
    assert not preview.can_execute
    assert "来源或目标仍有待审核草图" in preview.blockers
    await db_session.delete(candidate)
    run = MapAtlasRun(
        novel_id=uuid.UUID(test_project_id), run_kind="initial", status="completed"
    )
    db_session.add(run)
    await db_session.flush()
    db_session.add(
        MapAtlasPage(
            novel_id=uuid.UUID(test_project_id),
            run_id=run.id,
            node_id=uuid.UUID(source_id),
            title="来源地图图片",
            visual_brief="示意底图",
            prompt="示意底图",
            generation_status="failed",
            review_status="rejected",
        )
    )
    await db_session.flush()
    preview = await MapNodeMergeService().preview(
        db_session, test_project_id, source_id, target_id
    )
    assert not preview.can_execute
    assert any("来源或目标已有图片页" in item for item in preview.blockers)


@pytest.mark.asyncio
async def test_node_merge_preview_blocks_different_fixed_hierarchy_types(
    db_session, test_project_id
):
    target_document, source_document = await _merge_documents(db_session, test_project_id)
    level_type = await create_project_vocabulary_term(
        db_session,
        test_project_id,
        VocabularyTermCreate(kind="level", name="自定义区域"),
    )
    target_id, _ = await _saved_node(
        db_session, test_project_id, "目标地图", target_document
    )
    source_id, _ = await _saved_node(
        db_session,
        test_project_id,
        "来源地图",
        source_document,
        level_type_ref=level_type.id,
        level_type_revision_id=level_type.revision_id,
    )

    preview = await MapNodeMergeService().preview(
        db_session, test_project_id, source_id, target_id
    )

    assert not preview.can_execute
    assert "来源和目标的固定层级类型不同，不能合并" in preview.blockers


@pytest.mark.asyncio
async def test_node_merge_revalidates_source_hash_and_both_heads(
    db_session, test_project_id
):
    entity = CoreEntity(
        novel_id=uuid.UUID(test_project_id),
        entity_type="location",
        name="来源资料",
        summary="来源记载",
        status="canonical",
    )
    db_session.add(entity)
    await db_session.flush()
    target_document, source_document = await _merge_documents(
        db_session, test_project_id, source_entity=entity
    )
    target_id, target_saved = await _saved_node(
        db_session, test_project_id, "目标地图", target_document
    )
    source_id, source_saved = await _saved_node(
        db_session, test_project_id, "来源地图", source_document
    )
    service = MapNodeMergeService()
    preview = await service.preview(db_session, test_project_id, source_id, target_id)
    assert preview.can_execute
    entity.summary = "已经变化的来源记载"
    await db_session.flush()
    with pytest.raises(ValidationError, match="暂不可执行"):
        await service.apply(
            db_session,
            test_project_id,
            MapNodeMergeApplyRequest(
                source_node_id=source_id,
                target_node_id=target_id,
                preview_fingerprint=preview.fingerprint,
                confirmed_source_disposition=True,
            ),
        )
    source = await db_session.get(MapAtlasNode, uuid.UUID(source_id))
    target = await db_session.get(MapAtlasNode, uuid.UUID(target_id))
    assert source.merged_into_node_id is None
    assert target.current_revision_id == uuid.UUID(target_saved.id)
    assert source.current_revision_id == uuid.UUID(source_saved.id)


@pytest.mark.asyncio
async def test_node_merge_rejects_more_than_twenty_actual_map_changes(
    db_session, test_project_id
):
    target_document, source_document = await _merge_documents(db_session, test_project_id)
    feature_template = source_document.features[0]
    source_document = source_document.model_copy(
        update={
            "features": [
                *source_document.features,
                *[
                    feature_template.model_copy(
                        update={
                            "id": f"extra-{index}",
                            "label": f"附加图元{index}",
                            "depends_on": [],
                        }
                    )
                    for index in range(18)
                ],
            ]
        }
    )
    target_id, _ = await _saved_node(
        db_session, test_project_id, "目标地图", target_document
    )
    source_id, _ = await _saved_node(
        db_session, test_project_id, "来源地图", source_document
    )

    preview = await MapNodeMergeService().preview(
        db_session, test_project_id, source_id, target_id
    )

    assert not preview.can_execute
    assert preview.affected_count == 25
    assert any("25 项实际地图变更" in blocker for blocker in preview.blockers)
    assert preview.merged_document is None


@pytest.mark.asyncio
async def test_node_merge_rejects_cross_project_target(
    db_session, test_project_id, project_factory
):
    target_document, source_document = await _merge_documents(db_session, test_project_id)
    source_id, _ = await _saved_node(
        db_session, test_project_id, "来源地图", source_document
    )
    other_novel_id = str(await project_factory.create_project(title="另一个作品"))
    foreign_node = await MapStructureService().create_node(
        db_session,
        other_novel_id,
        MapNodeCreate(title="外部地图", level="region"),
    )

    with pytest.raises(NotFoundError):
        await MapNodeMergeService().preview(
            db_session, test_project_id, source_id, foreign_node["id"]
        )


@pytest.mark.asyncio
async def test_node_merge_rejects_stale_target_head(db_session, test_project_id):
    target_document, source_document = await _merge_documents(db_session, test_project_id)
    target_id, target_saved = await _saved_node(
        db_session, test_project_id, "目标地图", target_document
    )
    source_id, source_saved = await _saved_node(
        db_session, test_project_id, "来源地图", source_document
    )
    service = MapNodeMergeService()
    preview = await service.preview(db_session, test_project_id, source_id, target_id)
    assert preview.can_execute

    changed_target = target_document.model_copy(
        update={
            "features": [
                target_document.features[0].model_copy(update={"label": "新目标地点"}),
                *target_document.features[1:],
            ]
        }
    )
    await MapStructureService().save(
        db_session,
        test_project_id,
        target_id,
        MapSaveRequest(
            base_revision_id=uuid.UUID(target_saved.id),
            document=changed_target,
        ),
    )

    with pytest.raises(ConflictError, match="已变化"):
        await service.apply(
            db_session,
            test_project_id,
            MapNodeMergeApplyRequest(
                source_node_id=source_id,
                target_node_id=target_id,
                preview_fingerprint=preview.fingerprint,
                confirmed_source_disposition=True,
            ),
        )
    source = await db_session.get(MapAtlasNode, uuid.UUID(source_id))
    assert source is not None and source.merged_into_node_id is None
    assert source.current_revision_id == uuid.UUID(source_saved.id)


@pytest.mark.asyncio
async def test_node_merge_undo_refuses_to_replace_a_new_target_head(
    db_session, test_project_id
):
    target_document, source_document = await _merge_documents(db_session, test_project_id)
    target_id, target_saved = await _saved_node(
        db_session, test_project_id, "目标地图", target_document
    )
    source_id, _ = await _saved_node(
        db_session, test_project_id, "来源地图", source_document
    )
    service = MapNodeMergeService()
    preview = await service.preview(db_session, test_project_id, source_id, target_id)
    merged = await service.apply(
        db_session,
        test_project_id,
        MapNodeMergeApplyRequest(
            source_node_id=source_id,
            target_node_id=target_id,
            preview_fingerprint=preview.fingerprint,
            confirmed_source_disposition=True,
        ),
    )
    changed_target = target_document.model_copy(
        update={
            "features": [
                target_document.features[0].model_copy(
                    update={"label": "合并后的新修改"}
                ),
                *target_document.features[1:],
            ]
        }
    )
    await MapStructureService().save(
        db_session,
        test_project_id,
        target_id,
        MapSaveRequest(
            base_revision_id=uuid.UUID(merged["merged_revision_id"]),
            document=changed_target,
        ),
    )

    undo_preview = await service.preview_undo(
        db_session, test_project_id, source_id, target_id
    )

    assert not undo_preview.can_undo
    assert any("已有新变化" in blocker for blocker in undo_preview.blockers)
    with pytest.raises(ConflictError, match="不能自动撤回"):
        await service.undo(
            db_session,
            test_project_id,
            MapNodeMergeUndoRequest(
                source_node_id=source_id,
                target_node_id=target_id,
                preview_fingerprint=undo_preview.fingerprint,
                confirmed=True,
            ),
        )
    target = await db_session.get(MapAtlasNode, uuid.UUID(target_id))
    assert target is not None and target.current_revision_id != target_saved.id


@pytest.mark.asyncio
async def test_assistant_merge_operation_previews_and_confirms_source_disposition(
    db_session, test_project_id
):
    target_document, source_document = await _merge_documents(db_session, test_project_id)
    target_id, _ = await _saved_node(
        db_session, test_project_id, "目标地图", target_document
    )
    source_id, _ = await _saved_node(
        db_session, test_project_id, "来源地图", source_document
    )
    context = AssistantOperationContext(
        str(uuid.uuid4()),
        str(current_account_id()),
        WorkContext(page="map", scope="project"),
    )
    operation = world_map_operations["map.merge_nodes"]
    args = PreviewMapNodeMerge(
        source_node_id=uuid.UUID(source_id),
        target_node_id=uuid.UUID(target_id),
    )

    preview = await operation.prepare(db_session, test_project_id, args, context=context)

    assert preview["can_execute_merge"] is True
    assert preview["affected_count"] == 7
    assert preview["requires_source_disposition_confirmation"] is True
    result = await operation.apply(
        db_session, test_project_id, args, preview, context=context
    )
    source = await db_session.get(MapAtlasNode, uuid.UUID(source_id))
    target = await db_session.get(MapAtlasNode, uuid.UUID(target_id))
    assert result["type"] == "map_node_merge"
    assert source is not None and target is not None
    assert source.merged_into_node_id == target.id


@pytest.mark.asyncio
async def test_node_merge_api_preview_execute_and_undo_routes(
    async_client, db_session, test_project_id
):
    target_document, source_document = await _merge_documents(db_session, test_project_id)
    target_id, _ = await _saved_node(
        db_session, test_project_id, "目标地图", target_document
    )
    source_id, _ = await _saved_node(
        db_session, test_project_id, "来源地图", source_document
    )
    base = f"/api/world/map-atlas/{test_project_id}/nodes"
    pair = {"source_node_id": source_id, "target_node_id": target_id}

    preview_response = await async_client.post(f"{base}/merge-preview", json=pair)
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["can_execute"] is True
    assert preview["affected_count"] == 7

    merge_response = await async_client.post(
        f"{base}/merge",
        json={
            **pair,
            "preview_fingerprint": preview["fingerprint"],
            "confirmed_source_disposition": True,
        },
    )
    assert merge_response.status_code == 201, merge_response.text
    merged = merge_response.json()
    assert merged["type"] == "map_node_merge"

    undo_preview_response = await async_client.post(
        f"{base}/merge-undo-preview", json=pair
    )
    assert undo_preview_response.status_code == 200, undo_preview_response.text
    undo_preview = undo_preview_response.json()
    assert undo_preview["can_undo"] is True
    assert undo_preview["affected_count"] == 7
    undo_response = await async_client.post(
        f"{base}/merge-undo",
        json={
            **pair,
            "preview_fingerprint": undo_preview["fingerprint"],
            "confirmed": True,
        },
    )
    assert undo_response.status_code == 200, undo_response.text
    assert undo_response.json()["restored_revision_id"]


@pytest.mark.asyncio
async def test_demo_copy_preserves_merge_redirect_with_destination_owned_ids(
    db_session, monkeypatch
):
    from core.config import get_settings
    from modules.account.context import bind_principal, reset_principal
    from modules.project.demo_copy import DemoProjectCopyService
    from modules.project.tests.test_demo_copy import _principal, _seed_source

    source_owner, target_owner, source_project = await _seed_source(db_session)
    novel_id = str(source_project.id)
    monkeypatch.setenv("AUTH_MODE", "local")
    get_settings.cache_clear()
    source_token = bind_principal(_principal(source_owner))
    try:
        source_entity = await db_session.scalar(
            select(CoreEntity).where(
                CoreEntity.novel_id == source_project.id,
                CoreEntity.name == "雾港",
            )
        )
        assert source_entity is not None
        source_entity.summary = "来源记载"
        await db_session.flush()
        target_document, source_document = await _merge_documents(
            db_session, novel_id, source_entity=source_entity
        )
        target_id, _ = await _saved_node(
            db_session, novel_id, "目标地图", target_document
        )
        source_id, _ = await _saved_node(
            db_session, novel_id, "来源地图", source_document
        )
        preview = await MapNodeMergeService().preview(
            db_session, novel_id, source_id, target_id
        )
        await MapNodeMergeService().apply(
            db_session,
            novel_id,
            MapNodeMergeApplyRequest(
                source_node_id=source_id,
                target_node_id=target_id,
                preview_fingerprint=preview.fingerprint,
                confirmed_source_disposition=True,
            ),
        )
        source_before = await db_session.get(MapAtlasNode, uuid.UUID(source_id))
    finally:
        reset_principal(source_token)
    get_settings.cache_clear()
    assert source_before is not None and source_before.merge_metadata is not None
    original_receipt = source_before.merge_metadata

    monkeypatch.setenv("PUBLIC_DEMO_ENABLED", "true")
    monkeypatch.setenv("PUBLIC_DEMO_PROJECT_ID", novel_id)
    monkeypatch.setenv("PUBLIC_DEMO_VERSION", "2026-10-15")
    get_settings.cache_clear()
    token = bind_principal(_principal(target_owner))
    try:
        copied = await DemoProjectCopyService().copy(db_session)
    finally:
        reset_principal(token)
        get_settings.cache_clear()

    copied_novel_id = uuid.UUID(copied.project.id)
    copied_nodes = list(
        (
            await db_session.scalars(
                select(MapAtlasNode).where(MapAtlasNode.novel_id == copied_novel_id)
            )
        ).all()
    )
    by_title = {node.title: node for node in copied_nodes}
    copied_source = by_title["来源地图"]
    copied_target = by_title["目标地图"]
    assert len(copied_nodes) == 2
    assert copied_source.merged_into_node_id == copied_target.id
    assert copied_source.merged_into_node_id != uuid.UUID(target_id)
    assert copied_source.current_revision_id != source_before.current_revision_id
    assert copied_source.merge_metadata is not None
    for key in (
        "source_revision_id",
        "target_previous_revision_id",
        "target_merged_revision_id",
    ):
        assert copied_source.merge_metadata[key] != original_receipt[key]
    copied_revision_ids = {
        revision.id
        for revision in (
            await db_session.scalars(
                select(MapAtlasRevision).where(
                    MapAtlasRevision.novel_id == copied_novel_id
                )
            )
        ).all()
    }
    assert {
        uuid.UUID(copied_source.merge_metadata[key])
        for key in (
            "source_revision_id",
            "target_previous_revision_id",
            "target_merged_revision_id",
        )
    }.issubset(copied_revision_ids)
    copied_source_revision = await db_session.get(
        MapAtlasRevision, copied_source.current_revision_id
    )
    assert copied_source_revision is not None
    copied_document = MapDocument.model_validate(copied_source_revision.document)
    copied_entity_feature = next(
        feature for feature in copied_document.features if feature.entity_id is not None
    )
    assert copied_entity_feature.entity_id != source_entity.id
    tree_token = bind_principal(_principal(target_owner))
    try:
        tree = await MapAtlasService().get_tree(db_session, str(copied_novel_id))
        undo_preview = await MapNodeMergeService().preview_undo(
            db_session, str(copied_novel_id), copied_source.id, copied_target.id
        )
        assert undo_preview.can_undo, undo_preview.blockers
        undo_result = await MapNodeMergeService().undo(
            db_session,
            str(copied_novel_id),
            MapNodeMergeUndoRequest(
                source_node_id=copied_source.id,
                target_node_id=copied_target.id,
                preview_fingerprint=undo_preview.fingerprint,
                confirmed=True,
            ),
        )
    finally:
        reset_principal(tree_token)
    assert {node["id"] for node in _walk(tree["nodes"])} == {str(copied_target.id)}
    await db_session.refresh(copied_source)
    await db_session.refresh(copied_target)
    assert copied_source.merged_into_node_id is None
    assert copied_target.current_revision_id == uuid.UUID(
        undo_result["restored_revision_id"]
    )
    # Demo copy rewrites embedded entity IDs, so the copied hash must describe
    # the copied document rather than the source project's original identities.
    assert geometry_hash(copied_document) == copied_source_revision.geometry_hash


def test_node_merge_request_schemas_reject_unknown_or_malformed_fingerprints():
    with pytest.raises(ValueError):
        MapNodeMergePreviewRequest.model_validate(
            {
                "source_node_id": str(uuid.uuid4()),
                "target_node_id": str(uuid.uuid4()),
                "move_calibration": True,
            }
        )
    with pytest.raises(ValueError):
        MapNodeMergeApplyRequest(
            source_node_id=uuid.uuid4(),
            target_node_id=uuid.uuid4(),
            preview_fingerprint="stale",
            confirmed_source_disposition=True,
        )
