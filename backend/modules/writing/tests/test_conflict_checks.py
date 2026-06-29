"""Writing Scene conflict-check behavior."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.errors import LLMTimeoutError
from infrastructure.tasks.models import AsyncTask
from modules.memory.contracts import MemoryContinuityEvidenceContract


async def _create_project(async_client: AsyncClient, title: str = "冲突检查项目") -> str:
    resp = await async_client.post("/api/projects", json={"title": title})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _create_scene(
    async_client: AsyncClient,
    novel_id: str,
    *,
    chapter_index: int = 1,
    must_happen: str = "主角拿到令牌；王后签字",
    must_not_happen: str = "主角死亡",
    pov_character_id: str | None = None,
) -> dict:
    resp = await async_client.post(
        f"/api/outline/scenes?novel_id={novel_id}",
        json={
            "scene_index": chapter_index,
            "title": "东门交涉",
            "goal": "拿到入城许可",
            "core_conflict": "守卫拒绝放行",
            "must_happen": must_happen,
            "must_not_happen": must_not_happen,
            "pov_character_id": pov_character_id,
            "chapter_ids": [str(chapter_index)],
            "scene_chunks": [
                {
                    "chapter_id": str(chapter_index),
                    "chapter_index": chapter_index,
                    "start_pos": 0,
                    "end_pos": 1000,
                }
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_check(
    async_client: AsyncClient,
    novel_id: str,
    scene_id: str | None,
    *,
    content: str = "主角死亡。王后沉默。",
    chapter_index: int = 1,
    include_candidates: bool = False,
) -> dict:
    resp = await async_client.post(
        "/api/writing/conflict-checks",
        json={
            "novel_id": novel_id,
            "chapter_index": chapter_index,
            "scene_id": scene_id,
            "content": content,
            "include_candidates": include_candidates,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_context_confirmation(
    async_client: AsyncClient,
    novel_id: str,
    *,
    action: str,
    chapter_index: int = 1,
    scene_id: str | None = None,
    include_pending_objects: bool = False,
) -> str:
    payload = {
        "novel_id": novel_id,
        "action": action,
        "task": "writing conflict AI test",
        "scope": "chapter",
        "chapter_index": chapter_index,
        "context_mode": "canonical",
        "include_pending_objects": include_pending_objects,
    }
    if scene_id:
        payload["scene_id"] = scene_id
    resp = await async_client.post(
        "/api/context/confirm",
        json=payload,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_conflict_check_persists_rule_hits_and_summary(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)

    body = await _create_check(async_client, novel_id, scene["id"])

    assert body["status"] in {"completed", "degraded"}
    assert body["summary_json"]["total"] == len(body["items"])
    kinds = {item["kind"]: item for item in body["items"]}
    assert kinds["forbidden_present"]["severity"] == "high"
    assert kinds["forbidden_present"]["source_module"] == "outline"
    assert "主角死亡" in kinds["forbidden_present"]["evidence_summary"]
    forbidden_location = kinds["forbidden_present"]["location_json"]
    assert forbidden_location["source"] == {
        "module": "outline",
        "type": "scene.must_not_happen",
        "id": scene["id"],
        "label": "Scene：东门交涉",
        "field": "禁止发生",
        "excerpt": "主角死亡",
    }
    assert forbidden_location["open_target"] == {
        "kind": "outline_scene",
        "scene_id": scene["id"],
    }
    assert forbidden_location["text_range"]["start"] == 0
    assert forbidden_location["needs_review_reason"] is None
    assert kinds["required_missing"]["severity"] == "medium"
    required_summaries = [
        item["evidence_summary"]
        for item in body["items"]
        if item["kind"] == "required_missing"
    ]
    assert any("主角拿到令牌" in summary for summary in required_summaries)
    required_items = [
        item for item in body["items"] if item["kind"] == "required_missing"
    ]
    assert all(
        item["location_json"]["open_target"]["kind"] == "outline_scene"
        for item in required_items
    )
    required_location = required_items[0]["location_json"]
    assert required_location["source"]["type"] == "scene.must_happen"
    assert required_location["source"]["field"] == "必须发生"
    assert required_location["source"]["excerpt"] in {"主角拿到令牌", "王后签字"}
    assert kinds["required_missing"]["status"] == "open"


@pytest.mark.asyncio
async def test_conflict_item_status_update_is_novel_scoped(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client, "A")
    other_novel_id = await _create_project(async_client, "B")
    scene = await _create_scene(async_client, novel_id)
    check = await _create_check(async_client, novel_id, scene["id"])
    item_id = check["items"][0]["id"]

    wrong_scope = await async_client.patch(
        f"/api/writing/conflict-check-items/{item_id}?novel_id={other_novel_id}",
        json={"status": "later"},
    )
    assert wrong_scope.status_code == 404

    ok = await async_client.patch(
        f"/api/writing/conflict-check-items/{item_id}?novel_id={novel_id}",
        json={"status": "later"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "later"


@pytest.mark.asyncio
async def test_conflict_check_history_returns_latest_first(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    first = await _create_check(async_client, novel_id, scene["id"], content="正文一")
    second = await _create_check(async_client, novel_id, scene["id"], content="正文二")

    resp = await async_client.get(
        "/api/writing/conflict-checks",
        params={
            "novel_id": novel_id,
            "chapter_index": 1,
            "scene_id": scene["id"],
            "limit": 1,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    assert [item["id"] for item in body["items"]] == [second["id"]]
    assert first["id"] != second["id"]


@pytest.mark.asyncio
async def test_draft_only_autosave_creates_draft_without_publish_task(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    novel_id = await _create_project(async_client)

    resp = await async_client.post(
        "/api/writing/drafts/autosave",
        json={
            "novel_id": novel_id,
            "chapter_index": 3,
            "title": "第三章",
            "content": "尚未发布的正文",
        },
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["chapter_index"] == 3
    result = await db_session.execute(select(AsyncTask))
    assert result.scalars().all() == []


@pytest.mark.asyncio
async def test_publish_archives_latest_conflict_check_snapshot(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    check = await _create_check(async_client, novel_id, scene["id"])
    item_id = check["items"][0]["id"]

    published = await async_client.post(
        "/api/writing/drafts",
        json={
            "novel_id": novel_id,
            "chapter_index": 1,
            "scene_id": scene["id"],
            "title": "第一章",
            "content": "发布正文",
        },
    )
    assert published.status_code == 201, published.text
    snapshot = published.json()["draft"]["conflict_check_snapshot_json"]
    assert snapshot["check_id"] == check["id"]
    assert snapshot["open_high_count"] == 1
    first_snapshot_item = snapshot["items"][0]
    assert first_snapshot_item["location_json"]["source"]
    assert first_snapshot_item["location_json"]["open_target"]
    assert "text_range" not in first_snapshot_item["location_json"]

    status_resp = await async_client.patch(
        f"/api/writing/conflict-check-items/{item_id}?novel_id={novel_id}",
        json={"status": "ignored"},
    )
    assert status_resp.status_code == 200

    draft_id = published.json()["draft"]["id"]
    fetched = await async_client.get(
        f"/api/writing/drafts/{draft_id}",
        params={"novel_id": novel_id},
    )
    assert fetched.status_code == 200
    assert fetched.json()["conflict_check_snapshot_json"] == snapshot


@pytest.mark.asyncio
async def test_candidate_map_evidence_marks_item_for_review(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(
        async_client,
        novel_id,
        must_happen="",
        must_not_happen="",
    )

    async def fake_map_summary(_db, _novel_id, _scene_id, *, include_candidates=False):
        assert include_candidates is True
        return {
            "primary_location": None,
            "risks": [
                {
                    "level": "warning",
                    "message": "粮仓失火",
                    "depends_on_candidate": True,
                    "candidate_review_state": "candidate",
                    "evidence_excerpt": "粮仓火势正在扩大",
                    "open_target": {
                        "kind": "map_object",
                        "map_id": "map-1",
                        "observation_id": "obs-1",
                    },
                }
            ],
            "warnings": [],
        }

    monkeypatch.setattr(
        "modules.world.map_facade.summarize_scene_map_for_writing",
        fake_map_summary,
    )

    body = await _create_check(
        async_client,
        novel_id,
        scene["id"],
        content="粮仓火光照亮城墙。",
        include_candidates=True,
    )

    map_item = next(item for item in body["items"] if item["kind"] == "map_risk")
    assert map_item["needs_review"] is True
    location = map_item["location_json"]
    assert location["needs_review_reason"] == "依赖待确认地图观察"
    assert location["source"]["field"] == "地图风险"
    assert location["source"]["excerpt"] == "粮仓火势正在扩大"
    assert location["open_target"]["observation_id"] == "obs-1"


@pytest.mark.asyncio
async def test_confirmed_map_evidence_is_not_marked_for_review(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(
        async_client,
        novel_id,
        must_happen="",
        must_not_happen="",
    )

    async def fake_map_summary(_db, _novel_id, _scene_id, *, include_candidates=False):
        assert include_candidates is True
        return {
            "primary_location": None,
            "risks": [
                {
                    "level": "warning",
                    "message": "城门封锁",
                    "depends_on_candidate": False,
                    "evidence_excerpt": "城门已经封锁",
                    "open_target": {
                        "kind": "map_object",
                        "map_id": "map-1",
                        "object_id": "gate-1",
                    },
                }
            ],
            "warnings": [],
        }

    monkeypatch.setattr(
        "modules.world.map_facade.summarize_scene_map_for_writing",
        fake_map_summary,
    )

    body = await _create_check(
        async_client,
        novel_id,
        scene["id"],
        content="城门前挤满人群。",
        include_candidates=True,
    )

    map_item = next(item for item in body["items"] if item["kind"] == "map_risk")
    assert map_item["needs_review"] is False
    assert map_item["location_json"]["needs_review_reason"] is None


@pytest.mark.asyncio
async def test_continuity_location_mismatch_uses_memory_evidence_contract(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = await _create_project(async_client)
    pov_character_id = "pov-character-1"
    scene = await _create_scene(
        async_client,
        novel_id,
        chapter_index=2,
        must_happen="",
        must_not_happen="",
        pov_character_id=pov_character_id,
    )

    async def fake_map_summary(_db, _novel_id, _scene_id, *, include_candidates=False):
        return {
            "primary_location": {
                "entity_id": "loc-current",
                "name": "新城",
            },
            "risks": [],
            "warnings": [],
        }

    async def fake_continuity_evidence(
        _db,
        _novel_id,
        chapter_index,
        *,
        pov_character_id,
        current_location_id,
        current_location_name=None,
    ):
        assert chapter_index == 2
        assert pov_character_id == "pov-character-1"
        assert current_location_id == "loc-current"
        assert current_location_name == "新城"
        return MemoryContinuityEvidenceContract(
            source_module="memory",
            source_type="memory.character_location",
            source_id="pov-character-1",
            source_label="章节记忆：第 1 章",
            source_field="角色位置",
            source_excerpt="上一章 仍在旧城，当前 新城",
            open_target={
                "kind": "memory_chapter",
                "chapter_index": 1,
                "character_id": "pov-character-1",
            },
        )

    monkeypatch.setattr(
        "modules.memory.facade.get_continuity_evidence_for_writing",
        fake_continuity_evidence,
    )
    monkeypatch.setattr(
        "modules.world.map_facade.summarize_scene_map_for_writing",
        fake_map_summary,
    )

    body = await _create_check(
        async_client,
        novel_id,
        scene["id"],
        chapter_index=2,
        content="主角抵达新城。",
    )

    continuity_items = [
        item for item in body["items"] if item["kind"] == "continuity_location_mismatch"
    ]
    assert len(continuity_items) == 1
    item = continuity_items[0]
    assert item["severity"] == "medium"
    assert item["source_module"] == "memory"
    assert item["evidence_summary"] == "上一章 仍在旧城，当前 新城"
    assert item["location_json"]["source"] == {
        "module": "memory",
        "type": "memory.character_location",
        "id": "pov-character-1",
        "label": "章节记忆：第 1 章",
        "field": "角色位置",
        "excerpt": "上一章 仍在旧城，当前 新城",
    }
    assert item["location_json"]["open_target"] == {
        "kind": "memory_chapter",
        "chapter_index": 1,
        "character_id": "pov-character-1",
    }


@pytest.mark.asyncio
async def test_continuity_check_without_memory_history_has_no_mismatch(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(
        async_client,
        novel_id,
        chapter_index=2,
        must_happen="",
        must_not_happen="",
        pov_character_id="pov-character-1",
    )

    async def fake_map_summary(_db, _novel_id, _scene_id, *, include_candidates=False):
        return {
            "primary_location": {
                "entity_id": "loc-current",
                "name": "新城",
            },
            "risks": [],
            "warnings": [],
        }

    monkeypatch.setattr(
        "modules.world.map_facade.summarize_scene_map_for_writing",
        fake_map_summary,
    )

    body = await _create_check(
        async_client,
        novel_id,
        scene["id"],
        chapter_index=2,
        content="主角抵达新城。",
    )

    assert [
        item for item in body["items"] if item["kind"] == "continuity_location_mismatch"
    ] == []


@pytest.mark.asyncio
async def test_publish_without_scene_id_does_not_archive_scene_scoped_check(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    await _create_check(async_client, novel_id, scene["id"])

    published = await async_client.post(
        "/api/writing/drafts",
        json={
            "novel_id": novel_id,
            "chapter_index": 1,
            "title": "第一章",
            "content": "发布正文",
        },
    )

    assert published.status_code == 201, published.text
    assert published.json()["draft"]["conflict_check_snapshot_json"] is None


@pytest.mark.asyncio
async def test_ai_review_valid_output_adds_ai_judgment_items(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    check = await _create_check(async_client, novel_id, scene["id"])
    confirmation_id = await _create_context_confirmation(
        async_client,
        novel_id,
        action="writing.conflict_check.ai_review",
        scene_id=scene["id"],
    )

    async def fake_generate_structured(_self, _request, schema, **_kwargs):
        return schema.model_validate(
            {
                "issues": [
                    {
                        "kind": "motivation_gap",
                        "severity": "medium",
                        "summary": "主角突然信任港务长",
                        "evidence": "主角点头同意。",
                        "rationale": "此前没有建立信任动机。",
                        "location_hint": {
                            "chapter_index": 1,
                            "scene_id": scene["id"],
                            "text_quote": "点头同意",
                        },
                        "confidence": 0.72,
                        "depends_on_pending_objects": False,
                    }
                ]
            }
        )

    monkeypatch.setattr(
        "infrastructure.llm.client.LLMClient.generate_structured",
        fake_generate_structured,
    )

    resp = await async_client.post(
        f"/api/writing/conflict-checks/{check['id']}/ai-review",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": confirmation_id,
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ai_review_status"] == "done"
    ai_items = [item for item in body["items"] if item["is_ai_judgment"]]
    assert len(ai_items) == 1
    assert ai_items[0]["kind"] == "motivation_gap"
    assert ai_items[0]["source_module"] == "ai"
    assert ai_items[0]["source_confirmation_id"] == confirmation_id
    assert ai_items[0]["confidence"] == 0.72
    assert "信任动机" in ai_items[0]["llm_rationale"]


@pytest.mark.asyncio
async def test_ai_review_rejects_wrong_confirmation_action(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    check = await _create_check(async_client, novel_id, scene["id"])
    confirmation_id = await _create_context_confirmation(
        async_client,
        novel_id,
        action="writing.generate",
        scene_id=scene["id"],
    )

    resp = await async_client.post(
        f"/api/writing/conflict-checks/{check['id']}/ai-review",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": confirmation_id,
        },
    )

    assert resp.status_code == 400
    assert "action" in resp.text


@pytest.mark.asyncio
async def test_ai_review_rejects_confirmation_for_wrong_chapter(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    check = await _create_check(async_client, novel_id, scene["id"])
    confirmation_id = await _create_context_confirmation(
        async_client,
        novel_id,
        action="writing.conflict_check.ai_review",
        chapter_index=2,
        scene_id=scene["id"],
    )

    resp = await async_client.post(
        f"/api/writing/conflict-checks/{check['id']}/ai-review",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": confirmation_id,
        },
    )

    assert resp.status_code == 400
    assert "chapter_index" in resp.text


@pytest.mark.asyncio
async def test_ai_review_partial_invalid_output_records_discard_count(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    check = await _create_check(async_client, novel_id, scene["id"])
    confirmation_id = await _create_context_confirmation(
        async_client,
        novel_id,
        action="writing.conflict_check.ai_review",
        scene_id=scene["id"],
        include_pending_objects=True,
    )

    async def fake_generate_structured(_self, _request, schema, **_kwargs):
        return schema.model_validate(
            {
                "issues": [
                    {
                        "kind": "emotion_jump",
                        "severity": "low",
                        "summary": "情绪转折过快",
                        "evidence": "上一句愤怒，下一句平静。",
                        "rationale": "缺少情绪缓冲。",
                        "confidence": 0.61,
                        "depends_on_pending_objects": True,
                    },
                    {
                        "kind": "unknown_kind",
                        "severity": "medium",
                        "summary": "应被丢弃",
                        "evidence": "bad",
                        "rationale": "bad",
                        "confidence": 0.5,
                    },
                    "not an issue object",
                ]
            }
        )

    monkeypatch.setattr(
        "infrastructure.llm.client.LLMClient.generate_structured",
        fake_generate_structured,
    )

    resp = await async_client.post(
        f"/api/writing/conflict-checks/{check['id']}/ai-review",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": confirmation_id,
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ai_review_status"] == "partial"
    assert body["summary_json"]["ai_review"]["discarded_count"] == 2
    ai_items = [item for item in body["items"] if item["is_ai_judgment"]]
    assert len(ai_items) == 1
    assert ai_items[0]["needs_review"] is True


@pytest.mark.asyncio
async def test_ai_review_failure_keeps_rule_items_and_marks_check_failed(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    check = await _create_check(async_client, novel_id, scene["id"])
    confirmation_id = await _create_context_confirmation(
        async_client,
        novel_id,
        action="writing.conflict_check.ai_review",
        scene_id=scene["id"],
    )

    async def fake_generate_structured(_self, _request, _schema, **_kwargs):
        raise LLMTimeoutError("timeout", provider="fake")

    monkeypatch.setattr(
        "infrastructure.llm.client.LLMClient.generate_structured",
        fake_generate_structured,
    )

    resp = await async_client.post(
        f"/api/writing/conflict-checks/{check['id']}/ai-review",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": confirmation_id,
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ai_review_status"] == "failed"
    assert "timeout" in body["ai_review_error"]
    assert [item for item in body["items"] if not item["is_ai_judgment"]]


@pytest.mark.asyncio
async def test_ai_suggestion_stores_manual_suggestion_without_mutating_draft(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    check = await _create_check(async_client, novel_id, scene["id"])
    item_id = check["items"][0]["id"]
    draft = await async_client.post(
        "/api/writing/drafts/autosave",
        json={
            "novel_id": novel_id,
            "chapter_index": 1,
            "title": "第一章",
            "content": "原始正文",
        },
    )
    assert draft.status_code == 201, draft.text
    draft_id = draft.json()["id"]
    confirmation_id = await _create_context_confirmation(
        async_client,
        novel_id,
        action="writing.conflict_check.ai_suggestion",
        scene_id=scene["id"],
    )

    async def fake_generate_structured(_self, _request, schema, **_kwargs):
        return schema.model_validate(
            {
                "suggestion": {
                    "strategy": "补一段动机过渡",
                    "suggested_text": "他想起旧约，才勉强点头。",
                    "rationale": "补足信任动作的心理来源。",
                    "constraints": ["不能提前揭示证人全部真相"],
                    "risk_notes": ["保持港务长仍不可信"],
                }
            }
        )

    monkeypatch.setattr(
        "infrastructure.llm.client.LLMClient.generate_structured",
        fake_generate_structured,
    )

    resp = await async_client.post(
        f"/api/writing/conflict-check-items/{item_id}/ai-suggestion",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": confirmation_id,
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["suggestion_status"] == "done"
    assert body["suggestion_confirmation_id"] == confirmation_id
    assert "补一段动机过渡" in body["ai_suggestion"]
    fetched = await async_client.get(
        f"/api/writing/drafts/{draft_id}",
        params={"novel_id": novel_id},
    )
    assert fetched.status_code == 200
    assert fetched.json()["content"] == "原始正文"


@pytest.mark.asyncio
async def test_ai_suggestion_rejects_confirmation_for_wrong_chapter(
    async_client: AsyncClient,
) -> None:
    novel_id = await _create_project(async_client)
    scene = await _create_scene(async_client, novel_id)
    check = await _create_check(async_client, novel_id, scene["id"])
    item_id = check["items"][0]["id"]
    confirmation_id = await _create_context_confirmation(
        async_client,
        novel_id,
        action="writing.conflict_check.ai_suggestion",
        chapter_index=2,
        scene_id=scene["id"],
    )

    resp = await async_client.post(
        f"/api/writing/conflict-check-items/{item_id}/ai-suggestion",
        json={
            "novel_id": novel_id,
            "context_confirmation_id": confirmation_id,
        },
    )

    assert resp.status_code == 400
    assert "chapter_index" in resp.text
