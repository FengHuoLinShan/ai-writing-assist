"""Real PostgreSQL identity checks for typed simulation references."""

from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from modules.account.contracts import BOOTSTRAP_ACCOUNT_ID
from modules.account.models import Account
from modules.project.models import Project
from modules.story.rehearsals import validate_simulation_context_refs
from modules.story.simulation_v3 import (
    SimulationPosition,
    SimulationReference,
    SimulationV3Context,
)
from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.models import CoreEntity

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_v3_refs_require_current_world_identity_before_http_enqueue(
    db_session, async_client
):
    novel_id, other_novel_id = uuid4(), uuid4()
    actor_id, foreign_id, map_id, revision_id = (uuid4() for _ in range(4))
    if await db_session.get(Account, BOOTSTRAP_ACCOUNT_ID) is None:
        db_session.add(Account(id=BOOTSTRAP_ACCOUNT_ID, support_code="simulation-ref"))
    db_session.add_all(
        [
            Project(id=novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="推演引用测试"),
            Project(id=other_novel_id, owner_id=BOOTSTRAP_ACCOUNT_ID, title="另一本作品"),
        ]
    )
    await db_session.flush()
    db_session.add_all(
        [
            CoreEntity(
                id=actor_id,
                novel_id=novel_id,
                entity_type="character",
                name="当前人物",
                status="canonical",
            ),
            CoreEntity(
                id=foreign_id,
                novel_id=other_novel_id,
                entity_type="location",
                name="另一本作品的地点",
                status="canonical",
            ),
            MapAtlasNode(
                id=map_id,
                novel_id=novel_id,
                semantic_key="simulation-review-map",
                title="当前地图",
                level="city",
                status="adopted",
                current_revision_id=revision_id,
            ),
            MapAtlasRevision(
                id=revision_id,
                novel_id=novel_id,
                node_id=map_id,
                status="saved",
                document={},
                geometry_hash="a" * 64,
            ),
        ]
    )
    await db_session.flush()

    actor = SimulationReference(kind="object", id=str(actor_id))
    saved_map = SimulationReference(kind="map_node", id=str(map_id))
    context = SimulationV3Context(
        participants=[actor],
        locations=[saved_map],
        positions=[SimulationPosition(subject=actor, location=saved_map)],
        resources=[
            {
                "resource": {
                    "kind": "candidate",
                    "id": "temporary-prop",
                    "label": "本轮临时道具",
                }
            }
        ],
    )
    await validate_simulation_context_refs(db_session, str(novel_id), context)

    scene_id = str(uuid4())
    with (
        patch(
            "core.config.get_settings",
            autospec=True,
            return_value=SimpleNamespace(story_rehearsal_enabled=True),
        ),
        patch("modules.story.api.require_fresh_confirmation", autospec=True) as fresh,
    ):
        response = await async_client.post(
            f"/api/story/scenes/{scene_id}/rehearsals",
            json={
                "novel_id": str(novel_id),
                "scene_id": scene_id,
                "character_ids": [str(actor_id)],
                "context_confirmation_id": "synthetic-confirmation",
                "simulation_protocol": "simulation_v3",
                "simulation_seed": {
                    **context.model_dump(mode="json"),
                    "locations": [{"kind": "object", "id": str(foreign_id)}],
                    "positions": [],
                },
            },
        )
    assert response.status_code == 400
    assert "不属于当前作品" in response.json()["detail"]
    fresh.assert_not_awaited()
