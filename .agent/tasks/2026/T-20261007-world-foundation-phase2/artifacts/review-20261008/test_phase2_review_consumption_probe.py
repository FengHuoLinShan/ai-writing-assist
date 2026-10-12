import uuid

from modules.evolution.impact import load_scene_consumption_records
from modules.story.continuity.scene_projection import SceneMemoryProjectionService
from modules.story.continuity.services import MemoryService
from modules.writing.tests.test_p2c_recompute import _scene, _working_draft


async def test_actual_projection_records_its_consumption(db_session, test_project_id):
    scene = await _scene(db_session, test_project_id, 0, 1)
    await _working_draft(db_session, test_project_id, 1, 1, "甲将铜钥匙交给乙。")
    await MemoryService().record_scene_events(
        db_session, test_project_id, scene_id=str(scene.id), scene_index=0, chapter_index=1,
        events=[{"dimension": "entities", "event_type": "entity_created",
                 "entity_id": str(uuid.uuid4()),
                 "snapshot_after": {"name": "铜钥匙", "custody_holder": "乙"}}],
    )
    built = await SceneMemoryProjectionService().ensure_scene(
        db_session, test_project_id, str(scene.id)
    )
    assert len(built.items) == 6
    records = await load_scene_consumption_records(
        db_session, test_project_id,
        [{"id": str(scene.id), "scene_index": 0, "chapter_ids": [1]}],
    )
    assert records, "actual scene projection creates six checkpoints but no consumption record"
