"""
导入解析器

支持 txt / epub / html / mobi 四种格式的章节解析。
所有解析器统一返回 list[dict{title, content}]。
"""

from __future__ import annotations

import io
import re
import stat
import unicodedata
import zipfile
from typing import Any
from xml.etree import ElementTree

import chardet

CHAPTER_PATTERNS = [
    re.compile(
        r"^(?:第[一二三四五六七八九十百千万零\d]+[章节回话]|序章|序言|前言|楔子|引子).*",
        re.MULTILINE,
    ),
    re.compile(r"^(?:Chapter|Ch)\s+\d+.*", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^(?:Prologue|Preface|Introduction).*", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^\d+\.[\s　]+.*", re.MULTILINE),
    re.compile(r"^卷[一二三四五六七八九十\d].*", re.MULTILINE),
]

CHUNK_SIZE = 500 * 1024
ENCODING_DETECT_SAMPLE_SIZE = 64 * 1024
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
_COMMON_CHINESE_ENCODINGS = {"big5", "gb18030", "gb2312", "gbk"}
_DEFAULT_ENCODING_CONFIDENCE = 0.7
_CHINESE_ENCODING_CONFIDENCE = 0.2

ALLOWED_EXTENSIONS: set[str] = {".txt", ".epub", ".html", ".htm", ".mobi", ".azw3"}

_CONTENT_TYPE_MISMATCH_MESSAGE = "文件内容与扩展名不匹配"
_HTML_MARKUP_PATTERN = re.compile(
    r"<\s*(?:!doctype\s+html|html|head|body|title|meta|link|main|article|section|"
    r"header|footer|nav|h[1-6]|p|div|span|blockquote|pre|br|hr|ol|ul|li|table|"
    r"thead|tbody|tfoot|tr|th|td|figure|figcaption|a|em|strong|b|i|u|ruby|rt)\b",
    re.IGNORECASE,
)
_EPUB_MIMETYPE = b"application/epub+zip"
_EPUB_MAX_MEMBERS = 4096
_EPUB_MAX_UNCOMPRESSED_SIZE = MAX_FILE_SIZE * 2
_EPUB_MAX_MEMBER_SIZE = MAX_FILE_SIZE
_EPUB_MAX_CONTAINER_SIZE = 1024 * 1024
_EPUB_MAX_PACKAGE_SIZE = 4 * 1024 * 1024
_EPUB_ALLOWED_COMPRESSION = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
_EPUB_BOUNDED_READ_CHUNK = 64 * 1024
_EPUB_CONTAINER_PATH = "META-INF/container.xml"
_EPUB_CONTAINER_NAMESPACE = "urn:oasis:names:tc:opendocument:xmlns:container"
_EPUB_PACKAGE_NAMESPACE = "http://www.idpf.org/2007/opf"
_EPUB_PACKAGE_MEDIA_TYPE = "application/oebps-package+xml"
_PALMDB_HEADER_SIZE = 78
_PALMDB_RECORD_ENTRY_SIZE = 8
_PALMDOC_HEADER_SIZE = 16
_MOBI_MIN_HEADER_SIZE = 116
_MOBI_COMPRESSION_TYPES = {1, 2, 17480}
_MACH_O_MAGICS = {
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe",
    b"\xfe\xed\xfa\xce",
    b"\xfe\xed\xfa\xcf",
}


def detect_encoding(data: bytes) -> str:
    """检测文本编码"""
    result = chardet.detect(data[:ENCODING_DETECT_SAMPLE_SIZE])
    encoding = result.get("encoding")
    confidence = result.get("confidence") or 0
    normalized_encoding = str(encoding or "").lower().replace("-", "")
    minimum_confidence = (
        _CHINESE_ENCODING_CONFIDENCE
        if normalized_encoding in _COMMON_CHINESE_ENCODINGS
        else _DEFAULT_ENCODING_CONFIDENCE
    )
    if not encoding or confidence < minimum_confidence:
        return "utf-8"
    return encoding


def _raise_content_type_mismatch() -> None:
    raise ValueError(_CONTENT_TYPE_MISMATCH_MESSAGE)


def _looks_like_executable(data: bytes) -> bool:
    if data.startswith(b"\x7fELF") or data[:4] in _MACH_O_MAGICS:
        return True
    if not data.startswith(b"MZ") or len(data) < 64:
        return False
    pe_offset = int.from_bytes(data[60:64], "little")
    return pe_offset >= 64 and data[pe_offset : pe_offset + 4] == b"PE\x00\x00"


def _decode_text_for_validation(data: bytes) -> str:
    encoding = detect_encoding(data)
    try:
        text = data.decode(encoding, errors="strict")
    except (LookupError, UnicodeDecodeError) as exc:
        raise ValueError(
            "文本编码无法正确解析，请使用 UTF-8 或常见中文编码保存文件"
        ) from exc

    for char in text:
        if unicodedata.category(char) == "Cc" and char not in "\t\n\r\f":
            _raise_content_type_mismatch()
    return text


def _archive_path_is_unsafe(name: str) -> bool:
    if not name or "\x00" in name or "\\" in name:
        return True
    normalized = name.replace("\\", "/")
    parts = normalized.split("/")
    return (
        normalized.startswith("/")
        or ".." in parts
        or (len(normalized) >= 2 and normalized[0].isalpha() and normalized[1] == ":")
    )


def _read_member_bounded(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    *,
    max_actual_size: int,
) -> bytes:
    """按实测解压输出读取单个 zip 成员。

    中央目录里的 file_size 是攻击者可控的声明值，而 zipfile 的 read(-1) 会先
    把整个 DEFLATE 流解压进内存再按声明值截断；必须分块计数才能把真实输出
    限制在预期体积内。
    """
    output = bytearray()
    with archive.open(member, "r") as stream:
        while True:
            chunk = stream.read(_EPUB_BOUNDED_READ_CHUNK)
            if not chunk:
                break
            output.extend(chunk)
            if len(output) > max_actual_size:
                _raise_content_type_mismatch()
    return bytes(output)


def _audit_epub_member_sizes(
    archive: zipfile.ZipFile,
    members: list[zipfile.ZipInfo],
) -> None:
    """全成员解压审计：实际输出一旦超过声明 file_size 立即拒绝。

    审计通过后，后续 ebooklib 的整段 read 至多解压出已通过声明的体积，
    伪造头部的解压炸弹在这里被有界拦截。
    """
    for member in members:
        produced = 0
        with archive.open(member, "r") as stream:
            while True:
                chunk = stream.read(_EPUB_BOUNDED_READ_CHUNK)
                if not chunk:
                    break
                produced += len(chunk)
                if produced > member.file_size:
                    _raise_content_type_mismatch()


def _read_epub_xml(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    *,
    max_size: int,
) -> ElementTree.Element:
    if member.is_dir() or member.file_size > max_size:
        _raise_content_type_mismatch()
    content = _read_member_bounded(archive, member, max_actual_size=max_size)
    lowered = content.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        _raise_content_type_mismatch()
    try:
        return ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise ValueError(_CONTENT_TYPE_MISMATCH_MESSAGE) from exc


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _validate_epub_content(data: bytes) -> None:
    if not data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        _raise_content_type_mismatch()

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            names = [member.filename for member in members]
            if (
                not members
                or len(members) > _EPUB_MAX_MEMBERS
                or len(names) != len(set(names))
                or names.count("mimetype") != 1
                or names.count(_EPUB_CONTAINER_PATH) != 1
            ):
                _raise_content_type_mismatch()

            total_size = 0
            for member in members:
                if (
                    member.flag_bits & 0x1
                    or _archive_path_is_unsafe(member.filename)
                    or stat.S_ISLNK(member.external_attr >> 16)
                    or member.compress_type not in _EPUB_ALLOWED_COMPRESSION
                    or member.file_size > _EPUB_MAX_MEMBER_SIZE
                ):
                    _raise_content_type_mismatch()
                total_size += member.file_size
                if total_size > _EPUB_MAX_UNCOMPRESSED_SIZE:
                    _raise_content_type_mismatch()

            _audit_epub_member_sizes(archive, members)

            mimetype_info = archive.getinfo("mimetype")
            if (
                members[0].filename != "mimetype"
                or mimetype_info.header_offset != 0
                or mimetype_info.compress_type != zipfile.ZIP_STORED
                or mimetype_info.file_size != len(_EPUB_MIMETYPE)
                or _read_member_bounded(
                    archive,
                    mimetype_info,
                    max_actual_size=len(_EPUB_MIMETYPE),
                )
                != _EPUB_MIMETYPE
            ):
                _raise_content_type_mismatch()

            container = _read_epub_xml(
                archive,
                archive.getinfo(_EPUB_CONTAINER_PATH),
                max_size=_EPUB_MAX_CONTAINER_SIZE,
            )
            if container.tag != f"{{{_EPUB_CONTAINER_NAMESPACE}}}container":
                _raise_content_type_mismatch()
            rootfiles = [
                element
                for element in container.iter()
                if element.tag == f"{{{_EPUB_CONTAINER_NAMESPACE}}}rootfile"
                and element.get("media-type") == _EPUB_PACKAGE_MEDIA_TYPE
            ]
            if not rootfiles:
                _raise_content_type_mismatch()
            for rootfile in rootfiles:
                package_path = rootfile.get("full-path", "")
                if _archive_path_is_unsafe(package_path) or package_path not in names:
                    _raise_content_type_mismatch()
                package = _read_epub_xml(
                    archive,
                    archive.getinfo(package_path),
                    max_size=_EPUB_MAX_PACKAGE_SIZE,
                )
                required_package_elements = {"metadata", "manifest", "spine"}
                package_elements = {
                    _xml_local_name(element.tag)
                    for element in package
                    if isinstance(element.tag, str)
                    and element.tag.startswith(f"{{{_EPUB_PACKAGE_NAMESPACE}}}")
                }
                if (
                    package.tag != f"{{{_EPUB_PACKAGE_NAMESPACE}}}package"
                    or not required_package_elements.issubset(package_elements)
                ):
                    _raise_content_type_mismatch()
    except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise ValueError(_CONTENT_TYPE_MISMATCH_MESSAGE) from exc


def _validate_mobi_content(data: bytes) -> None:
    if len(data) < _PALMDB_HEADER_SIZE or data[60:68] != b"BOOKMOBI":
        _raise_content_type_mismatch()

    record_count = int.from_bytes(data[76:78], "big")
    record_table_end = _PALMDB_HEADER_SIZE + record_count * _PALMDB_RECORD_ENTRY_SIZE
    if record_count == 0 or record_table_end > len(data):
        _raise_content_type_mismatch()

    offsets = [
        int.from_bytes(data[offset : offset + 4], "big")
        for offset in range(
            _PALMDB_HEADER_SIZE,
            record_table_end,
            _PALMDB_RECORD_ENTRY_SIZE,
        )
    ]
    if (
        offsets[0] < record_table_end
        or offsets[-1] >= len(data)
        or any(current >= following for current, following in zip(offsets, offsets[1:]))
    ):
        _raise_content_type_mismatch()

    first_record_start = offsets[0]
    first_record_end = offsets[1] if len(offsets) > 1 else len(data)
    if first_record_end - first_record_start < _PALMDOC_HEADER_SIZE + 8:
        _raise_content_type_mismatch()
    compression = int.from_bytes(data[first_record_start : first_record_start + 2], "big")
    mobi_header_start = first_record_start + _PALMDOC_HEADER_SIZE
    mobi_header_size = int.from_bytes(
        data[mobi_header_start + 4 : mobi_header_start + 8],
        "big",
    )
    if (
        compression not in _MOBI_COMPRESSION_TYPES
        or data[mobi_header_start : mobi_header_start + 4] != b"MOBI"
        or mobi_header_size < _MOBI_MIN_HEADER_SIZE
        or mobi_header_start + mobi_header_size > first_record_end
    ):
        _raise_content_type_mismatch()


def _validate_file_content(data: bytes, file_type: str) -> None:
    """校验不可信上传内容，再分派到具体格式解析器。"""
    if not data:
        return
    if _looks_like_executable(data):
        _raise_content_type_mismatch()

    if file_type == "txt":
        _decode_text_for_validation(data)
    elif file_type in {"html", "htm"}:
        text = _decode_text_for_validation(data)
        if _HTML_MARKUP_PATTERN.search(text) is None:
            _raise_content_type_mismatch()
    elif file_type == "epub":
        _validate_epub_content(data)
    elif file_type in {"mobi", "azw3"}:
        _validate_mobi_content(data)


def split_chapters(text: str) -> list[dict[str, str]]:
    """按章节模式分割文本，返回 [{title, content}]"""
    if not text or not text.strip():
        return []

    best_splits: list[tuple[int, str]] = []
    for pattern in CHAPTER_PATTERNS:
        matches = list(pattern.finditer(text))
        if len(matches) > len(best_splits):
            best_splits = [(m.start(), m.group().strip()) for m in matches]

    if not best_splits:
        return [{"title": "全文", "content": text.strip()}]

    chapters: list[dict[str, str]] = []
    for i, (pos, title) in enumerate(best_splits):
        end_pos = best_splits[i + 1][0] if i + 1 < len(best_splits) else len(text)
        content = text[pos:end_pos].strip()
        lines = content.split("\n", 1)
        content = lines[1].strip() if len(lines) > 1 else ""
        chapters.append({"title": title, "content": content})

    return chapters if chapters else [{"title": "全文", "content": text.strip()}]


def parse_txt(data: bytes) -> list[dict[str, str]]:
    """解析 TXT 文件内容"""
    if not data:
        return []
    encoding = detect_encoding(data)
    if encoding is None:
        raise ValueError("无法检测文本编码，请使用 UTF-8 或常见中文编码保存文件")
    try:
        text = data.decode(encoding, errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError(
            "文本编码无法正确解析，请使用 UTF-8 或常见中文编码保存文件"
        ) from exc
    return split_chapters(text)


def parse_epub(data: bytes) -> list[dict[str, str]]:
    """解析 EPUB 文件内容"""
    import tempfile

    from bs4 import BeautifulSoup
    from ebooklib import epub

    with tempfile.NamedTemporaryFile(suffix=".epub", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        book = epub.read_epub(tmp_path)
        items_by_id = {item.get_id(): item for item in book.get_items()}

        chapters: list[dict[str, str]] = []
        for spine_item in book.spine:
            item_id = spine_item[0]
            item = items_by_id.get(item_id)
            if not item or item.get_type() != 9:
                continue

            html_content = item.get_body_content() or item.get_content()
            soup = BeautifulSoup(html_content, "lxml")

            title_tag = soup.find(["h1", "h2"])
            title = (
                title_tag.get_text(strip=True)
                if title_tag
                else (item.get_name() or "无标题")
            )

            for tag in soup(["script", "style", "nav"]):
                tag.decompose()
            parts: list[str] = []
            for p in soup.find_all(
                ["p", "div", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"]
            ):
                text = p.get_text(strip=True)
                if text:
                    parts.append(text)
            content = "\n\n".join(parts)

            if content.strip():
                chapters.append({"title": title, "content": content.strip()})

        if not chapters:
            all_text: list[str] = []
            for spine_item in book.spine:
                item = items_by_id.get(spine_item[0])
                if item:
                    soup = BeautifulSoup(item.get_content(), "lxml")
                    all_text.append(soup.get_text(strip=True))
            content = "\n\n".join(all_text)
            if content.strip():
                chapters.append({"title": "全文", "content": content.strip()})

        return chapters
    finally:
        import os

        os.unlink(tmp_path)


def parse_html(data: bytes) -> list[dict[str, str]]:
    """解析 HTML 文件内容"""
    encoding = detect_encoding(data)
    text = data.decode(encoding, errors="replace")
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(text, "lxml")

    heading_tags = soup.find_all(["h1", "h2"])
    chapter_headings = [
        h for h in heading_tags if _looks_like_chapter(h.get_text(strip=True))
    ]

    if chapter_headings:
        chapters: list[dict[str, str]] = []
        for i, heading in enumerate(chapter_headings):
            title = heading.get_text(strip=True)
            content_parts: list[str] = []
            cursor = heading.find_next_sibling()
            next_heading = (
                chapter_headings[i + 1] if i + 1 < len(chapter_headings) else None
            )

            while cursor and cursor is not next_heading:
                if cursor.name in (
                    "p",
                    "div",
                    "blockquote",
                    "h1",
                    "h2",
                    "h3",
                    "h4",
                    "h5",
                    "h6",
                    "section",
                ):
                    t = cursor.get_text(strip=True)
                    if t:
                        content_parts.append(t)
                cursor = cursor.find_next_sibling()
                if cursor and cursor.find_parent() is not heading.find_parent():
                    cursor = cursor.find_next_sibling()

            content = "\n\n".join(content_parts)
            if content.strip():
                chapters.append({"title": title, "content": content.strip()})

        if chapters:
            return chapters

    # Fallback to txt splitting
    for tag in soup(["script", "style", "nav"]):
        tag.decompose()
    plain_text = soup.get_text(separator="\n")
    return split_chapters(plain_text)


def parse_mobi(data: bytes) -> list[dict[str, str]]:
    """解析 MOBI 文件内容"""
    import shutil
    import tempfile

    import mobi

    with tempfile.NamedTemporaryFile(suffix=".mobi", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        temp_dir, extracted_path = mobi.extract(tmp_path)
        try:
            with open(extracted_path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
        return split_chapters(text)
    finally:
        import os

        os.unlink(tmp_path)


def _looks_like_chapter(text: str) -> bool:
    """判断标题文本是否看起来像章节标题"""
    keywords = [
        "章",
        "节",
        "回",
        "话",
        "序",
        "卷",
        "楔子",
        "chapter",
        "ch",
        "prologue",
        "preface",
    ]
    lower = text.lower().strip()
    return any(kw in lower for kw in keywords)


def parse_file(data: bytes, file_type: str) -> list[dict[str, str]]:
    """统一入口：根据文件类型选择解析器"""
    parsers: dict[str, Any] = {
        "txt": parse_txt,
        "epub": parse_epub,
        "html": parse_html,
        "htm": parse_html,
        "mobi": parse_mobi,
        "azw3": parse_mobi,
    }
    parser = parsers.get(file_type)
    if parser is None:
        raise ValueError(f"不支持的文件类型: {file_type}")
    _validate_file_content(data, file_type)
    return parser(data)
