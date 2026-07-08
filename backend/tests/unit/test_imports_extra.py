"""
Import 模组补充单元测试

覆盖模块内尚未被 test_imports.py / test_workflow.py 覆盖的文件与分支：

  parsers.py:       detect_encoding, _looks_like_chapter, split_chapters 英文/数字模式,
                    parse_html, parse_file azw3 别名
  schemas.py:       Pydantic 模型构建与默认值
  services.py:      _validate_file 各种场景, _get_extension 边界, _record_to_response,
                    upload_and_import 零章节 / ValueError / Exception 异常路径
  api.py:           API 端点 (upload / list / get / deep / resume)
  facade.py:        deep import 重复确认、force 入队、恢复 / 放弃兼容语义
  repositories.py:  update_status 不存在的记录
  tasks.py:         任务处理器 (handle_deep_import / stage handlers)

注意:
  - parse_epub / parse_mobi 需要真实的 epub/mobi 文件依赖 (ebooklib / mobi)，
    通过 mock 外部库测试意义有限，已在实文件 E2E (test_real_file_import.py) 覆盖。
  - parse_html 使用 BeautifulSoup，纯逻辑可测。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import DomainError
from core.errors import ValidationError as DomainValidationError
from infrastructure.tasks.models import AsyncTask
from modules.imports.contracts import TaskNotFoundError
from modules.imports.facade import (
    abandon_deep_import,
    resume_deep_import,
    start_deep_import,
)
from modules.imports.parsers import (
    ENCODING_DETECT_SAMPLE_SIZE,
    _looks_like_chapter,
    detect_encoding,
    parse_file,
    parse_html,
    parse_txt,
    split_chapters,
)
from modules.imports.repositories import ImportRecordRepository
from modules.imports.schemas import (
    ImportChapterItem,
    ImportedChapterListResponse,
    ImportedChapterResponse,
    ImportListResponse,
    ImportResponse,
)
from modules.imports.services import ImportService, _get_extension, _record_to_response

# 只在需要 DB session 或异步 fixture 的类上加 pytest.mark.asyncio，
# 纯函数测试不加，避免 pytest-asyncio deprecation warning。


async def _create_recoverable_deep_import_task(
    db_session: AsyncSession,
    *,
    task_type: str = "deep_import",
    status: str = "running",
    meta: dict | None = None,
    result: dict | None = None,
) -> AsyncTask:
    """Create a recoverable deep_import task for facade compatibility tests."""
    recovery_flags = {
        "interrupted": True,
        "recoverable": True,
        "recovery_required": True,
    }
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type=task_type,
        status=status,
        meta=(
            meta
            if meta is not None
            else {"novel_id": str(uuid.uuid4()), **recovery_flags}
        ),
        result=result if result is not None else dict(recovery_flags),
    )
    db_session.add(task)
    await db_session.flush()
    return task

# ====================================================================
# parsers.py — 补充测试
# ====================================================================


class TestDetectEncoding:
    """detect_encoding 边界条件"""

    def test_utf8_content(self):
        """UTF-8 编码应被正确识别"""
        data = "你好世界 Hello".encode()
        enc = detect_encoding(data)
        assert isinstance(enc, str)
        assert len(enc) > 0

    def test_ascii_content(self):
        """纯 ASCII 内容应返回有效编码"""
        data = b"Hello World, this is pure ASCII text."
        enc = detect_encoding(data)
        assert isinstance(enc, str)
        assert len(enc) > 0

    def test_empty_content_falls_back_to_utf8(self):
        """空字节序列应回退到 utf-8"""
        data = b""
        enc = detect_encoding(data)
        assert enc == "utf-8"

    def test_uses_only_encoding_detect_sample(self):
        """只把前 ENCODING_DETECT_SAMPLE_SIZE 字节传给 chardet"""
        data = b"A" * ENCODING_DETECT_SAMPLE_SIZE + b"B" * 500
        with patch("modules.imports.parsers.chardet.detect") as mock_detect:
            mock_detect.return_value = {"encoding": "ascii", "confidence": 1.0}
            enc = detect_encoding(data)

        mock_detect.assert_called_once_with(data[:ENCODING_DETECT_SAMPLE_SIZE])
        assert enc == "ascii"

    def test_low_confidence_falls_back_to_utf8(self):
        """chardet 低置信结果应回退到 utf-8"""
        data = "第一章\n内容".encode("gbk")
        with patch("modules.imports.parsers.chardet.detect") as mock_detect:
            mock_detect.return_value = {"encoding": "GB2312", "confidence": 0.69}
            enc = detect_encoding(data)

        assert enc == "utf-8"

    def test_missing_encoding_falls_back_to_utf8(self):
        """chardet 缺失 encoding 时应回退到 utf-8"""
        data = b"\x80\x81\x82"
        with patch("modules.imports.parsers.chardet.detect") as mock_detect:
            mock_detect.return_value = {"encoding": None, "confidence": 0.99}
            enc = detect_encoding(data)

        assert enc == "utf-8"

    def test_large_input_returns_valid_encoding(self):
        """大输入应返回有效编码"""
        data = b"A" * (ENCODING_DETECT_SAMPLE_SIZE + 500)
        enc = detect_encoding(data)
        assert isinstance(enc, str)

    def test_gbk_content(self):
        """GBK 编码应被识别（不为空字符串）"""
        data = "你好世界".encode("gbk")
        enc = detect_encoding(data)
        assert isinstance(enc, str)
        assert len(enc) > 0


class TestLooksLikeChapter:
    """_looks_like_chapter 判定逻辑"""

    @pytest.mark.parametrize(
        "text",
        [
            "第一章",
            "第2节",
            "第三回",
            "楔子",
            "序章",
            "序言",
            "卷 一",
            "卷1",
            "Chapter 1",
            "Ch 2",
            "CHAPTER THREE",
            "ch 4",
            "Prologue",
            "PREFACE",
            "preface",
            "话 一",
            "第一话",
        ],
    )
    def test_returns_true_for_chapter_like_text(self, text: str):
        """含章节关键词的文本应返回 True"""
        assert _looks_like_chapter(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "正文开始",
            "结尾",
            "后记",
            "附录",
            "索引",
            "鸣谢",
            "说明",
            "Title",
            "Introduction",
            "Summary",
            "Notes",
            "References",
        ],
    )
    def test_returns_false_for_ordinary_text(self, text: str):
        """不含章节关键词的文本应返回 False"""
        assert _looks_like_chapter(text) is False

    def test_empty_string_returns_false(self):
        """空字符串应返回 False"""
        assert _looks_like_chapter("") is False


class TestSplitChaptersMore:
    """split_chapters 更多边界"""

    def test_english_chapter_pattern(self):
        """英文 Chapter / Ch 模式应被识别"""
        text = (
            "Chapter 1\n"
            "The beginning of the story.\n\n"
            "Chapter 2\n"
            "The middle part.\n\n"
            "Ch 3\n"
            "The end.\n"
        )
        chapters = split_chapters(text)
        assert len(chapters) == 3
        assert chapters[0]["title"] == "Chapter 1"
        assert chapters[1]["title"] == "Chapter 2"
        assert chapters[2]["title"] == "Ch 3"

    def test_english_prologue_preface_introduction(self):
        """Prologue / Preface / Introduction 应被识别为章节（因模式 3 匹配数最多）"""
        text = (
            "Prologue\n"
            "The setup.\n\n"
            "Preface\n"
            "Author's note.\n\n"
            "Introduction\n"
            "Context.\n\n"
            "Chapter 1\n"
            "Real start.\n"
        )
        chapters = split_chapters(text)
        # Pattern 3 (Prologue|Preface|Introduction) wins with 3 matches
        # vs Pattern 2 (Chapter/Ch) with 1 match → Chapter 1 被 Introduction 吸收
        assert len(chapters) == 3
        assert chapters[0]["title"] == "Prologue"
        assert chapters[1]["title"] == "Preface"
        assert chapters[2]["title"] == "Introduction"

    def test_numbered_pattern_with_dot(self):
        """数字加点模式 '1. Title' 应被识别"""
        text = "1. 相遇\n他们在街头相遇。\n\n2. 相知\n慢慢了解彼此。\n"
        chapters = split_chapters(text)
        assert len(chapters) == 2

    def test_chinese_volume_pattern(self):
        """卷模式应被识别"""
        text = "卷一 春\n春天的故事。\n\n卷二 夏\n夏天的故事。\n"
        chapters = split_chapters(text)
        assert len(chapters) == 2
        assert chapters[0]["title"] == "卷一 春"

    def test_empty_text(self):
        """空字符串应返回空章节列表"""
        chapters = split_chapters("")
        assert chapters == []

    def test_whitespace_only_text(self):
        """空白文本应返回空章节列表"""
        chapters = split_chapters("   \n\n  \t  ")
        assert chapters == []

    def test_single_chapter_no_pattern(self):
        """无分章模式的长文本应返回单章"""
        text = "这是一段很长的连续文本，没有分章信号。"
        chapters = split_chapters(text)
        assert len(chapters) == 1
        assert chapters[0]["title"] == "全文"

    def test_chapter_with_no_content_after_title(self):
        """连续两个章节标记之间无内容时，前一个章节的 content 应为空"""
        text = "第一章\n\n第二章\n内容"
        chapters = split_chapters(text)
        assert len(chapters) == 2
        # 第一章和第二章紧挨着，第一章 content 为空
        assert chapters[0]["title"] == "第一章"
        assert chapters[0]["content"] == ""
        assert chapters[1]["title"] == "第二章"

    def test_best_pattern_selected_by_match_count(self):
        """选择匹配最多的分章模式"""
        text = "第一章 开始\n内容\n1. 片段\n内容\n第二章 中段\n内容\n"
        # 中文 CHAPTER_PATTERNS 匹配 "第一章", "第二章" 共 2 个
        # 数字模式匹配 "1." 但只有 1 个
        # 所以应选中文模式
        chapters = split_chapters(text)
        assert len(chapters) == 2
        assert chapters[0]["title"] == "第一章 开始"


class TestParseTextMore:
    """parse_txt 补充边界"""

    def test_large_content_no_crash(self):
        """处理较大内容不应崩溃"""
        content = ("第一章\n" + "A" * 10_000 + "\n\n第二章\n" + "B" * 10_000).encode()
        chapters = parse_txt(content)
        assert len(chapters) == 2

    def test_mixed_encoding_bytes(self):
        """含非法 UTF-8 序列应抛出 ValueError"""
        raw = b"\xff\xfe\x00\xe4\xbd\xa0\xe5\xa5\xbd"
        with pytest.raises(ValueError, match="文本编码无法正确解析"):
            parse_txt(raw)

    def test_content_only_bom(self):
        """纯 BOM 头部内容应返回空章节列表"""
        data = b"\xef\xbb\xbf"
        chapters = parse_txt(data)
        assert chapters == []


class TestParseHtml:
    """parse_html 解析逻辑"""

    def test_with_chapter_headings(self):
        """含章节标题的 HTML 应按标题分割"""
        html = (
            "<html><body>"
            "<h1>第一章 开始</h1><p>正文开始。</p>"
            "<h1>第二章 发展</h1><p>故事发展。</p>"
            "</body></html>"
        )
        chapters = parse_html(html.encode())
        assert len(chapters) == 2
        assert "正文开始" in chapters[0]["content"]

    def test_without_chapter_headings_fallback_to_txt(self):
        """不含章节标题的 HTML 应降级为纯文本分章"""
        html = "<html><body><p>一段连续的正文。</p><p>没有章节标题。</p></body></html>"
        chapters = parse_html(html.encode())
        assert len(chapters) == 1
        assert chapters[0]["title"] == "全文"

    def test_strips_script_style_tags(self):
        """应剔除 script 和 style 标签内容"""
        html = (
            "<html><body>"
            "<h1>第一章</h1><p>正文</p>"
            "<script>alert('xss')</script>"
            "<style>.hidden{display:none}</style>"
            "</body></html>"
        )
        chapters = parse_html(html.encode())
        assert len(chapters) == 1
        assert "alert" not in chapters[0]["content"]
        assert "hidden" not in chapters[0]["content"]

    def test_headings_that_dont_look_like_chapters(self):
        """标题不含章节关键词时降级为纯文本分章"""
        html = (
            "<html><body>"
            "<h1>About</h1><p>关于本书。</p>"
            "<h1>Summary</h1><p>内容摘要。</p>"
            "</body></html>"
        )
        chapters = parse_html(html.encode())
        # "About" 和 "Summary" 不包含章节关键词，走降级
        assert len(chapters) == 1
        assert chapters[0]["title"] == "全文"

    def test_mixed_chapter_and_non_chapter_headings(self):
        """混合章节/非章节标题：只按章节标题分割"""
        html = (
            "<html><body>"
            "<h1>第一章 剧情</h1><p>剧情开始。</p>"
            "<h1>人物介绍</h1><p>人物列表。</p>"
            "<h1>第二章 结尾</h1><p>故事结束。</p>"
            "</body></html>"
        )
        chapters = parse_html(html.encode())
        # 只有 "第一章 剧情" 和 "第二章 结尾" 被识别为章节标题
        assert len(chapters) == 2


class TestParseFileMore:
    """parse_file 统一入口补充"""

    def test_azw3_routes_to_mobi_parser(self):
        """azw3 文件类型应路由到 parse_mobi"""
        with patch("modules.imports.parsers.parse_mobi") as mock_mobi:
            mock_mobi.return_value = [{"title": "azw3 chapter", "content": "content"}]
            result = parse_file(b"fake-azw3-data", "azw3")
            assert len(result) == 1
            mock_mobi.assert_called_once_with(b"fake-azw3-data")

    def test_htm_routes_to_html_parser(self):
        """htm 文件类型应路由到 parse_html"""
        with patch("modules.imports.parsers.parse_html") as mock_html:
            mock_html.return_value = [{"title": "htm chapter", "content": "content"}]
            result = parse_file(b"fake-htm-data", "htm")
            assert len(result) == 1
            mock_html.assert_called_once_with(b"fake-htm-data")

    def test_unsupported_type_raises(self):
        """不支持的文件类型应抛出 ValueError"""
        with pytest.raises(ValueError, match="不支持的文件类型"):
            parse_file(b"data", "pdf")

    def test_unsupported_type_case_sensitive(self):
        """类型名称区分大小写"""
        with pytest.raises(ValueError, match="不支持的文件类型"):
            parse_file(b"data", "TXT")


# ====================================================================
# schemas.py — Pydantic 模型
# ====================================================================


class TestImportSchemas:
    """Pydantic schema 构建与默认值"""

    def test_import_response_defaults(self):
        """ImportResponse 字段默认值"""
        resp = ImportResponse(
            id="rec-1",
            novel_id="proj-1",
            file_name="test.txt",
            file_type="txt",
            status="done",
        )
        assert resp.file_size == 0
        assert resp.total_chapters == 0
        assert resp.imported_chapters == 0
        assert resp.error_message is None
        assert resp.created_at is None

    def test_import_response_with_all_fields(self):
        """ImportResponse 所有字段填充"""
        from datetime import datetime

        resp = ImportResponse(
            id="rec-1",
            novel_id="proj-1",
            file_name="test.txt",
            file_type="txt",
            file_size=1024,
            total_chapters=5,
            imported_chapters=5,
            status="done",
            error_message=None,
            created_at=datetime(2024, 1, 1, 12, 0, 0),
        )
        assert resp.file_size == 1024
        assert resp.total_chapters == 5

    def test_import_list_response(self):
        """ImportListResponse 包含 items 和 total"""
        items = [
            ImportResponse(
                id="1",
                novel_id="n1",
                file_name="a.txt",
                file_type="txt",
                status="done",
            ),
        ]
        resp = ImportListResponse(items=items, total=1)
        assert resp.total == 1
        assert len(resp.items) == 1

    def test_import_list_response_empty(self):
        """空列表的 ImportListResponse"""
        resp = ImportListResponse(items=[], total=0)
        assert resp.total == 0
        assert resp.items == []

    def test_import_chapter_item_defaults(self):
        """ImportChapterItem 字段"""
        item = ImportChapterItem(chapter_index=1, draft_id="draft-1")
        assert item.title is None
        assert item.word_count == 0

    def test_imported_chapter_response_defaults(self):
        """ImportedChapterResponse 默认值"""
        resp = ImportedChapterResponse(
            id="c1",
            novel_id="n1",
            import_record_id="r1",
            chapter_index=1,
            title="第一章",
            content="正文",
        )
        assert resp.is_analyzed is False
        assert resp.created_at is None

    def test_imported_chapter_list_response(self):
        """ImportedChapterListResponse 包含 items 和 total"""
        items = [
            ImportedChapterResponse(
                id="c1",
                novel_id="n1",
                import_record_id="r1",
                chapter_index=1,
                title="第一章",
                content="正文",
            ),
        ]
        resp = ImportedChapterListResponse(items=items, total=1)
        assert resp.total == 1

    def test_import_response_model_dump_roundtrip(self):
        """ImportResponse JSON 序列化/反序列化"""
        from datetime import UTC, datetime

        orig = ImportResponse(
            id="rec-1",
            novel_id="proj-1",
            file_name="test.txt",
            file_type="txt",
            file_size=1024,
            total_chapters=5,
            imported_chapters=5,
            status="done",
            error_message=None,
            created_at=datetime(2024, 6, 1, 10, 30, 0, tzinfo=UTC),
        )
        raw = orig.model_dump(mode="json")
        restored = ImportResponse(**raw)
        assert restored.id == orig.id
        assert restored.file_name == orig.file_name


# ====================================================================
# services.py — 补充业务逻辑测试
# ====================================================================


class TestImportServiceHelpers:
    """_validate_file / _get_extension / _record_to_response 纯函数"""

    def setup_method(self):
        self.service = ImportService()

    @pytest.mark.parametrize(
        ("file_name", "expected_type"),
        [
            ("test.txt", "txt"),
            ("book.epub", "epub"),
            ("document.HTML", "html"),
            ("page.htm", "htm"),
            ("novel.mobi", "mobi"),
            ("archive.azw3", "azw3"),
            ("/path/to/file.txt", "txt"),
        ],
    )
    def test_validate_file_valid_types(self, file_name: str, expected_type: str):
        """白名单内文件类型应返回除去点号后的类型"""
        result = self.service._validate_file(file_name, 1000)
        assert result == expected_type

    @pytest.mark.parametrize(
        "file_name",
        ["test.pdf", "book.docx", "file.unknown", "image.png", ""],
    )
    def test_validate_file_unsupported_types(self, file_name: str):
        """白名单外文件类型应抛出 400"""
        with pytest.raises(DomainValidationError) as exc:
            self.service._validate_file(file_name, 1000)
        assert exc.value.status_code == 400
        assert "不支持的文件类型" in exc.value.detail

    def test_validate_file_oversized_raises_413(self):
        """超过 50MB 的文件应抛出 413"""
        oversized = 51 * 1024 * 1024
        with pytest.raises(DomainValidationError) as exc:
            self.service._validate_file("test.txt", oversized)
        assert exc.value.status_code == 413
        assert "文件过大" in exc.value.detail

    def test_validate_file_boundary_size(self):
        """恰好 50MB 的文件应通过校验"""
        max_allowed = 50 * 1024 * 1024
        result = self.service._validate_file("test.txt", max_allowed)
        assert result == "txt"

    def test_validate_file_path_traversal(self):
        """包含路径穿越的文件名应安全提取扩展名"""
        result = self.service._validate_file("../../../etc/passwd.txt", 1000)
        assert result == "txt"

    @pytest.mark.parametrize(
        ("file_name", "expected"),
        [
            ("test.txt", ".txt"),
            ("", ""),
            ("noext", ""),
            (".hidden", ""),  # splitext('.hidden') → ('.hidden', '')
            ("archive.tar.gz", ".gz"),
            ("/absolute/path/file.doc", ".doc"),
        ],
    )
    def test_get_extension_various(self, file_name: str, expected: str):
        """_get_extension 边界条件"""
        assert _get_extension(file_name) == expected

    def test_record_to_response_maps_correctly(self):
        """_record_to_response 将 ORM 模型映射为 Pydantic response"""
        from modules.imports.models import ImportRecord

        record = MagicMock(spec=ImportRecord)
        rid = uuid.uuid4()
        nid = uuid.uuid4()
        record.id = rid
        record.novel_id = nid
        record.file_name = "test.txt"
        record.file_type = "txt"
        record.file_size = 2048
        record.total_chapters = 10
        record.imported_chapters = 8
        record.status = "done"
        record.error_message = None
        record.created_at = None

        resp = _record_to_response(record)
        assert resp.id == str(rid)
        assert resp.novel_id == str(nid)
        assert resp.file_name == "test.txt"
        assert resp.file_type == "txt"
        assert resp.file_size == 2048
        assert resp.total_chapters == 10
        assert resp.imported_chapters == 8
        assert resp.status == "done"
        assert resp.error_message is None

    def test_record_to_response_with_error_message(self):
        """_record_to_response 应保留错误信息"""
        from modules.imports.models import ImportRecord

        record = MagicMock(spec=ImportRecord)
        record.id = uuid.uuid4()
        record.novel_id = uuid.uuid4()
        record.file_name = "bad.txt"
        record.file_type = "txt"
        record.file_size = 0
        record.total_chapters = 0
        record.imported_chapters = 0
        record.status = "failed"
        record.error_message = "解析失败：文件损坏"
        record.created_at = None

        resp = _record_to_response(record)
        assert resp.status == "failed"
        assert resp.error_message == "解析失败：文件损坏"


class TestImportServiceErrors:
    """upload_and_import 异常路径（需 DB session）"""

    pytestmark = [pytest.mark.asyncio]

    @pytest.fixture
    def service(self) -> ImportService:
        return ImportService()

    @pytest.fixture
    def repo(self) -> ImportRecordRepository:
        return ImportRecordRepository()

    async def test_empty_chapters_raises_400(
        self,
        service: ImportService,
        db_session: AsyncSession,
        test_project_id: str,
    ):
        """解析出零章节应抛出 400"""
        with patch("modules.imports.services.parse_file", return_value=[]):
            with pytest.raises(DomainValidationError) as exc:
                await service.upload_and_import(
                    db_session,
                    test_project_id,
                    "empty.txt",
                    b"",
                )
        assert exc.value.status_code == 400
        assert "文件中未检测到有效章节" in exc.value.detail

    @pytest.mark.asyncio
    async def test_parse_value_error_raises_422(
        self,
        service: ImportService,
        db_session: AsyncSession,
        test_project_id: str,
    ):
        """parse_file 抛出 ValueError 应转为 422"""
        with patch(
            "modules.imports.services.parse_file",
            side_effect=ValueError("bad format"),
        ):
            with pytest.raises(DomainValidationError) as exc:
                await service.upload_and_import(
                    db_session,
                    test_project_id,
                    "bad.txt",
                    b"garbage",
                )
        assert exc.value.status_code == 422
        assert "bad format" in exc.value.detail

    @pytest.mark.asyncio
    async def test_generic_exception_raises_500(
        self,
        service: ImportService,
        db_session: AsyncSession,
        test_project_id: str,
    ):
        """parse_file 抛出未知异常应转为 500"""
        with patch(
            "modules.imports.services.parse_file",
            side_effect=RuntimeError("OOM"),
        ):
            with pytest.raises(DomainError) as exc:
                await service.upload_and_import(
                    db_session,
                    test_project_id,
                    "bad.txt",
                    b"garbage",
                )
        assert exc.value.status_code == 500
        assert "服务器错误" in exc.value.detail

    @pytest.mark.asyncio
    async def test_http_exception_is_re_raised(
        self,
        service: ImportService,
        db_session: AsyncSession,
        test_project_id: str,
    ):
        """从 _validate_file 抛出的领域错误应原样传递"""
        with patch.object(
            service,
            "_validate_file",
            side_effect=DomainValidationError("custom error"),
        ):
            with pytest.raises(DomainValidationError) as exc:
                await service.upload_and_import(
                    db_session,
                    test_project_id,
                    "bad",
                    b"data",
                )
        assert exc.value.status_code == 400
        assert "custom error" in exc.value.detail


# ====================================================================
# facade.py — deep import 兼容语义
# ====================================================================


class TestImportFacadeDeepImportCompatibility:
    """start/resume/abandon deep import facade compatibility."""

    pytestmark = [pytest.mark.asyncio]

    async def test_start_deep_import_duplicate_requires_confirmation_without_enqueue(
        self,
        db_session: AsyncSession,
    ):
        """重复导入默认只返回确认要求，不提前把 deep_import 任务入队。"""
        warning = "第 1-5 章已有数据。重新导入将覆盖现有数据。是否继续？"
        expected = {
            "workflow_id": None,
            "task_id": None,
            "status": "requires_confirmation",
            "requires_confirmation": True,
            "warning": warning,
            "message": warning,
        }
        novel_id = str(uuid.uuid4())

        with patch("modules.imports.facade._orchestrator") as mock_orchestrator:
            mock_orchestrator.start = AsyncMock(return_value=expected)

            result = await start_deep_import(
                db_session,
                novel_id=novel_id,
                start_chapter=1,
                end_chapter=5,
            )

        assert result == expected
        assert result["status"] == "requires_confirmation"
        assert result["requires_confirmation"] is True
        assert "覆盖现有数据" in result["warning"]
        assert result["task_id"] is None
        mock_orchestrator.start.assert_awaited_once_with(
            db_session,
            novel_id,
            1,
            5,
            force=False,
            high_quality=False,
        )

    async def test_start_deep_import_force_enqueues_after_duplicate_confirmation(
        self,
        db_session: AsyncSession,
    ):
        """用户确认覆盖后，force=True 才允许创建 deep_import 任务。"""
        task_id = str(uuid.uuid4())
        novel_id = str(uuid.uuid4())
        expected = {
            "workflow_id": task_id,
            "task_id": task_id,
            "status": "pending",
            "requires_confirmation": False,
            "message": "深度导入任务已提交（第1-5章）",
        }

        with patch("modules.imports.facade._orchestrator") as mock_orchestrator:
            mock_orchestrator.start = AsyncMock(return_value=expected)

            result = await start_deep_import(
                db_session,
                novel_id=novel_id,
                start_chapter=1,
                end_chapter=5,
                force=True,
            )

        assert result == expected
        assert result["task_id"] == task_id
        assert result["status"] == "pending"
        assert result["requires_confirmation"] is False
        assert "warning" not in result
        mock_orchestrator.start.assert_awaited_once_with(
            db_session,
            novel_id,
            1,
            5,
            force=True,
            high_quality=False,
        )

    async def test_resume_deep_import_with_valid_prev_task_reuses_original_task(
        self,
        db_session: AsyncSession,
    ):
        """恢复时复用原 deep_import 任务，不创建 resume 任务。"""
        prev_task = await _create_recoverable_deep_import_task(
            db_session,
            meta={
                "novel_id": str(uuid.uuid4()),
                "start_chapter": 1,
                "end_chapter": 5,
                "recovery_required": True,
                "recoverable": True,
                "interrupted": True,
            },
        )
        prev_task_id = str(prev_task.id)

        result = await resume_deep_import(db_session, prev_task_id)

        assert result["task_id"] == prev_task_id
        assert result["workflow_id"] == prev_task_id
        assert result["status"] == "pending"
        assert prev_task.status == "pending"
        assert prev_task.result["recovery_required"] is False
        assert prev_task.meta["recovery_required"] is False

    async def test_abandon_deep_import_with_valid_task_cancels_original_task(
        self,
        db_session: AsyncSession,
    ):
        """放弃恢复会取消原任务并返回 no-op 清理摘要。"""
        prev_task = await _create_recoverable_deep_import_task(db_session)
        prev_task_id = str(prev_task.id)

        result = await abandon_deep_import(db_session, prev_task_id)

        assert result["task_id"] == prev_task_id
        assert result["status"] == "cancelled"
        assert result["cleanup_summary"]["deprecated_scenes"] == 0
        assert result["cleanup_summary"]["hard_deleted_assets"] == 0
        assert prev_task.status == "cancelled"
        assert prev_task.finished_at is not None

    async def test_resume_deep_import_with_missing_prev_task_raises_404(
        self,
        db_session: AsyncSession,
    ):
        """prev_task_id 对应记录不存在时，应抛出 TaskNotFoundError。"""
        missing_id = str(uuid.uuid4())

        with pytest.raises(TaskNotFoundError) as excinfo:
            await resume_deep_import(db_session, missing_id)

        assert excinfo.value.task_id == missing_id

    async def test_resume_deep_import_with_invalid_uuid_raises_422(
        self,
        db_session: AsyncSession,
    ):
        """prev_task_id 不是有效 UUID 时，parse_uuid 应抛出领域 422。"""
        with pytest.raises(DomainValidationError) as excinfo:
            await resume_deep_import(db_session, "not-a-valid-uuid")

        assert excinfo.value.status_code == 422


# ====================================================================
# api.py — API 端点测试
# ====================================================================


class TestImportApi:
    """FastAPI 路由层验证"""

    pytestmark = [pytest.mark.asyncio]

    async def test_upload_returns_201(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """POST /api/imports/upload 正常上传返回 201"""
        mock_response = ImportResponse(
            id=str(uuid.uuid4()),
            novel_id=test_project_id,
            file_name="novel.txt",
            file_type="txt",
            file_size=100,
            total_chapters=3,
            imported_chapters=3,
            status="done",
        )
        with patch("modules.imports.api._service") as mock_svc:
            mock_svc.upload_and_import = AsyncMock(return_value=mock_response)

            resp = await async_client.post(
                "/api/imports/upload",
                data={"novel_id": test_project_id},
                files={"file": ("novel.txt", b"content", "text/plain")},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "done"
        assert data["file_name"] == "novel.txt"

    @pytest.mark.asyncio
    async def test_upload_missing_novel_id_returns_422(
        self,
        async_client: AsyncClient,
    ):
        """POST /api/imports/upload 缺 novel_id 应返回 422"""
        resp = await async_client.post(
            "/api/imports/upload",
            files={"file": ("novel.txt", b"content", "text/plain")},
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_list_imports_missing_novel_id_returns_422(
        self,
        async_client: AsyncClient,
    ):
        """GET /api/imports 缺 novel_id 应返回 422"""
        resp = await async_client.get("/api/imports")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_get_import_missing_novel_id_returns_422(
        self,
        async_client: AsyncClient,
    ):
        """GET /api/imports/{id} 缺 novel_id 应返回 422"""
        resp = await async_client.get(f"/api/imports/{uuid.uuid4()}")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_get_nonexistent_import_returns_404(
        self,
        async_client: AsyncClient,
        test_project_id: str,
    ):
        """GET /api/imports/{id} 不存在的记录应返回 404"""
        fake_id = uuid.uuid4()
        resp = await async_client.get(
            f"/api/imports/{fake_id}",
            params={"novel_id": test_project_id},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_deep_import_missing_novel_id_returns_422(
        self,
        async_client: AsyncClient,
    ):
        """POST /api/imports/deep 缺 novel_id 应返回 422"""
        resp = await async_client.post(
            "/api/imports/deep",
            json={},
        )
        assert resp.status_code == 422
        assert "novel_id" in resp.text

    @pytest.mark.asyncio
    async def test_deep_import_end_before_start_returns_422(
        self,
        async_client: AsyncClient,
    ):
        """POST /api/imports/deep end_chapter < start_chapter 应返回 422"""
        resp = await async_client.post(
            "/api/imports/deep",
            json={"novel_id": str(uuid.uuid4()), "start_chapter": 5, "end_chapter": 3},
        )
        assert resp.status_code == 422
        assert "end_chapter must be >= start_chapter" in resp.text

    @pytest.mark.asyncio
    async def test_resume_deep_missing_task_id_returns_400(
        self,
        async_client: AsyncClient,
    ):
        """POST /api/imports/deep/resume 缺 task_id 应返回 400"""
        resp = await async_client.post(
            "/api/imports/deep/resume",
            json={},
        )
        assert resp.status_code == 400
        assert "task_id" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_resume_deep_with_nonexistent_task_returns_404(
        self,
        async_client: AsyncClient,
    ):
        """POST /api/imports/deep/resume 不存在的 task_id 应返回 404"""
        fake_id = str(uuid.uuid4())
        resp = await async_client.post(
            "/api/imports/deep/resume",
            json={"task_id": fake_id},
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


# ====================================================================
# repositories.py — 补充数据访问
# ====================================================================


class TestImportRecordRepositoryMore:
    """ImportRecordRepository 补充覆盖"""

    pytestmark = [pytest.mark.asyncio]

    @pytest.fixture
    def repo(self) -> ImportRecordRepository:
        return ImportRecordRepository()

    async def test_update_status_nonexistent_returns_none(
        self,
        repo: ImportRecordRepository,
        db_session: AsyncSession,
    ):
        """update_status 不存在的记录应返回 None"""
        result = await repo.update_status(
            db_session,
            uuid.uuid4(),
            status="done",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_novel_empty(
        self,
        repo: ImportRecordRepository,
        db_session: AsyncSession,
    ):
        """get_by_novel 查询不存在的项目应返回空列表"""
        random_nid = uuid.uuid4()
        items, total = await repo.get_by_novel(db_session, random_nid)
        assert items == []
        assert total == 0


# ====================================================================
# tasks.py — 任务处理器
# ====================================================================


class TestImportTaskHandlers:
    """deep_import 及分阶段自动提取任务处理器"""

    pytestmark = [pytest.mark.asyncio]

    async def test_handle_deep_import_happy_path(self):
        """正常 deep_import 任务应调用 worklow 并返回进度"""
        from modules.imports.tasks import handle_deep_import

        task = MagicMock()
        task.meta = {
            "novel_id": str(uuid.uuid4()),
            "start_chapter": 1,
            "end_chapter": 5,
        }

        expected = {
            "phase": "done",
            "current_step": None,
            "completed_steps": [
                "scene_segmentation",
                "entity_extraction",
                "structure_analysis",
            ],
            "message": "深度导入完成",
            "degraded": False,
            "degraded_batches": [],
        }

        with patch("modules.imports.tasks.DeepImportOrchestrator") as mock_cls:
            mock_orchestrator = MagicMock()
            mock_orchestrator.run_task = AsyncMock(return_value=expected)
            mock_cls.return_value = mock_orchestrator

            db = MagicMock()
            result = await handle_deep_import(db, task)

        assert result == expected
        assert result["phase"] == "done"
        assert len(result["completed_steps"]) == 3
        mock_orchestrator.run_task.assert_awaited_once_with(db, task)

    @pytest.mark.asyncio
    async def test_handle_deep_import_missing_novel_id_raises(self):
        """novel_id 缺失时应抛出 ValueError"""
        from modules.imports.tasks import handle_deep_import

        task = MagicMock()
        task.meta = {"start_chapter": 1, "end_chapter": 5}

        db = MagicMock()
        with pytest.raises(ValueError, match="novel_id is required"):
            await handle_deep_import(db, task)

    @pytest.mark.asyncio
    async def test_handle_deep_import_none_meta_raises(self):
        """meta 为 None 时应抛出 ValueError"""
        from modules.imports.tasks import handle_deep_import

        task = MagicMock()
        task.meta = None

        db = MagicMock()
        with pytest.raises(ValueError, match="novel_id is required"):
            await handle_deep_import(db, task)

    @pytest.mark.asyncio
    async def test_handle_deep_import_empty_meta_raises(self):
        """meta 为空 dict 时应抛出 ValueError"""
        from modules.imports.tasks import handle_deep_import

        task = MagicMock()
        task.meta = {}

        db = MagicMock()
        with pytest.raises(ValueError, match="novel_id is required"):
            await handle_deep_import(db, task)

    @pytest.mark.asyncio
    async def test_handle_deep_import_delegates_missing_chapter_range_to_orchestrator(
        self,
    ):
        """章节范围缺省时，任务处理器仍应委托 orchestrator 统一处理。"""
        from modules.imports.tasks import handle_deep_import

        task = MagicMock()
        task.meta = {"novel_id": str(uuid.uuid4())}

        expected = {
            "phase": "done",
            "current_step": None,
            "completed_steps": [],
            "message": "",
            "degraded": False,
            "degraded_batches": [],
        }

        with patch("modules.imports.tasks.DeepImportOrchestrator") as mock_cls:
            mock_orchestrator = MagicMock()
            mock_orchestrator.run_task = AsyncMock(return_value=expected)
            mock_cls.return_value = mock_orchestrator

            db = MagicMock()
            result = await handle_deep_import(db, task)

        assert result == expected
        mock_orchestrator.run_task.assert_awaited_once_with(db, task)

    @pytest.mark.parametrize(
        ("handler_name", "stage"),
        [
            ("handle_scene_auto_extraction", "scenes"),
            ("handle_world_object_auto_extraction", "world_objects"),
            ("handle_plot_structure_auto_extraction", "plot_structure"),
        ],
    )
    @pytest.mark.asyncio
    async def test_stage_handlers_delegate_to_orchestrator(self, handler_name, stage):
        import modules.imports.tasks as tasks_module

        handler = getattr(tasks_module, handler_name)
        task = MagicMock()
        task.meta = {
            "novel_id": str(uuid.uuid4()),
            "start_chapter": 1,
            "end_chapter": 5,
        }
        expected = {
            "phase": "done",
            "current_step": None,
            "completed_steps": [],
            "message": "完成",
            "degraded": False,
            "degraded_batches": [],
        }

        with patch("modules.imports.tasks.DeepImportOrchestrator") as mock_cls:
            mock_orchestrator = MagicMock()
            mock_orchestrator.run_stage_task = AsyncMock(return_value=expected)
            mock_cls.return_value = mock_orchestrator

            db = MagicMock()
            result = await handler(db, task)

        assert result == expected
        mock_orchestrator.run_stage_task.assert_awaited_once_with(
            db,
            task,
            stage=stage,
        )
