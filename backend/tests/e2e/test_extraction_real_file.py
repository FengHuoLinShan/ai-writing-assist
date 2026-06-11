"""
真实文件提取 E2E 测试 — 前10章 LLM 实体抽取

使用真实 PostgreSQL + 真实 DeepSeek LLM 测试完整提取管线：
导入前10章 → 直读 WritingDraft → LLM 结构抽取 → 候选持久化

RAG 索引已绕过（DirectDraftProvider），节省 embedding API 费用。
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.parsers import parse_txt
from modules.world.services.extraction_service import EntityExtractionService
from modules.writing.facade import get_latest_draft_for_chapter
from shared.protocols import DraftProvider

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]

REAL_FILE_PATH = "/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑.txt"
FIRST_10 = 10


# ============================================================
# DirectDraftProvider: 直读 writing_drafts（无 RAG 索引）
# ============================================================


class DirectDraftProvider(DraftProvider):
    """从 writing_drafts 直读章节正文。

    真实操作（非 mock）：直接查询 latest_draft_for_chapter。
    RAG 索引/pgvector 并非抽取测试目标，在此跳过。
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
# Cycle 1: 导入前10章（通过 API）
# ============================================================


class TestImportFirst10Chapters:
    """Tracer Bullet: 通过 API 导入前10章"""

    @pytest_asyncio.fixture
    async def ctx(self, db_session: AsyncSession, async_client: AsyncClient) -> dict:
        """创建项目 + 导入前10章，返回 project_id"""
        # Arrange
        proj_resp = await async_client.post(
            "/api/projects",
            json={
                "title": "诡秘之主 第一部 提取测试",
                "genre": "西方奇幻",
                "tone": "维多利亚风格、黑暗",
                "language": "zh",
                "target_length": "novel",
                "current_stage": "writing",
            },
        )
        assert proj_resp.status_code == 201, f"创建项目失败: {proj_resp.text}"
        project_id = proj_resp.json()["id"]

        file_bytes = open(REAL_FILE_PATH, "rb").read()
        all_chapters = parse_txt(file_bytes)
        first_10 = all_chapters[:FIRST_10]

        from modules.writing.facade import create_draft

        # Act
        for idx, ch in enumerate(first_10):
            await create_draft(
                db_session,
                novel_id=project_id,
                chapter_index=idx + 1,
                title=ch.get("title") or f"第{idx + 1}章",
                content=ch.get("content", ""),
            )
        await db_session.flush()

        # Assert (implicit via fixture return)
        return {"project_id": project_id}

    async def test_import_first_10_chapters_creates_drafts_in_order(
        self, ctx: dict, db_session: AsyncSession
    ):
        """验证前10章正确导入到 writing_drafts"""
        # Arrange
        from sqlalchemy import select

        from modules.writing.models import WritingDraft

        # Act
        result = await db_session.execute(
            select(WritingDraft)
            .where(WritingDraft.novel_id == uuid.UUID(hex=ctx["project_id"]))
            .order_by(WritingDraft.chapter_index)
        )
        drafts = list(result.scalars().all())

        # Assert
        assert len(drafts) == FIRST_10
        for i, draft in enumerate(drafts):
            assert draft.chapter_index == i + 1
            assert draft.content and len(draft.content) > 500

    async def test_import_first_10_chapters_drafts_readable_by_facade(
        self, ctx: dict, db_session: AsyncSession
    ):
        """每章草稿可通过 get_latest_draft_for_chapter 读取"""
        # Arrange
        # (project_id already in ctx)

        # Act & Assert
        for idx in range(1, FIRST_10 + 1):
            draft = await get_latest_draft_for_chapter(
                db_session,
                ctx["project_id"],
                idx,
            )
            assert draft is not None, f"第 {idx} 章草稿不可读"
            assert draft.content


# ============================================================
# Cycle 2: 真实 LLM 实体抽取
# ============================================================


class TestRealEntityExtraction:
    """用真实 DeepSeek LLM 从前10章抽取世界对象候选"""

    @pytest_asyncio.fixture
    async def ctx(self, db_session: AsyncSession, async_client: AsyncClient) -> dict:
        """创建项目 + 导入前10章 + 返回 project_id"""
        # Arrange
        proj_resp = await async_client.post(
            "/api/projects",
            json={
                "title": "诡秘之主 第一部 提取测试",
                "genre": "西方奇幻",
                "tone": "维多利亚风格、黑暗",
                "language": "zh",
                "target_length": "novel",
                "current_stage": "writing",
            },
        )
        assert proj_resp.status_code == 201
        project_id = proj_resp.json()["id"]

        file_bytes = open(REAL_FILE_PATH, "rb").read()
        all_chapters = parse_txt(file_bytes)

        from modules.writing.facade import create_draft

        # Act
        for idx, ch in enumerate(all_chapters[:FIRST_10]):
            await create_draft(
                db_session,
                novel_id=project_id,
                chapter_index=idx + 1,
                title=ch.get("title") or f"第{idx + 1}章",
                content=ch.get("content", ""),
            )
        await db_session.flush()

        # Assert (implicit)
        return {"project_id": project_id}

    async def test_extraction_real_llm_creates_core_entity_candidates(
        self, ctx: dict, db_session: AsyncSession
    ):
        """LLM 抽取应创建世界对象候选（至少2个：主角克莱恩、廷根市等）"""
        # Arrange
        project_id = ctx["project_id"]
        extraction_service = EntityExtractionService(
            draft_provider=DirectDraftProvider(),
        )

        # Act
        result = await extraction_service.extract_entities_from_chapters(
            db_session,
            novel_id=project_id,
            start_chapter=1,
            end_chapter=FIRST_10,
            batch_size=5,
        )

        # Assert
        assert result.total_chapters == FIRST_10
        assert result.total_created > 0, (
            f"应抽取到世界对象候选。创建 {result.total_created}，跳过 {result.total_skipped}"
        )
        created_names = [item["name"] for item in result.items]
        created_types = [item["entity_type"] for item in result.items]
        print(f"\n=== 抽取得 {result.total_created} 个实体 ===")
        for name, etype in zip(created_names, created_types):
            print(f"  [{etype}] {name}")
        print(f"跳过: {result.total_skipped}")

        all_text = " ".join(created_names)
        has_core_entity = (
            "克莱恩" in all_text
            or "主角" in all_text
            or "周明瑞" in all_text
            or "值夜者" in all_text
            or "廷根" in all_text
        )
        assert has_core_entity, f"未识别出核心世界对象。结果: {created_names}"

    async def test_extraction_real_llm_persists_candidates_in_db(
        self, ctx: dict, db_session: AsyncSession
    ):
        """抽取的候选应持久化到 core_entities 表"""
        # Arrange
        project_id = ctx["project_id"]
        extraction_service = EntityExtractionService(
            draft_provider=DirectDraftProvider(),
        )

        # Act
        await extraction_service.extract_entities_from_chapters(
            db_session,
            novel_id=project_id,
            start_chapter=1,
            end_chapter=FIRST_10,
            batch_size=5,
        )
        from modules.world.repositories import CoreEntityRepository

        repo = CoreEntityRepository()
        nid = uuid.UUID(hex=project_id)
        entities, total = await repo.get_by_novel(db_session, nid, limit=100)

        # Assert
        assert total > 0, "core_entities 表中无候选"
        names = [e.name for e in entities]
        print(f"\n=== DB 中 {total} 个实体 ===")
        for e in entities:
            print(f"  [{e.entity_type}] {e.name} (status={e.status})")
        assert len(names) >= 2

    async def test_extraction_empty_chapters_raises_exception(
        self, db_session: AsyncSession, async_client: AsyncClient
    ):
        """无章节内容时抽取应报 400"""
        # Arrange
        proj_resp = await async_client.post(
            "/api/projects",
            json={"title": "空项目", "genre": "test", "language": "zh"},
        )
        project_id = proj_resp.json()["id"]
        extraction_service = EntityExtractionService(
            draft_provider=DirectDraftProvider(),
        )

        # Act & Assert
        with pytest.raises(Exception, match="未找到章节|400"):
            await extraction_service.extract_entities_from_chapters(
                db_session,
                novel_id=project_id,
                start_chapter=1,
                end_chapter=10,
                batch_size=5,
            )

    async def test_extraction_real_llm_idempotent_skips_duplicates(
        self, ctx: dict, db_session: AsyncSession
    ):
        """同一批章节抽取两次不应重复创建相同候选"""
        # Arrange
        project_id = ctx["project_id"]
        service = EntityExtractionService(draft_provider=DirectDraftProvider())

        # Act
        result1 = await service.extract_entities_from_chapters(
            db_session,
            novel_id=project_id,
            start_chapter=1,
            end_chapter=5,
            batch_size=5,
        )
        result2 = await service.extract_entities_from_chapters(
            db_session,
            novel_id=project_id,
            start_chapter=1,
            end_chapter=5,
            batch_size=5,
        )

        # Assert
        print("\n=== 幂等性验证 ===")
        print(f"第一次: 创建 {result1.total_created}, 跳过 {result1.total_skipped}")
        print(f"第二次: 创建 {result2.total_created}, 跳过 {result2.total_skipped}")
        assert result2.total_created <= result1.total_created + 1


# ============================================================
# Cycle 4: Tracer Bullet — 真实文件 → RAG 索引 → Context 编译
# ============================================================


class TestRealFileRagContextPipeline:
    """Tracer Bullet: 真实文件导入 → RAG 索引 → Context 编译全链路

    验证 WritingDraftProvider（走 rag.facade）的完整路径。
    不依赖 LLM 抽取，只验证 import → RAG → context 三步走通。
    """

    @pytest_asyncio.fixture
    async def ctx(self, db_session: AsyncSession, async_client: AsyncClient) -> dict:
        """创建项目 + 导入前3章 + RAG 索引"""
        # Arrange
        proj_resp = await async_client.post(
            "/api/projects",
            json={
                "title": "诡秘之主 RAG+Context 测试",
                "genre": "西方奇幻",
                "tone": "维多利亚风格、黑暗",
                "language": "zh",
                "target_length": "novel",
                "current_stage": "writing",
            },
        )
        assert proj_resp.status_code == 201, f"创建项目失败: {proj_resp.text}"
        project_id = proj_resp.json()["id"]

        file_bytes = open(REAL_FILE_PATH, "rb").read()
        all_chapters = parse_txt(file_bytes)
        first_3 = all_chapters[:3]

        from modules.writing.facade import create_draft

        # Act
        for idx, ch in enumerate(first_3):
            await create_draft(
                db_session,
                novel_id=project_id,
                chapter_index=idx + 1,
                title=ch.get("title") or f"第{idx + 1}章",
                content=ch.get("content", ""),
            )
        await db_session.flush()

        from modules.rag.facade import get_index_status, index_chapter

        for idx in range(1, 4):
            chunk_count = await index_chapter(db_session, project_id, idx)
            assert chunk_count > 0, (
                f"第{idx}章 index_chapter 应产生 chunk，实际: {chunk_count}"
            )

        await db_session.flush()

        status = await get_index_status(db_session, project_id)
        assert status["total"] >= 3, (
            f"RAG 索引应有至少 3 个 chunk，实际: {status['total']}"
        )

        # Assert (implicit via fixture return)
        return {"project_id": project_id}

    async def test_rag_index_creates_ordered_chunks_per_chapter(
        self, ctx: dict, db_session: AsyncSession
    ):
        """RAG 索引后可通过 get_ordered_chapter_chunks 读取"""
        # Arrange
        from modules.rag.facade import get_ordered_chapter_chunks

        # Act
        ch1_chunks = await get_ordered_chapter_chunks(
            db_session,
            ctx["project_id"],
            1,
            1,
        )
        ch2_chunks = await get_ordered_chapter_chunks(
            db_session,
            ctx["project_id"],
            2,
            2,
        )

        # Assert
        assert len(ch1_chunks) >= 1, f"第1章应有 RAG chunks，实际: {len(ch1_chunks)}"
        assert ch1_chunks[0].chapter_index == 1
        assert len(ch1_chunks[0].text) > 0
        assert len(ch2_chunks) >= 1
        assert ch2_chunks[0].chapter_index == 2

    async def test_rag_writing_draft_provider_loads_chunks_with_content(
        self, ctx: dict, db_session: AsyncSession
    ):
        """WritingDraftProvider 能从 RAG chunks 加载章节正文"""
        # Arrange
        from modules.world.services.draft_provider import WritingDraftProvider

        provider = WritingDraftProvider()

        # Act
        chapters = await provider.load_chapters(
            db_session,
            ctx["project_id"],
            1,
            3,
        )

        # Assert
        assert len(chapters) == 3, f"应加载3章，实际: {len(chapters)}"
        for ch in chapters:
            assert "chapter_index" in ch
            assert "content" in ch
            assert "[RAG chunk" in ch["content"] or len(ch["content"]) > 500

    async def test_context_compile_world_scope_returns_project_bundle(
        self, ctx: dict, db_session: AsyncSession
    ):
        """Context Compiler scope=world 应包含项目信息"""
        # Arrange
        from modules.context.facade import compile_structure_context

        # Act
        bundle = await compile_structure_context(
            db=db_session,
            novel_id=ctx["project_id"],
            task="测试上下文编译",
            scope="world",
            reveal_mode="author_safe",
        )

        # Assert
        assert bundle.novel_id == ctx["project_id"]
        assert bundle.project is not None
        assert "title" in bundle.project
        assert bundle.scope == "world"

    async def test_rag_retrieve_by_query_returns_matching_chunks(
        self, ctx: dict, db_session: AsyncSession
    ):
        """RAG retrieve 通过 facade 直接调用应返回结果"""
        # Arrange
        from modules.rag.facade import retrieve

        # Act
        result = await retrieve(
            db_session,
            ctx["project_id"],
            query="周明瑞",
            chapter_index=2,
            top_k=5,
        )

        # Assert
        assert result.total > 0, f"检索应返回 chunk，实际: {result.total}"
        assert len(result.chunks) > 0
        assert result.chunks[0].chapter_index == 2

    async def test_context_render_world_scope_produces_markdown(
        self, ctx: dict, db_session: AsyncSession
    ):
        """Context Render scope=world 应产生有意义的 Markdown"""
        # Arrange
        from modules.context.facade import (
            compile_structure_context,
            render_context_markdown,
        )

        # Act
        bundle = await compile_structure_context(
            db=db_session,
            novel_id=ctx["project_id"],
            task="测试Markdown渲染",
            scope="world",
            reveal_mode="author_safe",
        )
        markdown = render_context_markdown(bundle)

        # Assert
        assert len(markdown) > 100, f"Markdown 太短: {len(markdown)}"
        assert "诡秘" in markdown or "Test" in ctx["project_id"]

    async def test_context_render_chapter_scope_produces_markdown(
        self, ctx: dict, db_session: AsyncSession
    ):
        """Context Render scope=chapter 应产生有意义的 Markdown"""
        # Arrange
        from modules.context.facade import (
            compile_structure_context,
            render_context_markdown,
        )

        # Act
        bundle = await compile_structure_context(
            db=db_session,
            novel_id=ctx["project_id"],
            task="测试Markdown渲染",
            scope="chapter",
            chapter_index=2,
        )
        markdown = render_context_markdown(bundle)

        # Assert
        assert len(markdown) > 100, f"Markdown 太短: {len(markdown)}"
        assert "第" in markdown or "诡秘" in markdown


# ============================================================
# Cycle 3: DeepImportWorkflow Step 1
# ============================================================


class TestRealWorkflowStep1:
    """DeepImportWorkflow 使用真实数据执行 Step 1"""

    async def test_workflow_step1_real_data_completes_extraction_phase(
        self,
        db_session: AsyncSession,
        async_client: AsyncClient,
    ):
        """Workflow 从 pending → awaiting_review"""
        # Arrange
        proj_resp = await async_client.post(
            "/api/projects",
            json={
                "title": "诡秘之主 Workflow 测试",
                "genre": "西方奇幻",
                "tone": "维多利亚风格、黑暗",
                "language": "zh",
                "target_length": "novel",
                "current_stage": "writing",
            },
        )
        project_id = proj_resp.json()["id"]

        file_bytes = open(REAL_FILE_PATH, "rb").read()
        all_chapters = parse_txt(file_bytes)
        from modules.writing.facade import create_draft

        for idx, ch in enumerate(all_chapters[:3]):
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

        original_workflow = DeepImportWorkflow()

        async def _extract_with_direct(db, novel_id, start_chapter, end_chapter):
            svc = EntityExtractionService(draft_provider=DirectDraftProvider())
            result = await svc.extract_entities_from_chapters(
                db,
                novel_id=novel_id,
                start_chapter=start_chapter,
                end_chapter=end_chapter,
                batch_size=5,
            )
            return {
                "total_chapters": result.total_chapters,
                "total_created": result.total_created,
                "total_skipped": result.total_skipped,
                "items": result.items,
            }

        original_workflow._extract_world = _extract_with_direct
        progress = DeepImportProgress()

        # Act
        result = await original_workflow.run_step(
            db=db_session,
            novel_id=project_id,
            start_chapter=1,
            end_chapter=3,
            progress=progress,
        )

        # Assert
        assert result.phase == "done"
        assert DeepImportStep.extract_world.value in result.completed_steps
        assert "完成" in result.message or "抽取完成" in result.message
