"""Synthetic import coverage plus opt-in real-LLM acceptance tests."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.secret_store import ensure_encrypted_secret
from modules.imports.parsers import parse_txt
from modules.project.models import Project
from modules.world.services.core.extraction_service import EntityExtractionService
from modules.writing.facade import get_latest_draft_for_chapter
from modules.writing.models import WritingDraft
from shared.protocols import DraftProvider
from tests.utils import _mock_analyze, _mock_extract

SYNTHETIC_FILE_PATH = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "synthetic_ten_chapters.txt"
)
FIRST_10_CHAPTER_COUNT = 10
real_llm_required = pytest.mark.skipif(
    os.getenv("RUN_REAL_LLM_TESTS") != "1",
    reason="真实 LLM 抽取测试默认跳过；设置 RUN_REAL_LLM_TESTS=1 才运行",
)


def _synthetic_file_bytes() -> bytes:
    return SYNTHETIC_FILE_PATH.read_bytes()


def _manual_source_path() -> Path:
    raw_path = os.getenv("REAL_SOURCE_PATH")
    if not raw_path:
        pytest.fail(
            "手动真实语料验收需要 REAL_SOURCE_PATH；"
            "默认测试只使用 tests/fixtures/synthetic_ten_chapters.txt。"
        )
    source_path = Path(raw_path).expanduser()
    if not source_path.is_file():
        pytest.fail(f"REAL_SOURCE_PATH 不存在或不是文件：{source_path}")
    return source_path


def _real_deepseek_settings() -> dict:
    """Build the in-memory project profile used only by manual acceptance."""
    api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("LLM_API_KEY")
    if not api_key:
        pytest.fail(
            "真实 LLM 验收需要 DEEPSEEK_API_KEY 或 LLM_API_KEY，不会读取或输出密钥。"
        )
    return {
        "llm": {
            "provider_id": "deepseek",
            "label": "DeepSeek",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-v4-flash",
            "api_key": ensure_encrypted_secret(api_key),
        }
    }


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
    """Tracer Bullet: 导入合成十章节并验证。"""

    @pytest_asyncio.fixture
    async def ctx(self, db_session: AsyncSession) -> dict:
        """导入前10章并返回 project_id 和章节数据"""
        file_bytes = _synthetic_file_bytes()

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
            assert draft.content and len(draft.content) > 50

    @pytest.mark.asyncio
    async def test_first_chapter_keeps_fixture_content(self, ctx: dict):
        """The fixture preserves a stable first chapter title and narrative signal."""
        ch = ctx["chapters"][0]
        assert ch["title"] == "第一章 雨夜来信"
        assert "林舟" in ch["content"]

    @pytest.mark.asyncio
    async def test_10th_chapter_title(self, ctx: dict):
        """The ten-chapter fixture has a deterministic final chapter."""
        ch = ctx["chapters"][9]
        assert ch["title"] == "第十章 新的晨光"


# ============================================================
# Cycle 2: LLM 实体抽取（真实 DeepSeek API）
# ============================================================


@pytest.mark.real_llm
@real_llm_required
class TestRealEntityExtraction:
    """Cycle 2: 用真实 LLM 从前10章中抽取世界对象候选。"""

    @pytest_asyncio.fixture
    async def ctx(self, db_session: AsyncSession) -> dict:
        """导入前10章，返回 project_id"""
        file_bytes = _synthetic_file_bytes()

        pid = uuid.uuid4()
        project = Project(
            id=pid,
            title="诡秘之主 第一部 提取测试",
            genre="西方奇幻",
            tone="维多利亚风格、黑暗",
            language="zh",
            target_length="novel",
            current_stage="writing",
            settings=_real_deepseek_settings(),
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
    async def test_extraction_creates_candidate_entities(
        self, ctx: dict, db_session: AsyncSession
    ):
        """实体抽取应创建 candidate 实体，等待用户确认后入正史。"""
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
        created_names = [item["name"] for item in result.items]
        print(f"抽取到的实体: {created_names}")
        print(
            f"生成率: {result.total_created}/"
            f"{result.total_created + result.total_skipped}"
        )

        # 验证结果包含自动抽取来源标记
        assert all(item.get("auto_ingested") for item in result.items), (
            "所有实体应有 auto_ingested 标记"
        )
        # 验证所有实体共享同一 batch_id
        batch_ids = {
            item.get("batch_id") for item in result.items if item.get("batch_id")
        }
        assert len(batch_ids) == 1, f"应有统一 batch_id，实际 {batch_ids}"

    @pytest.mark.asyncio
    async def test_entities_persisted_as_candidate(
        self, ctx: dict, db_session: AsyncSession
    ):
        """抽取的实体应以 candidate 状态持久化到 core_entities 表"""
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

        # 验证全部为 candidate 状态
        statuses = {e.status for e in entities}
        assert statuses == {"candidate"}, f"所有实体应为 candidate，实际 {statuses}"

        # 验证包含 auto_ingested 元数据
        for e in entities:
            meta = (e.content_json or {}).get("_meta", {})
            assert meta.get("auto_ingested") is True, f"{e.name} 应标记 auto_ingested"
            assert meta.get("batch_id"), f"{e.name} 应有 batch_id"
            assert meta.get("ingested_at"), f"{e.name} 应有 ingested_at"

        names = [e.name for e in entities]
        print(f"DB中的实体 (candidate): {names}")

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
        """Workflow 从 pending → done，使用合成语料和 mock 三阶段。"""
        from unittest import mock

        file_bytes = _synthetic_file_bytes()

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

        from modules.imports.llm_schemas import SceneChunk
        from modules.imports.scene_commit import SceneCommitResult
        from modules.imports.scene_enrichment import Phase1bEnrichmentResult
        from modules.imports.scene_fusion import FinalSceneCandidate
        from modules.imports.scene_planning import ScenePlanResult, SceneWindowPlan
        from modules.imports.scene_slicing import SceneSliceCandidate, SceneSlicingResult
        from modules.imports.workflow import DeepImportWorkflow
        from modules.imports.workflow_schemas import DeepImportProgress, DeepImportStep

        workflow = DeepImportWorkflow()
        progress = DeepImportProgress()

        async def _mock_phase0_plan(_db, _novel_id, start_chapter, end_chapter):
            chapters = [
                {
                    "chapter_index": chapter,
                    "title": f"第{chapter}章",
                    "content": "正文",
                }
                for chapter in range(start_chapter, end_chapter + 1)
            ]
            return ScenePlanResult(
                chapters=chapters,
                windows=[
                    SceneWindowPlan(
                        window_index=1,
                        window_id="B0001-1-5-owned-1-5",
                        covered_start=start_chapter,
                        covered_end=end_chapter,
                        owned_start=start_chapter,
                        owned_end=end_chapter,
                        chapter_indices=list(range(start_chapter, end_chapter + 1)),
                        owned_chapter_indices=list(range(start_chapter, end_chapter + 1)),
                        input_chars=5000,
                        max_tokens=13_000,
                        batch_size=end_chapter - start_chapter + 1,
                        overlap=0,
                    )
                ],
                quality_stats={
                    "total_chapters": len(chapters),
                    "total_batches": 1,
                    "completed_batches": 1,
                    "window_count": 1,
                    "llm_calls": 0,
                },
            )

        async def _mock_phase1a_slicing(
            _db,
            _novel_id,
            start_chapter,
            end_chapter,
            _phase0_plan,
            **_kwargs,
        ):
            candidates = [
                SceneSliceCandidate(
                    candidate_id=f"phase1a-{chapter}",
                    source_window_id="B0001",
                    source_window_index=1,
                    title=f"第{chapter}章 Scene",
                    goal="推进章节事件。",
                    core_conflict="章节冲突。",
                    start_chapter=chapter,
                    end_chapter=chapter,
                    boundary_status="complete",
                    source_chapter_indices=[chapter],
                )
                for chapter in range(start_chapter, end_chapter + 1)
            ]
            return SceneSlicingResult(
                candidates=candidates,
                quality_stats={
                    "total_batches": 1,
                    "completed_batches": 1,
                    "success": 1,
                    "failed": 0,
                    "fallback_count": 0,
                    "scene_count": len(candidates),
                },
            )

        async def _mock_phase1b_enrichment(
            _db,
            _novel_id,
            _phase1a_candidates,
            *,
            start_chapter,
            end_chapter,
            **_kwargs,
        ):
            candidates = [
                FinalSceneCandidate(
                    phase="phase1b_enrichment",
                    title=f"第{chapter}章 Scene",
                    goal="提交测试 Scene。",
                    core_conflict="章节冲突。",
                    emotional_beat="测试情绪节拍。",
                    narrative_tag="imported",
                    scene_chunks=[SceneChunk(chapter_index=chapter)],
                    source_candidate_ids=[f"phase1a-{chapter}"],
                    source_rounds=["A"],
                    source_chapter_indices=[chapter],
                    operation="kept",
                    confidence=0.9,
                    boundary_status="complete",
                    boundary_reason="mocked workflow test",
                )
                for chapter in range(start_chapter, end_chapter + 1)
            ]
            return Phase1bEnrichmentResult(
                candidates=candidates,
                quality_stats={
                    "total_windows": len(candidates),
                    "completed_windows": len(candidates),
                    "total_scenes": len(candidates),
                    "completed": len(candidates),
                    "failed": 0,
                    "fallback_count": 0,
                },
            )

        async def _mock_commit(_db, _novel_id, _candidates, *, workflow_id):
            return SceneCommitResult(created_count=5)

        with (
            mock.patch.object(
                workflow,
                "_run_phase0_plan",
                side_effect=_mock_phase0_plan,
            ),
            mock.patch.object(
                workflow,
                "_run_phase1a_scene_slicing",
                side_effect=_mock_phase1a_slicing,
            ),
            mock.patch.object(
                workflow,
                "_run_phase1b_enrichment",
                side_effect=_mock_phase1b_enrichment,
            ),
            mock.patch.object(workflow, "_commit_fused_scenes", side_effect=_mock_commit),
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


@pytest.mark.real_llm
@real_llm_required
class TestAutoIngestContextLoading:
    """Cycle 4: 验证上下文加载使第二次抽取不重复创建已有实体"""

    @pytest_asyncio.fixture
    async def ctx(self, db_session: AsyncSession) -> dict:
        """导入前10章 + 首次抽取，返回 project_id"""
        file_bytes = _synthetic_file_bytes()

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

        # 验证已有 candidate 实体在 DB 中
        from modules.world.repositories import CoreEntityRepository
        from shared.utils import parse_uuid

        nid = parse_uuid(project_id, "novel_id")
        repo = CoreEntityRepository()
        entities, total = await repo.get_by_novel(db_session, nid, limit=200)
        assert total >= ctx["first_created"], (
            f"DB 中应有 >= {ctx['first_created']} 个实体，实际 {total}"
        )
        all_candidate = all(e.status == "candidate" for e in entities)
        assert all_candidate, "所有实体应为 candidate 状态"
        print(f"上下文中有 {total} 个 candidate 实体")

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
            f"首次创建: {ctx['first_created']}, "
            f"第二次创建: {second_result.total_created}, "
            f"跳过: {second_result.total_skipped}"
        )
        # 第二次不应创建比第一次更多实体（已创建的应被去重逻辑识别）
        assert second_result.total_created <= ctx["first_created"], (
            "第二次创建的实体数不应超过第一次"
        )

    @pytest.mark.asyncio
    async def test_entity_batches_available(self, ctx: dict, db_session: AsyncSession):
        """自动抽取候选可通过批次 API 查询"""
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
            f"批次 {batch['batch_id']}: {batch['entity_count']} 个实体, "
            f"导入时间 {batch['ingested_at']}"
        )


@pytest.mark.external_data
class TestManualExternalSource:
    """Keep original-novel parsing available without binding it to one machine."""

    def test_manual_source_contains_at_least_ten_chapters(self) -> None:
        chapters = parse_txt(_manual_source_path().read_bytes())
        assert len(chapters) >= FIRST_10_CHAPTER_COUNT
