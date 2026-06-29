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
