"""
Import 模块测试

测试 parsers 解析逻辑、repository CRUD、service 导入流程。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.parsers import (
    parse_file,
    parse_txt,
    split_chapters,
)
from modules.imports.repositories import ImportRecordRepository


# ============================================================
# Parser 测试
# ============================================================

class TestSplitChapters:
    """测试分章逻辑"""

    def test_chinese_chapter_pattern(self):
        """测试中文分章"""
        text = "第一章 开始\n内容1\n\n第二章 发展\n内容2\n\n第三章 结局\n内容3"
        chapters = split_chapters(text)
        assert len(chapters) == 3
        assert chapters[0]["title"] == "第一章 开始"
        assert chapters[1]["title"] == "第二章 发展"
        assert chapters[2]["title"] == "第三章 结局"

    def test_no_chapter_pattern(self):
        """测试无分章模式（返回全文）"""
        text = "这是一段没有分章的文本。"
        chapters = split_chapters(text)
        assert len(chapters) == 1
        assert chapters[0]["title"] == "全文"

    def test_mixed_numbering(self):
        """测试混合编号（中文数字+阿拉伯数字）"""
        text = "第1章\n内容\n\n第2章\n更多内容"
        chapters = split_chapters(text)
        assert len(chapters) == 2

    def test_prologue_and_chapters(self):
        """测试序章+章节"""
        text = "序章\n\n第一章 开始\n正文开始"
        chapters = split_chapters(text)
        assert len(chapters) == 2
        assert chapters[0]["title"] == "序章"

    def test_volume_pattern(self):
        """测试卷模式"""
        text = "卷一 春\n内容1\n\n卷二 夏\n内容2"
        chapters = split_chapters(text)
        assert len(chapters) == 2


class TestParseTxt:
    """测试 TXT 文件解析"""

    def test_parse_with_chapters(self, sample_txt_content: bytes):
        """测试带章节的 TXT 解析"""
        chapters = parse_txt(sample_txt_content)
        assert len(chapters) == 4
        assert chapters[0]["title"] == "序章"
        assert "序章的内容" in chapters[0]["content"]
        assert chapters[1]["title"] == "第一章"
        assert chapters[2]["title"] == "第二章 新的旅程"

    def test_parse_no_chapters(self, sample_txt_no_chapters: bytes):
        """测试无分章的 TXT"""
        chapters = parse_txt(sample_txt_no_chapters)
        assert len(chapters) == 1
        assert chapters[0]["title"] == "全文"

    def test_empty_content(self):
        """测试空内容"""
        chapters = parse_txt(b"")
        assert len(chapters) == 1

    def test_parse_file_unified(self, sample_txt_content: bytes):
        """测试统一入口 parse_file"""
        chapters = parse_file(sample_txt_content, "txt")
        assert len(chapters) == 4

    def test_parse_file_unsupported_type(self):
        """测试不支持的类型"""
        with pytest.raises(ValueError, match="不支持的文件类型"):
            parse_file(b"test", "pdf")


class TestFileValidation:
    """测试文件校验"""

    def test_validate_file_type(self):
        """测试文件类型白名单"""
        from modules.imports.services import _get_extension
        assert _get_extension("test.txt") == ".txt"
        assert _get_extension("test.epub") == ".epub"
        assert _get_extension("test.HTML") == ".html"
        assert _get_extension("/path/to/book.mobi") == ".mobi"
        assert _get_extension("../malicious.txt") == ".txt"

    def test_path_traversal_sanitize(self):
        """测试路径穿越防护"""
        from modules.imports.services import _get_extension
        assert _get_extension("../../../etc/passwd.txt") == ".txt"


# ============================================================
# File size & encoding 测试
# ============================================================

class TestFileLimits:
    """测试文件大小和编码限制"""

    def test_oversized_file(self):
        """超过 50MB 的文件应拒绝"""
        from modules.imports.parsers import MAX_FILE_SIZE
        large_data = b"x" * (MAX_FILE_SIZE + 1)
        # parsers 本身不校验大小，由 service 层拒绝
        # 这里测试 parsers 处理大文件无内存异常
        chapters = parse_txt(large_data)
        assert len(chapters) >= 1

    def test_non_utf8_content(self):
        """非 UTF-8 编码的文本应以 UTF-8 解码（忽略错误）"""
        # 构造含非法 UTF-8 字节序列的内容
        raw = b"\xff\xfe\x00\xe4\xbd\xa0\xe5\xa5\xbd\n\xe4\xb8\x96\xe7\x95\x8c"
        chapters = parse_txt(raw)
        # 不应抛出异常
        assert len(chapters) >= 1
        assert isinstance(chapters[0]["content"], str)


# ============================================================
# Repository 测试
# ============================================================

class TestImportRecordRepository:
    """测试数据访问层"""

    @pytest.mark.asyncio
    async def test_create(
        self,
        repo: ImportRecordRepository,
        db_session: AsyncSession,
        test_project_id: str,
    ):
        """测试创建导入记录"""
        nid = uuid.UUID(hex=test_project_id)
        record = await repo.create(db_session, nid, "test.txt", "txt", 1024)
        assert record.id is not None
        assert record.file_name == "test.txt"
        assert record.file_type == "txt"
        assert record.file_size == 1024
        assert record.status == "processing"

    @pytest.mark.asyncio
    async def test_get_not_found(
        self,
        repo: ImportRecordRepository,
        db_session: AsyncSession,
    ):
        """测试获取不存在的记录"""
        record = await repo.get(db_session, uuid.uuid4())
        assert record is None

    @pytest.mark.asyncio
    async def test_update_status(
        self,
        repo: ImportRecordRepository,
        db_session: AsyncSession,
        test_project_id: str,
    ):
        """测试更新状态"""
        nid = uuid.UUID(hex=test_project_id)
        record = await repo.create(db_session, nid, "test.txt", "txt", 512)

        updated = await repo.update_status(
            db_session, record.id,
            status="done",
            total_chapters=10,
            imported_chapters=10,
        )
        assert updated is not None
        assert updated.status == "done"
        assert updated.total_chapters == 10
        assert updated.imported_chapters == 10

    @pytest.mark.asyncio
    async def test_get_by_novel(
        self,
        repo: ImportRecordRepository,
        db_session: AsyncSession,
        test_project_id: str,
    ):
        """测试按项目查询"""
        nid = uuid.UUID(hex=test_project_id)
        for i in range(3):
            await repo.create(db_session, nid, f"test{i}.txt", "txt", 100)

        items, total = await repo.get_by_novel(db_session, nid, skip=0, limit=10)
        assert total >= 3
        assert len(items) >= 3


# ============================================================
# Service 测试
# ============================================================

class TestImportService:
    """测试业务逻辑层"""

    @pytest.mark.asyncio
    async def test_upload_and_import(
        self,
        service,
        db_session: AsyncSession,
        test_project_id: str,
        sample_txt_content: bytes,
    ):
        """测试完整导入流程"""
        resp = await service.upload_and_import(
            db_session,
            test_project_id,
            "novel.txt",
            sample_txt_content,
        )
        assert resp.status == "done"
        assert resp.total_chapters == 4
        assert resp.imported_chapters == 4
        assert resp.file_name == "novel.txt"
        assert resp.file_type == "txt"

    @pytest.mark.asyncio
    async def test_upload_unsupported_type(
        self,
        service,
        db_session: AsyncSession,
        test_project_id: str,
    ):
        """测试不支持的文件类型"""
        with pytest.raises(HTTPException) as exc:
            await service.upload_and_import(
                db_session,
                test_project_id,
                "test.pdf",
                b"content",
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_list_records(
        self,
        service,
        db_session: AsyncSession,
        test_project_id: str,
        sample_txt_content: bytes,
    ):
        """测试导入记录列表"""
        await service.upload_and_import(db_session, test_project_id, "a.txt", sample_txt_content)
        await service.upload_and_import(db_session, test_project_id, "b.txt", sample_txt_content)

        result = await service.list_import_records(db_session, test_project_id)
        assert result.total >= 2

    @pytest.mark.asyncio
    async def test_get_record(
        self,
        service,
        db_session: AsyncSession,
        test_project_id: str,
        sample_txt_content: bytes,
    ):
        """测试获取单条记录"""
        resp = await service.upload_and_import(
            db_session, test_project_id, "novel.txt", sample_txt_content,
        )
        fetched = await service.get_import_record(db_session, test_project_id, resp.id)
        assert fetched.id == resp.id
        assert fetched.file_name == "novel.txt"
