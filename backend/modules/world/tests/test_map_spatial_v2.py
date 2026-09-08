"""Author map hierarchy, point relations and bounded writing navigation."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from unittest.mock import patch

import pytest
from pydantic import ValidationError as SchemaError

from core.errors import ConflictError, NotFoundError, ValidationError
from modules.account.context import bind_principal, reset_principal
from modules.account.contracts import AccountPrincipal
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.map_atlas_schemas import MapAtlasNodeUpdate
from modules.world.map_atlas_service import MapAtlasService
from modules.world.map_structure_geometry import geometry_hash, layout
from modules.world.map_structure_schemas import (
    MapDocument,
    MapGenerateRequest,
    MapLinkQuery,
    MapNodeCreate,
    MapSaveRequest,
)
from modules.world.map_structure_service import MapStructureService
from modules.world.map_structure_workflow import enqueue_structure
from modules.writing.contracts import SourceRangeRefContract


@pytest.mark.parametrize("level", ["region", "city", "district", "street"])
async def test_all_spatial_levels_create_save_restore_and_enqueue(
    db_session,
    test_project_id,
    level,
):
    service = MapStructureService()
    node = await service.create_node(
        db_session, test_project_id, MapNodeCreate(title="示意", level=level)
    )
    doc = MapDocument(features=[{"id": "inn", "kind": "location", "label": "旅馆"}])
    saved = await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(
            base_revision_id=node["current_revision_id"],
            document=doc,
        ),
    )
    with pytest.raises(ConflictError):
        await service.save(
            db_session,
            test_project_id,
            node["id"],
            MapSaveRequest(
                base_revision_id=node["current_revision_id"],
                document=doc,
            ),
        )
    from modules.world.map_structure_schemas import MapRevisionReview

    restored = await service.review(
        db_session,
        test_project_id,
        node["id"],
        node["current_revision_id"],
        MapRevisionReview(action="restore", base_revision_id=saved.id),
    )
    assert restored.id != node["current_revision_id"]
    assert not restored.document.features
    # Stop at the confirmation boundary: every level reaches the same safety gate.
    with patch(
        "modules.world.map_structure_workflow.require_fresh_confirmation",
        autospec=True,
        side_effect=ValidationError("confirmation required"),
    ) as confirmation:
        with pytest.raises(ValidationError, match="confirmation required"):
            await enqueue_structure(
                db_session,
                test_project_id,
                node["id"],
                MapGenerateRequest(
                    operation_id=uuid.uuid4(),
                    base_revision_id=restored.id,
                    context_confirmation_id=uuid.uuid4(),
                    location_ids=[uuid.uuid4()],
                ),
            )
    confirmation.assert_awaited_once()


async def test_region_city_district_street_hierarchy_keeps_cas_and_boundaries(
    db_session, test_project_id
):
    service = MapStructureService()
    parent = None
    nodes = []
    for level in ("region", "city", "district", "street"):
        parent = await service.create_node(
            db_session,
            test_project_id,
            MapNodeCreate(
                title=level,
                level=level,
                parent_id=parent["id"] if parent else None,
            ),
        )
        nodes.append(parent)
    street = await db_session.get(MapAtlasNode, uuid.UUID(nodes[-1]["id"]))
    changed = await MapAtlasService().update_node(
        db_session,
        test_project_id,
        str(street.id),
        MapAtlasNodeUpdate(title="新街名", expected_updated_at=street.updated_at),
    )
    assert changed["current_revision_id"] == nodes[-1]["current_revision_id"]
    with pytest.raises(ValidationError):
        await service.create_node(
            db_session,
            test_project_id,
            MapNodeCreate(
                title="倒置",
                level="city",
                parent_id=street.id,
            ),
        )
    region = await db_session.get(MapAtlasNode, uuid.UUID(nodes[0]["id"]))
    with pytest.raises(ValidationError):
        await MapAtlasService().update_node(
            db_session,
            test_project_id,
            str(region.id),
            MapAtlasNodeUpdate(
                parent_id=street.id, expected_updated_at=region.updated_at
            ),
        )


def point_relations_document():
    return {
        "features": [
            {"id": "inn", "kind": "location", "label": "旅馆"},
            {"id": "entrance", "kind": "landmark", "label": "大门"},
            {"id": "sign", "kind": "landmark", "label": "路牌"},
            {
                "id": "street",
                "kind": "road",
                "label": "街道",
                "points": [{"x": 0, "y": 0}, {"x": 500, "y": 0}],
            },
            {
                "id": "square",
                "kind": "area",
                "label": "广场",
                "points": [
                    {"x": 0, "y": 300},
                    {"x": 400, "y": 300},
                    {"x": 400, "y": 600},
                    {"x": 0, "y": 600},
                ],
            },
        ],
        "constraints": [
            {
                "id": "street-link",
                "subject": "inn",
                "relation": "along_street",
                "target": "street",
            },
            {
                "id": "entrance-link",
                "subject": "entrance",
                "relation": "entrance_to",
                "target": "square",
            },
            {"id": "face-link", "subject": "sign", "relation": "faces", "target": "inn"},
        ],
    }


def test_point_relations_keep_manual_geometry_and_do_not_create_junctions():
    doc = MapDocument.model_validate(point_relations_document())
    placed = layout(doc)
    assert not placed.problems
    assert all(feature.points for feature in placed.document.features)
    assert len(placed.document.features) == len(doc.features)
    assert placed.model_dump() == layout(doc).model_dump()
    by_id = {feature.id: feature for feature in placed.document.features}
    assert abs(by_id["inn"].points[0].y) <= 45
    assert by_id["entrance"].points[0].y >= 225
    assert by_id["sign"].points != by_id["inn"].points
    edited = placed.document.model_dump()
    edited["features"][0]["points"] = [{"x": 900, "y": 900}]
    edited["features"][1]["points"] = [{"x": 900, "y": 900}]
    edited["features"][2]["points"] = [{"x": 900, "y": 900}]
    again = layout(MapDocument.model_validate(edited))
    assert {p.code for p in again.problems} == {
        "along_street_conflict",
        "entrance_to_conflict",
        "faces_conflict",
    }
    assert [f.points for f in again.document.features] == [
        f.points for f in MapDocument.model_validate(edited).features
    ]


@pytest.mark.parametrize(
    "relation,subject,target,via",
    [
        ("along_street", "street", "inn", []),
        ("along_street", "inn", "square", []),
        ("entrance_to", "street", "square", []),
        ("entrance_to", "inn", "street", []),
        ("faces", "inn", "inn", []),
        ("faces", "inn", "missing", []),
        ("faces", "square", "inn", []),
        ("faces", "inn", "square", ["sign"]),
    ],
)
def test_point_relations_reject_invalid_endpoints(relation, subject, target, via):
    doc = point_relations_document()
    doc["constraints"] = [
        {
            "id": "invalid",
            "subject": subject,
            "relation": relation,
            "target": target,
            "via": via,
        }
    ]
    with pytest.raises(SchemaError):
        MapDocument.model_validate(doc)


def test_unplaced_street_keeps_linked_point_unplaced():
    doc = point_relations_document()
    doc["features"][3]["points"] = []
    result = layout(MapDocument.model_validate(doc))
    assert not result.document.features[0].points
    assert "inn" in {key for problem in result.problems for key in problem.feature_ids}


async def add_saved_document(
    db, novel_id, title, *, label="旅馆", chapter=2, entity_id=None
):
    service = MapStructureService()
    node = await service.create_node(db, novel_id, MapNodeCreate(title=title))
    draft_id = str(uuid.uuid4())
    reference = SourceRangeRefContract(
        draft_id=draft_id,
        chapter_index=chapter,
        version_number=1,
        content_mode="canonical",
        start_offset=0,
        end_offset=1,
        source_hash="a" * 64,
        range_hash="b" * 64,
    )
    doc = MapDocument(
        features=[
            {
                "id": "inn",
                "kind": "location",
                "label": label,
                "entity_id": entity_id,
                "sources": [
                    {
                        "kind": "source_range",
                        "id": draft_id,
                        "source_hash": "a" * 64,
                        "quote": "PRIVATE QUOTE",
                        "source_ref": asdict(reference),
                    }
                ],
            }
        ]
    )
    saved = MapAtlasRevision(
        novel_id=uuid.UUID(novel_id),
        node_id=uuid.UUID(node["id"]),
        status="saved",
        document=doc.model_dump(mode="json"),
        geometry_hash=geometry_hash(doc),
        problems=[],
    )
    db.add(saved)
    await db.flush()
    row = await db.get(MapAtlasNode, uuid.UUID(node["id"]))
    row.current_revision_id = saved.id
    await db.flush()
    return row, saved


async def test_map_links_current_saved_only_filters_truncation_and_project_scope(
    db_session, test_project_id, project_factory, async_client
):
    entity_id = uuid.uuid4()
    first, revision = await add_saved_document(
        db_session, test_project_id, "廷根", entity_id=entity_id
    )
    await add_saved_document(
        db_session, test_project_id, "第二张图", label="旅馆二", chapter=3
    )
    hidden, _ = await add_saved_document(db_session, test_project_id, "候选节点")
    hidden.status = "provisional"
    candidate, candidate_revision = await add_saved_document(
        db_session, test_project_id, "候选版本"
    )
    candidate_revision.status = "candidate"
    other = str(await project_factory.create_project())
    await add_saved_document(db_session, other, "其他项目")
    await db_session.flush()
    path = f"/api/world/map-atlas/{test_project_id}/map-links"
    assert (await async_client.get(path)).json() == {"items": [], "truncated": False}
    response = await async_client.get(
        path, params={"chapter_index": 2, "entity_id": str(entity_id), "q": "廷根"}
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data == {
        "items": [
            {
                "node_id": str(first.id),
                "node_title": "廷根",
                "level": "region",
                "feature_id": "inn",
                "feature_label": "旅馆",
                "entity_id": str(entity_id),
                "chapter_indices": [2],
            }
        ],
        "truncated": False,
    }
    assert "PRIVATE" not in response.text
    assert (await async_client.get(path, params={"q": "旅馆", "limit": 1})).json()[
        "truncated"
    ] is True
    assert len((await async_client.get(path, params={"q": "旅馆"})).json()["items"]) == 2
    assert not (
        await async_client.get(
            path, params={"chapter_index": 3, "entity_id": str(entity_id)}
        )
    ).json()["items"]
    for params in (
        {"q": "a" * 101},
        {"entity_id": "bad"},
        {"chapter_index": 0},
        {"limit": 101},
    ):
        assert (await async_client.get(path, params=params)).status_code == 422
    token = bind_principal(
        AccountPrincipal(
            account_id=uuid.uuid4(),
            status="active",
            identity_type="email",
            support_code="U-FOREIGN",
        )
    )
    try:
        with pytest.raises(NotFoundError):
            await MapStructureService().map_links(
                db_session, test_project_id, MapLinkQuery(q="旅馆")
            )
    finally:
        reset_principal(token)


async def test_map_link_scan_limit_reports_incomplete_results(
    db_session, test_project_id
):
    nodes = [
        MapAtlasNode(
            novel_id=uuid.UUID(test_project_id),
            title="地图",
            level="street",
            semantic_key=f"manual:{uuid.uuid4()}",
            status="adopted",
        )
        for _ in range(201)
    ]
    db_session.add_all(nodes)
    await db_session.flush()
    doc = MapDocument()
    revisions = [
        MapAtlasRevision(
            novel_id=node.novel_id,
            node_id=node.id,
            status="saved",
            document=doc.model_dump(mode="json"),
            geometry_hash=geometry_hash(doc),
            problems=[],
        )
        for node in nodes
    ]
    db_session.add_all(revisions)
    await db_session.flush()
    for node, revision in zip(nodes, revisions, strict=True):
        node.current_revision_id = revision.id
    await db_session.flush()
    result = await MapStructureService().map_links(
        db_session, test_project_id, MapLinkQuery(q="不存在")
    )
    assert result.items == []
    assert result.truncated is True


async def test_map_node_level_change_to_street_keeps_existing_revision(
    db_session, test_project_id
):
    service = MapStructureService()
    node = await service.create_node(
        db_session, test_project_id, MapNodeCreate(title="地图")
    )
    row = await db_session.get(MapAtlasNode, uuid.UUID(node["id"]))
    result = await MapAtlasService().update_node(
        db_session,
        test_project_id,
        node["id"],
        MapAtlasNodeUpdate(level="street", expected_updated_at=row.updated_at),
    )
    assert result["level"] == "street"
    assert result["current_revision_id"] == node["current_revision_id"]
    saved = await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(
            base_revision_id=node["current_revision_id"], document=MapDocument()
        ),
    )
    assert saved.id != node["current_revision_id"]


def test_layout_places_area_entrance_before_drawing_its_explicit_route():
    doc = MapDocument.model_validate(
        {
            "features": [
                {"id": "inside", "kind": "location", "label": "院内房屋"},
                {"id": "entrance", "kind": "landmark", "label": "院门"},
                {"id": "courtyard", "kind": "area", "label": "庭院"},
            ],
            "constraints": [
                {
                    "id": "content",
                    "subject": "inside",
                    "relation": "inside",
                    "target": "courtyard",
                },
                {
                    "id": "gate",
                    "subject": "entrance",
                    "relation": "entrance_to",
                    "target": "courtyard",
                },
                {
                    "id": "path",
                    "subject": "entrance",
                    "relation": "connects",
                    "target": "inside",
                },
            ],
        }
    )
    result = layout(doc)
    assert not result.problems
    assert all(feature.points for feature in result.document.features)
    assert result.document.features[-1].points[0] == result.document.features[1].points[0]
