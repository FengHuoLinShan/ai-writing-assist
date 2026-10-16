from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.account.models import Account
from modules.project.models import Project
from modules.writing.models import WritingDraft


@pytest.mark.asyncio
async def test_chapter_order_http_preview_confirm_history_and_restore(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    project_response = await async_client.post(
        "/api/projects",
        json={"title": "章节目录 HTTP 测试"},
    )
    assert project_response.status_code == 201, project_response.text
    novel_id = project_response.json()["id"]

    draft_ids = []
    for chapter_index, title, content in (
        (1, "旧港", "第一章正文。"),
        (2, "来信", "第二章正文。"),
    ):
        response = await async_client.post(
            "/api/writing/drafts/autosave",
            json={
                "novel_id": novel_id,
                "chapter_index": chapter_index,
                "title": title,
                "content": content,
            },
        )
        assert response.status_code == 201, response.text
        draft_ids.append(uuid.UUID(response.json()["id"]))

    preview_response = await async_client.post(
        "/api/writing/chapters/order/preview",
        params={"novel_id": novel_id},
        json={"chapter_indices": [2, 1]},
    )
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    assert preview["requires_r3_confirmation"] is True
    assert preview["source_order"] == [1, 2]
    assert preview["target_order"] == [2, 1]
    assert preview["story_impact"]["blockers"] == []

    unchanged = list(
        (
            await db_session.scalars(
                select(WritingDraft).where(WritingDraft.id.in_(draft_ids))
            )
        ).all()
    )
    assert {row.id: row.chapter_index for row in unchanged} == {
        draft_ids[0]: 1,
        draft_ids[1]: 2,
    }

    confirm_response = await async_client.post(
        f"/api/writing/chapters/order/{preview['receipt_id']}/confirm",
        params={"novel_id": novel_id},
        json={"expected_preview_hash": preview["preview_hash"], "confirmed": True},
    )
    assert confirm_response.status_code == 200, confirm_response.text
    executed = confirm_response.json()
    assert executed["status"] == "executed"
    assert executed["result_ref"] == {
        "type": "writing_chapter_order",
        "id": preview["receipt_id"],
    }

    replay = await async_client.post(
        f"/api/writing/chapters/order/{preview['receipt_id']}/confirm",
        params={"novel_id": novel_id},
        json={"expected_preview_hash": preview["preview_hash"], "confirmed": True},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] is True

    history_response = await async_client.get(
        "/api/writing/chapters/order/history",
        params={"novel_id": novel_id},
    )
    assert history_response.status_code == 200, history_response.text
    assert history_response.json()["items"][0]["status"] == "executed"

    restore_preview_response = await async_client.get(
        f"/api/writing/chapters/order/{preview['receipt_id']}/restore-preview",
        params={"novel_id": novel_id},
    )
    assert restore_preview_response.status_code == 200, restore_preview_response.text
    restore_preview = restore_preview_response.json()
    assert restore_preview["can_restore"] is True

    restore_response = await async_client.post(
        f"/api/writing/chapters/order/{preview['receipt_id']}/restore",
        params={"novel_id": novel_id},
        json={
            "expected_preview_hash": restore_preview["restore_preview_hash"],
            "confirmed": True,
        },
    )
    assert restore_response.status_code == 200, restore_response.text
    restored = restore_response.json()
    assert restored["status"] == "restored"
    assert restored["result_ref"] == executed["result_ref"]

    final_rows = list(
        (
            await db_session.scalars(
                select(WritingDraft).where(WritingDraft.id.in_(draft_ids))
            )
        ).all()
    )
    assert {row.id: row.chapter_index for row in final_rows} == {
        draft_ids[0]: 1,
        draft_ids[1]: 2,
    }


@pytest.mark.asyncio
async def test_chapter_order_and_fact_timeline_http_hide_foreign_owner(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    created = await async_client.post(
        "/api/projects", json={"title": "隔离中的章节操作"}
    )
    assert created.status_code == 201, created.text
    novel_id = uuid.UUID(created.json()["id"])
    owner = Account(support_code=f"ORDER-{uuid.uuid4().hex[:12]}")
    db_session.add(owner)
    await db_session.flush()
    project = await db_session.get(Project, novel_id)
    assert project is not None
    project.owner_id = owner.id
    await db_session.flush()

    requests = [
        await async_client.post(
            "/api/writing/chapters/order/preview",
            params={"novel_id": str(novel_id)},
            json={"chapter_indices": [2, 1]},
        ),
        await async_client.get(
            "/api/writing/chapters/order/history",
            params={"novel_id": str(novel_id)},
        ),
        await async_client.get(
            f"/api/novels/{novel_id}/memories/fact-timeline"
        ),
    ]
    assert [response.status_code for response in requests] == [404, 404, 404]
