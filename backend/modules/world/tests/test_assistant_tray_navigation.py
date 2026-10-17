from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.assistant_operation_registry import world_map_operations
from core.errors import ConflictError, DomainError
from modules.account.facade import current_account_id
from modules.assistant.contracts import AssistantOperationContext, WorkContext
from modules.world.assistant_map_tools import PrepareTrayPlacement
from modules.world.map_atlas_models import MapAtlasNode
from modules.world.map_auto_draft_service import build_map_auto_drafts
from modules.world.map_structure_service import inspect_map_node
from modules.world.tests.test_map_auto_draft_service import (
    _build_request,
    _stage_bound_clue,
)


def test_tray_schema_has_no_model_coordinates_and_is_bounded():
    valid = dict(node_id=uuid4(), revision_id=uuid4(), item_ids=[uuid4()])
    for extra in (
        {"point": {"x": 1, "y": 2}},
        {"human_selected": True},
        {"item_ids": [uuid4() for _ in range(21)]},
        {"item_ids": []},
        {"item_ids": valid["item_ids"] * 2},
    ):
        with pytest.raises(ValidationError):
            PrepareTrayPlacement(**{**valid, **extra})


@pytest.mark.asyncio
async def test_read_prepare_navigation_revalidates_exact_target_and_head(
    db_session, two_projects
):
    db, (nid, other) = db_session, two_projects
    scene, _, _, clue = await _stage_bound_clue(db, nid, modality="character_statement")
    built = await build_map_auto_drafts(db, nid, _build_request(scene, clue))
    tray = built.tray_items[0]
    revision = next(item for item in built.revisions if item.node_id == tray.node_id)
    args = PrepareTrayPlacement(
        node_id=tray.node_id, revision_id=revision.revision_id, item_ids=[tray.item_id]
    )
    context = AssistantOperationContext(
        str(uuid4()), str(current_account_id()), WorkContext(page="map", scope="project")
    )
    read = await inspect_map_node(db, nid, str(tray.node_id))
    assert read["tray_placement_targets"]["targets"][0]["items"][0]["item_id"] == str(
        tray.item_id
    )
    op = world_map_operations["map.prepare_tray_placement"]
    bounded = AssistantOperationContext(
        str(uuid4()),
        str(current_account_id()),
        WorkContext(page="writing", scope="current", chapter_index=1),
    )
    with pytest.raises(ConflictError):
        await op.prepare(db, nid, args, context=bounded)
    preview = await op.prepare(db, nid, args, context=context)
    assert preview["base_revision_id"] is None
    assert preview["items"][0]["fingerprint"] == tray.fingerprint
    result = await op.apply(db, nid, args, preview, context=context)
    assert result["type"] == "map_tray_placement"
    assert "point" not in result
    assert (await db.get(MapAtlasNode, tray.node_id)).current_revision_id is None
    with pytest.raises(DomainError) as failure:
        await op.prepare(db, other, args, context=context)
    assert failure.value.status_code in {404, 409}
    for changed in (
        {"node_id": uuid4()},
        {"revision_id": uuid4()},
        {"item_ids": [uuid4()]},
    ):
        with pytest.raises(ConflictError):
            await op.prepare(db, nid, args.model_copy(update=changed), context=context)
    preview["items"][0]["fingerprint"] = "0" * 64
    with pytest.raises(ConflictError):
        await op.apply(db, nid, args, preview, context=context)
    node = await db.get(MapAtlasNode, tray.node_id)
    node.current_revision_id = revision.revision_id
    await db.flush()
    with pytest.raises(ConflictError):
        await op.prepare(db, nid, args, context=context)


@pytest.mark.asyncio
async def test_author_read_bounds_total_tray_targets_to_twenty(
    db_session, project_novel_id
):
    from modules.world.map_auto_draft_models import MapAutoDraftBatchRecord

    db, nid = db_session, project_novel_id
    scene, _, _, clue = await _stage_bound_clue(db, nid, modality="character_statement")
    built = await build_map_auto_drafts(db, nid, _build_request(scene, clue))
    batch = await db.get(MapAutoDraftBatchRecord, built.batch_id)
    original = batch.tray_items[0]
    batch.tray_items = [{**original, "item_id": str(uuid4())} for _ in range(25)]
    await db.flush()
    read = await inspect_map_node(db, nid, original["node_id"])
    targets = read["tray_placement_targets"]
    assert sum(len(target["items"]) for target in targets["targets"]) == 20
    assert targets["truncated"]


def test_existing_run_manifest_does_not_gain_tray_operation():
    from core.container import container_scope
    from modules.assistant.operations import operation_manifest, resolve_operations

    old = {
        key: op
        for key, op in world_map_operations.items()
        if key != "map.prepare_tray_placement"
    }
    with container_scope({"assistant.operations": old}):
        frozen = operation_manifest()
    with container_scope({"assistant.operations": world_map_operations}):
        assert "map.prepare_tray_placement" not in resolve_operations(frozen)
        assert "map.prepare_tray_placement" in resolve_operations(operation_manifest())
