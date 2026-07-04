"""
真实文件导入测试 — 诡秘之主_第一部_小丑.txt

使用真实小说文件（2.2MB, 213 章）测试导入管线全程。
不使用任何 mock — 真实解析器、真实数据库、真实文件内容。
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError as DomainValidationError
from infrastructure.tasks.models import AsyncTask
from modules.imports.models import ImportRecord
from modules.imports.parsers import parse_txt
from modules.imports.services import ImportService
from modules.project.models import Project
from modules.writing.models import WritingDraft

REAL_FILE_PATH = Path("/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑.txt")
EXPECTED_CHAPTER_COUNT = 213
FIRST_CHAPTER_TITLE = "第一章 绯红"
LAST_CHAPTER_TITLE = "第二百一十三章 再看一眼"


# ============================================================
# Cycle 1: Parser — 真实文件解析（Tracer Bullet）
# ============================================================


class TestRealFileParser:
    """Tracer Bullet: Parser 能否正确解析真实小说文件？"""

    @pytest.fixture(scope="class")
    def file_bytes(self) -> bytes:
        assert REAL_FILE_PATH.exists(), f"真实文件不存在: {REAL_FILE_PATH}"
        return REAL_FILE_PATH.read_bytes()

    def test_parser_splits_into_213_chapters(self, file_bytes: bytes):
        """RED: 编写 parser 测试 → GREEN: 预期通过"""
        chapters = parse_txt(file_bytes)
        assert len(chapters) == EXPECTED_CHAPTER_COUNT, (
            f"期望 {EXPECTED_CHAPTER_COUNT} 章，实际 {len(chapters)} 章"
        )

    def test_first_and_last_chapter_titles(self, file_bytes: bytes):
        """第一章和最后一章标题应与预期一致"""
        chapters = parse_txt(file_bytes)
        assert chapters[0]["title"] == FIRST_CHAPTER_TITLE
        assert chapters[-1]["title"] == LAST_CHAPTER_TITLE

    def test_chapters_have_sequential_indices(self, file_bytes: bytes):
        """所有章节标题应包含中文数字序号（第一章 ~ 第二百一十三章）"""
        chapters = parse_txt(file_bytes)
        for i, ch in enumerate(chapters):
            assert ch["title"].startswith("第"), (
                f"第 {i + 1} 章标题不以'第'开头: '{ch['title']}'"
            )
            assert "章" in ch["title"], f"第 {i + 1} 章标题不含'章': '{ch['title']}'"

    def test_each_chapter_has_substantial_content(self, file_bytes: bytes):
        """每个章节正文应有足够长度"""
        chapters = parse_txt(file_bytes)
        for i, ch in enumerate(chapters):
            assert len(ch["content"]) > 500, (
                f"第 {i + 1} 章 '{ch['title']}' 正文过短: {len(ch['content'])} 字符"
            )

    def test_first_chapter_content_starts_with_story(self, file_bytes: bytes):
        """第一章正文应以小说正文开头（不含书前信息）"""
        chapters = parse_txt(file_bytes)
        content = chapters[0]["content"]
        assert "痛" in content[:200], f"第一章开头不像正文: {content[:200]}"

    def test_book_metadata_excluded_from_chapters(self, file_bytes: bytes):
        """书前元信息（标题/作者/简介）不应出现在任何章节正文中"""
        chapters = parse_txt(file_bytes)
        for i, ch in enumerate(chapters):
            assert "知轩藏书" not in ch["content"], f"第 {i + 1} 章包含'知轩藏书'"
            assert "爱潜水的乌贼" not in ch["content"], f"第 {i + 1} 章包含'爱潜水的乌贼'"
            assert "内容简介" not in ch["content"], f"第 {i + 1} 章包含'内容简介'"

    def test_chapter_word_count_minimum(self, file_bytes: bytes):
        """每章应有足够的字数（中文字数 > 1000）"""
        chapters = parse_txt(file_bytes)
        for i, ch in enumerate(chapters):
            cn_chars = sum(1 for c in ch["content"] if "一" <= c <= "鿿")
            assert cn_chars > 1000, (
                f"第 {i + 1} 章 '{ch['title']}' 中文字数不足: {cn_chars}"
            )


# ============================================================
# Cycle 2: Service — 完整导入管线
# ============================================================


class TestRealFileImportService:
    """Cycle 2: ImportService 能否完成真实文件的完整导入？"""

    @pytest_asyncio.fixture
    async def real_project(self, db_session: AsyncSession) -> str:
        """创建一个真实的 Project 记录"""
        pid = uuid.uuid4()
        project = Project(
            id=pid,
            title="诡秘之主 第一部 测试",
            genre="西方奇幻",
            tone="维多利亚风格、黑暗",
            language="zh",
            target_length="novel",
            current_stage="writing",
        )
        db_session.add(project)
        await db_session.flush()
        return str(pid)

    @pytest_asyncio.fixture
    async def real_file_bytes(self) -> bytes:
        assert REAL_FILE_PATH.exists(), f"真实文件不存在: {REAL_FILE_PATH}"
        return REAL_FILE_PATH.read_bytes()

    @pytest.mark.asyncio
    async def test_import_creates_done_record(
        self,
        service: ImportService,
        db_session: AsyncSession,
        real_project: str,
        real_file_bytes: bytes,
    ):
        """完整导入后应创建 done 状态的导入记录，章节数正确"""
        resp = await service.upload_and_import(
            db_session,
            real_project,
            "诡秘之主_第一部_小丑.txt",
            real_file_bytes,
        )
        assert resp.status == "done"
        assert resp.total_chapters == EXPECTED_CHAPTER_COUNT
        assert resp.imported_chapters == EXPECTED_CHAPTER_COUNT
        assert resp.file_name == "诡秘之主_第一部_小丑.txt"
        assert resp.file_type == "txt"

    @pytest.mark.asyncio
    async def test_imported_chapters_written_to_drafts(
        self,
        service: ImportService,
        db_session: AsyncSession,
        real_project: str,
        real_file_bytes: bytes,
    ):
        """导入后 writing_drafts 应创建 10 条草稿"""
        await service.upload_and_import(
            db_session,
            real_project,
            "novel.txt",
            real_file_bytes,
        )

        result = await db_session.execute(
            select(WritingDraft)
            .where(WritingDraft.novel_id == uuid.UUID(hex=real_project))
            .order_by(WritingDraft.chapter_index)
        )
        drafts = list(result.scalars().all())

        assert len(drafts) == EXPECTED_CHAPTER_COUNT, (
            f"期望 {EXPECTED_CHAPTER_COUNT} 条草稿，实际 {len(drafts)}"
        )
        for i, draft in enumerate(drafts):
            assert draft.chapter_index == i + 1, f"第 {i + 1} 条草稿索引不正确"
            assert isinstance(draft.title, str) and draft.title.startswith("第"), (
                f"第 {i + 1} 条草稿标题格式不正确: '{draft.title}'"
            )
            assert draft.status == "draft"
            assert draft.version_number == 1
            assert draft.content and len(draft.content) > 500, (
                f"第 {i + 1} 章草稿正文过短"
            )

    @pytest.mark.asyncio
    async def test_publish_tasks_enqueued_without_duplicate_rag_index_tasks(
        self,
        service: ImportService,
        db_session: AsyncSession,
        real_project: str,
        real_file_bytes: bytes,
    ):
        """导入后应为每章节创建发布任务，避免重复 RAG 索引任务。"""
        await service.upload_and_import(
            db_session,
            real_project,
            "novel.txt",
            real_file_bytes,
        )

        result = await db_session.execute(
            select(AsyncTask).where(AsyncTask.task_type == "publish_chapter")
        )
        tasks = list(result.scalars().all())

        assert len(tasks) == EXPECTED_CHAPTER_COUNT
        chapter_indices = {
            task.meta.get("chapter_index", -1) for task in tasks if task.meta
        }
        assert chapter_indices == set(range(1, EXPECTED_CHAPTER_COUNT + 1))

        rag_result = await db_session.execute(
            select(AsyncTask).where(AsyncTask.task_type == "rag_index_chapter")
        )
        assert list(rag_result.scalars().all()) == []

    @pytest.mark.asyncio
    async def test_import_record_persisted_correctly(
        self,
        service: ImportService,
        db_session: AsyncSession,
        real_project: str,
        real_file_bytes: bytes,
    ):
        """导入记录在数据库中的字段应正确"""
        resp = await service.upload_and_import(
            db_session,
            real_project,
            "novel.txt",
            real_file_bytes,
        )

        result = await db_session.execute(
            select(ImportRecord).where(ImportRecord.id == uuid.UUID(hex=resp.id))
        )
        record = result.scalar_one_or_none()
        assert record is not None, "导入记录未持久化"
        assert record.total_chapters == EXPECTED_CHAPTER_COUNT
        assert record.imported_chapters == EXPECTED_CHAPTER_COUNT
        assert record.status == "done"
        assert record.file_size == len(real_file_bytes)

    @pytest.mark.asyncio
    async def test_import_twice_same_file_returns_400_and_preserves_first_record(
        self,
        service: ImportService,
        db_session: AsyncSession,
        real_project: str,
        real_file_bytes: bytes,
    ):
        """同一项目同名文件已成功导入后，再次导入应被拒绝。"""
        resp1 = await service.upload_and_import(
            db_session,
            real_project,
            "novel.txt",
            real_file_bytes,
        )

        with pytest.raises(DomainValidationError) as exc_info:
            await service.upload_and_import(
                db_session,
                real_project,
                "novel.txt",
                real_file_bytes,
            )

        assert resp1.status == "done"
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "文件已导入: novel.txt"

        result = await db_session.execute(
            select(ImportRecord).where(
                ImportRecord.novel_id == uuid.UUID(hex=real_project),
                ImportRecord.file_name == "novel.txt",
            )
        )
        records = list(result.scalars().all())
        assert len(records) == 1
        assert records[0].status == "done"


# ============================================================
# Cycle 3: 边界情况 — 非小说文本的导入
# ============================================================


class TestRealFileEdgeCases:
    """边界情况测试：确保导入管线对各种输入有合理行为"""

    @pytest.mark.asyncio
    async def test_empty_project_id_fails(
        self,
        service: ImportService,
        db_session: AsyncSession,
    ):
        """空 novel_id 应被拒绝"""
        with pytest.raises(Exception):
            await service.upload_and_import(
                db_session,
                "",
                "test.txt",
                b"content",
            )

    @pytest.mark.asyncio
    async def test_very_small_file_imports_as_single_chapter(
        self,
        service: ImportService,
        db_session: AsyncSession,
    ):
        """极小文件（无章节标记）应导入为单章"全文" """
        pid = uuid.uuid4()
        project = Project(id=pid, title="Test", genre="test", language="zh")
        db_session.add(project)
        await db_session.flush()

        resp = await service.upload_and_import(
            db_session,
            str(pid),
            "short.txt",
            "一段很短的内容。".encode(),
        )
        assert resp.status == "done"
        assert resp.total_chapters == 1
        assert resp.imported_chapters == 1
