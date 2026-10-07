"""有限条件比较走真实Scene/checkpoint/角色边界，不写事件或正典。"""

import uuid

import pytest
from sqlalchemy import func, select

from core.errors import ConflictError, NotFoundError
from modules.story.continuity.models import MemoryEvent
from modules.story.continuity.scene_projection import SceneMemoryProjectionService
from modules.story.continuity.scene_state_view import SceneStateViewService
from modules.story.continuity.services import MemoryService
from modules.story.continuity.state_trial import compare_scene_state_trial
from modules.story.continuity.tests.test_scene_state_view import _custody_scene
from modules.story.contracts import SceneStateTrialRequest


async def test_finite_transfer_lock_unknown_and_receipt_revalidation(
    db_session, test_project_id
):
    db, nid = db_session, test_project_id
    scene, ids = await _custody_scene(db, nid)
    scene_id, lock = str(scene.id), str(uuid.uuid4())
    # 为两个实际人物补同地位置；锁有显式三条件，实际月相未记录。
    events = [
        {
            "dimension": "entities",
            "event_type": "entity_created",
            "entity_id": lock,
            "snapshot_after": {
                "name": "三簧锁",
                "opening_key_id": ids["key"],
                "opening_moon_phase": "full",
                "opening_passphrase": "潮落",
            },
        },
        {
            "dimension": "locations",
            "event_type": "entity_moved",
            "entity_id": ids["jia"],
            "snapshot_after": {"node": "雾渡港灯塔", "name": "甲"},
        },
        {
            "dimension": "knowledge",
            "event_type": "knowledge_changed",
            "entity_id": ids["jia"],
            "snapshot_after": {
                "character_id": ids["jia"],
                "subject_id": lock,
                "fields": ["opening_passphrase"],
                "known_values": {"opening_passphrase": "潮落"},
                "knowledge": "甲知道口令",
            },
        },
    ]
    await MemoryService().record_scene_events(
        db,
        nid,
        scene_id=scene_id,
        scene_index=0,
        chapter_index=1,
        events=events,
        producer_family="finite_trial_test",
    )
    await SceneMemoryProjectionService().ensure_scene(db, nid, scene_id)
    view = await SceneStateViewService().get_view(
        db, novel_id=nid, scene_id=scene_id, viewpoint={"kind": "author"}
    )
    count = await db.scalar(select(func.count()).select_from(MemoryEvent))
    request = SceneStateTrialRequest(
        scene_id=scene.id,
        state_fingerprint=view.state_fingerprint,
        actor_id=ids["yi"],
        key_id=ids["key"],
        recipient_id=ids["jia"],
        action="transfer_key",
    )
    transfer = await compare_scene_state_trial(db, nid, request)
    assert transfer["baseline"]["outcome"] == "succeeded"
    state = transfer["baseline"]["candidate_state"]
    assert state["resource_holders"][ids["key"]] == ids["jia"]
    assert state["owners"][ids["key"]] == ids["jia"]
    opening = request.model_copy(
        update={
            "action": "open_lock",
            "actor_id": uuid.UUID(ids["jia"]),
            "lock_id": uuid.UUID(lock),
            "recipient_id": None,
            "candidate_holder_id": uuid.UUID(ids["jia"]),
            "candidate_moon_phase": "full",
        }
    )
    comparison = await compare_scene_state_trial(db, nid, opening)
    assert comparison["baseline"]["outcome"] == "failed"
    assert comparison["candidate"]["outcome"] == "succeeded"
    assert comparison["candidate"]["candidate_state"]["owners"][ids["key"]] == ids["jia"]
    assert comparison["candidate"]["resolution"]["state_patches"] == []  # 开锁不转移物品
    assert comparison["assumptions"]
    bound = opening.model_copy(
        update={"comparison_digest": comparison["comparison_digest"]}
    )
    assert (await compare_scene_state_trial(db, nid, bound))[
        "comparison_digest"
    ] == comparison["comparison_digest"]
    assert await db.scalar(select(func.count()).select_from(MemoryEvent)) == count
    # 旧口令知识不能自动放行已改变的口令。
    await MemoryService().record_scene_events(
        db,
        nid,
        scene_id=scene_id,
        scene_index=0,
        chapter_index=1,
        events=[
            {
                "dimension": "entities",
                "event_type": "entity_updated",
                "entity_id": lock,
                "snapshot_after": {"opening_passphrase": "潮起"},
            }
        ],
        producer_family="passphrase_revision",
    )
    await SceneMemoryProjectionService().ensure_scene(db, nid, scene_id)
    changed = await SceneStateViewService().get_view(
        db, novel_id=nid, scene_id=scene_id, viewpoint={"kind": "author"}
    )
    wrong_phrase = await compare_scene_state_trial(
        db,
        nid,
        opening.model_copy(update={"state_fingerprint": changed.state_fingerprint}),
    )
    assert wrong_phrase["candidate"]["conditions"][-1]["status"] == "unmet"
    assert wrong_phrase["candidate"]["outcome"] == "failed"
    await MemoryService().record_scene_events(
        db,
        nid,
        scene_id=scene_id,
        scene_index=0,
        chapter_index=1,
        events=[
            {
                "dimension": "knowledge",
                "event_type": "knowledge_changed",
                "entity_id": ids["jia"],
                "snapshot_after": {
                    "id": "new-phrase",
                    "character_id": ids["jia"],
                    "subject_id": lock,
                    "fields": ["opening_passphrase"],
                    "known_values": {"opening_passphrase": "潮起"},
                    "knowledge": "甲后来获知新口令",
                },
            }
        ],
        producer_family="later_knowledge",
    )
    await SceneMemoryProjectionService().ensure_scene(db, nid, scene_id)
    changed = await SceneStateViewService().get_view(
        db, novel_id=nid, scene_id=scene_id, viewpoint={"kind": "author"}
    )
    later_knowledge = await compare_scene_state_trial(
        db,
        nid,
        opening.model_copy(update={"state_fingerprint": changed.state_fingerprint}),
    )
    assert later_knowledge["candidate"]["outcome"] == "succeeded"
    assert later_knowledge["candidate"]["conditions"][-1]["observed"] == "潮起"
    with pytest.raises(ConflictError):
        await compare_scene_state_trial(
            db, nid, opening.model_copy(update={"state_fingerprint": "a" * 64})
        )
    with pytest.raises(NotFoundError):
        await compare_scene_state_trial(
            db,
            nid,
            opening.model_copy(
                update={
                    "actor_id": uuid.uuid4(),
                    "state_fingerprint": changed.state_fingerprint,
                }
            ),
        )
    # 直接改源基线不清空事实行：读时降级，旧条件回执不能采用。
    scene.chapter_ids = ["1", "2"]
    await db.flush()
    with pytest.raises(ConflictError):
        await compare_scene_state_trial(db, nid, bound)
