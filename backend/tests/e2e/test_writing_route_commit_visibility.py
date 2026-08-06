"""PostgreSQL visibility contract for author working-draft saves."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport
from sqlalchemy import select

from app.main import app
from core.database import get_manager
from modules.writing.models import WritingDraft
from tests.support.http import XhrAsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_working_draft_save_is_immediately_visible_after_success() -> None:
    """POST and PUT success responses expose only committed writing content."""
    transport = ASGITransport(app=app)
    project_id: str | None = None

    async with XhrAsyncClient(transport=transport, base_url="http://test") as client:
        try:
            project_response = await client.post(
                "/api/projects",
                json={"title": "工作稿提交可见性测试"},
            )
            assert project_response.status_code == 201, project_response.text
            project_id = project_response.json()["id"]

            create_response = await client.post(
                "/api/writing/drafts/autosave",
                json={
                    "novel_id": project_id,
                    "chapter_index": 1,
                    "title": "移动速记",
                    "content": "原始移动正文",
                },
            )
            assert create_response.status_code == 201, create_response.text
            created = create_response.json()

            async with get_manager().session_factory() as create_observer:
                persisted_create = await create_observer.scalar(
                    select(WritingDraft).where(
                        WritingDraft.id == uuid.UUID(created["id"]),
                        WritingDraft.novel_id == uuid.UUID(project_id),
                    )
                )

            assert persisted_create is not None
            assert persisted_create.content == "原始移动正文"
            assert persisted_create.status == "draft"

            update_response = await client.put(
                f"/api/writing/drafts/{created['id']}",
                params={"novel_id": project_id},
                json={
                    "title": "移动速记",
                    "content": "390px 下保存的短文本。",
                    "expected_version": created["version_number"],
                    "expected_updated_at": created["updated_at"],
                },
            )
            assert update_response.status_code == 200, update_response.text
            working = update_response.json()

            async with get_manager().session_factory() as update_observer:
                persisted_update = await update_observer.scalar(
                    select(WritingDraft).where(
                        WritingDraft.id == uuid.UUID(working["id"]),
                        WritingDraft.novel_id == uuid.UUID(project_id),
                    )
                )

            assert persisted_update is not None
            assert persisted_update.content == "390px 下保存的短文本。"
            assert persisted_update.status == "draft"
        finally:
            if project_id is not None:
                await client.delete(f"/api/projects/{project_id}")
                await client.delete(
                    f"/api/projects/{project_id}/permanent",
                    params={"confirmed": True},
                )
