from uuid import UUID, uuid4

import pytest

from core.errors import ConflictError
from modules.account.facade import current_account_id
from modules.assistant.contracts import AssistantOperationContext, WorkContext
from modules.world.assistant_map_tools import (
    OPERATIONS,
    AddKnownLocation,
    EditFeatureLabel,
)
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
    op = OPERATIONS["map.add_known_location"]
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
    op = OPERATIONS["map.edit_feature_label"]
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
