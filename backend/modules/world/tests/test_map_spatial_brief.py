from __future__ import annotations

import json
import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest

from infrastructure.stable_hash import stable_hash
from modules.world.map_spatial_anchors import resolve_validity
from modules.world.map_spatial_brief_schemas import MapSpatialBriefRequest
from modules.world.map_spatial_brief_service import (
    _safe_json,
    _within_cutoff,
    read_map_spatial_brief,
)
from modules.world.map_structure_schemas import (
    MapDocument,
    MapNodeCreate,
    MapSaveRequest,
    SpatialAnchor,
    SpatialValidity,
)
from modules.world.map_structure_service import (
    MapStructureService,
    source_digest,
    source_payload,
)
from modules.world.models import CoreEntity
from modules.world.project_vocabulary_schemas import (
    VocabularyTermCreate,
    VocabularyTraits,
)
from modules.world.project_vocabulary_service import create_project_vocabulary_term


def _range_ref() -> dict:
    return {
        "draft_id": str(uuid.uuid4()),
        "chapter_index": 2,
        "version_number": 1,
        "content_mode": "canonical",
        "start_offset": 0,
        "end_offset": 8,
        "source_hash": "a" * 64,
        "range_hash": "b" * 64,
    }


def test_map_validity_keeps_author_interval_when_story_identity_contract_is_missing() -> (
    None
):
    scene_id = str(uuid.uuid4())
    item = SimpleNamespace(
        id="map-declaration-1",
        effective=SpatialValidity(start=SpatialAnchor(kind="scene", id=scene_id)),
    )
    notices = {}

    active = _within_cutoff(
        item,
        scenes=[
            {
                "scene_id": scene_id,
                "scene_index": 2,
                "status": "canonical",
                "replaced_by_scene_ids": [],
            }
        ],
        scene_index=2,
        validity_notices=notices,
    )

    assert active is True
    assert notices["map-declaration-1:gap:story_map_declaration_unavailable"] == {
        "item_id": "map-declaration-1",
        "status": "gap",
        "gap": "story_map_declaration_unavailable",
        "author_active": True,
        "story_observation": None,
    }


def _scene_port(
    novel_id: str,
    scene_id: str,
    *,
    location_id: str | None,
    present_ids: list[str] | None = None,
    facts: list[dict] | None = None,
    temporal_scenes: list[dict] | None = None,
):
    scene = {
        "id": scene_id,
        "novel_id": novel_id,
        "status": "canonical",
        "scene_index": 2,
        "chapter_ids": ["2"],
        "structure_meta": {
            **({"location_entity_id": location_id} if location_id else {}),
            "present_entity_ids": list(present_ids or []),
        },
    }

    class Port:
        async def get_scene_contract(self, _db, _novel_id, _scene_id):
            return scene

        async def read_temporal_anchor_scenes(self, _db, _novel_id):
            return temporal_scenes or [
                {
                    "scene_id": scene_id,
                    "scene_index": 2,
                    "status": "canonical",
                    "chapter_ids": ["2"],
                    "replaced_by_scene_ids": [],
                }
            ]

        async def get_scene_state_view(self, *_args, **_kwargs):
            return {
                "status": "ok",
                "chapter_index": 2,
                "dimensions": [
                    {
                        "dimension": "locations",
                        "status": "ok",
                        "facts": list(facts or []),
                    }
                ],
            }

        async def validate_scene_source_ranges(self, *_args, **_kwargs):
            return None

        async def project_scene_presence(self, *_args, **_kwargs):
            return SimpleNamespace(
                nodes=[
                    SimpleNamespace(
                        character_id=entity_id,
                        scene_index=2,
                        presence_kind="confirmed_in_scene",
                    )
                    for entity_id in present_ids or []
                ]
            )

    return Port()


def _install_read_boundaries(monkeypatch, port, *, hidden_ids=frozenset()):
    from core import container
    from core.service_keys import STORY_SCENE_SOURCE

    get_service = container.get

    def get(key):
        return port if key == STORY_SCENE_SOURCE else get_service(key)

    monkeypatch.setattr(container, "get", get)

    async def check_visibility(_db, _novel_id, requests):
        return [
            SimpleNamespace(
                visible=(
                    str(request.target_id) not in hidden_ids
                    and request.apply_reader_reveal
                )
            )
            for request in requests
        ]

    async def inspect_target(_db, *, target_ref, **_kwargs):
        visible = str(target_ref["target_id"]) not in hidden_ids
        item = {"id": target_ref["target_id"]} if visible else None
        return {"visible": visible, "item": item}

    monkeypatch.setattr(
        "modules.world.facade.check_knowledge_visibility", check_visibility
    )
    monkeypatch.setattr("modules.evidence.facade.inspect_novel_target", inspect_target)


async def _entity(db, novel_id: str, name: str, *, entity_type="location"):
    entity = CoreEntity(
        novel_id=uuid.UUID(novel_id),
        entity_type=entity_type,
        name=name,
        summary=f"{name} 的已采用资料。",
        status="canonical",
    )
    db.add(entity)
    await db.flush()
    return entity


@pytest.mark.asyncio
async def test_spatial_brief_is_scene_bounded_and_uses_explicit_location_and_presence(
    db_session, test_project_id, monkeypatch
):
    place = await _entity(db_session, test_project_id, "临江城")
    old_place = await _entity(db_session, test_project_id, "旧码头")
    gate = await _entity(db_session, test_project_id, "黑石关")
    cart = await _entity(db_session, test_project_id, "运粮车", entity_type="item")
    future_place = await _entity(db_session, test_project_id, "未来城")
    hidden_place = await _entity(db_session, test_project_id, "密库")
    source = await _entity(db_session, test_project_id, "城道志")
    mobile_type = await create_project_vocabulary_term(
        db_session,
        test_project_id,
        VocabularyTermCreate(
            kind="feature",
            name="可移动物",
            traits=VocabularyTraits(other=["movable"]),
        ),
    )
    service = MapStructureService()
    node = await service.create_node(
        db_session, test_project_id, MapNodeCreate(title="临江区域", level="region")
    )
    map_source = {
        "kind": "entity",
        "id": str(source.id),
        "source_hash": source_digest(source_payload(source)),
        "quote": "城道志 的已采用资料。",
    }
    document = MapDocument.model_validate(
        {
            "schema_version": 2,
            "features": [
                {
                    "id": "harbor",
                    "kind": "location",
                    "label": "临江城",
                    "entity_id": str(place.id),
                    "sources": [map_source],
                },
                {
                    "id": "gate",
                    "kind": "location",
                    "label": "黑石关",
                    "entity_id": str(gate.id),
                    "sources": [map_source],
                },
                {
                    "id": "old-dock",
                    "kind": "location",
                    "label": "旧码头",
                    "entity_id": str(old_place.id),
                },
                {
                    "id": "cart",
                    "kind": "landmark",
                    "label": "运粮车",
                    "entity_id": str(cart.id),
                    "type_ref": str(mobile_type.id),
                    "type_revision_id": str(mobile_type.revision_id),
                },
                {
                    "id": "future",
                    "kind": "location",
                    "label": "未来城",
                    "entity_id": str(future_place.id),
                    "reader_from_chapter": 3,
                },
                {
                    "id": "secret",
                    "kind": "location",
                    "label": "密库",
                    "entity_id": str(hidden_place.id),
                },
                {
                    "id": "rumor",
                    "kind": "location",
                    "label": "传闻地点",
                    "modality": "belief",
                },
            ],
            "constraints": [
                {
                    "id": "road",
                    "subject": "harbor",
                    "relation": "connects",
                    "target": "gate",
                    "path_label": "北道",
                    "sources": [map_source],
                }
            ],
            "journeys": [
                {
                    "id": "trip",
                    "origin": "harbor",
                    "destination": "gate",
                    "transport_label": "驿车",
                    "duration": {"minimum": 2, "maximum": 3, "unit": "日"},
                    "access_conditions": [{"label": "关门前通行"}],
                    "sources": [map_source],
                }
            ],
        }
    )
    saved = await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(base_revision_id=node["current_revision_id"], document=document),
    )
    scene_id = str(uuid.uuid4())
    fact = {
        "subject_id": str(cart.id),
        "subject_label": "运粮车",
        "field": "location_id",
        "value": {"location_id": str(place.id)},
        "layer": "fact",
        "confidence": "confirmed",
        "occurred_at": {"scene_index": 2},
        "source": {
            "provenance": {
                "status": "exact",
                "source_refs": [_range_ref()],
            }
        },
    }
    old_fact = {
        **fact,
        "value": {"location_id": str(old_place.id)},
        "occurred_at": {"scene_index": 1},
    }
    port = _scene_port(
        test_project_id,
        scene_id,
        location_id=str(place.id),
        present_ids=[str(cart.id)],
        facts=[old_fact, fact],
    )
    _install_read_boundaries(monkeypatch, port, hidden_ids={str(hidden_place.id)})

    async def read_range(*_args, **_kwargs):
        return {"text": "位置转移已确认。", "visibility_decision": {"visible": True}}

    monkeypatch.setattr("modules.evidence.facade.read_novel_evidence", read_range)
    brief = await read_map_spatial_brief(
        db_session,
        MapSpatialBriefRequest(
            novel_id=test_project_id,
            scene_id=scene_id,
            reveal_mode="author_full",
        ),
    )

    assert len(brief.items) == 1
    assert brief.items[0].revision_id == saved.id
    assert brief.items[0].revision_hash == stable_hash(
        {
            "node_id": node["id"],
            "title": "临江区域",
            "revision_id": saved.id,
            "document": document.model_dump(mode="json"),
        }
    )
    payload = json.loads(brief.items[0].content)
    assert [item["label"] for item in payload["当前地点"]] == ["临江城"]
    assert payload["邻接与通路"][0]["relation"] == "connects"
    assert payload["行程与通行条件"][0]["access_conditions"][0]["label"] == "关门前通行"
    assert payload["移动对象最后位置"] == [
        {
            "object": "运粮车",
            "location": "临江城",
            "occurred_at": {"scene_index": 2},
        }
    ]
    assert "未来城" not in brief.items[0].content
    assert "传闻地点" not in brief.items[0].content

    for exclusion in (
        f"writing_draft:{fact['source']['provenance']['source_refs'][0]['draft_id']}",
        "writing_chapter:2",
        f"source_range:{fact['source']['provenance']['source_refs'][0]['range_hash']}",
        f"project_vocabulary_term:{mobile_type.id}",
        f"project_vocabulary_revision:{mobile_type.revision_id}",
    ):
        excluded_position = await read_map_spatial_brief(
            db_session,
            MapSpatialBriefRequest(
                novel_id=test_project_id,
                scene_id=scene_id,
                excluded_ids=[exclusion],
            ),
        )
        assert excluded_position.items
        excluded_payload = json.loads(excluded_position.items[0].content)
        assert excluded_payload["当前地点"][0]["label"] == "临江城"
        assert excluded_payload["移动对象最后位置"] == [], exclusion

    # The normal Evidence loader forwards frozen selection source_refs as draft
    # exclusions; exercise that adapter with the same real map reader.
    from core.config import get_settings
    from modules.evidence.compilation.contracts import (
        CompileOptions,
        StructureContextBundle,
    )
    from modules.evidence.compilation.services.loaders import map_spatial_loader

    settings = replace(
        get_settings(), map_spatial_enabled_capabilities=("writing.generate",)
    )
    monkeypatch.setattr(map_spatial_loader, "get_settings", lambda: settings)
    options = CompileOptions(
        novel_id=test_project_id,
        task="续写当前场景",
        scope="project",
        scene_id=scene_id,
        consumer_action="writing.generate",
        excluded_refs=[
            {
                "kind": "source",
                "source_ref": fact["source"]["provenance"]["source_refs"][0],
            }
        ],
    )
    bundle = StructureContextBundle(
        novel_id=test_project_id, task=options.task, scope="project"
    )
    await map_spatial_loader.MapSpatialLoader().load(db_session, options, bundle)
    assert bundle.map_spatial_brief["items"]
    assert (
        json.loads(bundle.map_spatial_brief["items"][0]["content"])["移动对象最后位置"]
        == []
    )

    earlier_cutoff = await read_map_spatial_brief(
        db_session,
        MapSpatialBriefRequest(
            novel_id=test_project_id,
            scene_id=scene_id,
            chapter_index=1,
        ),
    )
    assert earlier_cutoff.items == []

    hidden = await read_map_spatial_brief(
        db_session,
        MapSpatialBriefRequest(
            novel_id=test_project_id,
            scene_id=scene_id,
            reveal_mode="author_full",
            query_text="密库",
        ),
    )
    assert hidden.items
    assert "密库" not in "\n".join(item.content for item in hidden.items)


@pytest.mark.asyncio
async def test_brief_never_guesses_scene_location_and_honors_node_exclusion(
    db_session, test_project_id, monkeypatch
):
    place = await _entity(db_session, test_project_id, "临江城")
    service = MapStructureService()
    node = await service.create_node(
        db_session, test_project_id, MapNodeCreate(title="空白区域", level="region")
    )
    saved = await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(
            base_revision_id=node["current_revision_id"],
            document=MapDocument(
                features=[
                    {
                        "id": "harbor",
                        "kind": "location",
                        "label": "临江城",
                        "entity_id": str(place.id),
                    }
                ]
            ),
        ),
    )
    scene_id = str(uuid.uuid4())
    port = _scene_port(test_project_id, scene_id, location_id=None)
    _install_read_boundaries(monkeypatch, port)

    empty = await read_map_spatial_brief(
        db_session,
        MapSpatialBriefRequest(novel_id=test_project_id, scene_id=scene_id),
    )
    excluded = await read_map_spatial_brief(
        db_session,
        MapSpatialBriefRequest(
            novel_id=test_project_id,
            scene_id=scene_id,
            query_text="临江城",
            excluded_ids=[f"map_spatial:{node['id']}:{saved.id}"],
        ),
    )
    excluded_entity = await read_map_spatial_brief(
        db_session,
        MapSpatialBriefRequest(
            novel_id=test_project_id,
            scene_id=scene_id,
            query_text="临江城",
            excluded_ids=[f"world_entity:{place.id}"],
        ),
    )
    assert empty.items == []
    assert excluded.items == []
    assert excluded_entity.items == []
    excluded_revision = await read_map_spatial_brief(
        db_session,
        MapSpatialBriefRequest(
            novel_id=test_project_id,
            scene_id=scene_id,
            query_text="临江城",
            excluded_ids=[f"map_atlas_revision:{saved.id}"],
        ),
    )
    assert excluded_revision.items == []


@pytest.mark.asyncio
async def test_project_without_a_map_returns_no_placeholder(
    db_session, two_projects, monkeypatch
):
    _novel_id, empty_project_id = two_projects
    scene_id = str(uuid.uuid4())
    _install_read_boundaries(
        monkeypatch,
        _scene_port(empty_project_id, scene_id, location_id=None),
    )

    result = await read_map_spatial_brief(
        db_session,
        MapSpatialBriefRequest(novel_id=empty_project_id, scene_id=scene_id),
    )

    assert result.items == []
    assert result.omitted_count == 0


@pytest.mark.asyncio
async def test_brief_applies_expired_and_replaced_scene_anchors(
    db_session, test_project_id, monkeypatch
):
    current_place = await _entity(db_session, test_project_id, "白潮港")
    old_pass = await _entity(db_session, test_project_id, "旧关")
    service = MapStructureService()
    node = await service.create_node(
        db_session, test_project_id, MapNodeCreate(title="海港区域", level="region")
    )
    expired_scene_id = str(uuid.uuid4())
    replaced_scene_id = str(uuid.uuid4())
    current_scene_id = str(uuid.uuid4())
    scene_rows = [
        {
            "scene_id": expired_scene_id,
            "scene_index": 1,
            "status": "canonical",
            "chapter_ids": ["1"],
            "replaced_by_scene_ids": [],
        },
        {
            "scene_id": current_scene_id,
            "scene_index": 2,
            "status": "canonical",
            "chapter_ids": ["2"],
            "replaced_by_scene_ids": [],
        },
    ]
    _install_read_boundaries(
        monkeypatch,
        _scene_port(
            test_project_id,
            current_scene_id,
            location_id=str(current_place.id),
            temporal_scenes=scene_rows,
        ),
    )
    expired_document = MapDocument.model_validate(
        {
            "features": [
                {
                    "id": "harbor",
                    "kind": "location",
                    "label": "白潮港",
                    "entity_id": str(current_place.id),
                },
                {
                    "id": "old-pass",
                    "kind": "location",
                    "label": "旧关",
                    "entity_id": str(old_pass.id),
                    "effective": {"end": {"kind": "scene", "id": expired_scene_id}},
                },
            ],
            "constraints": [
                {
                    "id": "old-road",
                    "subject": "harbor",
                    "relation": "connects",
                    "target": "old-pass",
                }
            ],
        }
    )
    expired_saved = await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(
            base_revision_id=node["current_revision_id"], document=expired_document
        ),
    )
    expired = await read_map_spatial_brief(
        db_session,
        MapSpatialBriefRequest(novel_id=test_project_id, scene_id=current_scene_id),
    )
    assert len(expired.items) == 1
    assert "白潮港" in expired.items[0].content
    assert "旧关" not in expired.items[0].content
    assert "邻接与通路" in expired.items[0].content
    assert json.loads(expired.items[0].content)["邻接与通路"] == []

    replacement_document = MapDocument.model_validate(
        {
            "features": [
                {
                    "id": "harbor",
                    "kind": "location",
                    "label": "白潮港",
                    "entity_id": str(current_place.id),
                    "effective": {"start": {"kind": "scene", "id": replaced_scene_id}},
                }
            ]
        }
    )
    replacement_rows = [
        {
            "scene_id": replaced_scene_id,
            "scene_index": None,
            "status": "replaced",
            "chapter_ids": [],
            "replaced_by_scene_ids": [current_scene_id],
        },
        scene_rows[1],
    ]
    _install_read_boundaries(
        monkeypatch,
        _scene_port(
            test_project_id,
            current_scene_id,
            location_id=str(current_place.id),
            temporal_scenes=replacement_rows,
        ),
    )
    await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(
            base_revision_id=expired_saved.id,
            document=replacement_document,
        ),
    )
    replaced = await read_map_spatial_brief(
        db_session,
        MapSpatialBriefRequest(novel_id=test_project_id, scene_id=current_scene_id),
    )
    assert len(replaced.items) == 1
    assert "白潮港" in replaced.items[0].content


@pytest.mark.asyncio
async def test_brief_omits_hidden_and_stale_source_and_never_adds_empty_placeholder(
    db_session, test_project_id, monkeypatch
):
    place = await _entity(db_session, test_project_id, "霜桥")
    source = await _entity(db_session, test_project_id, "地方志")
    service = MapStructureService()
    node = await service.create_node(
        db_session, test_project_id, MapNodeCreate(title="北岸", level="region")
    )
    source_ref = {
        "kind": "entity",
        "id": str(source.id),
        "source_hash": source_digest(source_payload(source)),
        "quote": "地方志 的已采用资料。",
    }
    await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(
            base_revision_id=node["current_revision_id"],
            document=MapDocument(
                features=[
                    {
                        "id": "bridge",
                        "kind": "location",
                        "label": "霜桥",
                        "entity_id": str(place.id),
                        "sources": [source_ref],
                    }
                ]
            ),
        ),
    )
    scene_id = str(uuid.uuid4())
    port = _scene_port(test_project_id, scene_id, location_id=str(place.id))
    _install_read_boundaries(monkeypatch, port, hidden_ids={str(source.id)})

    hidden_source = await read_map_spatial_brief(
        db_session,
        MapSpatialBriefRequest(novel_id=test_project_id, scene_id=scene_id),
    )
    assert hidden_source.items == []

    from core.errors import ValidationError
    from modules.world.map_structure_schemas import MapSource

    with pytest.raises(ValidationError):
        await service.source(
            db_session,
            test_project_id,
            MapSource.model_validate({**source_ref, "quote": "不在原文中的引文"}),
        )

    source.summary = "来源资料已更新，原引文不再匹配。"
    await db_session.flush()
    _install_read_boundaries(monkeypatch, port)
    stale_source = await read_map_spatial_brief(
        db_session,
        MapSpatialBriefRequest(novel_id=test_project_id, scene_id=scene_id),
    )
    assert stale_source.items == []
    assert stale_source.omitted_count > 0


@pytest.mark.asyncio
async def test_brief_keeps_adopted_v1_manual_edges_without_sources_and_direction_text(
    db_session, test_project_id, monkeypatch
):
    harbor = await _entity(db_session, test_project_id, "临江城")
    pass_entity = await _entity(db_session, test_project_id, "黑石关")
    service = MapStructureService()
    node = await service.create_node(
        db_session, test_project_id, MapNodeCreate(title="旧城图", level="region")
    )
    document = MapDocument.model_validate(
        {
            "schema_version": 1,
            "features": [
                {
                    "id": "harbor",
                    "kind": "location",
                    "label": "临江城",
                    "entity_id": str(harbor.id),
                },
                {
                    "id": "pass",
                    "kind": "location",
                    "label": "黑石关",
                    "entity_id": str(pass_entity.id),
                },
            ],
            "constraints": [
                {
                    "id": "direction",
                    "subject": "harbor",
                    "relation": "north",
                    "target": "pass",
                },
                {
                    "id": "road",
                    "subject": "harbor",
                    "relation": "connects",
                    "target": "pass",
                    "path_label": "北道",
                },
            ],
        }
    )
    saved = await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(base_revision_id=node["current_revision_id"], document=document),
    )
    scene_id = str(uuid.uuid4())
    port = _scene_port(test_project_id, scene_id, location_id=str(harbor.id))
    _install_read_boundaries(monkeypatch, port)

    brief = await read_map_spatial_brief(
        db_session,
        MapSpatialBriefRequest(novel_id=test_project_id, scene_id=scene_id),
    )

    assert len(brief.items) == 1 and brief.items[0].revision_id == saved.id
    edges = json.loads(brief.items[0].content)["邻接与通路"]
    assert {item["relation"] for item in edges} == {"north", "connects"}
    assert "traversable" not in next(
        item for item in edges if item["relation"] == "north"
    )


def test_spatial_brief_handles_replaced_anchors_and_keeps_bounded_valid_json():
    replaced = str(uuid.uuid4())
    replacement = str(uuid.uuid4())
    from modules.world.map_structure_schemas import SpatialValidity

    validity = SpatialValidity.model_validate(
        {"start": {"kind": "scene", "id": replaced}}
    )
    scenes = [
        {
            "scene_id": replaced,
            "scene_index": None,
            "status": "replaced",
            "chapter_ids": [],
            "replaced_by_scene_ids": [replacement],
        },
        {
            "scene_id": replacement,
            "scene_index": 5,
            "status": "canonical",
            "chapter_ids": ["5"],
            "replaced_by_scene_ids": [],
        },
    ]
    resolution = resolve_validity(validity, scenes)
    assert resolution.valid and resolution.start_scene_index == 5

    text, clipped = _safe_json(
        {
            "当前地点": [{"label": "临江城" * 1000}],
            "邻接与通路": ["北道" * 20] * 40,
        }
    )
    assert clipped
    assert len(text) <= 3000
    assert isinstance(json.loads(text), dict)


@pytest.mark.asyncio
async def test_hidden_node_binding_cannot_leak_its_title_via_visible_feature(
    db_session, test_project_id, monkeypatch
):
    hidden = await _entity(db_session, test_project_id, "秘密洞天")
    visible = await _entity(db_session, test_project_id, "渡口")
    service = MapStructureService()
    node = await service.create_node(
        db_session,
        test_project_id,
        MapNodeCreate(title="秘密洞天", level="region", location_entity_id=hidden.id),
    )
    await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(
            base_revision_id=node["current_revision_id"],
            document=MapDocument(
                features=[
                    {
                        "id": "pier",
                        "kind": "location",
                        "label": "渡口",
                        "entity_id": visible.id,
                    }
                ]
            ),
        ),
    )
    _install_read_boundaries(
        monkeypatch,
        _scene_port(test_project_id, str(uuid.uuid4()), location_id=None),
        hidden_ids={str(hidden.id)},
    )
    result = await read_map_spatial_brief(
        db_session,
        MapSpatialBriefRequest(
            novel_id=test_project_id, query_text="渡口在哪里", reveal_mode="author_full"
        ),
    )
    assert result.items == []


@pytest.mark.asyncio
async def test_model_generated_feature_needs_source_even_after_adoption(
    db_session, test_project_id, monkeypatch
):
    from modules.world.map_atlas_models import MapAtlasRevision

    service = MapStructureService()
    node = await service.create_node(
        db_session, test_project_id, MapNodeCreate(title="北岸", level="region")
    )
    saved = await service.save(
        db_session,
        test_project_id,
        node["id"],
        MapSaveRequest(
            base_revision_id=node["current_revision_id"],
            document=MapDocument(
                features=[{"id": "pier", "kind": "location", "label": "没有引文的渡口"}]
            ),
        ),
    )
    revision = await db_session.get(MapAtlasRevision, uuid.UUID(saved.id))
    revision.task_id = uuid.uuid4()
    _install_read_boundaries(
        monkeypatch, _scene_port(test_project_id, str(uuid.uuid4()), location_id=None)
    )
    with db_session.no_autoflush:
        result = await read_map_spatial_brief(
            db_session,
            MapSpatialBriefRequest(novel_id=test_project_id, query_text="没有引文的渡口"),
        )
    assert result.items == []
