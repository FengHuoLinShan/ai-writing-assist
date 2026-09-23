"""Production evolution handler → Story → owner map API → source invalidation."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from modules.evolution.sampler import register_scene_sampler
from modules.evolution.tasks import handle_evolution_scene_step
from modules.story.continuity.models import MemoryEvent
from modules.story.outline_state.models import Scene
from modules.story.outline_state.repositories import SceneRepository
from modules.world.map_structure_schemas import MapDocument, MapNodeCreate, MapSaveRequest
from modules.world.map_structure_service import MapStructureService
from modules.world.models import CoreEntity
from modules.writing.facade import create_draft_only
from tests.support.evolution_review import frozen_state_review


async def test_map_reads_committed_presence_and_rejects_stale_history(
    db_session, test_project_id, async_client
):
    db, nid = db_session, test_project_id
    from modules.evolution.facade import switch_project_engine

    await switch_project_engine(db, nid, to_engine="evolution", expected_epoch=1)
    people = [
        CoreEntity(
            novel_id=UUID(nid), entity_type="character", name=name, status="canonical"
        )
        for name in ("林舟", "青竹", "未出场的人")
    ]
    scenes = [
        Scene(
            novel_id=UUID(nid),
            scene_index=index,
            chapter_ids=[index + 1],
            scene_chunks=[],
            title=f"场景{index + 1}",
            status="draft",
        )
        for index in range(3)
    ]
    db.add_all([*people, *scenes])
    await db.flush()
    ids = [str(value.id) for value in people]
    scene_ids = [str(value.id) for value in scenes]
    prose = [
        "林舟与青竹出现在白石城。",
        "林舟出现在渡口，没有说明中间行程。",
        "林舟后来到了深山。",
    ]
    for index, text in enumerate(prose):
        await create_draft_only(db, nid, index + 1, content=text)
    service = MapStructureService()
    node = await service.create_node(db, nid, MapNodeCreate(title="人物回看地图"))
    await db.commit()
    saved = await service.save(
        db,
        nid,
        node["id"],
        MapSaveRequest(
            base_revision_id=node["current_revision_id"],
            document=MapDocument.model_validate(
                {
                    "features": [
                        {
                            "id": f"place{index}",
                            "kind": "location",
                            "label": name,
                            "points": [{"x": index * 100, "y": 0}],
                        }
                        for index, name in enumerate(("白石城", "渡口", "深山"))
                    ]
                }
            ),
        ),
    )
    await db.commit()

    class Sampler:
        verify_state_events = staticmethod(frozen_state_review)
        async def sample(self, *, scene_text, input_manifest):
            index = input_manifest["scene_index"]
            subjects = range(2) if index == 0 else range(1)
            return {
                "observations": [
                    {
                        "predicate": scene_text,
                        "quote": scene_text,
                        "modality": "event_observed",
                        "mentions": [
                            {"surface": ("林舟", "青竹")[i], "entity_type": "character"}
                            for i in subjects
                        ],
                    }
                ],
                "scene_events": [
                    {
                        "dimension": "locations",
                        "event_type": "entity_moved",
                        "entity_id": ids[i],
                        "entity_type": "character",
                        "source_observation_indices": [0],
                        "snapshot_after": {
                            "text_state": ("白石城", "渡口", "深山")[index]
                        },
                    }
                    for i in subjects
                ],
            }

    provider = f"map-scene-{nid}"
    register_scene_sampler(provider, lambda db, novel_id: Sampler())
    for index in range(3):
        await handle_evolution_scene_step(
            db,
            SimpleNamespace(
                meta={
                    "novel_id": nid,
                    "run_key": "map-scene-chain",
                    "scene_index": index,
                    "scene_id": scene_ids[index],
                    "chapter_index": index + 1,
                    "scene_text": prose[index],
                    "sampler_provider": provider,
                    "budget_total": 6,
                    "state_review_version": 1,
                }
            ),
        )
        await db.commit()

    path = f"/api/world/map-atlas/{nid}/nodes/{node['id']}/scene-context"
    response = await async_client.get(path, params={"scene_id": scene_ids[1]})
    assert response.status_code == 200, response.text
    current = response.json()
    assert current["map_revision"] == saved.id
    presence = {value["character_name"]: value for value in current["presence_items"]}
    assert presence["林舟"]["presence_kind"] == "confirmed_in_scene"
    assert presence["林舟"]["feature_id"] == "place1"
    assert presence["青竹"]["presence_kind"] == "last_observed"
    assert presence["未出场的人"]["presence_kind"] == "unknown"
    assert presence["未出场的人"]["feature_id"] is None
    assert all(value["location"] != "深山" for value in current["history"])
    assert current["routes"][0]["status"] == "unknown"
    assert set(current["routes"][0]) == {
        "character_id",
        "from_scene_index",
        "from_location",
        "to_scene_index",
        "to_location",
        "status",
    }
    assert (
        presence["林舟"]["source_receipt"]["observations"][0]["evidence_quotes"][0][
            "quote"
        ]
        == prose[1]
    )
    assert (
        await async_client.get(path, params={"scene_id": scene_ids[1], "view": "reader"})
    ).status_code == 422
    assert (
        await async_client.get(path, params={"scene_id": str(uuid4())})
    ).status_code == 404

    await create_draft_only(db, nid, 1, content="林舟没有来到白石城。")
    await db.commit()
    refreshed = (await async_client.get(path, params={"scene_id": scene_ids[1]})).json()
    assert refreshed["generation_stamp"] != current["generation_stamp"]
    assert refreshed["request_context_id"] == current["request_context_id"]
    assert all(
        value["presence_kind"] == "unknown" for value in refreshed["presence_items"]
    )
    assert not refreshed["history"] and not refreshed["routes"]


@pytest.mark.parametrize("same_identity", [False, True])
async def test_map_uses_location_identity_not_same_display_name(
    db_session, test_project_id, same_identity
):
    from modules.world.map_atlas_facade import get_map_scene_context

    db, nid = db_session, test_project_id
    character, first, second = [
        CoreEntity(novel_id=UUID(nid), entity_type=kind, name=name, status="canonical")
        for kind, name in (
            ("character", "青竹"),
            ("location", "白石城"),
            ("location", "白石城"),
        )
    ]
    scene = Scene(novel_id=UUID(nid), scene_index=0, chapter_ids=[1], status="draft")
    db.add_all([character, first, second, scene])
    await db.flush()
    db.add(
        MemoryEvent(
            novel_id=UUID(nid),
            chapter_index=1,
            sequence=0,
            scene_id=scene.id,
            scene_index=0,
            scene_sequence=0,
            event_type="entity_moved",
            dimension="locations",
            entity_id=character.id,
            source="author_confirmation",
            snapshot_after={"text_state": "白石城", "location_id": str(first.id)},
        )
    )
    service = MapStructureService()
    node = await service.create_node(db, nid, MapNodeCreate(title="重名地点"))
    await db.commit()
    await service.save(
        db,
        nid,
        node["id"],
        MapSaveRequest(
            base_revision_id=node["current_revision_id"],
            document=MapDocument.model_validate(
                {
                    "features": [
                        {
                            "id": "city",
                            "kind": "location",
                            "entity_id": str(first.id if same_identity else second.id),
                            "label": "改过显示名的城" if same_identity else "白石城",
                            "points": [{"x": 1, "y": 1}],
                        }
                    ]
                }
            ),
        ),
    )
    result = await get_map_scene_context(db, nid, node["id"], str(scene.id))
    assert result.presence_items[0].location_id == str(first.id)
    assert result.presence_items[0].feature_id == ("city" if same_identity else None)


@pytest.mark.parametrize("remove", [False, True])
async def test_author_history_from_retired_scene_does_not_become_current(
    db_session, test_project_id, remove
):
    from modules.story.facade import project_scene_presence

    db, nid = db_session, test_project_id
    scene = Scene(novel_id=UUID(nid), scene_index=0, chapter_ids=[1], status="draft")
    db.add(scene)
    await db.flush()
    event = MemoryEvent(
        novel_id=UUID(nid),
        chapter_index=1,
        sequence=0,
        scene_id=scene.id,
        scene_index=0,
        scene_sequence=0,
        event_type="entity_moved",
        dimension="locations",
        entity_id=uuid4(),
        source="author_confirmation",
        snapshot_after={"text_state": "旧城"},
    )
    db.add(event)
    await db.flush()
    if remove:
        await SceneRepository().delete(db, scene.id)
    else:
        scene.status = "deprecated"
        await db.flush()
    db.add(
        Scene(
            novel_id=UUID(nid),
            scene_index=0 if remove else 1,
            chapter_ids=[1],
            status="draft",
        )
    )
    await db.flush()
    report = await project_scene_presence(db, nid, through_scene_index=1)
    assert not report.nodes
    assert await db.get(MemoryEvent, event.id) is not None
    assert not event.source_stale
