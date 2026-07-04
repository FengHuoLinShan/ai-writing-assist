from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.scene_workbench import SceneWorkbenchService
from modules.outline.schemas import SceneMergeRequest

pytestmark = [pytest.mark.asyncio, pytest.mark.api]


async def _create_scene(
    client: AsyncClient,
    novel_id: str,
    payload: dict,
) -> dict:
    resp = await client.post(
        "/api/outline/scenes",
        params={"novel_id": novel_id},
        json=payload,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _create_draft(
    client: AsyncClient,
    novel_id: str,
    chapter_index: int,
    title: str | None = None,
) -> dict:
    resp = await client.post(
        "/api/writing/drafts/autosave",
        json={
            "novel_id": novel_id,
            "chapter_index": chapter_index,
            "title": title or f"第{chapter_index}章",
            "content": f"第{chapter_index}章正文",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestSceneWorkbenchApi:
    async def test_merge_loader_batches_scene_lookup(self) -> None:
        novel_id = uuid.uuid4()
        target_id = uuid.uuid4()
        first_source_id = uuid.uuid4()
        second_source_id = uuid.uuid4()
        scenes = {
            target_id: SimpleNamespace(id=target_id, novel_id=novel_id),
            first_source_id: SimpleNamespace(id=first_source_id, novel_id=novel_id),
            second_source_id: SimpleNamespace(id=second_source_id, novel_id=novel_id),
        }

        class Repo:
            def __init__(self) -> None:
                self.batch_calls: list[list[uuid.UUID]] = []

            async def get_many_for_novel(
                self,
                _db,
                requested_novel_id,
                scene_ids,
            ):  # type: ignore[no-untyped-def]
                assert requested_novel_id == novel_id
                self.batch_calls.append(list(scene_ids))
                return [
                    scenes[second_source_id],
                    scenes[target_id],
                    scenes[first_source_id],
                ]

        repo = Repo()
        service = SceneWorkbenchService()
        service.repo = repo  # type: ignore[assignment]

        target, sources = await service._load_merge_scenes(
            None,  # type: ignore[arg-type]
            str(novel_id),
            SceneMergeRequest(
                target_scene_id=str(target_id),
                source_scene_ids=[str(first_source_id), str(second_source_id)],
            ),
        )

        assert target.id == target_id
        assert [scene.id for scene in sources] == [first_source_id, second_source_id]
        assert repo.batch_calls == [[target_id, first_source_id, second_source_id]]

    async def test_fusion_loader_batches_scene_lookup(self) -> None:
        novel_id = uuid.uuid4()
        first_id = uuid.uuid4()
        second_id = uuid.uuid4()
        scenes = {
            first_id: SimpleNamespace(id=first_id, novel_id=novel_id),
            second_id: SimpleNamespace(id=second_id, novel_id=novel_id),
        }

        class Repo:
            def __init__(self) -> None:
                self.batch_calls: list[list[uuid.UUID]] = []

            async def get_many_for_novel(
                self,
                _db,
                requested_novel_id,
                scene_ids,
            ):  # type: ignore[no-untyped-def]
                assert requested_novel_id == novel_id
                self.batch_calls.append(list(scene_ids))
                return [scenes[second_id], scenes[first_id]]

        repo = Repo()
        service = SceneWorkbenchService()
        service.repo = repo  # type: ignore[assignment]

        loaded = await service._load_fusion_scenes(
            None,  # type: ignore[arg-type]
            str(novel_id),
            [str(first_id), str(second_id)],
        )

        assert [scene.id for scene in loaded] == [first_id, second_id]
        assert repo.batch_calls == [[first_id, second_id]]

    async def test_legacy_scene_create_route_delegates_to_workbench(
        self,
        async_client: AsyncClient,
        test_project_id: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from modules.outline import api as outline_api

        called = {}

        async def fake_create_scene(db, novel_id, data):
            called["novel_id"] = novel_id
            return {
                "id": str(uuid.uuid4()),
                "novel_id": novel_id,
                "scene_index": data.scene_index,
                "title": data.title,
                "goal": None,
                "core_conflict": None,
                "emotional_beat": None,
                "must_happen": None,
                "must_not_happen": None,
                "narrative_tag": "draft",
                "source": "manual",
                "scene_chunks": [],
                "chapter_ids": [],
                "pov_character_id": None,
                "structure_meta": {},
                "status": "draft",
                "created_at": None,
                "updated_at": None,
            }

        monkeypatch.setattr(
            outline_api._scene_workbench_service,
            "create_scene",
            fake_create_scene,
        )

        resp = await async_client.post(
            "/api/outline/scenes",
            params={"novel_id": test_project_id},
            json={"scene_index": 9, "title": "Workbench adapter"},
        )

        assert resp.status_code == 201, resp.text
        assert called["novel_id"] == test_project_id
        assert resp.json()["title"] == "Workbench adapter"

    async def test_legacy_scene_delete_deprecates_scene(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        scene = await _create_scene(
            async_client,
            test_project_id,
            {"scene_index": 0, "title": "待废弃 Scene", "status": "canonical"},
        )

        resp = await async_client.delete(
            f"/api/outline/scenes/{scene['id']}",
            params={"novel_id": test_project_id},
        )

        assert resp.status_code == 204, resp.text
        get_resp = await async_client.get(
            f"/api/outline/scenes/{scene['id']}",
            params={"novel_id": test_project_id},
        )
        assert get_resp.status_code == 200, get_resp.text
        assert get_resp.json()["status"] == "deprecated"

    async def test_workbench_derives_fixed_health_and_unassigned_chapters(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        await _create_draft(async_client, test_project_id, 7)
        scene = await _create_scene(
            async_client,
            test_project_id,
            {
                "scene_index": 0,
                "title": "导入后待整理",
                "source": "deep_import",
                "status": "draft",
                "chapter_ids": [],
                "structure_meta": {"needs_organize": True},
            },
        )

        resp = await async_client.get(
            "/api/outline/scene-workbench",
            params={"novel_id": test_project_id},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert set(data["health"]) == {
            "unreviewed",
            "unassigned",
            "missing_setup",
            "needs_organize",
        }
        assert data["health"]["unreviewed"]["count"] == 1
        assert data["health"]["unassigned"]["count"] == 2
        assert data["health"]["missing_setup"]["count"] == 1
        assert data["health"]["needs_organize"]["count"] == 1
        assert data["unassigned_chapters"] == [7]
        item = next(item for item in data["items"] if item["scene"]["id"] == scene["id"])
        assert item["health"] == [
            "unreviewed",
            "unassigned",
            "missing_setup",
            "needs_organize",
        ]

    async def test_workbench_health_uses_all_matching_scenes_not_only_current_page(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        for chapter in range(1, 26):
            await _create_draft(async_client, test_project_id, chapter)
            await _create_scene(
                async_client,
                test_project_id,
                {
                    "scene_index": chapter,
                    "title": f"第{chapter}章 Scene",
                    "goal": "推进剧情",
                    "core_conflict": "冲突",
                    "must_happen": "必须发生",
                    "must_not_happen": "禁止发生",
                    "source": "deep_import",
                    "status": "draft",
                    "chapter_ids": [str(chapter)],
                },
            )

        resp = await async_client.get(
            "/api/outline/scene-workbench",
            params={"novel_id": test_project_id, "skip": 0, "limit": 20},
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data["items"]) == 20
        assert data["total"] == 25
        assert data["unassigned_chapters"] == []
        assert data["health"]["unassigned"]["count"] == 0

    async def test_cross_chapter_detector_extends_until_unrelated_chapter(
        self,
        db_session: AsyncSession,
        test_project_id: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from modules.outline.cross_chapter_detection import (
            CrossChapterDecision,
            CrossChapterDetectionService,
        )
        from modules.outline.repositories import SceneRepository
        from modules.outline.schemas import SceneCreate

        repo = SceneRepository()
        for chapter in range(1, 5):
            await repo.create(
                db_session,
                uuid.UUID(hex=test_project_id),
                SceneCreate(
                    scene_index=chapter - 1,
                    title=f"第{chapter}章边界",
                    goal="同一场追击" if chapter <= 3 else "新的转场",
                    chapter_ids=[str(chapter)],
                    scene_chunks=[{"chapter_index": chapter, "start_paragraph": 0}],
                    status="draft",
                ),
            )

        async def fake_evidence(self, db, novel_id, chain, next_scene):
            return [{"source_type": "test", "snippet": "证据"}], None

        async def fake_decide(self, *, novel_id, chain, next_scene, evidence):
            chapter = int(next_scene.chapter_ids[0])
            if chapter <= 3:
                return CrossChapterDecision(
                    action="extend_scene",
                    confidence=0.9,
                    reason="仍是同一场追击",
                )
            return CrossChapterDecision(
                action="keep_separate",
                confidence=0.8,
                reason="进入新事件",
            )

        monkeypatch.setattr(
            CrossChapterDetectionService,
            "_evidence_for_boundary",
            fake_evidence,
        )
        monkeypatch.setattr(
            CrossChapterDetectionService,
            "_decide_boundary",
            fake_decide,
        )

        result = await CrossChapterDetectionService().detect(
            db_session,
            novel_id=test_project_id,
        )

        assert result["suggestion_count"] == 1
        suggestion = result["suggestions"][0]
        assert suggestion["chapter_span"] == [1, 3]
        assert len(suggestion["source_scene_ids"]) == 3
        assert suggestion["stop_reason"] == "keep_separate"

    async def test_cross_chapter_detector_batches_draft_fallback_evidence(
        self,
        db_session: AsyncSession,
        test_project_id: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from modules.outline import cross_chapter_detection
        from modules.outline.cross_chapter_detection import CrossChapterDetectionService
        from modules.outline.repositories import SceneRepository
        from modules.outline.schemas import SceneCreate
        from modules.writing.contracts import WritingDraftContract

        repo = SceneRepository()
        current = await repo.create(
            db_session,
            uuid.UUID(hex=test_project_id),
            SceneCreate(
                scene_index=1,
                title="追击上半",
                goal="继续追击",
                chapter_ids=["1"],
                status="draft",
            ),
        )
        next_scene = await repo.create(
            db_session,
            uuid.UUID(hex=test_project_id),
            SceneCreate(
                scene_index=2,
                title="追击下半",
                goal="追击收束",
                chapter_ids=["2"],
                status="draft",
            ),
        )
        batch_calls: list[list[int]] = []

        async def fail_retrieve(*args, **kwargs):
            raise RuntimeError("rag unavailable")

        async def fail_single_fetch(*args, **kwargs):
            raise AssertionError("should not fetch fallback drafts one by one")

        async def fake_batch_fetch(db, novel_id, chapter_indices):
            batch_calls.append(list(chapter_indices))
            return [
                WritingDraftContract(
                    novel_id=novel_id,
                    chapter_index=1,
                    content="第一章追击证据",
                ),
                WritingDraftContract(
                    novel_id=novel_id,
                    chapter_index=2,
                    content="第二章追击证据",
                ),
            ]

        monkeypatch.setattr(
            cross_chapter_detection.rag_facade,
            "retrieve",
            fail_retrieve,
        )
        monkeypatch.setattr(
            cross_chapter_detection,
            "get_latest_draft_for_chapter",
            fail_single_fetch,
            raising=False,
        )
        monkeypatch.setattr(
            cross_chapter_detection,
            "list_latest_drafts_for_chapters",
            fake_batch_fetch,
            raising=False,
        )

        service = CrossChapterDetectionService()
        evidence, degraded_reason = await service._evidence_for_boundary(
            db_session,
            test_project_id,
            [current],
            next_scene,
        )

        assert batch_calls == [[1, 2]]
        assert degraded_reason == "draft_fallback"
        assert [item["chapter_index"] for item in evidence] == [1, 2]
        assert evidence[0]["snippet"] == "第一章追击证据"

    async def test_workbench_includes_candidate_scenes(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        scene = await _create_scene(
            async_client,
            test_project_id,
            {
                "scene_index": 0,
                "title": "候选 Scene",
                "source": "deep_import",
                "status": "candidate",
                "chapter_ids": ["1"],
            },
        )

        resp = await async_client.get(
            "/api/outline/scene-workbench",
            params={"novel_id": test_project_id},
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert [item["scene"]["id"] for item in data["items"]] == [scene["id"]]
        assert data["items"][0]["health"][:1] == ["unreviewed"]

    async def test_workbench_filters_deep_import_scene_metadata(
        self,
        async_client: AsyncClient,
        test_project_id: str,
        sample_novel_id: str,
    ) -> None:
        matching = await _create_scene(
            async_client,
            test_project_id,
            {
                "scene_index": 0,
                "title": "需复核 fallback",
                "source": "deep_import",
                "status": "deprecated",
                "structure_meta": {
                    "workflow_id": "wf-scene-filter",
                    "phase": "phase1a_fallback",
                    "boundary_status": "uncertain",
                    "needs_review": True,
                    "phase1a_fallback": True,
                },
            },
        )
        await _create_scene(
            async_client,
            test_project_id,
            {
                "scene_index": 1,
                "title": "其他 workflow",
                "source": "deep_import",
                "status": "deprecated",
                "structure_meta": {
                    "workflow_id": "wf-other",
                    "phase": "phase1a_fallback",
                    "boundary_status": "uncertain",
                    "needs_review": True,
                    "phase1a_fallback": True,
                },
            },
        )
        await _create_scene(
            async_client,
            sample_novel_id,
            {
                "scene_index": 0,
                "title": "其他小说",
                "source": "deep_import",
                "status": "deprecated",
                "structure_meta": {
                    "workflow_id": "wf-scene-filter",
                    "phase": "phase1a_fallback",
                    "boundary_status": "uncertain",
                    "needs_review": True,
                    "phase1a_fallback": True,
                },
            },
        )

        resp = await async_client.get(
            "/api/outline/scene-workbench",
            params={
                "novel_id": test_project_id,
                "status": "deprecated",
                "source": "deep_import",
                "workflow_id": "wf-scene-filter",
                "needs_review": "true",
                "boundary_status": "uncertain",
                "phase": "phase1a_fallback",
                "phase1a_fallback": "true",
                "skip": 0,
                "limit": 20,
            },
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert [item["scene"]["id"] for item in data["items"]] == [matching["id"]]
        assert data["items"][0]["scene"]["structure_meta"]["workflow_id"] == (
            "wf-scene-filter"
        )

    async def test_workbench_marks_cross_scene_duplicate_chapters_needs_organize(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        first = await _create_scene(
            async_client,
            test_project_id,
            {
                "scene_index": 0,
                "title": "重复一",
                "chapter_ids": ["1"],
                "goal": "目标",
                "core_conflict": "冲突",
                "must_happen": "必须",
                "must_not_happen": "禁止",
            },
        )
        second = await _create_scene(
            async_client,
            test_project_id,
            {
                "scene_index": 1,
                "title": "重复二",
                "chapter_ids": ["1"],
                "goal": "目标",
                "core_conflict": "冲突",
                "must_happen": "必须",
                "must_not_happen": "禁止",
            },
        )

        resp = await async_client.get(
            "/api/outline/scene-workbench",
            params={"novel_id": test_project_id},
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        health_by_scene = {
            item["scene"]["id"]: item["health"] for item in data["items"]
        }
        assert "needs_organize" in health_by_scene[first["id"]]
        assert "needs_organize" in health_by_scene[second["id"]]
        assert data["health"]["needs_organize"]["count"] == 2

    async def test_mapping_update_changes_scene_mapping_without_touching_text(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        await _create_draft(async_client, test_project_id, 1, "第一章")
        await _create_draft(async_client, test_project_id, 2, "第二章")
        scene = await _create_scene(
            async_client,
            test_project_id,
            {
                "scene_index": 0,
                "title": "旅程",
                "goal": "启程",
                "core_conflict": "追兵逼近",
                "must_happen": "离城",
                "must_not_happen": "主角死亡",
                "chapter_ids": ["1"],
            },
        )

        resp = await async_client.patch(
            f"/api/outline/scene-workbench/scenes/{scene['id']}/mapping",
            params={"novel_id": test_project_id},
            json={
                "chapter_ids": ["1", "2"],
                "scene_chunks": [
                    {
                        "chapter_id": "1",
                        "chapter_index": 1,
                        "start_pos": 0,
                        "end_pos": 10,
                    },
                    {
                        "chapter_id": "2",
                        "chapter_index": 2,
                        "start_pos": 0,
                        "end_pos": 10,
                    },
                ],
                "structure_meta": {"needs_organize": False},
            },
        )

        assert resp.status_code == 200, resp.text
        updated = resp.json()
        assert updated["chapter_ids"] == ["1", "2"]
        assert updated["scene_chunks"][1]["chapter_index"] == 2
        assert updated["structure_meta"]["needs_organize"] is False

        draft_resp = await async_client.get(
            "/api/writing/chapters/2/draft",
            params={"novel_id": test_project_id},
        )
        assert draft_resp.status_code == 200
        assert draft_resp.json()["content"] == "第2章正文"

    @pytest.mark.parametrize(
        "payload",
        [
            {"chapter_ids": ["999"]},
            {"chapter_ids": ["chapter-1"]},
            {"scene_chunks": [{"chapter_id": "999", "chapter_index": 999}]},
            {"scene_chunks": [{"chapter_id": "1", "chapter_index": 2}]},
        ],
        ids=[
            "unknown_chapter",
            "non_numeric_chapter",
            "unknown_chunk_chapter",
            "chunk_id_index_mismatch",
        ],
    )
    async def test_mapping_update_rejects_invalid_chapter_mappings(
        self,
        async_client: AsyncClient,
        test_project_id: str,
        payload: dict,
    ) -> None:
        await _create_draft(async_client, test_project_id, 1, "第一章")
        scene = await _create_scene(
            async_client,
            test_project_id,
            {
                "scene_index": 0,
                "title": "旅程",
                "chapter_ids": ["1"],
            },
        )

        resp = await async_client.patch(
            f"/api/outline/scene-workbench/scenes/{scene['id']}/mapping",
            params={"novel_id": test_project_id},
            json=payload,
        )

        assert resp.status_code == 400

    async def test_scene_detail_update_can_clear_nullable_fields(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        scene = await _create_scene(
            async_client,
            test_project_id,
            {
                "scene_index": 0,
                "title": "可清空字段",
                "goal": "旧目标",
                "core_conflict": "旧冲突",
                "must_happen": "旧必须",
                "must_not_happen": "旧禁止",
                "pov_character_id": "char-1",
            },
        )

        resp = await async_client.patch(
            f"/api/outline/scenes/{scene['id']}",
            params={"novel_id": test_project_id},
            json={
                "goal": None,
                "core_conflict": None,
                "pov_character_id": None,
            },
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["goal"] is None
        assert data["core_conflict"] is None
        assert data["pov_character_id"] is None

    async def test_merge_preview_is_side_effect_free_and_merge_requires_confirmation(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        target = await _create_scene(
            async_client,
            test_project_id,
            {
                "scene_index": 0,
                "title": "目标 Scene",
                "chapter_ids": ["1"],
                "goal": None,
                "core_conflict": "目标冲突",
            },
        )
        source = await _create_scene(
            async_client,
            test_project_id,
            {
                "scene_index": 1,
                "title": "来源 Scene",
                "chapter_ids": ["2"],
                "goal": "来源目标",
                "must_happen": "钥匙出现",
            },
        )

        preview_resp = await async_client.post(
            "/api/outline/scene-workbench/merge/preview",
            params={"novel_id": test_project_id},
            json={
                "target_scene_id": target["id"],
                "source_scene_ids": [source["id"]],
            },
        )
        assert preview_resp.status_code == 200, preview_resp.text
        preview = preview_resp.json()
        assert preview["operation"] == "merge"
        assert preview["chapter_mapping_change"]["after"][target["id"]] == ["1", "2"]
        assert preview["field_changes"]["goal"]["after"] == "来源目标"

        source_after_preview = await async_client.get(
            f"/api/outline/scenes/{source['id']}",
            params={"novel_id": test_project_id},
        )
        assert source_after_preview.json()["status"] == "draft"

        denied = await async_client.post(
            "/api/outline/scene-workbench/merge",
            params={"novel_id": test_project_id},
            json={
                "target_scene_id": target["id"],
                "source_scene_ids": [source["id"]],
            },
        )
        assert denied.status_code == 400

        merged_resp = await async_client.post(
            "/api/outline/scene-workbench/merge",
            params={"novel_id": test_project_id},
            json={
                "target_scene_id": target["id"],
                "source_scene_ids": [source["id"]],
                "confirmed": True,
            },
        )
        assert merged_resp.status_code == 200, merged_resp.text
        merged = merged_resp.json()
        assert merged["scene"]["chapter_ids"] == ["1", "2"]
        assert merged["scene"]["goal"] == "来源目标"
        assert merged["scene"]["core_conflict"] == "目标冲突"
        assert merged["scene"]["structure_meta"]["merged_from_scene_ids"] == [
            source["id"]
        ]

        source_after_merge = await async_client.get(
            f"/api/outline/scenes/{source['id']}",
            params={"novel_id": test_project_id},
        )
        assert source_after_merge.json()["status"] == "deprecated"
        assert source_after_merge.json()["chapter_ids"] == []
        assert (
            source_after_merge.json()["structure_meta"]["merged_into_scene_id"]
            == target["id"]
        )

    async def test_split_preview_is_side_effect_free_and_split_requires_confirmation(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        scene = await _create_scene(
            async_client,
            test_project_id,
            {
                "scene_index": 0,
                "title": "长 Scene",
                "goal": "完成潜入",
                "core_conflict": "守卫阻拦",
                "must_happen": "拿到文书",
                "must_not_happen": "身份暴露",
                "narrative_tag": "rising_action",
                "chapter_ids": ["1", "2", "3"],
                "scene_chunks": [
                    {
                        "chapter_id": "1",
                        "chapter_index": 1,
                        "start_pos": 0,
                        "end_pos": 10,
                    },
                    {
                        "chapter_id": "2",
                        "chapter_index": 2,
                        "start_pos": 0,
                        "end_pos": 10,
                    },
                    {
                        "chapter_id": "3",
                        "chapter_index": 3,
                        "start_pos": 0,
                        "end_pos": 10,
                    },
                ],
            },
        )

        preview_resp = await async_client.post(
            "/api/outline/scene-workbench/split/preview",
            params={"novel_id": test_project_id},
            json={"source_scene_id": scene["id"], "split_chapter_index": 2},
        )
        assert preview_resp.status_code == 200, preview_resp.text
        preview = preview_resp.json()
        assert preview["operation"] == "split"
        assert preview["chapter_mapping_change"]["after"][scene["id"]] == ["1"]
        assert preview["new_scene"]["chapter_ids"] == ["2", "3"]
        assert len(preview["draft_scenes"]) == 2
        assert preview["primary_scene_id"] == scene["id"]
        assert preview["field_references"]["title"][0]["role"] == "primary"

        after_preview = await async_client.get(
            f"/api/outline/scenes/{scene['id']}",
            params={"novel_id": test_project_id},
        )
        assert after_preview.json()["chapter_ids"] == ["1", "2", "3"]

        denied = await async_client.post(
            "/api/outline/scene-workbench/split",
            params={"novel_id": test_project_id},
            json={"source_scene_id": scene["id"], "split_chapter_index": 2},
        )
        assert denied.status_code == 400

        split_resp = await async_client.post(
            "/api/outline/scene-workbench/split",
            params={"novel_id": test_project_id},
            json={
                "source_scene_id": scene["id"],
                "split_chapter_index": 2,
                "confirmed": True,
            },
        )
        assert split_resp.status_code == 200, split_resp.text
        result = split_resp.json()
        assert result["scene"]["chapter_ids"] == ["1"]
        assert result["new_scene"]["chapter_ids"] == ["2", "3"]
        assert result["new_scene"]["status"] == "draft"
        assert result["new_scene"]["structure_meta"]["split_from_scene_id"] == scene["id"]
        assert result["new_scene"]["structure_meta"]["split_at_chapter_index"] == 2

    async def test_split_with_split_pos_keeps_source_chunk_front_half(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        scene = await _create_scene(
            async_client,
            test_project_id,
            {
                "scene_index": 0,
                "title": "同章拆分",
                "chapter_ids": ["1", "2"],
                "scene_chunks": [
                    {
                        "chapter_id": "1",
                        "chapter_index": 1,
                        "start_pos": 0,
                        "end_pos": 10,
                    },
                    {
                        "chapter_id": "2",
                        "chapter_index": 2,
                        "start_pos": 0,
                        "end_pos": 100,
                    },
                ],
            },
        )

        split_resp = await async_client.post(
            "/api/outline/scene-workbench/split",
            params={"novel_id": test_project_id},
            json={
                "source_scene_id": scene["id"],
                "split_chapter_index": 2,
                "split_pos": 40,
                "confirmed": True,
            },
        )

        assert split_resp.status_code == 200, split_resp.text
        result = split_resp.json()
        assert result["scene"]["chapter_ids"] == ["1", "2"]
        assert result["scene"]["scene_chunks"][1]["start_pos"] == 0
        assert result["scene"]["scene_chunks"][1]["end_pos"] == 40
        assert result["new_scene"]["chapter_ids"] == ["2"]
        assert result["new_scene"]["scene_chunks"][0]["start_pos"] == 40
        assert result["new_scene"]["scene_chunks"][0]["end_pos"] == 100

    async def test_split_save_applies_draft_semantics_but_keeps_system_mapping(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        scene = await _create_scene(
            async_client,
            test_project_id,
            {
                "scene_index": 0,
                "title": "原始长 Scene",
                "goal": "原目标",
                "chapter_ids": ["1", "2"],
                "scene_chunks": [
                    {"chapter_index": 1, "start_pos": 0, "end_pos": 10},
                    {"chapter_index": 2, "start_pos": 0, "end_pos": 10},
                ],
            },
        )

        resp = await async_client.post(
            "/api/outline/scene-workbench/split",
            params={"novel_id": test_project_id},
            json={
                "source_scene_id": scene["id"],
                "split_chapter_index": 2,
                "confirmed": True,
                "draft_scenes": [
                    {"title": "前半草稿", "goal": "保留前半", "chapter_ids": ["999"]},
                    {"title": "后半草稿", "goal": "推进后半", "chapter_ids": ["888"]},
                ],
            },
        )

        assert resp.status_code == 200, resp.text
        result = resp.json()
        assert result["scene"]["title"] == "前半草稿"
        assert result["scene"]["goal"] == "保留前半"
        assert result["scene"]["chapter_ids"] == ["1"]
        assert result["new_scene"]["title"] == "后半草稿"
        assert result["new_scene"]["goal"] == "推进后半"
        assert result["new_scene"]["chapter_ids"] == ["2"]

    async def test_fusion_preview_is_side_effect_free_and_returns_sources(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        first = await _create_scene(
            async_client,
            test_project_id,
            {
                "scene_index": 0,
                "title": "潜入",
                "goal": "拿到密信",
                "core_conflict": "守卫巡逻",
                "must_happen": "发现暗门",
                "chapter_ids": ["1"],
            },
        )
        second = await _create_scene(
            async_client,
            test_project_id,
            {
                "scene_index": 1,
                "title": "逃离",
                "goal": "带着密信脱身",
                "emotional_beat": "紧张升级",
                "must_not_happen": "身份暴露",
                "chapter_ids": ["2"],
            },
        )

        resp = await async_client.post(
            "/api/outline/scene-workbench/fusion/preview",
            params={"novel_id": test_project_id},
            json={
                "source_scene_ids": [first["id"], second["id"]],
                "primary_scene_id": first["id"],
            },
        )

        assert resp.status_code == 200, resp.text
        preview = resp.json()
        assert preview["mode"] == "fusion"
        assert preview["source_scene_ids"] == [first["id"], second["id"]]
        assert preview["primary_scene_id"] == first["id"]
        assert preview["draft_scene"]["chapter_ids"] == ["1", "2"]
        assert preview["fused_scene"]["status"] == "draft"
        assert preview["fused_scene"]["chapter_ids"] == ["1", "2"]
        assert preview["fused_scene"]["structure_meta"]["fused_from_scene_ids"] == [
            first["id"],
            second["id"],
        ]
        assert preview["field_references"]["goal"][0]["role"] == "primary"
        assert {
            item["scene_id"] for item in preview["field_references"]["goal"]
        } == {first["id"], second["id"]}

        for scene in (first, second):
            after_preview = await async_client.get(
                f"/api/outline/scenes/{scene['id']}",
                params={"novel_id": test_project_id},
            )
            assert after_preview.status_code == 200
            assert after_preview.json()["status"] == "draft"

    async def test_fusion_preview_requires_primary_scene(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        first = await _create_scene(
            async_client,
            test_project_id,
            {"scene_index": 0, "title": "甲", "chapter_ids": ["1"]},
        )
        second = await _create_scene(
            async_client,
            test_project_id,
            {"scene_index": 1, "title": "乙", "chapter_ids": ["2"]},
        )

        resp = await async_client.post(
            "/api/outline/scene-workbench/fusion/preview",
            params={"novel_id": test_project_id},
            json={"source_scene_ids": [first["id"], second["id"]]},
        )

        assert resp.status_code == 400
        assert "primary_scene_id" in resp.text

    async def test_fusion_preview_uses_primary_scene_as_draft_backbone(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        first = await _create_scene(
            async_client,
            test_project_id,
            {
                "scene_index": 0,
                "title": "较弱识别",
                "goal": "模糊目标",
                "narrative_tag": "setup",
                "pov_character_id": "char-low",
                "chapter_ids": ["1"],
            },
        )
        primary = await _create_scene(
            async_client,
            test_project_id,
            {
                "scene_index": 1,
                "title": "高质量识别",
                "goal": "以高质量识别为主线",
                "narrative_tag": "climax",
                "pov_character_id": "char-main",
                "chapter_ids": ["2"],
            },
        )

        resp = await async_client.post(
            "/api/outline/scene-workbench/fusion/preview",
            params={"novel_id": test_project_id},
            json={
                "source_scene_ids": [first["id"], primary["id"]],
                "primary_scene_id": primary["id"],
            },
        )

        assert resp.status_code == 200, resp.text
        preview = resp.json()
        draft = preview["draft_scene"]
        assert draft["goal"].startswith("以高质量识别为主线")
        assert draft["narrative_tag"] == "climax"
        assert draft["pov_character_id"] == "char-main"
        assert draft["structure_meta"]["primary_scene_id"] == primary["id"]

    async def test_fusion_preview_rejects_primary_scene_outside_sources(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        first = await _create_scene(
            async_client,
            test_project_id,
            {"scene_index": 0, "title": "甲", "chapter_ids": ["1"]},
        )
        second = await _create_scene(
            async_client,
            test_project_id,
            {"scene_index": 1, "title": "乙", "chapter_ids": ["2"]},
        )
        third = await _create_scene(
            async_client,
            test_project_id,
            {"scene_index": 2, "title": "丙", "chapter_ids": ["3"]},
        )

        resp = await async_client.post(
            "/api/outline/scene-workbench/fusion/preview",
            params={"novel_id": test_project_id},
            json={
                "source_scene_ids": [first["id"], second["id"]],
                "primary_scene_id": third["id"],
            },
        )

        assert resp.status_code == 400
        assert "primary_scene_id" in resp.text

    async def test_fusion_keep_originals_creates_draft_without_changing_sources(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        first = await _create_scene(
            async_client,
            test_project_id,
            {"scene_index": 0, "title": "甲", "goal": "目标甲", "chapter_ids": ["1"]},
        )
        second = await _create_scene(
            async_client,
            test_project_id,
            {"scene_index": 1, "title": "乙", "goal": "目标乙", "chapter_ids": ["2"]},
        )

        resp = await async_client.post(
            "/api/outline/scene-workbench/fusion/save",
            params={"novel_id": test_project_id},
            json={
                "source_scene_ids": [first["id"], second["id"]],
                "mode": "keep_originals",
            },
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "saved"
        assert data["fused_scene"]["status"] == "draft"
        assert data["fused_scene"]["source"] == "manual_fusion"
        assert data["fused_scene"]["structure_meta"]["fused_from_scene_ids"] == [
            first["id"],
            second["id"],
        ]
        assert data["fused_scene"]["chapter_ids"] == ["1", "2"]

        for scene in (first, second):
            source_resp = await async_client.get(
                f"/api/outline/scenes/{scene['id']}",
                params={"novel_id": test_project_id},
            )
            assert source_resp.json()["status"] == "draft"

    async def test_fusion_deprecate_originals_creates_draft_and_marks_sources(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        first = await _create_scene(
            async_client,
            test_project_id,
            {"scene_index": 0, "title": "甲", "chapter_ids": ["1"]},
        )
        second = await _create_scene(
            async_client,
            test_project_id,
            {"scene_index": 1, "title": "乙", "chapter_ids": ["2"]},
        )

        resp = await async_client.post(
            "/api/outline/scene-workbench/fusion/save",
            params={"novel_id": test_project_id},
            json={
                "source_scene_ids": [first["id"], second["id"]],
                "mode": "deprecate_originals",
            },
        )

        assert resp.status_code == 200, resp.text
        fused_scene = resp.json()["fused_scene"]
        assert fused_scene["status"] == "draft"
        assert fused_scene["source"] == "manual_fusion"

        for source in (first, second):
            source_resp = await async_client.get(
                f"/api/outline/scenes/{source['id']}",
                params={"novel_id": test_project_id},
            )
            source_data = source_resp.json()
            assert source_data["status"] == "deprecated"
            assert source_data["structure_meta"]["fused_into_scene_id"] == (
                fused_scene["id"]
            )

    async def test_fusion_discard_does_not_create_or_change_sources(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        first = await _create_scene(
            async_client,
            test_project_id,
            {"scene_index": 0, "title": "甲", "chapter_ids": ["1"]},
        )
        second = await _create_scene(
            async_client,
            test_project_id,
            {"scene_index": 1, "title": "乙", "chapter_ids": ["2"]},
        )

        resp = await async_client.post(
            "/api/outline/scene-workbench/fusion/save",
            params={"novel_id": test_project_id},
            json={
                "source_scene_ids": [first["id"], second["id"]],
                "mode": "discard",
            },
        )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "discarded"
        assert data["fused_scene"] is None

        list_resp = await async_client.get(
            "/api/outline/scenes",
            params={"novel_id": test_project_id},
        )
        assert list_resp.json()["total"] == 2
        for scene in (first, second):
            source_resp = await async_client.get(
                f"/api/outline/scenes/{scene['id']}",
                params={"novel_id": test_project_id},
            )
            assert source_resp.json()["status"] == "draft"

    async def test_fusion_edit_then_save_uses_user_edited_fields(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        first = await _create_scene(
            async_client,
            test_project_id,
            {"scene_index": 0, "title": "甲", "goal": "旧目标", "chapter_ids": ["1"]},
        )
        second = await _create_scene(
            async_client,
            test_project_id,
            {"scene_index": 1, "title": "乙", "chapter_ids": ["2"]},
        )

        resp = await async_client.post(
            "/api/outline/scene-workbench/fusion/save",
            params={"novel_id": test_project_id},
            json={
                "source_scene_ids": [first["id"], second["id"]],
                "mode": "edit_then_save",
                "fused_scene": {
                    "title": "用户编辑后的融合",
                    "goal": "用户确认目标",
                    "chapter_ids": ["2"],
                    "structure_meta": {"reviewed_at": "manual"},
                },
            },
        )

        assert resp.status_code == 200, resp.text
        fused_scene = resp.json()["fused_scene"]
        assert fused_scene["title"] == "用户编辑后的融合"
        assert fused_scene["goal"] == "用户确认目标"
        assert fused_scene["chapter_ids"] == ["2"]
        assert fused_scene["status"] == "draft"
        assert fused_scene["structure_meta"]["reviewed_at"] == "manual"
        assert fused_scene["structure_meta"]["fused_from_scene_ids"] == [
            first["id"],
            second["id"],
        ]

        for scene in (first, second):
            source_resp = await async_client.get(
                f"/api/outline/scenes/{scene['id']}",
                params={"novel_id": test_project_id},
            )
            assert source_resp.json()["status"] == "draft"

    async def test_fusion_rejects_source_scene_from_another_novel(
        self,
        async_client: AsyncClient,
        test_project_id: str,
        sample_novel_id: str,
    ) -> None:
        local_scene = await _create_scene(
            async_client,
            test_project_id,
            {"scene_index": 0, "title": "本小说", "chapter_ids": ["1"]},
        )
        other_scene = await _create_scene(
            async_client,
            sample_novel_id,
            {"scene_index": 0, "title": "其他小说", "chapter_ids": ["1"]},
        )

        resp = await async_client.post(
            "/api/outline/scene-workbench/fusion/preview",
            params={"novel_id": test_project_id},
            json={
                "source_scene_ids": [local_scene["id"], other_scene["id"]],
                "primary_scene_id": local_scene["id"],
            },
        )

        assert resp.status_code == 404

    async def test_fusion_requires_at_least_two_scenes(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        scene = await _create_scene(
            async_client,
            test_project_id,
            {"scene_index": 0, "title": "孤立 Scene", "chapter_ids": ["1"]},
        )

        resp = await async_client.post(
            "/api/outline/scene-workbench/fusion/preview",
            params={"novel_id": test_project_id},
            json={"source_scene_ids": [scene["id"]]},
        )

        assert resp.status_code == 422

    async def test_fusion_rejects_edited_chapter_outside_novel(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ) -> None:
        await _create_draft(async_client, test_project_id, 1)
        await _create_draft(async_client, test_project_id, 2)
        first = await _create_scene(
            async_client,
            test_project_id,
            {"scene_index": 0, "title": "甲", "chapter_ids": ["1"]},
        )
        second = await _create_scene(
            async_client,
            test_project_id,
            {"scene_index": 1, "title": "乙", "chapter_ids": ["2"]},
        )

        resp = await async_client.post(
            "/api/outline/scene-workbench/fusion/save",
            params={"novel_id": test_project_id},
            json={
                "source_scene_ids": [first["id"], second["id"]],
                "mode": "edit_then_save",
                "fused_scene": {"chapter_ids": ["999"]},
            },
        )

        assert resp.status_code == 400
        assert "Chapter 999 is not in this novel" in resp.text

    async def test_scene_workbench_write_operations_keep_novel_id_isolation(
        self,
        async_client: AsyncClient,
        test_project_id: str,
        sample_novel_id: str,
    ) -> None:
        other_scene = await _create_scene(
            async_client,
            sample_novel_id,
            {
                "scene_index": 0,
                "title": "其他小说 Scene",
                "chapter_ids": ["1"],
            },
        )

        resp = await async_client.patch(
            f"/api/outline/scene-workbench/scenes/{other_scene['id']}/mapping",
            params={"novel_id": test_project_id},
            json={"chapter_ids": ["2"]},
        )

        assert resp.status_code == 404
