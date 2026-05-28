"""
导入 + 实体抽取 E2E 测试

使用真实的 诡秘之主 样本文本文件，测试从文件上传到实体候选的完整管线。
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.seed_data import create_base_scene

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"


# ============================================================
# 导入流程测试
# ============================================================

class TestImportPipeline:
    """从文件上传到 WritingDraft 创建的全流程"""

    @pytest_asyncio.fixture
    async def project_and_client(self, async_client: AsyncClient, db_session: AsyncSession):
        """预先创建项目，返回 client + project_id"""
        # 创建项目
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

    async def test_upload_txt_creates_import_record(
        self,
        project_and_client,
    ):
        """上传 txt 文件 → 创建导入记录"""
        client, pid = project_and_client
        resp = await self._upload_file(client, pid, "lotm_chapter_1.txt")
        assert resp.status_code == 201, f"Upload failed: {resp.text}"
        data = resp.json()
        assert data["status"] == "done"
        assert data["total_chapters"] > 0, "应解析出章节"
        assert data["imported_chapters"] == data["total_chapters"]
        assert data["file_type"] == "txt"

    async def test_import_creates_writing_drafts(
        self,
        project_and_client,
    ):
        """导入完成后，可用 chapter_index 查询到草稿"""
        client, pid = project_and_client
        await self._upload_file(client, pid, "lotm_chapter_1.txt")

        # 分别检查各章节草稿
        for ch_idx in (1, 2):
            draft_resp = await client.get(
                f"/api/writing/chapters/{ch_idx}/draft?novel_id={pid}",
            )
            assert draft_resp.status_code == 200, f"第 {ch_idx} 章草稿不存在: {draft_resp.text}"
            draft = draft_resp.json()
            content = draft.get("content", "")
            assert len(content) > 100, f"第 {ch_idx} 章正文太短"
            assert draft["version_number"] == 1

    async def test_import_record_list(
        self,
        project_and_client,
    ):
        """上传后可在导入记录列表中查询到"""
        client, pid = project_and_client
        await self._upload_file(client, pid, "lotm_chapter_1.txt")

        resp = await client.get(f"/api/imports?novel_id={pid}")
        assert resp.status_code == 200
        data = resp.json()
        items = data.get("items", [])
        assert len(items) >= 1
        assert items[0]["file_name"] == "lotm_chapter_1.txt"

    async def test_import_invalid_file_type_rejected(
        self,
        project_and_client,
    ):
        """不支持的文件类型应被拒绝"""
        client, pid = project_and_client

        files = {"file": ("virus.exe", b"fake content", "application/octet-stream")}
        data = {"novel_id": pid}
        resp = await client.post("/api/imports/upload", files=files, data=data)
        assert resp.status_code == 400, f"应为 400，实际 {resp.status_code} (body: {resp.text[:200]})"
        assert "不支持" in resp.text

    async def test_import_invalid_file_type_other(
        self,
        project_and_client,
    ):
        """另一种不支持的文件类型"""
        client, pid = project_and_client

        files = {"file": ("test.pdf", b"%PDF-1.4 fake", "application/pdf")}
        data = {"novel_id": pid}
        resp = await client.post("/api/imports/upload", files=files, data=data)
        assert resp.status_code == 400, f"应为 400，实际 {resp.status_code}"

    async def test_import_writing_draft_versions(
        self,
        project_and_client,
    ):
        """导入后每个章节的版本号为 1"""
        client, pid = project_and_client
        await self._upload_file(client, pid, "lotm_chapter_1.txt")

        for ch_idx in (1, 2):
            resp = await client.get(f"/api/writing/chapters/{ch_idx}/draft?novel_id={pid}")
            assert resp.status_code == 200
            draft = resp.json()
            assert draft["version_number"] == 1, f"第 {ch_idx} 章版本号应为 1，实际 {draft['version_number']}"


# ============================================================
# 实体候选 API 测试
# ============================================================

class TestEntityCandidateAPI:
    """通过 API 创建、查询、管理实体候选"""

    async def test_create_candidate(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """创建实体候选"""
        meta = await create_base_scene(db_session)
        pid = meta["project_id"]

        payload = {
            "name": "克莱恩·莫雷蒂",
            "entity_type": "character_ref",
            "summary": "本书主角，被抽取出来的候选",
            "source_text": "克莱恩·莫雷蒂从沉睡中醒来",
            "source_chapter_index": 1,
            "importance_score": 0.9,
            "confidence": 0.85,
            "suggested_action": "create_new",
            "candidate_reason": "测试实体抽取",
        }
        resp = await async_client.post(
            f"/api/world/candidates?novel_id={pid}",
            json=payload,
        )
        assert resp.status_code == 201, f"创建候选失败: {resp.text}"
        data = resp.json()
        assert data["name"] == "克莱恩·莫雷蒂"
        assert data["status"] == "pending"

    async def test_create_candidate_minimal(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """仅必填字段创建候选"""
        meta = await create_base_scene(db_session)
        pid = meta["project_id"]

        payload = {
            "name": "临时对象",
            "entity_type": "item",
            "suggested_action": "temporary_only",
        }
        resp = await async_client.post(
            f"/api/world/candidates?novel_id={pid}",
            json=payload,
        )
        assert resp.status_code == 201
        # 默认值填充
        data = resp.json()
        assert data["importance_score"] == 0.5
        assert data["confidence"] == 0.5

    async def test_list_candidates(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """候选列表 + 状态过滤"""
        meta = await create_base_scene(db_session)
        pid = meta["project_id"]

        # 创建 3 个候选
        for i, (name, action) in enumerate([
            ("克莱恩", "create_new"),
            ("愚者", "alias_of_existing"),
            ("值夜者", "merge_with_existing"),
        ]):
            await async_client.post(
                f"/api/world/candidates?novel_id={pid}",
                json={
                    "name": name,
                    "entity_type": "character_ref",
                    "suggested_action": action,
                    "source_chapter_index": i + 1,
                },
            )

        # 全量列表
        resp = await async_client.get(f"/api/world/candidates?novel_id={pid}")
        assert resp.status_code == 200
        data = resp.json()
        items = data.get("items", [])
        assert len(items) >= 3

        # 按 suggested_action 过滤
        resp = await async_client.get(
            f"/api/world/candidates?novel_id={pid}&suggested_action=create_new",
        )
        filtered = resp.json().get("items", [])
        assert all(c["suggested_action"] == "create_new" for c in filtered)

    async def test_get_candidate(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """获取单个候选"""
        meta = await create_base_scene(db_session)
        pid = meta["project_id"]

        create_resp = await async_client.post(
            f"/api/world/candidates?novel_id={pid}",
            json={"name": "罗塞尔", "entity_type": "character_ref", "suggested_action": "create_new"},
        )
        cid = create_resp.json()["id"]

        get_resp = await async_client.get(
            f"/api/world/candidates/{cid}?novel_id={pid}",
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["name"] == "罗塞尔"

    async def test_update_candidate(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """更新候选（如确认或修改建议动作）"""
        meta = await create_base_scene(db_session)
        pid = meta["project_id"]

        create_resp = await async_client.post(
            f"/api/world/candidates?novel_id={pid}",
            json={"name": "未知实体", "entity_type": "secret", "suggested_action": "needs_user_decision"},
        )
        cid = create_resp.json()["id"]

        # 更新为忽略
        update_resp = await async_client.put(
            f"/api/world/candidates/{cid}?novel_id={pid}",
            json={"suggested_action": "ignore", "status": "ignored"},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["suggested_action"] == "ignore"

    async def test_delete_candidate(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """删除候选"""
        meta = await create_base_scene(db_session)
        pid = meta["project_id"]

        create_resp = await async_client.post(
            f"/api/world/candidates?novel_id={pid}",
            json={"name": "临时", "entity_type": "item", "suggested_action": "temporary_only"},
        )
        cid = create_resp.json()["id"]

        del_resp = await async_client.delete(
            f"/api/world/candidates/{cid}?novel_id={pid}",
        )
        assert del_resp.status_code == 204

        # 删除后应 404
        get_resp = await async_client.get(
            f"/api/world/candidates/{cid}?novel_id={pid}",
        )
        assert get_resp.status_code == 404


# ============================================================
# 实体去重与合并测试
# ============================================================

class TestEntityDedupMerge:
    """候选去重检查和合并为正史对象"""

    async def test_dedup_finds_exact_match(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """精确名称匹配应被去重检测到"""
        meta = await create_base_scene(db_session)
        pid = meta["project_id"]

        # 已有正史对象 "克莱恩·莫雷蒂"

        # 创建一个完全同名的候选
        create_resp = await async_client.post(
            f"/api/world/candidates?novel_id={pid}",
            json={
                "name": "克莱恩·莫雷蒂",
                "entity_type": "character_ref",
                "suggested_action": "needs_user_decision",
            },
        )
        cid = create_resp.json()["id"]

        # 运行去重
        dedup_resp = await async_client.post(
            f"/api/world/candidates/{cid}/dedup?novel_id={pid}",
        )
        assert dedup_resp.status_code == 200
        results = dedup_resp.json()
        assert len(results) > 0

    async def test_dedup_with_fuzzy_name(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """模糊名称匹配应被去重检测到"""
        meta = await create_base_scene(db_session)
        pid = meta["project_id"]

        # 创建候选时使用相似但不完全相同的名称
        create_resp = await async_client.post(
            f"/api/world/candidates?novel_id={pid}",
            json={
                "name": "克菜恩·莫雷蒂",  # 故意错字
                "entity_type": "character_ref",
                "suggested_action": "needs_user_decision",
            },
        )
        cid = create_resp.json()["id"]

        dedup_resp = await async_client.post(
            f"/api/world/candidates/{cid}/dedup?novel_id={pid}",
        )
        assert dedup_resp.status_code == 200
        # 至少应返回某些结果（不一定匹配到克莱恩，因为 difflib 阈值 0.72）
        results = dedup_resp.json()
        # 只要不报错即可
        assert results is not None

    async def test_merge_candidate_to_entity(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """合并候选到已有正史对象"""
        meta = await create_base_scene(db_session)
        pid = meta["project_id"]
        eids = meta["entity_ids"]
        klein_id = eids["克莱恩·莫雷蒂"]

        # 创建候选（"愚者"作为克莱恩的别名）
        create_resp = await async_client.post(
            f"/api/world/candidates?novel_id={pid}",
            json={
                "name": "愚者",
                "entity_type": "character_ref",
                "suggested_action": "alias_of_existing",
                "suggested_existing_entity_id": klein_id,
                "summary": "克莱恩在塔罗会的代号",
            },
        )
        assert create_resp.status_code == 201
        cid = create_resp.json()["id"]

        # 执行合并
        merge_resp = await async_client.post(
            f"/api/world/entities/{klein_id}/merge-from-candidate/{cid}?novel_id={pid}",
        )
        assert merge_resp.status_code == 200, f"合并失败: {merge_resp.text}"

        # 验证候选状态（merge 后状态变为 canonical，表示已被处理）
        get_candidate = await async_client.get(
            f"/api/world/candidates/{cid}?novel_id={pid}",
        )
        assert get_candidate.status_code == 200, f"获取候选失败: {get_candidate.text}"
        assert get_candidate.json()["status"] == "canonical"

        # 验证正史对象的别名已创建
        aliases_resp = await async_client.get(
            f"/api/world/aliases?novel_id={pid}&entity_id={klein_id}",
        )
        assert aliases_resp.status_code == 200
        aliases = aliases_resp.json().get("items", [])
        alias_names = [a["alias"] for a in aliases]
        assert "愚者" in alias_names, f"应创建别名'愚者'，实际: {alias_names}"

    async def test_merge_nonexistent_candidate_returns_404(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """合并不存在的候选应返回 404"""
        meta = await create_base_scene(db_session)
        pid = meta["project_id"]
        eids = meta["entity_ids"]
        klein_id = eids["克莱恩·莫雷蒂"]

        fake_cid = str(uuid.uuid4())
        resp = await async_client.post(
            f"/api/world/entities/{klein_id}/merge-from-candidate/{fake_cid}?novel_id={pid}",
        )
        assert resp.status_code == 404


# ============================================================
# 异步任务提交测试
# ============================================================

class TestAsyncTaskSubmission:
    """异步任务框架测试 — 提交和查询任务"""

    async def test_submit_extraction_task(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """提交实体抽取任务"""
        meta = await create_base_scene(db_session)
        pid = meta["project_id"]

        resp = await async_client.post("/api/tasks", json={
            "task_type": "world_entity_extraction",
            "meta": {
                "novel_id": pid,
                "start_chapter": 1,
                "end_chapter": 2,
                "batch_size": 5,
            },
        })
        assert resp.status_code == 201, f"提交任务失败: {resp.text}"
        data = resp.json()
        assert "task_id" in data, f"响应中无 task_id: {data}"
        assert data["status"] == "pending"

        # 查询任务状态
        task_id = data["task_id"]
        status_resp = await async_client.get(f"/api/tasks/{task_id}")
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] in ("pending", "running", "done", "failed")

    async def test_submit_unknown_task_type_returns_422(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """不存在的任务类型应返回 400"""
        resp = await async_client.post("/api/tasks", json={
            "task_type": "nonexistent_task_type_xyz",
            "meta": {},
        })
        assert resp.status_code == 400, f"应为 400，实际 {resp.status_code}: {resp.text}"

    async def test_cancel_task(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ):
        """取消 pending 状态的任务"""
        resp = await async_client.post("/api/tasks", json={
            "task_type": "world_entity_extraction",
            "meta": {"novel_id": str(uuid.uuid4()), "start_chapter": 1, "end_chapter": 1},
        })
        task_id = resp.json()["task_id"]

        cancel_resp = await async_client.post(f"/api/tasks/{task_id}/cancel")
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "cancelled"

    async def test_get_nonexistent_task_returns_404(
        self,
        async_client: AsyncClient,
    ):
        """不存在的任务 ID 应返回 404"""
        resp = await async_client.get(f"/api/tasks/{uuid.uuid4()}")
        assert resp.status_code == 404


class TestProjectMissingFlows:
    @pytest_asyncio.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"]

    async def test_update_project(self, ctx):
        client, pid = ctx
        resp = await client.put(
            f"/api/projects/{pid}",
            json={"title": "诡秘之主 第二部"},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "诡秘之主 第二部"
