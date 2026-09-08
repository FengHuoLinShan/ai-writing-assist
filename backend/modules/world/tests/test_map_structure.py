from __future__ import annotations

import uuid

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
)
from modules.world.map_structure_service import MapStructureService


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
    for level in ("cover", "world", "interior"):
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
        json={"level": "city", "expected_updated_at": baseline},
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
    for patch in (
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
                MapAtlasNodeUpdate(expected_updated_at=row.updated_at, **patch),
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
    page.review_status = "deprecated"
    await db_session.flush()
    state = await service.get_map(db_session, test_project_id, node["id"])
    assert state.image_layers[0]["state"] == "unavailable"
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
    assert all(set(f) == {"id", "kind", "label", "points"} for f in early["features"])
    late = await service.reader_preview(
        db_session, test_project_id, node["id"], chapter=5
    )
    assert {f["id"] for f in late["features"]} == {"harbor", "pass", "fort", "road"}
    assert early["features"][0]["points"] == late["features"][0]["points"]


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
