from __future__ import annotations

import pytest
from httpx import AsyncClient

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
            json={"source_scene_ids": [first["id"], second["id"]]},
        )

        assert resp.status_code == 200, resp.text
        preview = resp.json()
        assert preview["source_scene_ids"] == [first["id"], second["id"]]
        assert preview["fused_scene"]["status"] == "draft"
        assert preview["fused_scene"]["chapter_ids"] == ["1", "2"]
        assert preview["fused_scene"]["structure_meta"]["fused_from_scene_ids"] == [
            first["id"],
            second["id"],
        ]

        for scene in (first, second):
            after_preview = await async_client.get(
                f"/api/outline/scenes/{scene['id']}",
                params={"novel_id": test_project_id},
            )
            assert after_preview.status_code == 200
            assert after_preview.json()["status"] == "draft"

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
            json={"source_scene_ids": [local_scene["id"], other_scene["id"]]},
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
