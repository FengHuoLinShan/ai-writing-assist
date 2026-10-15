from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from core.errors import ConflictError, NotFoundError
from modules.world.map_declaration_state import (
    map_declaration_subject_id,
    require_map_declaration_state,
)
from modules.world.map_structure_schemas import MapDocument


class _ScalarDb:
    def __init__(self, values):
        self.values = iter(values)

    async def scalar(self, _statement):
        return next(self.values)


def _map_rows(*, novel_id, node_id, revision_id, declaration_id="feature:harbor"):
    scene_id = uuid4()
    document = MapDocument.model_validate(
        {
            "schema_version": 2,
            "features": [
                {
                    "id": declaration_id,
                    "kind": "location",
                    "label": "北港",
                    "effective": {"start": {"kind": "scene", "id": str(scene_id)}},
                }
            ],
        }
    )
    node = SimpleNamespace(
        id=node_id,
        novel_id=novel_id,
        status="adopted",
        merged_into_node_id=None,
        current_revision_id=revision_id,
    )
    revision = SimpleNamespace(
        id=revision_id,
        node_id=node_id,
        novel_id=novel_id,
        status="saved",
        document=document.model_dump(mode="json"),
    )
    return node, revision


@pytest.mark.asyncio
async def test_world_binds_only_current_project_revision_and_exact_declaration():
    novel_id, node_id, revision_id = uuid4(), uuid4(), uuid4()
    node, revision = _map_rows(
        novel_id=novel_id, node_id=node_id, revision_id=revision_id
    )
    binding = await require_map_declaration_state(
        _ScalarDb([node, revision]),
        str(novel_id),
        node_id=str(node_id),
        revision_id=str(revision_id),
        declaration_kind="feature",
        declaration_id="feature:harbor",
    )

    assert binding == {
        "novel_id": str(novel_id),
        "node_id": str(node_id),
        "revision_id": str(revision_id),
        "declaration_kind": "feature",
        "declaration_id": "feature:harbor",
        "field_key": "effective_status",
        "subject_id": map_declaration_subject_id(
            str(novel_id), str(node_id), "feature", "feature:harbor"
        ),
        "label": "地图结构状态",
    }


@pytest.mark.asyncio
async def test_world_rejects_stale_revision_cross_project_or_removed_declaration():
    novel_id, node_id, revision_id = uuid4(), uuid4(), uuid4()
    current_node, _revision = _map_rows(
        novel_id=novel_id, node_id=node_id, revision_id=uuid4()
    )
    with pytest.raises(ConflictError, match="Map changed"):
        await require_map_declaration_state(
            _ScalarDb([current_node]),
            str(novel_id),
            node_id=str(node_id),
            revision_id=str(revision_id),
            declaration_kind="feature",
            declaration_id="feature:harbor",
        )

    with pytest.raises(NotFoundError):
        await require_map_declaration_state(
            _ScalarDb([None]),
            str(uuid4()),
            node_id=str(node_id),
            revision_id=str(revision_id),
            declaration_kind="feature",
            declaration_id="feature:harbor",
        )

    node, revision = _map_rows(
        novel_id=novel_id, node_id=node_id, revision_id=revision_id
    )
    with pytest.raises(ConflictError, match="declaration or its author interval"):
        await require_map_declaration_state(
            _ScalarDb([node, revision]),
            str(novel_id),
            node_id=str(node_id),
            revision_id=str(revision_id),
            declaration_kind="feature",
            declaration_id="feature:deleted",
        )


@pytest.mark.asyncio
async def test_world_rejects_unadopted_and_unbounded_map_items():
    novel_id, node_id, revision_id = uuid4(), uuid4(), uuid4()
    node, revision = _map_rows(
        novel_id=novel_id, node_id=node_id, revision_id=revision_id
    )
    node.status = "provisional"
    with pytest.raises(NotFoundError):
        await require_map_declaration_state(
            _ScalarDb([node]),
            str(novel_id),
            node_id=str(node_id),
            revision_id=str(revision_id),
            declaration_kind="feature",
            declaration_id="feature:harbor",
        )

    node.status = "adopted"
    revision.document["features"][0]["effective"] = None
    with pytest.raises(ConflictError, match="declaration or its author interval"):
        await require_map_declaration_state(
            _ScalarDb([node, revision]),
            str(novel_id),
            node_id=str(node_id),
            revision_id=str(revision_id),
            declaration_kind="feature",
            declaration_id="feature:harbor",
        )
