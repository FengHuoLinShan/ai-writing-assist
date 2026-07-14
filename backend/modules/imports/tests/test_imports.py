"""
Import 模块测试

测试 parsers 解析逻辑、repository CRUD、service 导入流程。
"""

from __future__ import annotations

import io
import uuid
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import DomainError, NotFoundError
from core.errors import ValidationError as DomainValidationError
from infrastructure.tasks.models import AsyncTask
from modules.imports.parsers import (
    MAX_FILE_SIZE,
    parse_file,
    parse_txt,
    split_chapters,
)
from modules.imports.repositories import ImportRecordRepository
from modules.imports.services import ImportService

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
        assert chapters == []

    def test_whitespace_only_content(self):
        """纯空白内容不产生有效章节"""
        chapters = parse_txt(b" \n\t \n")
        assert chapters == []

    def test_parse_file_unified(self, sample_txt_content: bytes):
        """测试统一入口 parse_file"""
        chapters = parse_file(sample_txt_content, "txt")
        assert len(chapters) == 4

    def test_parse_file_unsupported_type(self):
        """测试不支持的类型"""
        with pytest.raises(ValueError, match="不支持的文件类型"):
            parse_file(b"test", "pdf")


class TestParseFileContentValidation:
    """上传解析入口必须校验扩展名对应的真实内容格式。"""

    @staticmethod
    def _epub_bytes(*, mimetype: bytes = b"application/epub+zip") -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("mimetype", mimetype, compress_type=zipfile.ZIP_STORED)
            archive.writestr(
                "META-INF/container.xml",
                """<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
                <rootfiles><rootfile full-path="OEBPS/content.opf"
                media-type="application/oebps-package+xml" /></rootfiles>
                </container>""",
            )
            archive.writestr(
                "OEBPS/content.opf",
                """<package xmlns="http://www.idpf.org/2007/opf" version="3.0"
                unique-identifier="book-id">
                <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
                <dc:identifier id="book-id">test-book</dc:identifier>
                <dc:title>测试书籍</dc:title><dc:language>zh</dc:language>
                </metadata>
                <manifest><item id="chapter-1" href="chapter.xhtml"
                media-type="application/xhtml+xml" /></manifest>
                <spine><itemref idref="chapter-1" /></spine>
                </package>""",
            )
            archive.writestr(
                "OEBPS/chapter.xhtml",
                """<html xmlns="http://www.w3.org/1999/xhtml"><body>
                <h1>第一章</h1><p>正文</p></body></html>""",
            )
        return output.getvalue()

    @staticmethod
    def _mobi_bytes() -> bytes:
        first_record_offset = 88
        payload = bytearray(first_record_offset + 16 + 116)
        payload[60:68] = b"BOOKMOBI"
        payload[76:78] = (1).to_bytes(2, "big")
        payload[78:82] = first_record_offset.to_bytes(4, "big")
        payload[first_record_offset : first_record_offset + 2] = (1).to_bytes(2, "big")
        payload[first_record_offset + 16 : first_record_offset + 20] = b"MOBI"
        payload[first_record_offset + 20 : first_record_offset + 24] = (116).to_bytes(
            4,
            "big",
        )
        return bytes(payload)

    def test_executable_renamed_to_txt_is_rejected(self):
        payload = bytearray(132)
        payload[:2] = b"MZ"
        payload[60:64] = (128).to_bytes(4, "little")
        payload[128:132] = b"PE\x00\x00"

        with pytest.raises(ValueError, match="文件内容与扩展名不匹配"):
            parse_file(bytes(payload), "txt")

    @pytest.mark.parametrize(
        "payload",
        [
            b"\x7fELF" + b"A" * 64,
            b"\xcf\xfa\xed\xfe" + b"A" * 64,
            b"\xca\xfe\xba\xbe" + b"A" * 64,
        ],
    )
    def test_non_pe_executable_renamed_to_txt_is_rejected(self, payload: bytes):
        with pytest.raises(ValueError, match="文件内容与扩展名不匹配"):
            parse_file(payload, "txt")

    def test_html_requires_markup(self):
        with pytest.raises(ValueError, match="文件内容与扩展名不匹配"):
            parse_file(b"this is plain text, not html", "html")

    def test_html_fragment_remains_supported(self):
        payload = "<h1>第一章</h1><p>正文</p>".encode()

        chapters = parse_file(payload, "html")

        assert chapters == [{"title": "第一章", "content": "正文"}]

    def test_ordinary_zip_renamed_to_epub_is_rejected(self):
        payload = self._epub_bytes(mimetype=b"application/zip")

        with patch(
            "modules.imports.parsers.parse_epub",
            autospec=True,
            return_value=[{"title": "伪装内容", "content": "正文"}],
        ) as parser:
            with pytest.raises(ValueError, match="文件内容与扩展名不匹配"):
                parse_file(payload, "epub")

        parser.assert_not_called()

    def test_epub_signature_routes_to_existing_parser(self):
        payload = self._epub_bytes()
        expected = [{"title": "第一章", "content": "正文"}]

        with patch(
            "modules.imports.parsers.parse_epub",
            autospec=True,
            return_value=expected,
        ) as parser:
            assert parse_file(payload, "epub") == expected

        parser.assert_called_once_with(payload)

    def test_valid_minimal_epub_remains_supported(self):
        chapters = parse_file(self._epub_bytes(), "epub")

        assert chapters == [{"title": "第一章", "content": "第一章\n\n正文"}]

    def test_epub_malformed_container_is_rejected_before_parser(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr(
                "mimetype",
                b"application/epub+zip",
                compress_type=zipfile.ZIP_STORED,
            )
            archive.writestr("META-INF/container.xml", b"<container>")

        with patch("modules.imports.parsers.parse_epub", autospec=True) as parser:
            with pytest.raises(ValueError, match="文件内容与扩展名不匹配"):
                parse_file(output.getvalue(), "epub")

        parser.assert_not_called()

    def test_epub_unsafe_member_path_is_rejected_before_parser(self):
        payload = self._epub_bytes()
        source = io.BytesIO(payload)
        output = io.BytesIO()
        with zipfile.ZipFile(source) as original, zipfile.ZipFile(output, "w") as archive:
            for member in original.infolist():
                archive.writestr(member, original.read(member))
            archive.writestr("../outside.xhtml", "<p>escape</p>")

        with patch("modules.imports.parsers.parse_epub", autospec=True) as parser:
            with pytest.raises(ValueError, match="文件内容与扩展名不匹配"):
                parse_file(output.getvalue(), "epub")

        parser.assert_not_called()

    @pytest.mark.parametrize("file_type", ["mobi", "azw3"])
    def test_mobi_family_requires_bookmobi_signature(self, file_type: str):
        with patch(
            "modules.imports.parsers.parse_mobi",
            autospec=True,
            return_value=[{"title": "伪装内容", "content": "正文"}],
        ) as parser:
            with pytest.raises(ValueError, match="文件内容与扩展名不匹配"):
                parse_file(b"not-a-palm-database", file_type)

        parser.assert_not_called()

    def test_mobi_marker_without_valid_record_table_is_rejected(self):
        payload = bytearray(78)
        payload[60:68] = b"BOOKMOBI"

        with patch("modules.imports.parsers.parse_mobi", autospec=True) as parser:
            with pytest.raises(ValueError, match="文件内容与扩展名不匹配"):
                parse_file(bytes(payload), "mobi")

        parser.assert_not_called()

    @pytest.mark.parametrize("file_type", ["mobi", "azw3"])
    def test_mobi_family_signature_routes_to_existing_parser(self, file_type: str):
        payload = self._mobi_bytes()
        expected = [{"title": "第一章", "content": "正文"}]

        with patch(
            "modules.imports.parsers.parse_mobi",
            autospec=True,
            return_value=expected,
        ) as parser:
            assert parse_file(payload, file_type) == expected

        parser.assert_called_once_with(payload)

    def test_utf16_txt_remains_supported(self):
        payload = "第一章\n这是正文\n".encode("utf-16")

        chapters = parse_file(payload, "txt")

        assert chapters == [{"title": "第一章", "content": "这是正文"}]


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
        """GBK 等常见中文编码的文本应被正确检测并解码"""
        raw = "第一章\n这是第一章的内容\n".encode("gbk")
        chapters = parse_txt(raw)
        assert len(chapters) >= 1
        assert isinstance(chapters[0]["content"], str)
        assert "第一章" in chapters[0]["title"]

    def test_unrecoverable_encoding_records_failed(self):
        """无法正确解码的文本应视为编码失败"""
        # chardet 识别为 UTF-8-SIG，但末尾是截断的多字节序列
        raw = b"\xef\xbb\xbf" + "第一章".encode() + b"\xe4\xb8"
        with pytest.raises(ValueError, match="编码"):
            parse_txt(raw)


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
        imports_test_project_id: str,
    ):
        """测试创建导入记录"""
        nid = uuid.UUID(hex=imports_test_project_id)
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
        imports_test_project_id: str,
    ):
        """测试更新状态"""
        nid = uuid.UUID(hex=imports_test_project_id)
        record = await repo.create(db_session, nid, "test.txt", "txt", 512)

        updated = await repo.update_status(
            db_session,
            record.id,
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
        imports_test_project_id: str,
    ):
        """测试按项目查询"""
        nid = uuid.UUID(hex=imports_test_project_id)
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
    async def test_import_service_has_no_direct_http_exception_dependency(self):
        source = Path(__file__).resolve().parents[1].joinpath("services.py").read_text()

        assert "from fastapi import HTTPException" not in source
        assert "raise HTTPException" not in source

    @pytest.mark.asyncio
    async def test_upload_and_import(
        self,
        service,
        db_session: AsyncSession,
        imports_test_project_id: str,
        sample_txt_content: bytes,
    ):
        """测试完整导入流程"""
        resp = await service.upload_and_import(
            db_session,
            imports_test_project_id,
            "novel.txt",
            sample_txt_content,
        )
        assert resp.status == "done"
        assert resp.total_chapters == 4
        assert resp.imported_chapters == 4
        assert resp.file_name == "novel.txt"
        assert resp.file_type == "txt"
        assert len(resp.chapters) == 4
        assert [chapter.chapter_index for chapter in resp.chapters] == [1, 2, 3, 4]
        assert resp.chapters[0].title == "序章"
        assert resp.chapters[0].draft_id
        assert resp.chapters[0].word_count > 0
        from modules.writing.models import WritingDraft

        result = await db_session.execute(
            select(WritingDraft).where(
                WritingDraft.id == uuid.UUID(resp.chapters[0].draft_id)
            )
        )
        assert result.scalar_one().status == "published"

    @pytest.mark.asyncio
    async def test_upload_and_import_enqueues_publish_tasks_only(
        self,
        service,
        db_session: AsyncSession,
        imports_test_project_id: str,
        sample_txt_content: bytes,
    ):
        """导入章节后只排发布任务，由发布任务统一负责 RAG 索引。"""
        resp = await service.upload_and_import(
            db_session,
            imports_test_project_id,
            "novel.txt",
            sample_txt_content,
        )

        result = await db_session.execute(
            select(AsyncTask).where(AsyncTask.task_type == "publish_chapter")
        )
        tasks = list(result.scalars().all())

        assert len(tasks) == resp.imported_chapters
        assert {task.meta["chapter_index"] for task in tasks} == {1, 2, 3, 4}
        assert all(task.meta["novel_id"] == imports_test_project_id for task in tasks)

        rag_result = await db_session.execute(
            select(AsyncTask).where(AsyncTask.task_type == "rag_index_chapter")
        )
        assert list(rag_result.scalars().all()) == []

    @pytest.mark.asyncio
    async def test_upload_unsupported_type(
        self,
        service,
        db_session: AsyncSession,
        imports_test_project_id: str,
    ):
        """测试不支持的文件类型"""
        with pytest.raises(DomainValidationError) as exc:
            await service.upload_and_import(
                db_session,
                imports_test_project_id,
                "test.pdf",
                b"content",
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_list_records(
        self,
        service,
        db_session: AsyncSession,
        imports_test_project_id: str,
        sample_txt_content: bytes,
    ):
        """测试导入记录列表"""
        await service.upload_and_import(
            db_session, imports_test_project_id, "a.txt", sample_txt_content
        )
        await service.upload_and_import(
            db_session, imports_test_project_id, "b.txt", sample_txt_content
        )

        result = await service.list_import_records(db_session, imports_test_project_id)
        assert result.total >= 2

    @pytest.mark.asyncio
    async def test_get_record(
        self,
        service,
        db_session: AsyncSession,
        imports_test_project_id: str,
        sample_txt_content: bytes,
    ):
        """测试获取单条记录"""
        resp = await service.upload_and_import(
            db_session,
            imports_test_project_id,
            "novel.txt",
            sample_txt_content,
        )
        fetched = await service.get_import_record(
            db_session, imports_test_project_id, resp.id
        )
        assert fetched.id == resp.id
        assert fetched.file_name == "novel.txt"

    @pytest.mark.asyncio
    async def test_upload_oversized_file(
        self,
        service,
        db_session: AsyncSession,
        imports_test_project_id: str,
    ):
        """超过 50MB 的文件应返回 413"""
        large_data = b"x" * (MAX_FILE_SIZE + 1)
        with pytest.raises(DomainValidationError) as exc:
            await service.upload_and_import(
                db_session,
                imports_test_project_id,
                "large.txt",
                large_data,
            )
        assert exc.value.status_code == 413

    @pytest.mark.asyncio
    async def test_upload_empty_file_records_failed_status(
        self,
        service,
        db_session: AsyncSession,
        imports_test_project_id: str,
        monkeypatch,
    ):
        """空文件应记录 failed，不创建正文草稿"""
        commit_spy = AsyncMock()
        monkeypatch.setattr(db_session, "commit", commit_spy)

        with pytest.raises(DomainValidationError) as exc:
            await service.upload_and_import(
                db_session,
                imports_test_project_id,
                "empty.txt",
                b"",
            )

        assert exc.value.status_code == 400
        assert "文件中未检测到有效章节" in str(exc.value.detail)

        records = await service.list_import_records(db_session, imports_test_project_id)
        assert records.total == 1
        assert records.items[0].status == "failed"
        assert records.items[0].error_message == "文件中未检测到有效章节"

        from modules.writing.models import WritingDraft

        result = await db_session.execute(
            select(WritingDraft).where(
                WritingDraft.novel_id == uuid.UUID(imports_test_project_id)
            )
        )
        assert list(result.scalars().all()) == []
        commit_spy.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_record_novel_id_isolation(
        self,
        service,
        db_session: AsyncSession,
        imports_test_project_id: str,
        sample_txt_content: bytes,
    ):
        """跨 novel_id 访问导入记录应返回 404"""
        resp = await service.upload_and_import(
            db_session,
            imports_test_project_id,
            "novel.txt",
            sample_txt_content,
        )
        other_novel_id = str(uuid.uuid4())
        with pytest.raises(NotFoundError) as exc:
            await service.get_import_record(
                db_session,
                other_novel_id,
                resp.id,
            )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_upload_records_failed_status(
        self,
        service,
        db_session: AsyncSession,
        imports_test_project_id: str,
        sample_txt_content: bytes,
        repo: ImportRecordRepository,
    ):
        """解析失败时记录状态应标记为 failed 并附带错误信息"""
        with patch(
            "modules.imports.services.parse_file",
            side_effect=ValueError("mock parse error"),
        ):
            with pytest.raises(DomainValidationError) as exc:
                await service.upload_and_import(
                    db_session,
                    imports_test_project_id,
                    "fail.txt",
                    sample_txt_content,
                )
            assert exc.value.status_code == 422

        nid = uuid.UUID(hex=imports_test_project_id)
        items, total = await repo.get_by_novel(db_session, nid)
        assert total == 1
        record = items[0]
        assert record.status == "failed"
        assert "mock parse error" in record.error_message

    @pytest.mark.asyncio
    async def test_list_records_pagination(
        self,
        service,
        db_session: AsyncSession,
        imports_test_project_id: str,
        sample_txt_content: bytes,
    ):
        """测试导入记录列表 skip/limit 分页"""
        await service.upload_and_import(
            db_session,
            imports_test_project_id,
            "a.txt",
            sample_txt_content,
        )
        await service.upload_and_import(
            db_session,
            imports_test_project_id,
            "b.txt",
            sample_txt_content,
        )
        await service.upload_and_import(
            db_session,
            imports_test_project_id,
            "c.txt",
            sample_txt_content,
        )

        page1 = await service.list_import_records(
            db_session,
            imports_test_project_id,
            skip=0,
            limit=2,
        )
        assert page1.total == 3
        assert len(page1.items) == 2

        page2 = await service.list_import_records(
            db_session,
            imports_test_project_id,
            skip=2,
            limit=2,
        )
        assert page2.total == 3
        assert len(page2.items) == 1

    @pytest.mark.asyncio
    async def test_upload_failure_does_not_mask_error_when_update_status_fails(
        self,
        service: ImportService,
        db_session: AsyncSession,
        imports_test_project_id: str,
        sample_txt_content: bytes,
        monkeypatch,
    ):
        """update_status 也失败时，仍应抛业务领域错误而非二次异常。"""

        async def _broken_update_status(*args, **kwargs):
            raise RuntimeError("transaction aborted")

        monkeypatch.setattr(service._repo, "update_status", _broken_update_status)

        with patch(
            "modules.imports.services.create_published_draft_only",
            side_effect=RuntimeError("draft write failed"),
        ):
            with pytest.raises(DomainError) as exc:
                await service.upload_and_import(
                    db_session,
                    imports_test_project_id,
                    "fail.txt",
                    sample_txt_content,
                )
        assert exc.value.status_code == 500
        assert "导入过程中发生服务器错误" in exc.value.detail

    @pytest.mark.asyncio
    async def test_concurrent_duplicate_done_rolls_back_outer_transaction(
        self,
        service: ImportService,
        db_session: AsyncSession,
        imports_test_project_id: str,
        sample_txt_content: bytes,
        monkeypatch,
    ):
        """done 状态唯一约束冲突时必须回滚外层事务，避免 draft/task 残留。"""
        original_update_status = service._repo.update_status
        rollback_spy = AsyncMock()

        async def update_status_with_done_conflict(db, record_id, **kwargs):
            if kwargs.get("status") == "done":
                raise IntegrityError("update imports", {}, Exception("unique"))
            return await original_update_status(db, record_id, **kwargs)

        monkeypatch.setattr(
            service._repo,
            "update_status",
            update_status_with_done_conflict,
        )
        monkeypatch.setattr(db_session, "rollback", rollback_spy)

        with pytest.raises(DomainValidationError) as exc:
            await service.upload_and_import(
                db_session,
                imports_test_project_id,
                "race.txt",
                sample_txt_content,
            )

        assert exc.value.status_code == 400
        assert "文件已导入" in exc.value.detail
        rollback_spy.assert_awaited_once()
