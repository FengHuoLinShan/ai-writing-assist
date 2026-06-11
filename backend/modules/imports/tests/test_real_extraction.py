"""
真实文件提取测试 — 诡秘之主_第一部_小丑.txt 前10章

测试从导入 → LLM 抽取 → 候选创建的完整管线。
使用真实文件、真实数据库、真实 LLM（DeepSeek）。
DraftProvider 直读 writing_drafts（绕过不可用的 pgvector RAG）。
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.parsers import parse_txt
from modules.project.models import Project
from modules.world.services.extraction_service import EntityExtractionService
from modules.writing.facade import get_latest_draft_for_chapter
from modules.writing.models import WritingDraft
from shared.protocols import DraftProvider

REAL_FILE_PATH = Path("/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑.txt")
FIRST_10_CHAPTER_COUNT = 10


# ============================================================
# DraftProvider: 直读 writing_drafts（无需 RAG/pgvector）
# ============================================================


class DirectDraftProvider(DraftProvider):
    """从 writing_drafts 直读章节正文，不依赖 RAG 索引/pgvector。

    真实操作（非 mock）：直接查询 latest_draft_for_chapter。
    RAG 不可用（无 pgvector）时的替代 DraftProvider 实现。
    """

    async def load_chapters(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> list[dict]:
        chapters: list[dict] = []
        for idx in range(start_chapter, end_chapter + 1):
            draft = await get_latest_draft_for_chapter(db, novel_id, idx)
            if draft and draft.content:
                chapters.append(
                    {
                        "chapter_index": idx,
                        "title": draft.title or f"第{idx}章",
                        "content": draft.content,
                    }
                )
        return chapters


# ============================================================
# Cycle 1: 导入前10章 + 验证
# ============================================================


class TestImportFirst10Chapters:
    """Tracer Bullet: 导入前10章并验证"""

    @pytest_asyncio.fixture
    async def ctx(self, db_session: AsyncSession) -> dict:
        """导入前10章并返回 project_id 和章节数据"""
        assert REAL_FILE_PATH.exists(), f"真实文件不存在: {REAL_FILE_PATH}"
        file_bytes = REAL_FILE_PATH.read_bytes()

        # 1. 解析全部章节
        all_chapters = parse_txt(file_bytes)
        assert len(all_chapters) >= FIRST_10_CHAPTER_COUNT

        # 2. 创建项目
        pid = uuid.uuid4()
        project = Project(
            id=pid,
            title="诡秘之主 第一部 提取测试",
            genre="西方奇幻",
            tone="维多利亚风格、黑暗",
            language="zh",
            target_length="novel",
            current_stage="writing",
        )
        db_session.add(project)
        await db_session.flush()
        project_id = str(pid)

        # 3. 只导入前10章（写入 writing_drafts）
        from modules.writing.facade import create_draft

        for idx in range(FIRST_10_CHAPTER_COUNT):
            ch = all_chapters[idx]
            await create_draft(
                db_session,
                novel_id=project_id,
                chapter_index=idx + 1,
                title=ch.get("title") or f"第{idx + 1}章",
                content=ch.get("content", ""),
            )

        await db_session.flush()
        return {
            "project_id": project_id,
            "chapters": all_chapters[:FIRST_10_CHAPTER_COUNT],
        }

    @pytest.mark.asyncio
    async def test_10_chapters_imported(self, ctx: dict, db_session: AsyncSession):
        """前10章正确导入到 writing_drafts"""
        result = await db_session.execute(
            select(WritingDraft)
            .where(WritingDraft.novel_id == uuid.UUID(hex=ctx["project_id"]))
            .order_by(WritingDraft.chapter_index)
        )
        drafts = list(result.scalars().all())
        assert len(drafts) == FIRST_10_CHAPTER_COUNT
        for i, draft in enumerate(drafts):
            assert draft.chapter_index == i + 1
            assert draft.content and len(draft.content) > 500

    @pytest.mark.asyncio
    async def test_first_chapter_starts_with_pain(self, ctx: dict):
        """第一章正文以"痛！"开头"""
        ch = ctx["chapters"][0]
        assert ch["title"] == "第一章 绯红"
        assert "痛" in ch["content"][:100]

    @pytest.mark.asyncio
    async def test_10th_chapter_title(self, ctx: dict):
        """第十章标题为'第十章 常态'"""
        ch = ctx["chapters"][9]
        assert ch["title"] == "第十章 常态"


# ============================================================
# Cycle 2: LLM 实体抽取（真实 DeepSeek API）
# ============================================================


class TestRealEntityExtraction:
    """Cycle 2: 用真实 LLM 从前10章中抽取世界对象（自动入库）"""

    @pytest_asyncio.fixture
    async def ctx(self, db_session: AsyncSession) -> dict:
        """导入前10章，返回 project_id"""
        assert REAL_FILE_PATH.exists()
        file_bytes = REAL_FILE_PATH.read_bytes()

        pid = uuid.uuid4()
        project = Project(
            id=pid,
            title="诡秘之主 第一部 提取测试",
            genre="西方奇幻",
            tone="维多利亚风格、黑暗",
            language="zh",
            target_length="novel",
            current_stage="writing",
        )
        db_session.add(project)
        await db_session.flush()
        project_id = str(pid)

        # 导入前10章
        all_chapters = parse_txt(file_bytes)
        from modules.writing.facade import create_draft

        for idx in range(FIRST_10_CHAPTER_COUNT):
            ch = all_chapters[idx]
            await create_draft(
                db_session,
                novel_id=project_id,
                chapter_index=idx + 1,
                title=ch.get("title") or f"第{idx + 1}章",
                content=ch.get("content", ""),
            )

        await db_session.flush()
        return {"project_id": project_id}

    @pytest.mark.asyncio
    async def test_extraction_creates_canonical_entities(
        self, ctx: dict, db_session: AsyncSession
    ):
        """实体抽取应创建 canonical 实体（自动入库），而非候选"""
        project_id = ctx["project_id"]

        # 创建抽取服务（注入直读 DraftProvider，不依赖 RAG/pgvector）
        extraction_service = EntityExtractionService(
            draft_provider=DirectDraftProvider(),
        )

        result = await extraction_service.extract_entities_from_chapters(
            db_session,
            novel_id=project_id,
            start_chapter=1,
            end_chapter=10,
            batch_size=5,
        )

        assert result.total_chapters == FIRST_10_CHAPTER_COUNT
        assert result.total_created > 0, (
            f"应抽取到世界对象。创建 {result.total_created}，跳过 {result.total_skipped}"
        )
        # 至少应识别出核心实体（克莱恩、廷根市、值夜者等）
        created_names = [item["name"] for item in result.items]
        print(f"抽取到的实体: {created_names}")
        print(
            f"生成率: {result.total_created}/{result.total_created + result.total_skipped}"
        )

        # 验证结果包含自动入库标记
        assert all(item.get("auto_ingested") for item in result.items), (
            "所有实体应有 auto_ingested 标记"
        )
        # 验证所有实体共享同一 batch_id
        batch_ids = {
            item.get("batch_id") for item in result.items if item.get("batch_id")
        }
        assert len(batch_ids) == 1, f"应有统一 batch_id，实际 {batch_ids}"

    @pytest.mark.asyncio
    async def test_entities_persisted_as_canonical(
        self, ctx: dict, db_session: AsyncSession
    ):
        """抽取的实体应以 canonical 状态持久化到 core_entities 表"""
        project_id = ctx["project_id"]

        extraction_service = EntityExtractionService(
            draft_provider=DirectDraftProvider(),
        )

        await extraction_service.extract_entities_from_chapters(
            db_session,
            novel_id=project_id,
            start_chapter=1,
            end_chapter=10,
            batch_size=5,
        )

        # 用 repo 查询
        from modules.world.repositories import CoreEntityRepository

        nid = uuid.UUID(hex=project_id)
        repo = CoreEntityRepository()
        entities, total = await repo.get_by_novel(db_session, nid, limit=100)
        assert total > 0, "core_entities 表中有实体"

        # 验证全部为 canonical 状态
        statuses = {e.status for e in entities}
        assert statuses == {"canonical"}, f"所有实体应为 canonical，实际 {statuses}"

        # 验证包含 auto_ingested 元数据
        for e in entities:
            meta = (e.content_json or {}).get("_meta", {})
            assert meta.get("auto_ingested") is True, f"{e.name} 应标记 auto_ingested"
            assert meta.get("batch_id"), f"{e.name} 应有 batch_id"
            assert meta.get("ingested_at"), f"{e.name} 应有 ingested_at"

        names = [e.name for e in entities]
        print(f"DB中的实体 (canonical): {names}")

    @pytest.mark.asyncio
    async def test_extraction_without_chapters_returns_400(
        self, db_session: AsyncSession
    ):
        """无章节内容时抽取应报错"""
        pid = uuid.uuid4()
        project = Project(id=pid, title="空项目", genre="test", language="zh")
        db_session.add(project)
        await db_session.flush()

        extraction_service = EntityExtractionService(
            draft_provider=DirectDraftProvider(),
        )

        with pytest.raises(Exception, match="未找到章节"):
            await extraction_service.extract_entities_from_chapters(
                db_session,
                novel_id=str(pid),
                start_chapter=1,
                end_chapter=10,
                batch_size=5,
            )


# ============================================================
# Cycle 3: Workflow 编排
# ============================================================


class TestRealWorkflowStep1:
    """Cycle 3: DeepImportWorkflow 三阶段流水线测试（mock 内部方法）"""

    @pytest.mark.asyncio
    async def test_workflow_3_phase_with_real_data_setup(
        self,
        db_session: AsyncSession,
    ) -> None:
        """Workflow 从 pending → done，使用真实文件导入数据 + mock 三阶段"""
        from unittest import mock

        assert REAL_FILE_PATH.exists()
        file_bytes = REAL_FILE_PATH.read_bytes()

        pid = uuid.uuid4()
        project = Project(
            id=pid,
            title="诡秘之主 第一部 Workflow 测试",
            genre="西方奇幻",
            tone="维多利亚风格、黑暗",
            language="zh",
            target_length="novel",
            current_stage="writing",
        )
        db_session.add(project)
        await db_session.flush()
        project_id = str(pid)

        # 导入前5章
        all_chapters = parse_txt(file_bytes)
        from modules.writing.facade import create_draft

        for idx in range(FIRST_10_CHAPTER_COUNT):
            ch = all_chapters[idx]
            await create_draft(
                db_session,
                novel_id=project_id,
                chapter_index=idx + 1,
                title=ch.get("title") or f"第{idx + 1}章",
                content=ch.get("content", ""),
            )

        await db_session.flush()

        from modules.imports.workflow import DeepImportWorkflow
        from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep

        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()

        async def _mock_segment(db, novel_id, start_chapter, end_chapter):
            return {"total_scenes": 3, "failed_batches": [], "degraded": False}

        async def _mock_extract(db, novel_id):
            return {"total_created": 5, "total_deltas": 3}

        async def _mock_analyze(db, novel_id, start_chapter, end_chapter):
            return {
                "total_threads": 2,
                "total_arcs": 1,
                "threads": [],
                "arcs": [],
                "extra_sections": {},
            }

        with (
            mock.patch.object(workflow, "_segment_scenes", side_effect=_mock_segment),
            mock.patch.object(
                workflow,
                "_extract_entities_by_scene",
                side_effect=_mock_extract,
            ),
            mock.patch.object(
                workflow,
                "_analyze_structure",
                side_effect=_mock_analyze,
            ),
        ):
            result = await workflow.run_step(
                db=db_session,
                novel_id=project_id,
                start_chapter=1,
                end_chapter=5,
                progress=progress,
            )

        assert result.phase == "done", f"阶段应为 done，实际 {result.phase}"
        assert DeepImportStep.scene_segmentation.value in result.completed_steps
        assert DeepImportStep.entity_extraction.value in result.completed_steps
        assert DeepImportStep.structure_analysis.value in result.completed_steps
        assert "深度导入完成" in result.message


# ============================================================
# Cycle 4: 上下文加载 — 第二次抽取不重复创建
# ============================================================


class TestAutoIngestContextLoading:
    """Cycle 4: 验证上下文加载使第二次抽取不重复创建已有实体"""

    @pytest_asyncio.fixture
    async def ctx(self, db_session: AsyncSession) -> dict:
        """导入前10章 + 首次抽取，返回 project_id"""
        assert REAL_FILE_PATH.exists()
        file_bytes = REAL_FILE_PATH.read_bytes()

        pid = uuid.uuid4()
        project = Project(
            id=pid,
            title="诡秘之主 上下文加载测试",
            genre="西方奇幻",
            tone="维多利亚风格、黑暗",
            language="zh",
            target_length="novel",
            current_stage="writing",
        )
        db_session.add(project)
        await db_session.flush()
        project_id = str(pid)

        # 导入前10章
        all_chapters = parse_txt(file_bytes)
        from modules.writing.facade import create_draft

        for idx in range(FIRST_10_CHAPTER_COUNT):
            ch = all_chapters[idx]
            await create_draft(
                db_session,
                novel_id=project_id,
                chapter_index=idx + 1,
                title=ch.get("title") or f"第{idx + 1}章",
                content=ch.get("content", ""),
            )

        await db_session.flush()

        # 首次抽取
        service = EntityExtractionService(draft_provider=DirectDraftProvider())
        first_result = await service.extract_entities_from_chapters(
            db_session,
            novel_id=project_id,
            start_chapter=1,
            end_chapter=5,
            batch_size=5,
        )

        return {"project_id": project_id, "first_created": first_result.total_created}

    @pytest.mark.asyncio
    async def test_second_extraction_uses_context(
        self, ctx: dict, db_session: AsyncSession
    ):
        """第二次抽取（相同章节）应加载已有实体作为上下文"""
        project_id = ctx["project_id"]

        # 验证已有 canonical 实体在 DB 中
        from modules.world.repositories import CoreEntityRepository
        from shared.utils import parse_uuid

        nid = parse_uuid(project_id, "novel_id")
        repo = CoreEntityRepository()
        entities, total = await repo.get_by_novel(db_session, nid, limit=200)
        assert total >= ctx["first_created"], (
            f"DB 中应有 >= {ctx['first_created']} 个实体，实际 {total}"
        )
        all_canonical = all(e.status == "canonical" for e in entities)
        assert all_canonical, "所有实体应为 canonical 状态"
        print(f"上下文中有 {total} 个 canonical 实体")

        # 第二次抽取（验证加载上下文不会崩溃，且重复实体被跳过）
        service = EntityExtractionService(draft_provider=DirectDraftProvider())
        second_result = await service.extract_entities_from_chapters(
            db_session,
            novel_id=project_id,
            start_chapter=1,
            end_chapter=5,
            batch_size=5,
        )

        print(
            f"首次创建: {ctx['first_created']}, 第二次创建: {second_result.total_created}, 跳过: {second_result.total_skipped}"
        )
        # 第二次不应创建比第一次更多实体（已创建的应被去重逻辑识别）
        assert second_result.total_created <= ctx["first_created"], (
            "第二次创建的实体数不应超过第一次"
        )

    @pytest.mark.asyncio
    async def test_entity_batches_available(self, ctx: dict, db_session: AsyncSession):
        """自动入库实体可通过批次 API 查询"""
        project_id = ctx["project_id"]

        from modules.world.repositories import CoreEntityRepository
        from shared.utils import parse_uuid

        nid = parse_uuid(project_id, "novel_id")
        repo = CoreEntityRepository()
        batches = await repo.get_entity_batches(db_session, nid, limit=5)
        assert len(batches) >= 1, "至少有一个导入批次"
        batch = batches[0]
        assert batch["batch_id"], "批次应有 batch_id"
        assert batch["entity_count"] >= 1, (
            f"批次应有至少1个实体，实际 {batch['entity_count']}"
        )
        print(
            f"批次 {batch['batch_id']}: {batch['entity_count']} 个实体, 导入时间 {batch['ingested_at']}"
        )
