"""
导入解析器

支持 txt / epub / html / mobi 四种格式的章节解析。
所有解析器统一返回 list[dict{title, content}]。
"""

from __future__ import annotations

import re
from typing import Any

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
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

ALLOWED_EXTENSIONS: set[str] = {".txt", ".epub", ".html", ".htm", ".mobi", ".azw3"}


def detect_encoding(data: bytes) -> str:
    """检测文本编码"""
    result = chardet.detect(data[:CHUNK_SIZE])
    return result.get("encoding", "utf-8") or "utf-8"


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
    return parser(data)
