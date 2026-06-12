"""
Import API 层测试

通过 async_client 验证 HTTP 契约：成功导入、格式不支持、超大文件、
空文件、路径穿越文件名、编码/解析失败。
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from modules.imports.parsers import MAX_FILE_SIZE


@pytest.fixture
async def sample_project(async_client: AsyncClient):
    resp = await async_client.post("/api/projects", json={"title": "导入 API 测试小说"})
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.asyncio
async def test_upload_txt_success(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    """成功导入 txt 文件并写入 writing_drafts"""
    novel_id = sample_project["id"]
    content = (
        "第一章 开始\n这是第一章的内容。\n\n"
        "第二章 继续\n这是第二章的内容。\n"
    ).encode()

    resp = await async_client.post(
        "/api/imports/upload",
        data={"novel_id": novel_id},
        files={"file": ("novel.txt", content, "text/plain")},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["file_name"] == "novel.txt"
    assert data["file_type"] == "txt"
    assert data["file_size"] == len(content)
    assert data["total_chapters"] == 2
    assert data["imported_chapters"] == 2
    assert data["status"] == "done"

    # 验证 writing_drafts 已创建
    chapters_resp = await async_client.get(
        f"/api/writing/chapters?novel_id={novel_id}"
    )
    assert chapters_resp.status_code == 200
    chapter_indices = chapters_resp.json()["chapter_indices"]
    assert sorted(chapter_indices) == [1, 2]


@pytest.mark.asyncio
async def test_upload_unsupported_format_returns_400(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    """不支持的文件格式返回 400"""
    resp = await async_client.post(
        "/api/imports/upload",
        data={"novel_id": sample_project["id"]},
        files={"file": ("book.pdf", b"PDF content", "application/pdf")},
    )
    assert resp.status_code == 400
    assert "不支持的文件类型" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upload_oversized_file_returns_413(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    """超过 50MB 的文件返回 413"""
    large_data = b"x" * (MAX_FILE_SIZE + 1)
    resp = await async_client.post(
        "/api/imports/upload",
        data={"novel_id": sample_project["id"]},
        files={"file": ("large.txt", large_data, "text/plain")},
    )
    assert resp.status_code == 413
    assert "50MB" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upload_empty_file_records_failed(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    """空文件标记导入失败且不创建章节"""
    novel_id = sample_project["id"]
    resp = await async_client.post(
        "/api/imports/upload",
        data={"novel_id": novel_id},
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert resp.status_code == 400
    assert "文件中未检测到有效章节" in resp.json()["detail"]

    # 验证未创建 writing_drafts
    chapters_resp = await async_client.get(
        f"/api/writing/chapters?novel_id={novel_id}"
    )
    assert chapters_resp.json()["chapter_indices"] == []

    # 验证导入记录状态为 failed
    list_resp = await async_client.get(f"/api/imports?novel_id={novel_id}")
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "failed"
    assert items[0]["error_message"] == "文件中未检测到有效章节"


@pytest.mark.asyncio
async def test_upload_path_traversal_filename_sanitized(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    """路径穿越文件名被 os.path.basename 处理"""
    content = "第一章\n正文内容\n".encode()
    resp = await async_client.post(
        "/api/imports/upload",
        data={"novel_id": sample_project["id"]},
        files={"file": ("../../../etc/passwd.txt", content, "text/plain")},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["file_name"] == "passwd.txt"
    assert "/" not in data["file_name"]


@pytest.mark.asyncio
async def test_upload_non_utf8_txt_success(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    """非 UTF-8 编码的 txt 通过替换错误字符成功导入，不崩溃"""
    # GBK 编码的中文字节，会被 chardet 检测到并解码
    content = "第一章\n这是第一章内容\n".encode("gbk")
    resp = await async_client.post(
        "/api/imports/upload",
        data={"novel_id": sample_project["id"]},
        files={"file": ("gbk.txt", content, "text/plain")},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["status"] == "done"
    assert data["imported_chapters"] >= 1


@pytest.mark.asyncio
async def test_list_and_get_import_records(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    """导入记录列表和详情"""
    novel_id = sample_project["id"]
    content = "第一章\n内容\n".encode()
    upload_resp = await async_client.post(
        "/api/imports/upload",
        data={"novel_id": novel_id},
        files={"file": ("book.txt", content, "text/plain")},
    )
    record_id = upload_resp.json()["id"]

    list_resp = await async_client.get(f"/api/imports?novel_id={novel_id}")
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1

    get_resp = await async_client.get(
        f"/api/imports/{record_id}?novel_id={novel_id}"
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == record_id


@pytest.mark.asyncio
async def test_get_import_record_novel_id_isolation(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    """跨 novel_id 访问导入记录返回 404"""
    novel_id = sample_project["id"]
    content = "第一章\n内容\n".encode()
    upload_resp = await async_client.post(
        "/api/imports/upload",
        data={"novel_id": novel_id},
        files={"file": ("book.txt", content, "text/plain")},
    )
    record_id = upload_resp.json()["id"]

    other_novel_id = str(uuid.uuid4())
    resp = await async_client.get(
        f"/api/imports/{record_id}?novel_id={other_novel_id}"
    )
    assert resp.status_code == 404
