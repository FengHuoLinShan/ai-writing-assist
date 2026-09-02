from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from modules.interaction import api as interaction_api
from modules.interaction.schemas import InteractionSourceRevisionResponse
from modules.project.models import Project
from modules.writing.models import WritingDraft

pytestmark = pytest.mark.asyncio
XHR = {"X-Requested-With": "XMLHttpRequest"}


async def test_source_import_preview_creates_nothing_then_apply_creates_author_project(
    async_client,
    db_session,
) -> None:
    content = "第一章\n雾中的汽笛。\n\n第二章\n旅人走下站台。".encode()
    preview = await async_client.post(
        "/api/interactions/sources/import-preview",
        headers=XHR,
        files={"file": ("serial.txt", content, "text/plain")},
        data={"title": "未完结连载", "mode": "full"},
    )
    projects_before = (
        await db_session.execute(select(func.count(Project.id)))
    ).scalar_one()

    async def fake_source(_db, *, project_id, **_kwargs):  # noqa: ANN001
        return InteractionSourceRevisionResponse(
            id="22222222-2222-4222-8222-222222222222",
            project_id=project_id,
            title="未完结连载",
            version_number=1,
            status="organizing",
            chapter_count=2,
            progress_message="正在完整整理当前导入版本",
        )

    with patch.object(
        interaction_api._source_service,  # noqa: SLF001
        "create_from_project",
        autospec=True,
        side_effect=fake_source,
    ):
        applied = await async_client.post(
            "/api/interactions/sources/import",
            headers=XHR,
            files={"file": ("serial.txt", content, "text/plain")},
            data={
                "title": "未完结连载",
                "mode": "full",
                "expected_preview_hash": preview.json()["preview_hash"],
                "destructive_confirmed": "false",
                "authorization_confirmed": "true",
            },
        )

    projects_after = (
        await db_session.execute(select(func.count(Project.id)))
    ).scalar_one()
    drafts = (await db_session.execute(select(func.count(WritingDraft.id)))).scalar_one()
    created_project = await db_session.get(
        Project,
        uuid.UUID(applied.json()["project_id"]),
    )

    assert preview.status_code == 200
    assert projects_before == 0
    assert applied.status_code == 202
    assert projects_after == 1
    assert drafts == 2
    assert created_project is not None
    assert created_project.project_kind == "author"


async def test_invalid_source_preview_does_not_leave_empty_project(
    async_client,
    db_session,
) -> None:
    response = await async_client.post(
        "/api/interactions/sources/import-preview",
        headers=XHR,
        files={"file": ("novel.pdf", b"not a supported manuscript", "application/pdf")},
        data={"title": "不应创建", "mode": "full"},
    )
    project_count = (
        await db_session.execute(select(func.count(Project.id)))
    ).scalar_one()

    assert response.status_code == 400
    assert project_count == 0
