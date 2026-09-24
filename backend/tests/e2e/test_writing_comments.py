"""PostgreSQL smoke coverage for saved manuscript comment anchors."""

import uuid

import pytest
from sqlalchemy import select

from modules.writing.models import WritingComment


@pytest.mark.asyncio
async def test_comment_anchor_persists_in_project_and_is_version_bound(
    async_client, db_session
):
    project = await async_client.post("/api/projects", json={"title": "批注 E2E"})
    assert project.status_code == 201, project.text
    novel_id = project.json()["id"]
    draft_response = await async_client.post(
        "/api/writing/drafts",
        json={
            "novel_id": novel_id,
            "chapter_index": 1,
            "title": "批注",
            "content": "甲😀乙",
        },
    )
    assert draft_response.status_code == 201, draft_response.text
    draft = draft_response.json()["draft"]
    response = await async_client.post(
        f"/api/writing/drafts/{draft['id']}/comments",
        json={
            "novel_id": novel_id,
            "source_hash": draft["content_hash"],
            "start_offset": 1,
            "end_offset": 3,
            "excerpt": "😀乙",
            "body": "调整这句。",
        },
    )
    assert response.status_code == 201, response.text
    saved = await db_session.scalar(
        select(WritingComment).where(
            WritingComment.id == uuid.UUID(response.json()["id"]),
            WritingComment.novel_id == uuid.UUID(novel_id),
        )
    )
    assert saved is not None
    assert saved.range_hash and saved.source_hash == draft["content_hash"]
    assert (saved.start_offset, saved.end_offset) == (1, 3)
