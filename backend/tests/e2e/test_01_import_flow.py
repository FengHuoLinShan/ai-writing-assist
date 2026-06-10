"""
导入 + 实体抽取 E2E 测试

使用真实的 诡秘之主 样本文本文件，测试从文件上传到实体候选的完整管线。
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.seed_data import create_base_scene

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"


class TestImportPipeline:
    """导入流程 E2E 测试 — 覆盖文件上传、草稿创建、导入记录查询、错误路径"""

    @pytest.fixture
    async def project_and_client(
        self, async_client: AsyncClient, db_session: AsyncSession
    ):
        """预先创建项目，返回 client + project_id"""
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"]

    async def _upload_file(
        self,
        client: AsyncClient,
        project_id: str,
        filename: str,
    ):
        """上传文件并返回响应"""
        filepath = SAMPLES_DIR / filename
        if filepath.exists():
            content = filepath.read_bytes()
        else:
            # 动态生成文件内容用于错误路径测试
            content = b""

        files = {"file": (filename, content, "text/plain")}
        data = {"novel_id": project_id}
        return await client.post("/api/imports/upload", files=files, data=data)

    async def test_import_upload_txt_creates_import_record_with_done_status(
        self,
        project_and_client,
    ):
        """上传 txt 文件应创建状态为 done 的导入记录，且章节全部解析成功"""
        client, pid = project_and_client

        # Act
        resp = await self._upload_file(client, pid, "lotm_chapter_1.txt")

        # Assert
        assert resp.status_code == 201, f"Upload failed: {resp.text}"
        data = resp.json()
        assert data["status"] == "done"
        assert data["total_chapters"] > 0, "应解析出章节"
        assert data["imported_chapters"] == data["total_chapters"]
        assert data["file_type"] == "txt"

    async def test_import_upload_txt_creates_writing_drafts_with_version_one(
        self,
        project_and_client,
    ):
        """导入完成后，可用 chapter_index 查询到版本号为 1 的草稿"""
        client, pid = project_and_client

        # Arrange
        await self._upload_file(client, pid, "lotm_chapter_1.txt")

        # Act & Assert
        for ch_idx in (1, 2):
            draft_resp = await client.get(
                f"/api/writing/chapters/{ch_idx}/draft?novel_id={pid}",
            )
            assert draft_resp.status_code == 200, f"第 {ch_idx} 章草稿不存在: {draft_resp.text}"
            draft = draft_resp.json()
            content = draft.get("content", "")
            assert len(content) > 100, f"第 {ch_idx} 章正文太短"
            assert draft["version_number"] == 1

    async def test_import_upload_txt_appears_in_import_list(
        self,
        project_and_client,
    ):
        """上传后可在导入记录列表中查询到对应记录"""
        client, pid = project_and_client

        # Arrange
        await self._upload_file(client, pid, "lotm_chapter_1.txt")

        # Act
        resp = await client.get(f"/api/imports?novel_id={pid}")

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        items = data.get("items", [])
        assert len(items) >= 1
        assert items[0]["file_name"] == "lotm_chapter_1.txt"

    async def test_import_upload_invalid_exe_returns_400(
        self,
        project_and_client,
    ):
        """不支持的 exe 文件类型应被上传接口拒绝"""
        client, pid = project_and_client

        # Arrange
        files = {"file": ("virus.exe", b"fake content", "application/octet-stream")}
        data = {"novel_id": pid}

        # Act
        resp = await client.post("/api/imports/upload", files=files, data=data)

        # Assert
        assert resp.status_code == 400, f"应为 400，实际 {resp.status_code} (body: {resp.text[:200]})"
        assert "不支持" in resp.text

    async def test_import_upload_invalid_pdf_returns_400(
        self,
        project_and_client,
    ):
        """不支持的 pdf 文件类型应被上传接口拒绝"""
        client, pid = project_and_client

        # Arrange
        files = {"file": ("test.pdf", b"%PDF-1.4 fake", "application/pdf")}
        data = {"novel_id": pid}

        # Act
        resp = await client.post("/api/imports/upload", files=files, data=data)

        # Assert
        assert resp.status_code == 400, f"应为 400，实际 {resp.status_code}"

    async def test_import_upload_txt_drafts_have_version_number_one(
        self,
        project_and_client,
    ):
        """导入后每个章节的草稿版本号应为 1"""
        client, pid = project_and_client

        # Arrange
        await self._upload_file(client, pid, "lotm_chapter_1.txt")

        # Act & Assert
        for ch_idx in (1, 2):
            resp = await client.get(f"/api/writing/chapters/{ch_idx}/draft?novel_id={pid}")
            assert resp.status_code == 200
            draft = resp.json()
            assert draft["version_number"] == 1, f"第 {ch_idx} 章版本号应为 1，实际 {draft['version_number']}"


@pytest.mark.skip(reason="端点已移除: /api/world/candidates")
class TestEntityCandidateAPI:
    """实体候选 API E2E 测试 — 覆盖创建、列表、查询、更新、删除"""

    async def test_candidate_create_with_all_fields_returns_201_with_pending_status(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """使用完整字段创建实体候选应返回 201 且状态为 pending"""
        # Arrange
        meta = await create_base_scene(db_session)
        pid = meta["project_id"]
        payload = {
            "name": "克莱恩·莫雷蒂",
            "entity_type": "character",
            "summary": "本书主角，被抽取出来的候选",
            "source_text": "克莱恩·莫雷蒂从沉睡中醒来",
            "source_chapter_index": 1,
            "importance_score": 0.9,
            "confidence": 0.85,
            "suggested_action": "create_new",
            "candidate_reason": "测试实体抽取",
        }

        # Act
        resp = await async_client.post(
            f"/api/world/candidates?novel_id={pid}",
            json=payload,
        )

        # Assert
        assert resp.status_code == 201, f"创建候选失败: {resp.text}"
        data = resp.json()
        assert data["name"] == "克莱恩·莫雷蒂"
        assert data["status"] == "pending"

    async def test_candidate_create_with_minimal_fields_uses_default_scores(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """仅必填字段创建候选应返回 201 并使用默认分数"""
        # Arrange
        meta = await create_base_scene(db_session)
        pid = meta["project_id"]
        payload = {
            "name": "临时对象",
            "entity_type": "item",
            "suggested_action": "temporary_only",
        }

        # Act
        resp = await async_client.post(
            f"/api/world/candidates?novel_id={pid}",
            json=payload,
        )

        # Assert
        assert resp.status_code == 201
        data = resp.json()
        assert data["importance_score"] == 0.5
        assert data["confidence"] == 0.5

    async def test_candidate_list_returns_all_and_filters_by_action(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """候选列表应返回全部候选，且支持按 suggested_action 过滤"""
        # Arrange
        meta = await create_base_scene(db_session)
        pid = meta["project_id"]
        for i, (name, action) in enumerate([
            ("克莱恩", "create_new"),
            ("愚者", "alias_of_existing"),
            ("值夜者", "merge_with_existing"),
        ]):
            await async_client.post(
                f"/api/world/candidates?novel_id={pid}",
                json={
                    "name": name,
                    "entity_type": "character",
                    "suggested_action": action,
                    "source_chapter_index": i + 1,
                },
            )

        # Act
        resp = await async_client.get(f"/api/world/candidates?novel_id={pid}")

        # Assert
        assert resp.status_code == 200
        data = resp.json()
        items = data.get("items", [])
        assert len(items) >= 3

        # Act — 按 suggested_action 过滤
        resp = await async_client.get(
            f"/api/world/candidates?novel_id={pid}&suggested_action=create_new",
        )
        filtered = resp.json().get("items", [])

        # Assert
        assert all(c["suggested_action"] == "create_new" for c in filtered)

    async def test_candidate_get_by_id_returns_correct_candidate(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """获取单个候选应返回正确的候选详情"""
        # Arrange
        meta = await create_base_scene(db_session)
        pid = meta["project_id"]
        create_resp = await async_client.post(
            f"/api/world/candidates?novel_id={pid}",
            json={"name": "罗塞尔", "entity_type": "character", "suggested_action": "create_new"},
        )
        cid = create_resp.json()["id"]

        # Act
        get_resp = await async_client.get(
            f"/api/world/candidates/{cid}?novel_id={pid}",
        )

        # Assert
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == "罗塞尔"

    async def test_candidate_update_changes_suggested_action_and_status(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """更新候选的 suggested_action 和 status 应持久化"""
        # Arrange
        meta = await create_base_scene(db_session)
        pid = meta["project_id"]
        create_resp = await async_client.post(
            f"/api/world/candidates?novel_id={pid}",
            json={"name": "未知实体", "entity_type": "secret", "suggested_action": "needs_user_decision"},
        )
        cid = create_resp.json()["id"]

        # Act
        update_resp = await async_client.put(
            f"/api/world/candidates/{cid}?novel_id={pid}",
            json={"suggested_action": "ignore", "status": "ignored"},
        )

        # Assert
        assert update_resp.status_code == 200
        assert update_resp.json()["suggested_action"] == "ignore"

    async def test_candidate_delete_removes_candidate_and_returns_404(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """删除候选后再次获取应返回 404"""
        # Arrange
        meta = await create_base_scene(db_session)
        pid = meta["project_id"]
        create_resp = await async_client.post(
            f"/api/world/candidates?novel_id={pid}",
            json={"name": "临时", "entity_type": "item", "suggested_action": "temporary_only"},
        )
        cid = create_resp.json()["id"]

        # Act
        del_resp = await async_client.delete(
            f"/api/world/candidates/{cid}?novel_id={pid}",
        )

        # Assert
        assert del_resp.status_code == 204

        # Act
        get_resp = await async_client.get(
            f"/api/world/candidates/{cid}?novel_id={pid}",
        )

        # Assert
        assert get_resp.status_code == 404


@pytest.mark.skip(reason="端点已移除")
class TestEntityDedupMerge:
    """实体去重与合并 E2E 测试 — 覆盖精确匹配、模糊匹配、合并到正史对象"""

    async def test_candidate_dedup_exact_name_finds_match(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """精确名称匹配的候选应被去重检测到"""
        # Arrange
        meta = await create_base_scene(db_session)
        pid = meta["project_id"]
        create_resp = await async_client.post(
            f"/api/world/candidates?novel_id={pid}",
            json={
                "name": "克莱恩·莫雷蒂",
                "entity_type": "character",
                "suggested_action": "needs_user_decision",
            },
        )
        cid = create_resp.json()["id"]

        # Act
        dedup_resp = await async_client.post(
            f"/api/world/candidates/{cid}/dedup?novel_id={pid}",
        )

        # Assert
        assert dedup_resp.status_code == 200
        results = dedup_resp.json()
        assert len(results) > 0

    async def test_candidate_dedup_fuzzy_name_returns_results(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """模糊名称匹配的候选应被去重检测到并返回结果"""
        # Arrange
        meta = await create_base_scene(db_session)
        pid = meta["project_id"]
        create_resp = await async_client.post(
            f"/api/world/candidates?novel_id={pid}",
            json={
                "name": "克菜恩·莫雷蒂",  # 故意错字
                "entity_type": "character",
                "suggested_action": "needs_user_decision",
            },
        )
        cid = create_resp.json()["id"]

        # Act
        dedup_resp = await async_client.post(
            f"/api/world/candidates/{cid}/dedup?novel_id={pid}",
        )

        # Assert
        assert dedup_resp.status_code == 200
        results = dedup_resp.json()
        assert results is not None

    async def test_candidate_merge_to_existing_entity_creates_alias_and_updates_status(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """合并候选到已有正史对象应创建别名并将候选状态变为 canonical"""
        # Arrange
        meta = await create_base_scene(db_session)
        pid = meta["project_id"]
        eids = meta["entity_ids"]
        klein_id = eids["克莱恩·莫雷蒂"]
        create_resp = await async_client.post(
            f"/api/world/candidates?novel_id={pid}",
            json={
                "name": "愚者",
                "entity_type": "character",
                "suggested_action": "alias_of_existing",
                "suggested_existing_entity_id": klein_id,
                "summary": "克莱恩在塔罗会的代号",
            },
        )
        assert create_resp.status_code == 201
        cid = create_resp.json()["id"]

        # Act — 执行合并
        merge_resp = await async_client.post(
            f"/api/world/entities/{klein_id}/merge-from-candidate/{cid}?novel_id={pid}",
        )

        # Assert
        assert merge_resp.status_code == 200, f"合并失败: {merge_resp.text}"

        # Act — 验证候选状态
        get_candidate = await async_client.get(
            f"/api/world/candidates/{cid}?novel_id={pid}",
        )

        # Assert
        assert get_candidate.status_code == 200, f"获取候选失败: {get_candidate.text}"
        assert get_candidate.json()["status"] == "canonical"

        # Act — 验证正史对象别名
        aliases_resp = await async_client.get(
            f"/api/world/aliases?novel_id={pid}&entity_id={klein_id}",
        )

        # Assert
        assert aliases_resp.status_code == 200
        aliases = aliases_resp.json().get("items", [])
        alias_names = [a["alias"] for a in aliases]
        assert "愚者" in alias_names, f"应创建别名'愚者'，实际: {alias_names}"

    async def test_candidate_merge_nonexistent_returns_404(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """合并不存在的候选应返回 404"""
        # Arrange
        meta = await create_base_scene(db_session)
        pid = meta["project_id"]
        eids = meta["entity_ids"]
        klein_id = eids["克莱恩·莫雷蒂"]
        fake_cid = str(uuid.uuid4())

        # Act
        resp = await async_client.post(
            f"/api/world/entities/{klein_id}/merge-from-candidate/{fake_cid}?novel_id={pid}",
        )

        # Assert
        assert resp.status_code == 404


class TestAsyncTaskSubmission:
    """异步任务提交 E2E 测试 — 覆盖任务创建、查询、取消、错误路径"""

    async def test_task_submit_extraction_returns_task_id_with_pending_status(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """提交实体抽取任务应返回 task_id 且状态为 pending"""
        # Arrange
        meta = await create_base_scene(db_session)
        pid = meta["project_id"]

        # Act
        resp = await async_client.post("/api/tasks", json={
            "task_type": "world_entity_extraction",
            "meta": {
                "novel_id": pid,
                "start_chapter": 1,
                "end_chapter": 2,
                "batch_size": 5,
            },
        })

        # Assert
        assert resp.status_code == 201, f"提交任务失败: {resp.text}"
        data = resp.json()
        assert "task_id" in data, f"响应中无 task_id: {data}"
        assert data["status"] == "pending"

        # Act — 查询任务状态
        task_id = data["task_id"]
        status_resp = await async_client.get(f"/api/tasks/{task_id}")

        # Assert
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] in ("pending", "running", "done", "failed")

    async def test_task_submit_unknown_type_returns_400(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """不存在的任务类型应返回 400"""
        # Arrange
        payload = {
            "task_type": "nonexistent_task_type_xyz",
            "meta": {},
        }

        # Act
        resp = await async_client.post("/api/tasks", json=payload)

        # Assert
        assert resp.status_code == 400, f"应为 400，实际 {resp.status_code}: {resp.text}"

    async def test_task_cancel_pending_returns_cancelled_status(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """取消 pending 状态的任务应返回 cancelled"""
        # Arrange
        resp = await async_client.post("/api/tasks", json={
            "task_type": "world_entity_extraction",
            "meta": {"novel_id": str(uuid.uuid4()), "start_chapter": 1, "end_chapter": 1},
        })
        task_id = resp.json()["task_id"]

        # Act
        cancel_resp = await async_client.post(f"/api/tasks/{task_id}/cancel")

        # Assert
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "cancelled"

    async def test_task_get_nonexistent_returns_404(
        self,
        async_client: AsyncClient,
    ):
        """不存在的任务 ID 应返回 404"""
        # Arrange
        fake_task_id = str(uuid.uuid4())

        # Act
        resp = await async_client.get(f"/api/tasks/{fake_task_id}")

        # Assert
        assert resp.status_code == 404


class TestProjectUpdate:
    """项目更新 E2E 测试"""

    @pytest.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"]

    async def test_project_update_title_persists_new_value(
        self,
        ctx,
    ):
        """更新项目标题应持久化新值"""
        client, pid = ctx

        # Act
        resp = await client.put(
            f"/api/projects/{pid}",
            json={"title": "诡秘之主 第二部"},
        )

        # Assert
        assert resp.status_code == 200
        assert resp.json()["title"] == "诡秘之主 第二部"
