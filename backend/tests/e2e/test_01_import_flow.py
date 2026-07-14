"""Current import, task, and project E2E regressions.

Retired candidate and legacy dedup endpoints are covered by the current entity
lifecycle tests instead of being retained as permanently skipped cases.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.seed_data import create_base_scene

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]

SAMPLE_NOVEL_TEXT = """第一章 雨夜
林舟在雨夜收到一封来自钟楼的信，决定在天亮前寻找星盘。

第二章 钟声
柳青带着旧钥匙赶到钟楼，两人发现城门外有人正在追踪他们。
"""


class TestImportPipeline:
    @pytest_asyncio.fixture
    async def project_and_client(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> tuple[AsyncClient, str]:
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return async_client, meta["project_id"]

    async def _upload(self, client: AsyncClient, project_id: str):
        return await client.post(
            "/api/imports/upload",
            files={
                "file": (
                    "synthetic_novel.txt",
                    SAMPLE_NOVEL_TEXT.encode(),
                    "text/plain",
                )
            },
            data={"novel_id": project_id},
        )

    async def test_upload_creates_import_record_and_chapter_drafts(
        self,
        project_and_client: tuple[AsyncClient, str],
    ) -> None:
        client, project_id = project_and_client
        uploaded = await self._upload(client, project_id)
        assert uploaded.status_code == 201, uploaded.text
        payload = uploaded.json()
        assert payload["status"] == "done"
        assert payload["total_chapters"] == 2

        draft = await client.get(f"/api/writing/chapters/1/draft?novel_id={project_id}")
        assert draft.status_code == 200, draft.text
        assert "林舟" in draft.json()["content"]

    async def test_upload_rejects_non_whitelisted_file_type(
        self,
        project_and_client: tuple[AsyncClient, str],
    ) -> None:
        client, project_id = project_and_client
        response = await client.post(
            "/api/imports/upload",
            files={"file": ("payload.exe", b"not a novel", "application/octet-stream")},
            data={"novel_id": project_id},
        )
        assert response.status_code == 400


class TestAsyncTaskSubmission:
    @pytest_asyncio.fixture
    async def project_id(self, db_session: AsyncSession) -> str:
        meta = await create_base_scene(db_session)
        await db_session.flush()
        return meta["project_id"]

    async def test_submit_and_query_publish_task(
        self,
        async_client: AsyncClient,
        project_id: str,
    ) -> None:
        created = await async_client.post(
            "/api/writing/drafts",
            json={
                "novel_id": project_id,
                "chapter_index": 1,
                "title": "Module-owned publish",
                "content": "Published through the writing schema.",
            },
        )
        assert created.status_code == 201, created.text
        task_id = created.json()["task_id"]
        assert task_id

        status = await async_client.get(
            f"/api/tasks/{task_id}",
            params={"novel_id": project_id},
        )
        assert status.status_code == 200, status.text
        assert status.json()["task_type"] == "publish_chapter"

    async def test_cancel_pending_task_preserves_novel_scope(
        self,
        async_client: AsyncClient,
        project_id: str,
    ) -> None:
        created = await async_client.post(
            "/api/writing/drafts",
            json={
                "novel_id": project_id,
                "chapter_index": 1,
                "title": "Pending publish",
                "content": "Cancel the derived task, not schema validation.",
            },
        )
        assert created.status_code == 201, created.text
        task_id = created.json()["task_id"]
        assert task_id
        cancelled = await async_client.post(
            f"/api/tasks/{task_id}/cancel",
            params={"novel_id": project_id},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"

    async def test_unknown_task_type_is_rejected(self, async_client: AsyncClient) -> None:
        response = await async_client.post(
            "/api/tasks",
            json={"task_type": "not_a_task", "meta": {"novel_id": str(uuid.uuid4())}},
        )
        assert response.status_code == 400

    async def test_module_owned_task_type_requires_module_api(
        self,
        async_client: AsyncClient,
        project_id: str,
    ) -> None:
        response = await async_client.post(
            "/api/tasks",
            json={
                "task_type": "publish_chapter",
                "meta": {"novel_id": project_id, "chapter_index": 1},
            },
        )
        assert response.status_code == 403


class TestProjectUpdate:
    async def test_project_title_update_persists(
        self,
        async_client: AsyncClient,
        db_session: AsyncSession,
    ) -> None:
        meta = await create_base_scene(db_session)
        await db_session.flush()
        response = await async_client.put(
            f"/api/projects/{meta['project_id']}",
            json={"title": "更新后的测试小说"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["title"] == "更新后的测试小说"
