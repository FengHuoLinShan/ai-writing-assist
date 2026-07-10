"""
Import API 层测试

通过 async_client 验证 HTTP 契约：成功导入、格式不支持、超大文件、
空文件、路径穿越文件名、编码/解析失败。
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from infrastructure.tasks.models import AsyncTask
from modules.imports import api as import_api
from modules.imports import services as import_services
from modules.imports.schemas import ImportResponse


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
        "第一章 开始\n这是第一章的内容。\n\n第二章 继续\n这是第二章的内容。\n"
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
    assert data["chapters"] == [
        {
            "chapter_index": 1,
            "title": "第一章 开始",
            "word_count": len("这是第一章的内容。"),
            "draft_id": data["chapters"][0]["draft_id"],
        },
        {
            "chapter_index": 2,
            "title": "第二章 继续",
            "word_count": len("这是第二章的内容。"),
            "draft_id": data["chapters"][1]["draft_id"],
        },
    ]
    assert all(ch["draft_id"] for ch in data["chapters"])

    # 验证 writing_drafts 已创建，且导入章节默认已发布
    chapters_resp = await async_client.get(f"/api/writing/chapters?novel_id={novel_id}")
    assert chapters_resp.status_code == 200
    chapter_indices = chapters_resp.json()["chapter_indices"]
    assert sorted(chapter_indices) == [1, 2]

    draft_resp = await async_client.get(
        f"/api/writing/chapters/1/draft?novel_id={novel_id}"
    )
    assert draft_resp.status_code == 200
    assert draft_resp.json()["status"] == "published"
    assert draft_resp.json()["version_number"] == 1


@pytest.mark.asyncio
async def test_upload_passes_complete_bytes_to_service(
    async_client: AsyncClient,
    sample_project: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """上传 API 仍把完整 bytes 和 basename 后文件名传给 service。"""
    novel_id = sample_project["id"]
    content = b"first chunk\nsecond chunk"
    service_response = ImportResponse(
        id=str(uuid.uuid4()),
        novel_id=novel_id,
        file_name="book.txt",
        file_type="txt",
        file_size=len(content),
        total_chapters=1,
        imported_chapters=1,
        status="done",
    )
    fake_service = SimpleNamespace(
        upload_and_import=AsyncMock(return_value=service_response),
    )
    monkeypatch.setattr(import_api, "_service", fake_service)

    resp = await async_client.post(
        "/api/imports/upload",
        data={"novel_id": novel_id},
        files={"file": ("../../book.txt", content, "text/plain")},
    )

    assert resp.status_code == 201
    fake_service.upload_and_import.assert_awaited_once()
    args = fake_service.upload_and_import.await_args.args
    assert args[1] == novel_id
    assert args[2] == "book.txt"
    assert args[3] == content


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """超限上传通过 HTTP 返回 413，且不调用 service。"""
    fake_service = SimpleNamespace(upload_and_import=AsyncMock())
    monkeypatch.setattr(import_api, "_service", fake_service)
    monkeypatch.setattr(import_api, "MAX_FILE_SIZE", 4)

    resp = await async_client.post(
        "/api/imports/upload",
        data={"novel_id": sample_project["id"]},
        files={"file": ("large.txt", b"12345", "text/plain")},
    )

    assert resp.status_code == 413
    data = resp.json()
    assert data["status_code"] == 413
    assert data["error"] == "validation_error"
    assert "50MB" in data["detail"]
    assert "最大允许 4 bytes" in data["detail"]
    fake_service.upload_and_import.assert_not_awaited()


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
    chapters_resp = await async_client.get(f"/api/writing/chapters?novel_id={novel_id}")
    assert chapters_resp.json()["chapter_indices"] == []

    # 验证导入记录状态为 failed
    list_resp = await async_client.get(f"/api/imports?novel_id={novel_id}")
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "failed"
    assert items[0]["error_message"] == "文件中未检测到有效章节"


@pytest.mark.asyncio
async def test_upload_chapter_count_limit_records_failed_without_writing(
    async_client: AsyncClient,
    sample_project: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """解析章节数超限返回 413，记录 failed 且不写入章节。"""
    novel_id = sample_project["id"]
    monkeypatch.setattr(
        import_services,
        "get_settings",
        lambda: SimpleNamespace(import_max_chapters=1),
    )
    content = (
        "第一章 开始\n这是第一章的内容。\n\n第二章 继续\n这是第二章的内容。\n"
    ).encode()

    resp = await async_client.post(
        "/api/imports/upload",
        data={"novel_id": novel_id},
        files={"file": ("too-many.txt", content, "text/plain")},
    )

    assert resp.status_code == 413
    assert "导入章节数 2 超过上限 1" in resp.json()["detail"]

    chapters_resp = await async_client.get(f"/api/writing/chapters?novel_id={novel_id}")
    assert chapters_resp.json()["chapter_indices"] == []

    list_resp = await async_client.get(f"/api/imports?novel_id={novel_id}")
    items = list_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "failed"
    assert items[0]["error_message"] == "导入章节数 2 超过上限 1"


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
    """GBK 等常见中文编码的 txt 被正确检测并导入"""
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
async def test_upload_truncated_utf8_records_failed(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    """截断的 UTF-8 序列触发编码失败，记录 failed 且不创建章节"""
    novel_id = sample_project["id"]
    content = b"\xef\xbb\xbf" + "第一章".encode() + b"\xe4\xb8"
    resp = await async_client.post(
        "/api/imports/upload",
        data={"novel_id": novel_id},
        files={"file": ("bad.txt", content, "text/plain")},
    )
    assert resp.status_code == 422
    assert "编码" in resp.json()["detail"]

    chapters_resp = await async_client.get(f"/api/writing/chapters?novel_id={novel_id}")
    assert chapters_resp.json()["chapter_indices"] == []

    list_resp = await async_client.get(f"/api/imports?novel_id={novel_id}")
    items = list_resp.json()["items"]
    assert len(items) == 1
    assert items[0]["status"] == "failed"
    assert "编码" in items[0]["error_message"]


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

    get_resp = await async_client.get(f"/api/imports/{record_id}?novel_id={novel_id}")
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
    resp = await async_client.get(f"/api/imports/{record_id}?novel_id={other_novel_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_deep_import_empty_project_returns_clear_error(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    """空项目调用深度导入（end_chapter=0）应返回明确的业务错误，而非 500"""
    novel_id = sample_project["id"]
    resp = await async_client.post(
        "/api/imports/deep",
        json={
            "novel_id": novel_id,
            "start_chapter": 1,
            "end_chapter": 0,
            "authorization_confirmed": True,
        },
    )
    assert resp.status_code == 400
    assert "章节" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_deep_import_explicit_range_valid(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    """显式指定 end_chapter < start_chapter 仍返回参数错误"""
    novel_id = sample_project["id"]
    resp = await async_client.post(
        "/api/imports/deep",
        json={
            "novel_id": novel_id,
            "start_chapter": 5,
            "end_chapter": 1,
            "authorization_confirmed": True,
        },
    )
    assert resp.status_code == 422
    assert "end_chapter must be >= start_chapter" in resp.text


@pytest.mark.asyncio
async def test_deep_import_range_limit_returns_400_without_task(
    async_client: AsyncClient,
    db_session,
    sample_project: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """deep 显式章节范围超限返回 400，且不新增 AsyncTask。"""
    novel_id = sample_project["id"]
    monkeypatch.setattr(
        import_api,
        "get_settings",
        lambda: SimpleNamespace(import_max_chapters=2),
    )

    resp = await async_client.post(
        "/api/imports/deep",
        json={
            "novel_id": novel_id,
            "start_chapter": 1,
            "end_chapter": 3,
            "authorization_confirmed": True,
        },
    )

    assert resp.status_code == 400
    assert "共 3 章" in resp.json()["detail"]
    assert "超过上限 2" in resp.json()["detail"]
    result = await db_session.execute(select(func.count()).select_from(AsyncTask))
    assert result.scalar_one() == 0


@pytest.mark.asyncio
async def test_stage_range_limit_returns_400_without_task(
    async_client: AsyncClient,
    db_session,
    sample_project: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stage 入口复用章节范围上限校验，超限不新增 AsyncTask。"""
    novel_id = sample_project["id"]
    monkeypatch.setattr(
        import_api,
        "get_settings",
        lambda: SimpleNamespace(import_max_chapters=2),
    )

    resp = await async_client.post(
        "/api/imports/stages/scenes",
        json={
            "novel_id": novel_id,
            "start_chapter": 4,
            "end_chapter": 6,
            "authorization_confirmed": True,
        },
    )

    assert resp.status_code == 400
    assert "共 3 章" in resp.json()["detail"]
    assert "超过上限 2" in resp.json()["detail"]
    result = await db_session.execute(select(func.count()).select_from(AsyncTask))
    assert result.scalar_one() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint", "expected_type"),
    [
        ("/api/imports/stages/scenes", "scene_auto_extraction"),
        ("/api/imports/stages/world-objects", "world_object_auto_extraction"),
        ("/api/imports/stages/plot-structure", "plot_structure_auto_extraction"),
    ],
)
async def test_deep_import_stage_endpoints_enqueue_expected_task(
    async_client: AsyncClient,
    db_session,
    sample_project: dict,
    endpoint: str,
    expected_type: str,
) -> None:
    novel_id = sample_project["id"]

    resp = await async_client.post(
        endpoint,
        json={
            "novel_id": novel_id,
            "start_chapter": 1,
            "end_chapter": 5,
            "authorization_confirmed": True,
        },
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["task_id"]
    assert data["workflow_type"] == expected_type

    result = await db_session.execute(
        select(AsyncTask).where(AsyncTask.id == uuid.UUID(data["task_id"]))
    )
    task = result.scalar_one()
    assert task.task_type == expected_type
    assert task.meta["novel_id"] == novel_id
    assert task.meta["start_chapter"] == 1
    assert task.meta["end_chapter"] == 5
    assert task.meta["high_quality"] is False
    assert task.meta["adoption_policy"] == "user_authorized_pipeline"
    assert task.meta["authorization_confirmed"] is True
    assert task.meta["authorization_snapshot"]["scope"]["stage"]
    assert task.meta["authorization_snapshot"]["rollback"] == {
        "supported": True,
        "mode": "workflow_owned_soft_deprecate",
    }
    assert task.result["authorization_snapshot"] == task.meta["authorization_snapshot"]
    assert task.result["asset_summary"]["adopted"] == 0


@pytest.mark.asyncio
async def test_scene_stage_endpoint_accepts_high_quality_flag(
    async_client: AsyncClient,
    db_session,
    sample_project: dict,
) -> None:
    novel_id = sample_project["id"]

    resp = await async_client.post(
        "/api/imports/stages/scenes",
        json={
            "novel_id": novel_id,
            "start_chapter": 1,
            "end_chapter": 5,
            "high_quality": True,
            "authorization_confirmed": True,
        },
    )

    assert resp.status_code == 201
    data = resp.json()
    result = await db_session.execute(
        select(AsyncTask).where(AsyncTask.id == uuid.UUID(data["task_id"]))
    )
    task = result.scalar_one()
    assert task.task_type == "scene_auto_extraction"
    assert task.meta["high_quality"] is True


@pytest.mark.asyncio
async def test_deep_import_stage_endpoint_validates_chapter_range(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    novel_id = sample_project["id"]
    resp = await async_client.post(
        "/api/imports/stages/scenes",
        json={
            "novel_id": novel_id,
            "start_chapter": 5,
            "end_chapter": 1,
            "authorization_confirmed": True,
        },
    )
    assert resp.status_code == 422
    assert "end_chapter must be >= start_chapter" in resp.text


@pytest.mark.asyncio
@pytest.mark.parametrize("authorization_value", [None, False])
async def test_deep_import_requires_explicit_pipeline_authorization(
    async_client: AsyncClient,
    sample_project: dict,
    authorization_value: bool | None,
) -> None:
    payload = {
        "novel_id": sample_project["id"],
        "start_chapter": 1,
        "end_chapter": 1,
    }
    if authorization_value is not None:
        payload["authorization_confirmed"] = authorization_value

    response = await async_client.post("/api/imports/deep", json=payload)

    assert response.status_code == 422
    assert "authorization_confirmed" in response.text


@pytest.mark.asyncio
async def test_upload_duplicate_done_file_returns_400(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    """同一项目重复上传已导入完成的同名文件应返回 400"""
    novel_id = sample_project["id"]
    content = "第一章\n内容\n".encode()

    first = await async_client.post(
        "/api/imports/upload",
        data={"novel_id": novel_id},
        files={"file": ("duplicate.txt", content, "text/plain")},
    )
    assert first.status_code == 201
    assert first.json()["status"] == "done"

    second = await async_client.post(
        "/api/imports/upload",
        data={"novel_id": novel_id},
        files={"file": ("duplicate.txt", content, "text/plain")},
    )
    assert second.status_code == 400
    assert "已导入" in second.json()["detail"]


@pytest.mark.asyncio
async def test_upload_same_file_name_in_different_projects_succeeds(
    async_client: AsyncClient,
    sample_project: dict,
) -> None:
    """同名文件只在同一 novel 内判重，不应跨 novel 拦截。"""
    other_project = (
        await async_client.post("/api/projects", json={"title": "另一个导入项目"})
    ).json()
    content = "第一章\n内容\n".encode()

    first = await async_client.post(
        "/api/imports/upload",
        data={"novel_id": sample_project["id"]},
        files={"file": ("same-name.txt", content, "text/plain")},
    )
    second = await async_client.post(
        "/api/imports/upload",
        data={"novel_id": other_project["id"]},
        files={"file": ("same-name.txt", content, "text/plain")},
    )

    assert first.status_code == 201
    assert second.status_code == 201
