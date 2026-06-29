"""Manual real-LLM acceptance for Writing conflict checks.

Skipped by default. Run with:
    RUN_REAL_LLM_TESTS=1 pytest \
        modules/writing/tests/test_conflict_checks_real_llm.py -q -s
"""

from __future__ import annotations

import json
import os
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.memory.models import MemoryEvent, MemorySnapshot
from modules.world.models import CoreEntity

real_llm_required = pytest.mark.skipif(
    os.getenv("RUN_REAL_LLM_TESTS") != "1",
    reason="真实 LLM 写作冲突检查验收默认跳过；设置 RUN_REAL_LLM_TESTS=1 才运行",
)

pytestmark = [pytest.mark.asyncio, pytest.mark.real_llm, real_llm_required]

TEST_TITLE = "第一章 旧约门"
CHAPTER_INDEX = 3
TEST_CONTENT = (
    "雨夜里，主角在旧约门前拦住守门人。守门人提到银色通行符，却还没来得及"
    "交出它，主角杀死守门人，转身就相信了一封没有署名的敌方祭司来信。"
    "他没有向旧盟友解释自己为什么违背昨日立下的誓约，只说这条路一定正确，"
    "随后独自走进禁区。"
)


async def _create_project(async_client: AsyncClient) -> str:
    resp = await async_client.post(
        "/api/projects",
        json={
            "title": "真实 LLM 写作冲突验收",
            "genre": "fantasy",
            "language": "zh",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_scene(async_client: AsyncClient, novel_id: str) -> dict:
    character = await _create_entity(
        async_client,
        novel_id,
        {
            "name": "沈砚",
            "entity_type": "character",
            "status": "canonical",
        },
    )
    resp = await async_client.post(
        f"/api/outline/scenes?novel_id={novel_id}",
        json={
            "scene_index": CHAPTER_INDEX,
            "title": "旧约门交涉",
            "goal": "主角必须不杀守门人，并取得进入禁区的合法通行方式。",
            "core_conflict": "守门人怀疑主角背弃旧盟友，拒绝放行。",
            "must_happen": "守门人交出银色通行符；主角向旧盟友解释违背誓约的原因",
            "must_not_happen": "主角杀死守门人",
            "pov_character_id": character["id"],
            "chapter_ids": [str(CHAPTER_INDEX)],
            "scene_chunks": [
                {
                    "chapter_id": str(CHAPTER_INDEX),
                    "chapter_index": CHAPTER_INDEX,
                    "start_pos": 0,
                    "end_pos": 1000,
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    scene = resp.json()
    scene["pov_character_id"] = character["id"]
    return scene


async def _create_entity(
    async_client: AsyncClient,
    novel_id: str,
    data: dict,
) -> dict:
    resp = await async_client.post(
        f"/api/world/entities?novel_id={novel_id}",
        json=data,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _seed_map_evidence(
    async_client: AsyncClient,
    novel_id: str,
    *,
    scene_id: str,
    character_id: str,
) -> dict:
    location = await _create_entity(
        async_client,
        novel_id,
        {
            "name": "旧约门",
            "entity_type": "location",
            "status": "canonical",
        },
    )
    map_resp = await async_client.post(
        f"/api/world/maps?novel_id={novel_id}",
        json={
            "name": "旧约门风险图",
            "map_type": "world",
            "grid_width": 5,
            "grid_height": 5,
            "template": "blank",
        },
    )
    assert map_resp.status_code == 201, map_resp.text
    map_data = map_resp.json()

    binding_resp = await async_client.post(
        f"/api/world/maps/{map_data['id']}/location-bindings?novel_id={novel_id}",
        json={
            "location_entity_id": location["id"],
            "hexes": [{"hex_q": 1, "hex_r": 1, "is_center": True}],
        },
    )
    assert binding_resp.status_code == 201, binding_resp.text

    marker_resp = await async_client.post(
        f"/api/world/maps/{map_data['id']}/markers?novel_id={novel_id}",
        json={
            "entity_id": character_id,
            "marker_type": "character",
            "hex_q": 1,
            "hex_r": 1,
            "label": "沈砚",
            "start_scene_id": scene_id,
            "start_scene_index": CHAPTER_INDEX,
            "visible": True,
        },
    )
    assert marker_resp.status_code == 201, marker_resp.text

    observation_resp = await async_client.post(
        f"/api/world/maps/{map_data['id']}/observations?novel_id={novel_id}",
        json={
            "target_entity_id": location["id"],
            "target_entity_type": "location",
            "target_name": "旧约门粮仓火势",
            "dynamic_type": "risk",
            "time_anchor": {
                "chapter_index": CHAPTER_INDEX,
                "scene_id": scene_id,
                "scene_index": CHAPTER_INDEX,
            },
            "spatial_anchor": {
                "hex_q": 1,
                "hex_r": 1,
                "location_name": "旧约门",
            },
            "value_json": {"risk": "粮仓火势正在扩大"},
            "confidence": 0.86,
            "review_state": "candidate",
            "source_ref": {
                "source": "writing_conflict_real_llm_pytest",
                "chapter_index": CHAPTER_INDEX,
                "scene_id": scene_id,
            },
            "evidence_text": "真实 LLM pytest 候选地图证据：旧约门粮仓火势正在扩大。",
            "scene_id": scene_id,
            "scene_index": CHAPTER_INDEX,
            "source_chapter_index": CHAPTER_INDEX,
        },
    )
    assert observation_resp.status_code == 201, observation_resp.text
    return {
        "map": map_data,
        "location": location,
        "observation": observation_resp.json(),
    }


async def _seed_memory_evidence(
    db_session: AsyncSession,
    novel_id: str,
    *,
    character_id: str,
) -> None:
    db_session.add(
        MemoryEvent(
            novel_id=uuid.UUID(novel_id),
            chapter_index=CHAPTER_INDEX - 1,
            sequence=1,
            event_type="entity_moved",
            entity_id=uuid.UUID(character_id),
            entity_type="character",
            snapshot_before={},
            snapshot_after={
                "location_id": "old-gate-location",
                "text_state": "上一章仍在旧城外门",
                "chapter_index": CHAPTER_INDEX - 1,
            },
            source="manual_edit",
        )
    )
    await db_session.flush()


async def _create_context_confirmation(
    async_client: AsyncClient,
    novel_id: str,
    *,
    action: str,
    scene_id: str,
    chapter_index: int = CHAPTER_INDEX,
) -> str:
    resp = await async_client.post(
        "/api/context/confirm",
        json={
            "novel_id": novel_id,
            "action": action,
            "task": (
                "真实 LLM 写作冲突验收：重点检查主角突然相信敌方祭司来信、"
                "没有解释背誓原因的动机软冲突。"
            ),
            "scope": "chapter",
            "chapter_index": chapter_index,
            "scene_id": scene_id,
            "context_mode": "canonical",
            "include_pending_objects": False,
            "user_note": "请只报告与当前 Scene 目标相关的软冲突，避免重复规则层硬冲突。",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _count_rows(db_session: AsyncSession, model: type) -> int:
    result = await db_session.execute(select(func.count()).select_from(model))
    return int(result.scalar_one())


@real_llm_required
async def test_real_llm_conflict_review_suggestion_status_and_publish_snapshot(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    scene_id = scene["id"]
    map_seed = await _seed_map_evidence(
        async_client,
        novel_id,
        scene_id=scene_id,
        character_id=scene["pov_character_id"],
    )
    await _seed_memory_evidence(
        db_session,
        novel_id,
        character_id=scene["pov_character_id"],
    )

    world_count_before = await _count_rows(db_session, CoreEntity)
    memory_events_before = await _count_rows(db_session, MemoryEvent)
    memory_snapshots_before = await _count_rows(db_session, MemorySnapshot)

    draft_resp = await async_client.post(
        "/api/writing/drafts/autosave",
        json={
            "novel_id": novel_id,
            "chapter_index": CHAPTER_INDEX,
            "title": TEST_TITLE,
            "content": TEST_CONTENT,
        },
    )
    assert draft_resp.status_code == 201, draft_resp.text
    draft = draft_resp.json()

    check_resp = await async_client.post(
        "/api/writing/conflict-checks",
        json={
            "novel_id": novel_id,
            "chapter_index": CHAPTER_INDEX,
            "scene_id": scene_id,
            "draft_id": draft["id"],
            "version_number": draft["version_number"],
            "include_candidates": True,
            "content": TEST_CONTENT,
        },
    )
    assert check_resp.status_code == 201, check_resp.text
    check = check_resp.json()
    rule_kinds = {item["kind"] for item in check["items"]}
    assert "forbidden_present" in rule_kinds, check
    assert "required_missing" in rule_kinds, check
    assert "map_risk" in rule_kinds, check
    assert "continuity_location_mismatch" in rule_kinds, check
    map_item = next(item for item in check["items"] if item["kind"] == "map_risk")
    assert map_item["source_module"] == "world"
    assert map_item["needs_review"] is True
    assert map_item["location_json"]["source"]["module"] == "world"
    assert map_item["location_json"]["source"]["type"] == "map.scene_summary"
    assert map_item["location_json"]["open_target"] == {
        "kind": "map_object",
        "map_id": map_seed["map"]["id"],
        "scene_id": scene_id,
        "observation_id": map_seed["observation"]["id"],
        "focus_entity_id": map_seed["location"]["id"],
    }
    memory_item = next(
        item for item in check["items"] if item["kind"] == "continuity_location_mismatch"
    )
    assert memory_item["source_module"] == "memory"
    assert memory_item["location_json"]["source"]["module"] == "memory"
    assert memory_item["location_json"]["open_target"] == {
        "kind": "memory_chapter",
        "chapter_index": CHAPTER_INDEX - 1,
        "character_id": scene["pov_character_id"],
    }

    review_confirmation_id = await _create_context_confirmation(
        async_client,
        novel_id,
        action="writing.conflict_check.ai_review",
        scene_id=scene_id,
    )
    review_resp = await async_client.post(
        f"/api/writing/conflict-checks/{check['id']}/ai-review",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": review_confirmation_id,
        },
    )
    assert review_resp.status_code == 200, review_resp.text
    reviewed = review_resp.json()
    assert reviewed["ai_review_status"] in {"done", "partial"}, (
        "AI review did not complete with a usable terminal status: "
        f"check_id={check['id']} confirmation_id={review_confirmation_id} "
        f"status={reviewed.get('ai_review_status')} "
        f"error={reviewed.get('ai_review_error')}"
    )
    ai_items = [item for item in reviewed["items"] if item["is_ai_judgment"]]
    assert ai_items, (
        "真实 LLM 未产出 AI 软冲突项；请检查 prompt 或模型兼容性。"
        f" check_id={check['id']} summary={reviewed.get('summary_json')}"
    )
    ai_item = ai_items[0]
    assert ai_item["source_module"] == "ai"
    assert ai_item["source_confirmation_id"] == review_confirmation_id
    assert 0 <= ai_item["confidence"] <= 1
    assert ai_item["llm_rationale"]

    draft_after_review = await async_client.get(
        f"/api/writing/drafts/{draft['id']}",
        params={"novel_id": novel_id},
    )
    assert draft_after_review.status_code == 200, draft_after_review.text
    assert draft_after_review.json()["content"] == TEST_CONTENT

    suggestion_confirmation_id = await _create_context_confirmation(
        async_client,
        novel_id,
        action="writing.conflict_check.ai_suggestion",
        scene_id=scene_id,
    )
    suggestion_resp = await async_client.post(
        f"/api/writing/conflict-check-items/{ai_item['id']}/ai-suggestion",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": suggestion_confirmation_id,
        },
    )
    assert suggestion_resp.status_code == 200, suggestion_resp.text
    suggested = suggestion_resp.json()
    assert suggested["suggestion_status"] == "done", (
        "AI suggestion did not complete: "
        f"item_id={ai_item['id']} confirmation_id={suggestion_confirmation_id} "
        f"status={suggested.get('suggestion_status')} "
        f"error={suggested.get('suggestion_error')}"
    )
    assert suggested["suggestion_confirmation_id"] == suggestion_confirmation_id
    suggestion_payload = json.loads(suggested["ai_suggestion"])
    assert suggestion_payload["strategy"]
    assert suggestion_payload["suggested_text"]
    assert suggestion_payload["rationale"]

    draft_after_suggestion = await async_client.get(
        f"/api/writing/drafts/{draft['id']}",
        params={"novel_id": novel_id},
    )
    assert draft_after_suggestion.status_code == 200, draft_after_suggestion.text
    assert draft_after_suggestion.json()["content"] == TEST_CONTENT
    assert await _count_rows(db_session, CoreEntity) == world_count_before
    assert await _count_rows(db_session, MemoryEvent) == memory_events_before
    assert await _count_rows(db_session, MemorySnapshot) == memory_snapshots_before

    status_resp = await async_client.patch(
        f"/api/writing/conflict-check-items/{ai_item['id']}?novel_id={novel_id}",
        json={"status": "later"},
    )
    assert status_resp.status_code == 200, status_resp.text
    assert status_resp.json()["status"] == "later"

    published_resp = await async_client.post(
        "/api/writing/drafts",
        json={
            "novel_id": novel_id,
            "chapter_index": CHAPTER_INDEX,
            "scene_id": scene_id,
            "title": TEST_TITLE,
            "content": TEST_CONTENT,
        },
    )
    assert published_resp.status_code == 201, published_resp.text
    snapshot = published_resp.json()["draft"]["conflict_check_snapshot_json"]
    assert snapshot["check_id"] == check["id"]
    assert snapshot["ai_review_status"] in {"done", "partial"}
    assert snapshot["ai_judgment_count"] >= 1
    assert snapshot["suggestion_count"] >= 1
    assert any(item["is_ai_judgment"] for item in snapshot["items"])
    assert any(item["has_ai_suggestion"] for item in snapshot["items"])
    assert any(
        item["kind"] == "forbidden_present" and item["source_module"] == "outline"
        for item in snapshot["items"]
    )
    snapshot_map_item = next(
        item for item in snapshot["items"] if item["kind"] == "map_risk"
    )
    assert snapshot_map_item["source_module"] == "world"
    assert snapshot_map_item["needs_review"] is True
    assert snapshot_map_item["location_json"]["source"]["module"] == "world"
    assert snapshot_map_item["location_json"]["open_target"] == {
        "kind": "map_object",
        "map_id": map_seed["map"]["id"],
        "scene_id": scene_id,
        "observation_id": map_seed["observation"]["id"],
        "focus_entity_id": map_seed["location"]["id"],
    }
    assert "text_range" not in snapshot_map_item["location_json"]
    snapshot_memory_item = next(
        item
        for item in snapshot["items"]
        if item["kind"] == "continuity_location_mismatch"
    )
    assert snapshot_memory_item["source_module"] == "memory"
    assert snapshot_memory_item["location_json"]["source"]["module"] == "memory"
    assert snapshot_memory_item["location_json"]["open_target"] == {
        "kind": "memory_chapter",
        "chapter_index": CHAPTER_INDEX - 1,
        "character_id": scene["pov_character_id"],
    }
    assert "text_range" not in snapshot_memory_item["location_json"]

    print(
        "[REAL-LLM-WRITING-CONFLICT] "
        f"novel_id={novel_id} check_id={check['id']} "
        f"ai_items={len(ai_items)} suggestion_item={ai_item['id']}"
    )
