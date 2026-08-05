"""PostgreSQL contract for upload success visibility across sessions."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport
from sqlalchemy import func, select

from app.main import app
from core.database import get_manager
from infrastructure.tasks.models import AsyncTask
from modules.imports.models import ImportRecord
from modules.writing.models import WritingDraft
from tests.support.http import XhrAsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_upload_201_is_immediately_visible_to_an_independent_session() -> None:
    """A 201 response commits records, drafts, and tasks before another request."""
    transport = ASGITransport(app=app)
    project_id: str | None = None
    content = (
        "第一章 雨夜\n林舟收到一封来自钟楼的信。\n\n"
        "第二章 钟声\n柳青带着旧钥匙赶到钟楼。\n"
    ).encode()

    async with XhrAsyncClient(transport=transport, base_url="http://test") as client:
        try:
            project_response = await client.post(
                "/api/projects",
                json={"title": "导入提交可见性测试"},
            )
            assert project_response.status_code == 201, project_response.text
            project_id = project_response.json()["id"]

            upload_response = await client.post(
                "/api/imports/upload",
                data={"novel_id": project_id},
                files={"file": ("visibility.txt", content, "text/plain")},
            )
            assert upload_response.status_code == 201, upload_response.text
            assert upload_response.json()["imported_chapters"] == 2

            chapters_response = await client.get(
                "/api/writing/chapters",
                params={"novel_id": project_id},
            )
            assert chapters_response.status_code == 200, chapters_response.text
            assert chapters_response.json()["chapter_indices"] == [1, 2]

            novel_uuid = uuid.UUID(project_id)
            async with get_manager().session_factory() as observer:
                import_record = await observer.scalar(
                    select(ImportRecord).where(ImportRecord.novel_id == novel_uuid)
                )
                draft_count = await observer.scalar(
                    select(func.count())
                    .select_from(WritingDraft)
                    .where(WritingDraft.novel_id == novel_uuid)
                )
                publish_tasks = (
                    (
                        await observer.execute(
                            select(AsyncTask).where(
                                AsyncTask.task_type == "publish_chapter",
                                AsyncTask.novel_id == novel_uuid,
                            )
                        )
                    )
                    .scalars()
                    .all()
                )

            assert import_record is not None
            assert import_record.status == "done"
            assert import_record.imported_chapters == 2
            assert draft_count == 2
            assert len(publish_tasks) == 2
        finally:
            if project_id is not None:
                await client.delete(f"/api/projects/{project_id}")
                await client.delete(
                    f"/api/projects/{project_id}/permanent",
                    params={"confirmed": True},
                )
