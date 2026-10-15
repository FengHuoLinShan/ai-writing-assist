from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from pydantic import ValidationError as SchemaError

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.world.map_atlas_models import (
    MapAtlasNode,
    MapAtlasPage,
    MapAtlasRevision,
    MapAtlasRun,
)
from modules.world.map_atlas_schemas import MapAtlasNodeUpdate
from modules.world.map_atlas_service import MapAtlasService, _path_part
from modules.world.map_structure_geometry import (
    affine_transform,
    geometry_hash,
    layout,
    render_structure_png,
)
from modules.world.map_structure_schemas import (
    MapDocument,
    MapImagePlacement,
    MapNodeCreate,
    MapRevisionReview,
    MapSaveRequest,
    MapSource,
    SpatialJourney,
)
from modules.world.map_structure_service import MapStructureService
from modules.world.project_vocabulary_schemas import (
    VocabularyTermCreate,
    VocabularyTermUpdate,
    VocabularyTraits,
)
from modules.world.project_vocabulary_service import (
    archive_project_vocabulary_term,
    create_project_vocabulary_term,
    update_project_vocabulary_term,
)


def document():
    return MapDocument.model_validate(
        {
            "features": [
                {
                    "id": "harbor",
                    "kind": "location",
                    "label": "临江城",
                    "points": [{"x": 100, "y": 100}],
                    "locked": True,
                    "reader_from_chapter": 1,
                },
                {
                    "id": "pass",
                    "kind": "location",
                    "label": "黑石关",
                    "points": [{"x": 300, "y": 100}],
                    "reader_from_chapter": 1,
                },
                {
                    "id": "fort",
                    "kind": "location",
                    "label": "北堡",
                    "points": [{"x": 100, "y": 300}],
                    "reader_from_chapter": 5,
                },
            ]
        }
    )


def image_placement(page_id=None):
    return MapImagePlacement.model_validate(
        {
            "page_id": str(page_id or uuid.uuid4()),
            "role": "background",
            "anchors": [
                {"feature_id": "harbor", "image_x": 0, "image_y": 0},
                {"feature_id": "pass", "image_x": 1, "image_y": 0},
                {"feature_id": "fort", "image_x": 0, "image_y": 1},
            ],
        }
    )


async def create_map(db, project_id):
    service = MapStructureService()
    node = await service.create_node(db, project_id, MapNodeCreate(title="三河区域"))
    return service, node


def test_layout_is_stable_preserves_existing_points_and_explicit_routes():
    source = MapDocument.model_validate(
        {
            "features": [
                {"id": "a", "kind": "location", "label": "甲城"},
                {"id": "b", "kind": "location", "label": "乙城"},
            ],
            "constraints": [
                {"id": "direction", "subject": "b", "relation": "north", "target": "a"},
                {"id": "road", "subject": "a", "relation": "connects", "target": "b"},
            ],
        }
    )
    first = layout(source)
    assert not first.problems
    assert first.model_dump() == layout(source).model_dump()
    assert first.document.features[1].points[0].y < first.document.features[0].points[0].y
    assert first.document.features[2].kind == "road"
    assert first.document.features[2].depends_on == ["a", "b"]
    updated = first.document.model_dump()
    updated["features"].append({"id": "c", "kind": "location", "label": "丙城"})
    second = layout(MapDocument.model_validate(updated))
    assert [f.points for f in second.document.features[:2]] == [
        f.points for f in first.document.features[:2]
    ]


@pytest.mark.asyncio
async def test_spatial_service_uses_pinned_active_type_traits_only(
    db_session, test_project_id
):
    feature_type = await create_project_vocabulary_term(
        db_session,
        test_project_id,
        VocabularyTermCreate(
            kind="feature",
            name="点状地点",
            traits=VocabularyTraits(geometry=["point"]),
        ),
    )
    relation_type = await create_project_vocabulary_term(
        db_session,
        test_project_id,
        VocabularyTermCreate(
            kind="relation",
            name="北向关系",
            traits=VocabularyTraits(orientation=["compass"]),
        ),
    )
    changed_feature_type = await update_project_vocabulary_term(
        db_session,
        test_project_id,
        str(feature_type.id),
        VocabularyTermUpdate(
            name="文字地点",
            description="",
            aliases=[],
            traits=VocabularyTraits(),
            expected_revision_id=feature_type.revision_id,
        ),
    )
    changed_relation_type = await update_project_vocabulary_term(
        db_session,
        test_project_id,
        str(relation_type.id),
        VocabularyTermUpdate(
            name="普通关系",
            description="",
            aliases=[],
            traits=VocabularyTraits(),
            expected_revision_id=relation_type.revision_id,
        ),
    )
    service, node = await create_map(db_session, test_project_id)
    document_with_old_revisions = MapDocument.model_validate(
        {
            "schema_version": 2,
            "features": [
                {
                    "id": "a",
                    "kind": "location",
                    "label": "甲",
                    "type_ref": str(feature_type.id),
                    "type_revision_id": str(feature_type.revision_id),
                    "points": [{"x": 0, "y": 100}],
                },
                {
                    "id": "b",
                    "kind": "location",
                    "label": "乙",
                    "type_ref": str(feature_type.id),
                    "type_revision_id": str(feature_type.revision_id),
                    "points": [{"x": 0, "y": 0}],
                },
            ],
            "constraints": [
                {
                    "id": "north",
                    "subject": "a",
                    "relation": "north",
                    "target": "b",
                    "type_ref": str(relation_type.id),
                    "type_revision_id": str(relation_type.revision_id),
                }
            ],
        }
    )
    request = MapSaveRequest(
        base_revision_id=node["current_revision_id"],
        document=document_with_old_revisions,
    )

    old_revision_result = await service.preview_layout(
        db_session, test_project_id, node["id"], request
    )
    assert any(
        problem.code == "direction_conflict" for problem in old_revision_result.problems
    )
    assert changed_feature_type.revision_id != feature_type.revision_id
    assert changed_relation_type.revision_id != relation_type.revision_id

    saved = await service.save(db_session, test_project_id, node["id"], request)
    assert "direction_conflict" in {item.code for item in saved.problems}
    request.base_revision_id = uuid.UUID(saved.id)

    archived = await archive_project_vocabulary_term(
        db_session,
        test_project_id,
        str(feature_type.id),
        changed_feature_type.revision_id,
    )
    archived_result = await service.preview_layout(
        db_session, test_project_id, node["id"], request
    )
    assert not any(
        problem.code == "direction_conflict" for problem in archived_result.problems
    )
    assert any(
        problem.code == "spatial_type_not_computable"
        for problem in archived_result.problems
    )
    assert archived.status == "archived"
    current = await service.get_map(db_session, test_project_id, node["id"])
    historic = await service.preview_revision(
        db_session, test_project_id, node["id"], saved.id
    )
    assert "direction_conflict" not in {item.code for item in current.revision.problems}
    assert "direction_conflict" not in {item.code for item in historic.problems}


@pytest.mark.asyncio
async def test_atlas_node_persists_a_revision_pinned_custom_level(
    db_session, test_project_id
):
    level_type = await create_project_vocabulary_term(
        db_session,
        test_project_id,
        VocabularyTermCreate(kind="level", name="浮空群岛"),
    )
    service = MapStructureService()

    node = await service.create_node(
        db_session,
        test_project_id,
        MapNodeCreate(
            title="天穹群岛",
            level="region",
            level_type_ref=level_type.id,
            level_type_revision_id=level_type.revision_id,
        ),
    )

    stored = await db_session.get(MapAtlasNode, uuid.UUID(node["id"]))
    assert stored.level == "region"
    assert stored.level_type_ref == level_type.id
    assert stored.level_type_revision_id == level_type.revision_id
    assert node["level_type_ref"] == str(level_type.id)


def test_contradictory_directions_stay_unplaced():
    source = MapDocument.model_validate(
        {
            "features": [
                {"id": "a", "kind": "location", "label": "甲"},
                {"id": "b", "kind": "location", "label": "乙"},
            ],
            "constraints": [
                {"id": "east1", "subject": "a", "relation": "east", "target": "b"},
                {"id": "east2", "subject": "b", "relation": "east", "target": "a"},
            ],
        }
    )
    result = layout(source)
    assert "direction_cycle" in {p.code for p in result.problems}
    assert all(not f.points for f in result.document.features)


@pytest.mark.parametrize(
    "patch",
    [
        {
            "features": [
                {
                    "id": "a",
                    "kind": "location",
                    "label": "bad",
                    "points": [{"x": float("nan"), "y": 0}],
                }
            ]
        },
        {
            "constraints": [
                {"id": "bad", "subject": "absent", "target": "harbor", "relation": "east"}
            ]
        },
        {"script": "alert(1)"},
    ],
)
def test_document_rejects_invalid_geometry_refs_and_executable_payload(patch):
    with pytest.raises(SchemaError):
        MapDocument.model_validate({**document().model_dump(), **patch})


def test_affine_calibration_and_structure_fingerprint():
    original = document()
    matrix = affine_transform(image_placement(), original)
    assert matrix == [200, 0, 0, 200, 100, 100]
    with_image = original.model_copy(deep=True)
    with_image.images = [image_placement()]
    with_image.features[0].reader_from_chapter = 3
    from modules.world.map_structure_schemas import MapSource

    with_image.features[0].sources = [
        MapSource(kind="entity", id=uuid.uuid4(), source_hash="a" * 64)
    ]
    with_image.images[0].opacity = 0.2
    assert geometry_hash(original) == geometry_hash(with_image)
    with_image.features[0].points[0].x += 1
    assert geometry_hash(original) != geometry_hash(with_image)
    invalid = image_placement()
    invalid.anchors[2].image_x, invalid.anchors[2].image_y = 0.5, 0
    with pytest.raises(ValueError, match="共线"):
        affine_transform(invalid, original)
    assert render_structure_png(original).startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.asyncio
async def test_manual_map_needs_no_image_run_and_is_in_existing_tree(
    db_session, test_project_id
):
    service, node = await create_map(db_session, test_project_id)
    state = await service.get_map(db_session, test_project_id, node["id"])
    assert state.revision.document.features == []
    model = await db_session.get(MapAtlasNode, uuid.UUID(node["id"]))
    assert model.created_by_run_id is None
    tree = await MapAtlasService().get_tree(db_session, test_project_id)
    assert tree["total_pages"] == 0
    assert tree["nodes"][0]["id"] == node["id"]
    child = await service.create_node(
        db_session,
        test_project_id,
        MapNodeCreate(title="临江城", level="city", parent_id=node["id"]),
    )
    tree = await MapAtlasService().get_tree(db_session, test_project_id)
    assert tree["nodes"][0]["children"][0]["id"] == child["id"]


@pytest.mark.asyncio
async def test_manual_map_can_rename_move_and_reorder_with_cas(
    db_session, test_project_id, async_client
):
    structure, parent = await create_map(db_session, test_project_id)
    _, other = await create_map(db_session, test_project_id)
    child = await structure.create_node(
        db_session,
        test_project_id,
        MapNodeCreate(title="旧城图", level="city", parent_id=parent["id"]),
    )
    child_row = await db_session.get(MapAtlasNode, uuid.UUID(child["id"]))
    baseline = child_row.updated_at.isoformat()
    path = f"/api/world/map-atlas/{test_project_id}/nodes/{child['id']}"
    response = await async_client.patch(
        path,
        json={
            "title": "  城市位置示意  ",
            "parent_id": other["id"],
            "expected_updated_at": baseline,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "城市位置示意"
    assert response.json()["parent_id"] == other["id"]
    assert response.json()["current_revision_id"] == child["current_revision_id"]
    conflict = await async_client.patch(
        path,
        json={
            "title": "过期编辑",
            "expected_updated_at": baseline,
        },
    )
    assert conflict.status_code == 409
    other_row = await db_session.get(MapAtlasNode, uuid.UUID(other["id"]))
    updated = await MapAtlasService().update_node(
        db_session,
        test_project_id,
        other["id"],
        MapAtlasNodeUpdate(
            before_node_id=parent["id"], expected_updated_at=other_row.updated_at
        ),
    )
    tree = await MapAtlasService().get_tree(db_session, test_project_id)
    assert [node["id"] for node in tree["nodes"]] == [other["id"], parent["id"]]
    assert updated["sort_order"] == 0
    assert tree["nodes"][0]["children"][0]["title"] == "城市位置示意"


@pytest.mark.asyncio
async def test_spatial_node_level_changes_preserve_editing(
    db_session, test_project_id, async_client
):
    service, node = await create_map(db_session, test_project_id)
    path = f"/api/world/map-atlas/{test_project_id}/nodes/{node['id']}"
    row = await db_session.get(MapAtlasNode, uuid.UUID(node["id"]))
    baseline = row.updated_at.isoformat()
    for level in ("cover", "world"):
        response = await async_client.patch(
            path,
            json={
                "title": "不能覆盖的名称",
                "level": level,
                "expected_updated_at": baseline,
            },
        )
        assert response.status_code == 400, response.text
        assert row.level == "region"
        assert row.title == node["title"]
        assert str(row.current_revision_id) == node["current_revision_id"]
    response = await async_client.patch(
        path,
        json={"level": "interior", "expected_updated_at": baseline},
    )
    assert response.status_code == 200, response.text
    saved = await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(base_revision_id=node["current_revision_id"], document=document()),
    )
    assert saved.document.features
    image_only = MapAtlasNode(
        novel_id=uuid.UUID(test_project_id),
        semantic_key=f"manual:{uuid.uuid4()}",
        title="旧街区图片",
        level="district",
        status="adopted",
    )
    db_session.add(image_only)
    await db_session.flush()
    updated = await MapAtlasService().update_node(
        db_session,
        test_project_id,
        str(image_only.id),
        MapAtlasNodeUpdate(level="street", expected_updated_at=image_only.updated_at),
    )
    assert updated["level"] == "street"


@pytest.mark.asyncio
async def test_interior_map_can_be_created_saved_and_keeps_hierarchy(
    db_session, test_project_id
):
    service, parent = await create_map(db_session, test_project_id)
    room = await service.create_node(
        db_session,
        test_project_id,
        MapNodeCreate(title="租住公寓", level="interior", parent_id=parent["id"]),
    )
    saved = await service.save(
        db_session,
        test_project_id,
        room["id"],
        MapSaveRequest(base_revision_id=room["current_revision_id"], document=document()),
    )
    assert saved.document.features
    with pytest.raises(ValidationError):
        await service.create_node(
            db_session,
            test_project_id,
            MapNodeCreate(title="非法街道子图", level="street", parent_id=room["id"]),
        )


@pytest.mark.asyncio
async def test_path_node_rename_and_move_rewrite_only_actual_path_descendants(
    db_session, test_project_id
):
    nodes = []
    for title, level in (("旧世界", "world"), ("地区", "region"), ("城", "city")):
        parent = nodes[-1] if nodes else None
        parent_key = parent.semantic_key if parent else "root"
        node = MapAtlasNode(
            novel_id=uuid.UUID(test_project_id),
            semantic_key=f"path:{parent_key}:{_path_part(title)}",
            title=title,
            level=level,
            parent_id=parent.id if parent else None,
            status="adopted",
        )
        db_session.add(node)
        await db_session.flush()
        nodes.append(node)
    root, region, city = nodes
    _, destination = await create_map(db_session, test_project_id)
    # A legacy key can share the text prefix without belonging to this subtree.
    unrelated = MapAtlasNode(
        novel_id=uuid.UUID(test_project_id),
        semantic_key=f"{root.semantic_key}:unrelated",
        title="独立区域",
        level="region",
        status="adopted",
    )
    fixed_identity = MapAtlasNode(
        novel_id=uuid.UUID(test_project_id),
        semantic_key=f"manual:{uuid.uuid4()}",
        title="手工图",
        level="region",
        parent_id=root.id,
        status="adopted",
    )
    db_session.add_all([unrelated, fixed_identity])
    await db_session.flush()
    preserved = (unrelated.semantic_key, fixed_identity.semantic_key)
    service = MapAtlasService()
    await service.update_node(
        db_session,
        test_project_id,
        str(root.id),
        MapAtlasNodeUpdate(title="新世界", expected_updated_at=root.updated_at),
    )
    assert root.semantic_key == f"path:root:{_path_part('新世界')}"
    assert region.semantic_key == f"path:{root.semantic_key}:{_path_part('地区')}"
    assert city.semantic_key == f"path:{region.semantic_key}:{_path_part('城')}"
    await service.update_node(
        db_session,
        test_project_id,
        str(city.id),
        MapAtlasNodeUpdate(
            parent_id=destination["id"], expected_updated_at=city.updated_at
        ),
    )
    destination_row = await db_session.get(MapAtlasNode, uuid.UUID(destination["id"]))
    assert city.semantic_key == f"path:{destination_row.semantic_key}:{_path_part('城')}"
    assert (unrelated.semantic_key, fixed_identity.semantic_key) == preserved


@pytest.mark.asyncio
async def test_manual_node_update_preserves_hierarchy_and_project_boundaries(
    db_session, test_project_id, project_factory
):
    structure, parent = await create_map(db_session, test_project_id)
    child = await structure.create_node(
        db_session,
        test_project_id,
        MapNodeCreate(title="城", level="city", parent_id=parent["id"]),
    )
    foreign_id = str(await project_factory.create_project())
    _, foreign = await create_map(db_session, foreign_id)
    service = MapAtlasService()
    row = await db_session.get(MapAtlasNode, uuid.UUID(parent["id"]))
    for update_fields in (
        {"parent_id": parent["id"]},
        {"parent_id": child["id"]},
        {"parent_id": foreign["id"]},
        {"before_node_id": foreign["id"]},
        {"level": "district"},
    ):
        with pytest.raises(ValidationError):
            await service.update_node(
                db_session,
                test_project_id,
                parent["id"],
                MapAtlasNodeUpdate(expected_updated_at=row.updated_at, **update_fields),
            )
    with pytest.raises(NotFoundError):
        await service.update_node(
            db_session,
            test_project_id,
            foreign["id"],
            MapAtlasNodeUpdate(title="越界", expected_updated_at=foreign["updated_at"]),
        )
    assert row.parent_id is None
    assert row.level == "region"


@pytest.mark.asyncio
async def test_map_title_update_does_not_rename_bound_world_location(
    db_session, test_project_id
):
    from modules.world.models import CoreEntity

    entity = CoreEntity(
        novel_id=uuid.UUID(test_project_id),
        entity_type="location",
        name="廷根",
        status="canonical",
    )
    db_session.add(entity)
    await db_session.flush()
    node = await MapStructureService().create_node(
        db_session,
        test_project_id,
        MapNodeCreate(title="廷根", level="city", location_entity_id=entity.id),
    )
    row = await db_session.get(MapAtlasNode, uuid.UUID(node["id"]))
    with pytest.raises(ValidationError, match="绑定世界地点"):
        await MapAtlasService().update_node(
            db_session,
            test_project_id,
            node["id"],
            MapAtlasNodeUpdate(title="改名", expected_updated_at=row.updated_at),
        )
    assert entity.name == "廷根"
    assert (await db_session.get(MapAtlasNode, uuid.UUID(node["id"]))).title == "廷根"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "feature_qualifiers",
    [
        {},
        {"modality": "belief"},
        {"effective": {"start": {"kind": "scene", "id": str(uuid.UUID(int=99))}}},
    ],
)
async def test_continuity_facts_require_current_adopted_revision_and_sources(
    db_session, test_project_id, feature_qualifiers
):
    from modules.world.facade import list_adopted_map_continuity_facts
    from modules.world.map_structure_service import source_digest, source_payload
    from modules.world.models import CoreEntity

    source = CoreEntity(
        novel_id=uuid.UUID(test_project_id),
        entity_type="location",
        name="道路志",
        summary="甲城与乙城由北道相连。",
        status="canonical",
    )
    start = CoreEntity(
        novel_id=uuid.UUID(test_project_id),
        entity_type="location",
        name="甲城",
        status="canonical",
    )
    end = CoreEntity(
        novel_id=uuid.UUID(test_project_id),
        entity_type="location",
        name="乙城",
        status="canonical",
    )
    db_session.add_all([source, start, end])
    await db_session.flush()
    relation_type = await create_project_vocabulary_term(
        db_session,
        test_project_id,
        VocabularyTermCreate(
            kind="relation",
            name="可通行连通",
            traits=VocabularyTraits(connection=["traversable"]),
        ),
    )
    node = await MapStructureService().create_node(
        db_session,
        test_project_id,
        MapNodeCreate(title="北道", level="region"),
    )
    document = MapDocument(
        features=[
            {
                "id": "start",
                "kind": "location",
                "label": "甲城",
                "entity_id": start.id,
                **feature_qualifiers,
            },
            {
                "id": "end",
                "kind": "location",
                "label": "乙城",
                "entity_id": end.id,
            },
        ],
        constraints=[
            {
                "id": "north-road",
                "subject": "start",
                "relation": "connects",
                "target": "end",
                "type_ref": str(relation_type.id),
                "type_revision_id": str(relation_type.revision_id),
                "sources": [
                    {
                        "kind": "entity",
                        "id": source.id,
                        "source_hash": source_digest(source_payload(source)),
                    }
                ],
            }
        ],
    )
    await MapStructureService().save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(
            base_revision_id=node["current_revision_id"],
            document=document,
        ),
    )

    facts = await list_adopted_map_continuity_facts(
        db_session,
        test_project_id,
        [str(start.id), str(end.id)],
    )

    if feature_qualifiers:
        assert facts == []
        return
    assert len(facts) == 1
    assert facts[0].relation == "connects"
    assert facts[0].subject_entity_id == str(start.id)
    assert facts[0].target_entity_id == str(end.id)
    assert facts[0].source_hashes

    await archive_project_vocabulary_term(
        db_session,
        test_project_id,
        str(relation_type.id),
        relation_type.revision_id,
    )
    assert (
        await list_adopted_map_continuity_facts(
            db_session,
            test_project_id,
            [str(start.id), str(end.id)],
        )
        == []
    )

    source.summary = "来源已修改。"
    await db_session.flush()
    assert (
        await list_adopted_map_continuity_facts(
            db_session,
            test_project_id,
            [str(start.id), str(end.id)],
        )
        == []
    )


@pytest.mark.asyncio
async def test_map_read_and_node_update_require_current_owner(
    db_session, test_project_id
):
    from modules.account.context import bind_principal, reset_principal
    from modules.account.contracts import AccountPrincipal

    service, node = await create_map(db_session, test_project_id)
    token = bind_principal(
        AccountPrincipal(
            account_id=uuid.uuid4(),
            status="active",
            identity_type="email",
            support_code="MAP-OTHER-OWNER",
        )
    )
    try:
        with pytest.raises(NotFoundError):
            await service.get_map(db_session, test_project_id, node["id"])
        with pytest.raises(NotFoundError):
            await MapAtlasService().update_node(
                db_session,
                test_project_id,
                node["id"],
                MapAtlasNodeUpdate(title="越权", expected_updated_at=node["updated_at"]),
            )
    finally:
        reset_principal(token)


@pytest.mark.asyncio
@pytest.mark.parametrize("run_kind", [None, "initial", "upload"])
async def test_only_uploaded_provisional_nodes_allow_manual_changes(
    db_session, test_project_id, run_kind
):
    run = None
    if run_kind:
        run = MapAtlasRun(
            novel_id=uuid.UUID(test_project_id), run_kind=run_kind, status="review_ready"
        )
        db_session.add(run)
        await db_session.flush()
    node = MapAtlasNode(
        novel_id=uuid.UUID(test_project_id),
        created_by_run_id=run.id if run else None,
        semantic_key=f"manual:{uuid.uuid4()}",
        title="候选图",
        level="region",
        status="provisional",
    )
    db_session.add(node)
    await db_session.flush()
    request = MapAtlasNodeUpdate(title="手工改名", expected_updated_at=node.updated_at)
    service = MapAtlasService()
    if run_kind != "upload":
        with pytest.raises(ConflictError, match="候选节点不能手动调整"):
            await service.update_node(db_session, test_project_id, str(node.id), request)
        assert node.title == "候选图"
    else:
        updated = await service.update_node(
            db_session, test_project_id, str(node.id), request
        )
        assert updated["title"] == "手工改名"


@pytest.mark.asyncio
async def test_save_cas_and_append_only_restore(db_session, test_project_id):
    service, node = await create_map(db_session, test_project_id)
    baseline = uuid.UUID(node["current_revision_id"])
    saved = await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(base_revision_id=baseline, document=document()),
    )
    with pytest.raises(ConflictError):
        await service.save(
            db_session,
            test_project_id,
            node["id"],
            MapSaveRequest(base_revision_id=baseline, document=document()),
        )
    restored = await service.review(
        db_session,
        test_project_id,
        node["id"],
        str(baseline),
        MapRevisionReview(base_revision_id=saved.id, action="restore"),
    )
    assert restored.id not in {str(baseline), saved.id}
    assert restored.document.features == []
    history = await service.history(db_session, test_project_id, node["id"])
    assert len(history) == 3
    assert (
        next(row for row in history if row.id == saved.id).document.features[0].label
        == "临江城"
    )


@pytest.mark.asyncio
async def test_candidate_cannot_replace_later_author_edits(db_session, test_project_id):
    service, node = await create_map(db_session, test_project_id)
    baseline = uuid.UUID(node["current_revision_id"])
    candidate = MapAtlasRevision(
        novel_id=uuid.UUID(test_project_id),
        node_id=uuid.UUID(node["id"]),
        base_revision_id=baseline,
        status="candidate",
        document=document().model_dump(mode="json"),
        geometry_hash=geometry_hash(document()),
        problems=[],
    )
    db_session.add(candidate)
    await db_session.flush()
    saved = await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(base_revision_id=baseline, document=document()),
    )
    with pytest.raises(ConflictError):
        await service.review(
            db_session,
            test_project_id,
            node["id"],
            str(candidate.id),
            MapRevisionReview(base_revision_id=saved.id, action="adopt"),
        )
    assert candidate.status == "candidate"


@pytest.mark.asyncio
async def test_map_rejects_foreign_node_revision_and_missing_entity(
    db_session, test_project_id
):
    service, node = await create_map(db_session, test_project_id)
    _, other = await create_map(db_session, test_project_id)
    with pytest.raises(NotFoundError):
        await service.revision(
            db_session, test_project_id, node["id"], other["current_revision_id"]
        )
    doc = document()
    doc.features[0].entity_id = uuid.uuid4()
    with pytest.raises(ValidationError):
        await service.save(
            db_session,
            test_project_id,
            node["id"],
            MapSaveRequest(base_revision_id=node["current_revision_id"], document=doc),
        )


@pytest.mark.asyncio
async def test_images_share_node_and_stale_background_is_disabled(
    db_session, test_project_id
):
    service, node = await create_map(db_session, test_project_id)
    run = MapAtlasRun(
        novel_id=uuid.UUID(test_project_id), run_kind="upload", status="review_ready"
    )
    db_session.add(run)
    await db_session.flush()
    page = MapAtlasPage(
        novel_id=run.novel_id,
        node_id=uuid.UUID(node["id"]),
        run_id=run.id,
        title="区域图",
        visual_brief="",
        prompt="",
        generation_status="review_ready",
        review_status="adopted",
        sha256="a" * 64,
    )
    db_session.add(page)
    await db_session.flush()
    doc = document()
    doc.images = [image_placement(page.id)]
    saved = await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(base_revision_id=node["current_revision_id"], document=doc),
    )
    state = await service.get_map(db_session, test_project_id, node["id"])
    assert state.image_layers[0]["transform"] == [200, 0, 0, 200, 100, 100]
    assert page.source_map_revision_id is None  # This image came from an upload.
    assert state.image_layers[0]["calibration_revision_id"] == saved.id
    assert state.image_layers[0]["calibration_lookup_status"] == "found"
    changed = saved.document.model_copy(deep=True)
    changed.features[0].points[0].x += 10
    await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(base_revision_id=saved.id, document=changed),
    )
    state = await service.get_map(db_session, test_project_id, node["id"])
    assert state.image_layers[0]["state"] == "stale"
    assert state.image_layers[0]["transform"] is None
    assert state.image_layers[0]["calibration_revision_id"] == saved.id
    historic = await service.preview_revision(
        db_session, test_project_id, node["id"], saved.id
    )
    assert historic.image_layers[0]["state"] == "ready"
    assert historic.image_layers[0]["calibration_revision_id"] == saved.id
    page.review_status = "deprecated"
    await db_session.flush()
    state = await service.get_map(db_session, test_project_id, node["id"])
    assert state.image_layers[0]["state"] == "unavailable"
    assert state.image_layers[0]["calibration_revision_id"] == saved.id
    assert (await MapAtlasService().get_tree(db_session, test_project_id))["nodes"]


@pytest.mark.asyncio
async def test_reader_projection_omits_hidden_endpoints_routes_and_source_fields(
    db_session, test_project_id
):
    service, node = await create_map(db_session, test_project_id)
    doc = document().model_dump(mode="json")
    doc["features"].append(
        {
            "id": "road",
            "kind": "road",
            "label": "秘密路线",
            "points": [{"x": 100, "y": 100}, {"x": 100, "y": 300}],
            "depends_on": ["harbor", "fort"],
            "reader_from_chapter": 1,
        }
    )
    await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(base_revision_id=node["current_revision_id"], document=doc),
    )
    early = await service.reader_preview(
        db_session, test_project_id, node["id"], chapter=1
    )
    assert {f["id"] for f in early["features"]} == {"harbor", "pass"}
    assert all(
        set(f) == {"id", "space_id", "kind", "label", "points"} for f in early["features"]
    )
    late = await service.reader_preview(
        db_session, test_project_id, node["id"], chapter=5
    )
    assert {f["id"] for f in late["features"]} == {"harbor", "pass", "fort", "road"}
    assert early["features"][0]["points"] == late["features"][0]["points"]


@pytest.mark.asyncio
async def test_reader_projection_includes_only_public_event_journeys(
    db_session, test_project_id
):
    service, node = await create_map(db_session, test_project_id)
    doc = document()
    source = MapSource(
        kind="entity",
        id=uuid.uuid4(),
        source_hash="a" * 64,
        quote="乘船半日可达",
    )
    doc.journeys = [
        SpatialJourney(
            id="ferry-trip",
            origin="harbor",
            destination="pass",
            transport_label="渡船",
            duration={"minimum": 0.5, "maximum": 1, "unit": "day"},
            sources=[source],
        ),
        SpatialJourney(
            id="rumored-trip",
            origin="harbor",
            destination="pass",
            transport_label="传闻中的暗道",
            modality="belief",
            sources=[source],
        ),
    ]
    with (
        patch.object(
            MapStructureService,
            "source",
            autospec=True,
            return_value="乘船半日可达",
        ),
        patch.object(
            MapStructureService,
            "reader_source_visible",
            autospec=True,
            return_value=True,
        ),
    ):
        saved = await service.save(
            db_session,
            test_project_id,
            node["id"],
            MapSaveRequest(base_revision_id=node["current_revision_id"], document=doc),
        )
        projection = await service.reader_preview(
            db_session, test_project_id, node["id"], chapter=1
        )

    assert [journey["id"] for journey in projection["journeys"]] == ["ferry-trip"]
    assert projection["journeys"][0]["duration"]["unit"] == "day"
    assert "sources" not in projection["journeys"][0]
    assert saved.document.journeys[0].id == "ferry-trip"


@pytest.mark.asyncio
async def test_node_http_create_save_and_layout(async_client, test_project_id):
    base = f"/api/world/map-atlas/{test_project_id}"
    created = await async_client.post(
        f"{base}/nodes", json={"title": "区域", "level": "region"}
    )
    assert created.status_code == 201, created.text
    node = created.json()
    response = await async_client.post(
        f"{base}/nodes/{node['id']}/revisions",
        json={
            "base_revision_id": node["current_revision_id"],
            "document": document().model_dump(mode="json"),
        },
    )
    assert response.status_code == 201, response.text
    state = await async_client.get(f"{base}/nodes/{node['id']}/map")
    assert state.status_code == 200, state.text
    assert len(state.json()["revision"]["document"]["features"]) == 3


@pytest.mark.asyncio
async def test_existing_stale_sources_remain_editable_but_cannot_be_copied_to_new_facts(
    db_session, test_project_id
):
    from modules.world.map_structure_schemas import MapSource
    from modules.world.map_structure_service import source_digest, source_payload
    from modules.world.models import CoreEntity

    service, node = await create_map(db_session, test_project_id)
    entity = CoreEntity(
        novel_id=uuid.UUID(test_project_id),
        entity_type="location",
        name="临江城",
        status="canonical",
        summary="旧记载",
        reveal_level="revealed",
    )
    db_session.add(entity)
    await db_session.flush()
    doc = document()
    doc.features[0].entity_id = entity.id
    doc.features[0].sources = [
        MapSource(
            kind="entity",
            id=entity.id,
            source_hash=source_digest(source_payload(entity)),
            quote="旧记载",
        )
    ]
    saved = await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(base_revision_id=node["current_revision_id"], document=doc),
    )
    entity.summary = "已经修改的记载"
    await db_session.flush()
    loaded = await service.get_map(db_session, test_project_id, node["id"])
    assert loaded.revision.id == saved.id
    assert [(p.code, p.feature_ids) for p in loaded.revision.problems] == [
        ("source_stale", ["harbor"])
    ]
    persisted = await db_session.get(MapAtlasRevision, uuid.UUID(saved.id))
    assert persisted.problems == []
    assert not db_session.dirty
    edited = saved.document.model_copy(deep=True)
    edited.features[0].points[0].x += 10
    retained = await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(base_revision_id=saved.id, document=edited),
    )
    assert "source_stale" in {problem.code for problem in retained.problems}
    projection = await service.reader_preview(
        db_session, test_project_id, node["id"], chapter=5
    )
    assert "harbor" not in {feature["id"] for feature in projection["features"]}
    copied = retained.document.model_copy(deep=True)
    copied.features.append(copied.features[0].model_copy(update={"id": "new-fact"}))
    with pytest.raises(ConflictError, match="资料已经变化"):
        await service.save(
            db_session,
            test_project_id,
            node["id"],
            MapSaveRequest(base_revision_id=retained.id, document=copied),
        )
    candidate = MapAtlasRevision(
        novel_id=uuid.UUID(test_project_id),
        node_id=uuid.UUID(node["id"]),
        base_revision_id=uuid.UUID(retained.id),
        status="candidate",
        document=retained.document.model_dump(mode="json"),
        geometry_hash=retained.geometry_hash,
        problems=[],
    )
    db_session.add(candidate)
    entity.status = "deprecated"
    await db_session.flush()
    unavailable = await service.get_map(db_session, test_project_id, node["id"])
    assert unavailable.revision.problems[0].code == "source_stale"
    assert unavailable.candidates[0].problems[0].code == "source_stale"
    assert candidate.problems == []
    entity.status, entity.summary = "canonical", "旧记载"
    await db_session.flush()
    recovered = await service.get_map(db_session, test_project_id, node["id"])
    assert recovered.revision.problems == []
    assert recovered.candidates[0].problems == []
    history = await service.history(db_session, test_project_id, node["id"])
    assert next(row for row in history if row.id == retained.id).problems
    assert not db_session.dirty


@pytest.mark.asyncio
async def test_bound_annotation_uses_spatial_coordinates_and_rejects_old_position_writer(
    db_session, test_project_id
):
    from modules.world.map_atlas_models import MapAtlasAnnotation
    from modules.world.map_atlas_schemas import MapAtlasAnnotationUpdate
    from modules.world.map_structure_schemas import MapAnnotationBinding

    service, node = await create_map(db_session, test_project_id)
    run = MapAtlasRun(
        novel_id=uuid.UUID(test_project_id), run_kind="upload", status="review_ready"
    )
    db_session.add(run)
    await db_session.flush()
    page = MapAtlasPage(
        novel_id=run.novel_id,
        run_id=run.id,
        node_id=uuid.UUID(node["id"]),
        title="已有图片",
        visual_brief="",
        prompt="",
        generation_status="review_ready",
        review_status="adopted",
    )
    db_session.add(page)
    await db_session.flush()
    annotation = MapAtlasAnnotation(
        novel_id=run.novel_id,
        page_id=page.id,
        label="旧名称",
        position_x=0.5,
        position_y=0.5,
    )
    db_session.add(annotation)
    await db_session.flush()
    doc = document()
    doc.images = [image_placement(page.id)]
    doc.annotation_bindings = [
        MapAnnotationBinding(annotation_id=annotation.id, feature_id="harbor")
    ]
    await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(base_revision_id=node["current_revision_id"], document=doc),
    )
    tree = await MapAtlasService().get_tree(db_session, test_project_id)
    bound = tree["nodes"][0]["pages"][0]["annotations"][0]
    assert bound["label"] == "临江城"
    assert bound["position_x"] == pytest.approx(0)
    assert bound["position_y"] == pytest.approx(0)
    assert bound["bound_feature_id"] == "harbor"
    with pytest.raises(ConflictError, match="绑定空间地点"):
        await MapAtlasService().update_annotation(
            db_session,
            test_project_id,
            str(annotation.id),
            MapAtlasAnnotationUpdate(
                expected_updated_at=annotation.updated_at, position_x=0.8
            ),
        )


def test_known_river_relations_generate_a_river_without_inventing_locations():
    doc = MapDocument.model_validate(
        {
            "features": [
                {"id": "a", "kind": "location", "label": "上游"},
                {"id": "b", "kind": "location", "label": "河口"},
            ],
            "constraints": [
                {
                    "id": "river",
                    "subject": "a",
                    "relation": "connects",
                    "target": "b",
                    "path_kind": "river",
                    "path_label": "青河",
                }
            ],
        }
    )
    result = layout(doc)
    assert len(result.document.features) == 3
    assert result.document.features[-1].kind == "river"
    assert result.document.features[-1].label == "青河"
    assert {f.id for f in result.document.features if f.kind == "location"} == {"a", "b"}


def test_structure_task_is_registered_with_project_scope():
    from app.task_runtime import register_task_handlers
    from infrastructure.tasks.registry import get_registry

    register_task_handlers()
    definition = get_registry().get_definition("world_map_schematic_generate")
    assert definition.owner_scope == "project"
    assert definition.recovery_policy == "manual_resume"
    assert definition.max_attempts == 4


async def test_calibration_history_requires_matching_owner_node_page_and_anchors(
    db_session,
    test_project_id,
    project_factory,
):
    from sqlalchemy import select

    service, node = await create_map(db_session, test_project_id)
    run = MapAtlasRun(
        novel_id=uuid.UUID(test_project_id), run_kind="upload", status="review_ready"
    )
    db_session.add(run)
    await db_session.flush()
    page = MapAtlasPage(
        novel_id=run.novel_id,
        node_id=uuid.UUID(node["id"]),
        run_id=run.id,
        title="上传底图",
        visual_brief="",
        prompt="",
        generation_status="review_ready",
        review_status="adopted",
    )
    db_session.add(page)
    await db_session.flush()
    doc = document()
    placement = image_placement(page.id)
    placement.geometry_hash = geometry_hash(doc)
    doc.images = [placement]
    _, other_node = await create_map(db_session, test_project_id)
    foreign_id = str(await project_factory.create_project())
    _, foreign_node = await create_map(db_session, foreign_id)
    variants = [
        (test_project_id, other_node["id"], "saved", {}),
        (foreign_id, foreign_node["id"], "saved", {}),
        (test_project_id, node["id"], "candidate", {}),
        (test_project_id, node["id"], "rejected", {}),
        (test_project_id, node["id"], "saved", {"page_id": str(uuid.uuid4())}),
        (test_project_id, node["id"], "saved", {"geometry_hash": "b" * 64}),
        (
            test_project_id,
            node["id"],
            "saved",
            {"anchors": [anchor.model_dump() for anchor in reversed(placement.anchors)]},
        ),
    ]
    for owner, target, status, change in variants:
        payload = doc.model_dump(mode="json")
        payload["images"][0].update(change)
        db_session.add(
            MapAtlasRevision(
                novel_id=uuid.UUID(owner),
                node_id=uuid.UUID(target),
                status=status,
                document=payload,
                geometry_hash=placement.geometry_hash,
                problems=[],
            )
        )
    await db_session.flush()
    before = list((await db_session.scalars(select(MapAtlasRevision.id))).all())
    layers = await service.image_layers(db_session, test_project_id, node["id"], doc)
    assert layers[0]["calibration_revision_id"] is None
    assert layers[0]["calibration_lookup_status"] == "not_found"
    assert list((await db_session.scalars(select(MapAtlasRevision.id))).all()) == before
    exact = MapAtlasRevision(
        novel_id=run.novel_id,
        node_id=page.node_id,
        status="saved",
        document=doc.model_dump(mode="json"),
        geometry_hash=placement.geometry_hash,
        problems=[],
    )
    db_session.add(exact)
    await db_session.flush()
    layers = await service.image_layers(db_session, test_project_id, node["id"], doc)
    assert layers[0]["calibration_revision_id"] == str(exact.id)
    assert layers[0]["calibration_lookup_status"] == "found"


async def test_calibration_history_reports_scan_truncation_without_loading_geometry(
    db_session,
    test_project_id,
    monkeypatch,
):
    from datetime import UTC, datetime, timedelta

    service, node = await create_map(db_session, test_project_id)
    run = MapAtlasRun(
        novel_id=uuid.UUID(test_project_id), run_kind="upload", status="review_ready"
    )
    db_session.add(run)
    await db_session.flush()
    page = MapAtlasPage(
        novel_id=run.novel_id,
        node_id=uuid.UUID(node["id"]),
        run_id=run.id,
        title="上传底图",
        visual_brief="",
        prompt="",
        generation_status="review_ready",
        review_status="adopted",
    )
    db_session.add(page)
    await db_session.flush()
    doc = document()
    placement = image_placement(page.id)
    placement.geometry_hash = geometry_hash(doc)
    doc.images = [placement]
    saved = []
    for index in range(3):
        payload = doc.model_dump(mode="json")
        if index:
            payload["images"][0]["anchors"][0]["image_x"] = index * 0.1
        row = MapAtlasRevision(
            novel_id=run.novel_id,
            node_id=page.node_id,
            status="saved",
            document=payload,
            geometry_hash=placement.geometry_hash,
            problems=[],
            created_at=datetime.now(UTC) + timedelta(seconds=index),
        )
        db_session.add(row)
        saved.append(row)
    await db_session.flush()
    monkeypatch.setattr(
        "modules.world.map_structure_service._CALIBRATION_HISTORY_LIMIT", 2
    )
    execute = db_session.execute
    selected_columns = []

    async def capture(statement, *args, **kwargs):
        selected_columns.append(list(statement.selected_columns))
        return await execute(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", capture)
    layers = await service.image_layers(db_session, test_project_id, node["id"], doc)
    assert layers[0]["calibration_revision_id"] is None
    assert layers[0]["calibration_lookup_status"] == "truncated"
    assert len(selected_columns[-1]) == 2
    assert selected_columns[-1][0].name == "id"
    assert selected_columns[-1][1].name == "images"
    monkeypatch.setattr(
        "modules.world.map_structure_service._CALIBRATION_HISTORY_LIMIT", 3
    )
    layers = await service.image_layers(db_session, test_project_id, node["id"], doc)
    assert layers[0]["calibration_revision_id"] == str(saved[0].id)
    assert layers[0]["calibration_lookup_status"] == "found"


@pytest.mark.asyncio
async def test_save_records_writing_chapter_index_and_history_notes(
    db_session, test_project_id
):
    """保存地图时记录当时写作进度；历史列表带备注。"""
    from modules.world.services.revision_notes import set_revision_note

    service, node = await create_map(db_session, test_project_id)
    baseline = uuid.UUID(node["current_revision_id"])

    # 无正文时初始保存的写作进度为 0。
    history = await service.history(db_session, test_project_id, node["id"])
    initial = next(row for row in history if row.id == str(baseline))
    assert initial.writing_chapter_index == 0

    from modules.writing.facade import create_published_draft_only

    await create_published_draft_only(
        db_session, test_project_id, 4, "第四章", "第四章的正文"
    )
    saved = await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(base_revision_id=baseline, document=document()),
    )
    assert saved.writing_chapter_index == 4

    await set_revision_note(db_session, test_project_id, "map", saved.id, "补画黑石关")
    history = await service.history(db_session, test_project_id, node["id"])
    saved_row = next(row for row in history if row.id == saved.id)
    assert saved_row.writing_chapter_index == 4
    assert saved_row.change_note == "补画黑石关"
    assert initial.change_note is None


@pytest.mark.asyncio
async def test_read_map_node_heads_returns_current_head_identity(
    db_session, test_project_id
):
    """G8b：批量 head 出口的常态——revision/采用状态/来源 hash 一次查询可取。"""
    from modules.world.facade import read_map_node_heads
    from modules.world.map_structure_service import source_digest, source_payload
    from modules.world.models import CoreEntity

    source = CoreEntity(
        novel_id=uuid.UUID(test_project_id),
        entity_type="location",
        name="道路志",
        summary="甲城与乙城由北道相连。",
        status="canonical",
    )
    start = CoreEntity(
        novel_id=uuid.UUID(test_project_id),
        entity_type="location",
        name="甲城",
        status="canonical",
    )
    end = CoreEntity(
        novel_id=uuid.UUID(test_project_id),
        entity_type="location",
        name="乙城",
        status="canonical",
    )
    db_session.add_all([source, start, end])
    await db_session.flush()
    node = await MapStructureService().create_node(
        db_session,
        test_project_id,
        MapNodeCreate(title="北道", level="region"),
    )
    digest = source_digest(source_payload(source))
    document = MapDocument(
        features=[
            {"id": "start", "kind": "location", "label": "甲城", "entity_id": start.id},
            {"id": "end", "kind": "location", "label": "乙城", "entity_id": end.id},
        ],
        constraints=[
            {
                "id": "north-road",
                "subject": "start",
                "relation": "connects",
                "target": "end",
                "sources": [{"kind": "entity", "id": source.id, "source_hash": digest}],
            }
        ],
    )
    saved = await MapStructureService().save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(base_revision_id=node["current_revision_id"], document=document),
    )

    heads = await read_map_node_heads(db_session, test_project_id, [node["id"]])

    assert set(heads) == {node["id"]}
    head = heads[node["id"]]
    assert head["status"] == "adopted"
    assert head["revision_id"] == saved.id != node["current_revision_id"]
    assert head["title"] == "北道"
    assert digest in head["source_hashes"]

    # 再次保存产生新 head：批量读取报告新 revision_id（geometry_hash 不作版本信号）。
    resaved = await MapStructureService().save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(base_revision_id=saved.id, document=document),
    )
    heads = await read_map_node_heads(
        db_session, test_project_id, [node["id"], node["id"]]
    )
    assert heads[node["id"]]["revision_id"] == resaved.id != saved.id


@pytest.mark.asyncio
async def test_read_map_node_heads_is_empty_for_unknown_unsaved_or_other_novel(
    db_session, two_projects
):
    """G8b：空态与跨项目隔离——空列表、未知节点、未保存 head、别的项目都不返回。"""
    from modules.world.facade import read_map_node_heads

    novel_id, other_novel_id = two_projects
    node = await MapStructureService().create_node(
        db_session,
        novel_id,
        MapNodeCreate(title="尚无结构的区域", level="region"),
    )

    assert await read_map_node_heads(db_session, novel_id, []) == {}
    assert await read_map_node_heads(db_session, novel_id, [str(uuid.uuid4())]) == {}
    # create_node 即落一个空文档 head（无来源）；跨项目读取不返回该节点。
    heads = await read_map_node_heads(db_session, novel_id, [node["id"]])
    assert set(heads) == {node["id"]}
    assert heads[node["id"]]["source_hashes"] == ()
    assert await read_map_node_heads(db_session, other_novel_id, [node["id"]]) == {}


async def test_reader_and_layout_exclude_archived_space_but_keep_its_author_document(
    db_session, test_project_id
):
    space_type = await create_project_vocabulary_term(
        db_session,
        test_project_id,
        VocabularyTermCreate(kind="space", name="梦境"),
    )
    service, node = await create_map(db_session, test_project_id)
    doc = document()
    doc.spaces[0].type_ref = space_type.id
    doc.spaces[0].type_revision_id = space_type.revision_id
    saved = await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(base_revision_id=node["current_revision_id"], document=doc),
    )
    assert (
        await service.reader_preview(db_session, test_project_id, node["id"], chapter=1)
    )["features"]
    await archive_project_vocabulary_term(
        db_session, test_project_id, str(space_type.id), space_type.revision_id
    )
    projection = await service.reader_preview(
        db_session, test_project_id, node["id"], chapter=1
    )
    assert projection["features"] == []
    unplaced = doc.model_copy(deep=True)
    for item in unplaced.features:
        item.points = []
    result = await service.preview_layout(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(base_revision_id=saved.id, document=unplaced),
    )
    assert all(not item.points for item in result.document.features)
    assert len(result.document.features) == 3
    assert any(
        problem.code == "spatial_type_not_computable" for problem in result.problems
    )


async def test_reader_journey_types_must_be_active_and_cross_space_connections_capable(
    db_session, test_project_id
):
    archived_transport = await create_project_vocabulary_term(
        db_session,
        test_project_id,
        VocabularyTermCreate(kind="transport", name="弃用渡船"),
    )
    connections = []
    for name, traits in (
        ("普通通路", ["traversable"]),
        ("传送门", ["cross_space", "traversable"]),
    ):
        connections.append(
            await create_project_vocabulary_term(
                db_session,
                test_project_id,
                VocabularyTermCreate(
                    kind="relation", name=name, traits=VocabularyTraits(connection=traits)
                ),
            )
        )
    service, node = await create_map(db_session, test_project_id)
    doc = document().model_dump(mode="json")
    doc["spaces"].append({"id": "dream", "label": "作者秘密空间名"})
    doc["features"].append(
        {
            "id": "dream-entry",
            "kind": "location",
            "label": "入口",
            "space_id": "dream",
            "points": [{"x": 0, "y": 0}],
            "reader_from_chapter": 1,
        }
    )
    source = {
        "kind": "entity",
        "id": str(uuid.uuid4()),
        "source_hash": "a" * 64,
        "quote": "乘船半日可达",
    }
    base = {
        "origin": "harbor",
        "destination": "pass",
        "transport_label": "渡船",
        "sources": [source],
    }
    doc["journeys"] = [
        {**base, "id": "public"},
        {
            **base,
            "id": "archived",
            "transport_type_ref": archived_transport.id,
            "transport_type_revision_id": archived_transport.revision_id,
        },
        *[
            {
                **base,
                "id": f"cross-{index}",
                "destination": "dream-entry",
                "connection_type_ref": term.id,
                "connection_type_revision_id": term.revision_id,
            }
            for index, term in enumerate(connections)
        ],
    ]
    with (
        patch.object(
            MapStructureService, "source", autospec=True, return_value="乘船半日可达"
        ),
        patch.object(
            MapStructureService, "reader_source_visible", autospec=True, return_value=True
        ),
    ):
        await service.save(
            db_session,
            test_project_id,
            node["id"],
            MapSaveRequest(base_revision_id=node["current_revision_id"], document=doc),
        )
        await archive_project_vocabulary_term(
            db_session,
            test_project_id,
            str(archived_transport.id),
            archived_transport.revision_id,
        )
        projection = await service.reader_preview(
            db_session, test_project_id, node["id"], chapter=1
        )
    assert [item["id"] for item in projection["journeys"]] == ["public", "cross-1"]
    assert {item["id"]: item["space_id"] for item in projection["features"]} == {
        "harbor": "main",
        "pass": "main",
        "dream-entry": "dream",
    }
    assert "spaces" not in projection


async def test_anchor_warnings_refresh_after_reorder_in_current_and_revision_views(
    db_session, test_project_id
):
    service, node = await create_map(db_session, test_project_id)
    doc = document()
    from modules.world.map_structure_schemas import SpatialValidity

    doc.features[0].effective = SpatialValidity(
        start={"kind": "scene", "id": str(uuid.UUID(int=1))},
        end={"kind": "scene", "id": str(uuid.UUID(int=2))},
    )
    scenes = [
        {"scene_id": str(uuid.UUID(int=1)), "status": "canonical", "scene_index": 8},
        {"scene_id": str(uuid.UUID(int=2)), "status": "canonical", "scene_index": 3},
    ]
    from modules.world.map_spatial_anchors import validity_problems
    from modules.world.map_structure_schemas import MapProblem

    async def current_problems(db, novel_id, document):
        return [
            MapProblem.model_validate(item)
            for item in validity_problems(document, scenes)
        ]

    with patch(
        "modules.world.map_structure_service.spatial_anchor_problems",
        autospec=True,
        side_effect=current_problems,
    ):
        saved = await service.save(
            db_session,
            test_project_id,
            node["id"],
            MapSaveRequest(base_revision_id=node["current_revision_id"], document=doc),
        )
        assert "spatial_anchor_order_reversed" in {item.code for item in saved.problems}
        scenes[0]["scene_index"] = 1
        current = await service.get_map(db_session, test_project_id, node["id"])
        preview = await service.preview_revision(
            db_session, test_project_id, node["id"], saved.id
        )
        assert "spatial_anchor_order_reversed" not in {
            item.code for item in current.revision.problems
        }
        assert "spatial_anchor_order_reversed" not in {
            item.code for item in preview.problems
        }
        scenes[0]["scene_index"] = 10
        preview = await service.preview_revision(
            db_session, test_project_id, node["id"], saved.id
        )
        assert "spatial_anchor_order_reversed" in {item.code for item in preview.problems}


@pytest.mark.parametrize(
    "bad_reference", ["foreign_project", "different_term", "wrong_kind"]
)
async def test_spatial_type_reference_rejects_foreign_mismatched_revision_and_kind(
    db_session, test_project_id, project_factory, bad_reference
):
    first = await create_project_vocabulary_term(
        db_session,
        test_project_id,
        VocabularyTermCreate(
            kind="feature", name="地点一", traits=VocabularyTraits(geometry=["point"])
        ),
    )
    second_project = (
        str(await project_factory.create_project())
        if bad_reference == "foreign_project"
        else test_project_id
    )
    second = await create_project_vocabulary_term(
        db_session,
        second_project,
        VocabularyTermCreate(
            kind="level" if bad_reference == "wrong_kind" else "feature", name="类型二"
        ),
    )
    service, node = await create_map(db_session, test_project_id)
    doc = document()
    doc.features[0].type_ref = (
        first.id if bad_reference == "different_term" else second.id
    )
    doc.features[0].type_revision_id = second.revision_id
    with pytest.raises(ValidationError, match="空间类型引用"):
        await service.save(
            db_session,
            test_project_id,
            node["id"],
            MapSaveRequest(base_revision_id=node["current_revision_id"], document=doc),
        )
    stored_node = await db_session.get(MapAtlasNode, uuid.UUID(node["id"]))
    assert str(stored_node.current_revision_id) == node["current_revision_id"]
