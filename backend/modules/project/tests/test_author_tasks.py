"""Author task lifecycle, isolation, source loss, and summary tests."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError
from modules.account.models import Account
from modules.project.models import Project, ProjectAuthorTask

XHR = {"X-Requested-With": "XMLHttpRequest"}


async def _project(async_client: AsyncClient, title: str) -> str:
    response = await async_client.post("/api/projects", json={"title": title})
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.asyncio
async def test_author_task_lifecycle_and_workspace_summary(
    async_client: AsyncClient,
) -> None:
    project_id = await _project(async_client, "任务测试")
    today = date.today()
    created = await async_client.post(
        f"/api/projects/{project_id}/author-tasks",
        json={"title": "  核对港口规则  ", "due_date": today.isoformat()},
        headers=XHR,
    )
    assert created.status_code == 201
    task = created.json()
    assert task["title"] == "核对港口规则"
    assert task["status"] == "open"

    listing = await async_client.get(
        f"/api/projects/{project_id}/author-tasks",
        params={"scope": "today", "on_date": today.isoformat()},
    )
    assert listing.status_code == 200
    assert listing.json()["counts"] == {
        "today": 1,
        "inbox": 0,
        "later": 0,
        "completed": 0,
    }

    completed = await async_client.patch(
        f"/api/projects/{project_id}/author-tasks/{task['id']}",
        json={"status": "completed", "expected_updated_at": task["updated_at"]},
        headers=XHR,
    )
    assert completed.status_code == 200
    assert completed.json()["completed_at"] is not None

    repeated = await async_client.patch(
        f"/api/projects/{project_id}/author-tasks/{task['id']}",
        json={"status": "completed", "expected_updated_at": task["updated_at"]},
        headers=XHR,
    )
    assert repeated.status_code == 200
    assert repeated.json()["updated_at"].rstrip("Z") == completed.json()[
        "updated_at"
    ].rstrip("Z")
    assert repeated.json()["completed_at"].rstrip("Z") == completed.json()[
        "completed_at"
    ].rstrip("Z")

    stale = await async_client.patch(
        f"/api/projects/{project_id}/author-tasks/{task['id']}",
        json={"status": "open", "expected_updated_at": task["updated_at"]},
        headers=XHR,
    )
    assert stale.status_code == 409
    assert stale.json()["error"] == "author_task_changed"

    reopened = await async_client.patch(
        f"/api/projects/{project_id}/author-tasks/{task['id']}",
        json={
            "status": "open",
            "expected_updated_at": completed.json()["updated_at"],
        },
        headers=XHR,
    )
    assert reopened.status_code == 200
    assert reopened.json()["completed_at"] is None

    blind_edit = await async_client.patch(
        f"/api/projects/{project_id}/author-tasks/{task['id']}",
        json={"title": "不应盲写"},
        headers=XHR,
    )
    assert blind_edit.status_code == 400

    archived = await async_client.patch(
        f"/api/projects/{project_id}/author-tasks/{task['id']}",
        json={
            "status": "archived",
            "expected_updated_at": reopened.json()["updated_at"],
        },
        headers=XHR,
    )
    assert archived.status_code == 200
    normal_views = await async_client.get(
        f"/api/projects/{project_id}/author-tasks",
        params={"scope": "today", "on_date": today.isoformat()},
    )
    assert normal_views.json()["items"] == []

    summary = await async_client.get(f"/api/projects/{project_id}/workspace-summary")
    assert summary.status_code == 200
    assert summary.json()["author_tasks"] == {
        "today_count": 0,
        "inbox_count": 0,
        "later_count": 0,
        "preview": [],
    }


@pytest.mark.asyncio
async def test_author_tasks_group_by_date_and_preview_only_due_items(
    async_client: AsyncClient,
) -> None:
    project_id = await _project(async_client, "日期视图")
    today = date.today()
    for payload in (
        {"title": "逾期", "due_date": (today - timedelta(days=1)).isoformat()},
        {"title": "收件箱"},
        {"title": "之后", "due_date": (today + timedelta(days=1)).isoformat()},
    ):
        response = await async_client.post(
            f"/api/projects/{project_id}/author-tasks",
            json=payload,
            headers=XHR,
        )
        assert response.status_code == 201

    summary = (
        await async_client.get(f"/api/projects/{project_id}/workspace-summary")
    ).json()["author_tasks"]
    assert (summary["today_count"], summary["inbox_count"], summary["later_count"]) == (
        1,
        1,
        1,
    )
    assert [item["title"] for item in summary["preview"]] == ["逾期"]


@pytest.mark.asyncio
async def test_author_task_body_and_project_isolation(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    project_a = await _project(async_client, "任务 A")
    project_b = await _project(async_client, "任务 B")
    rejected = await async_client.post(
        f"/api/projects/{project_a}/author-tasks",
        json={"title": "越界", "novel_id": project_b, "owner_id": str(uuid.uuid4())},
        headers=XHR,
    )
    assert rejected.status_code == 422

    created = await async_client.post(
        f"/api/projects/{project_a}/author-tasks",
        json={"title": "只属于 A"},
        headers=XHR,
    )
    task_id = created.json()["id"]
    cross_project = await async_client.patch(
        f"/api/projects/{project_b}/author-tasks/{task_id}",
        json={"status": "completed"},
        headers=XHR,
    )
    assert cross_project.status_code == 404

    foreign_owner = uuid.uuid4()
    foreign_project = uuid.uuid4()
    db_session.add(Account(id=foreign_owner, status="active", support_code="TASK-OWNER"))
    db_session.add(
        Project(
            id=foreign_project,
            owner_id=foreign_owner,
            title="他人任务",
            settings={},
        )
    )
    db_session.add(
        ProjectAuthorTask(
            novel_id=foreign_project,
            title="不可见",
            status="open",
        )
    )
    await db_session.flush()
    foreign_list = await async_client.get(
        f"/api/projects/{foreign_project}/author-tasks",
        params={"scope": "inbox"},
    )
    assert foreign_list.status_code == 404


@pytest.mark.asyncio
async def test_author_task_source_validation_and_lost_source_projection(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    project_id = await _project(async_client, "来源失效")
    missing_source = await async_client.post(
        f"/api/projects/{project_id}/author-tasks",
        json={
            "title": "不存在的来源",
            "source": {"kind": "world_entity", "id": str(uuid.uuid4())},
        },
        headers=XHR,
    )
    assert missing_source.status_code == 404

    db_session.add(
        ProjectAuthorTask(
            novel_id=uuid.UUID(project_id),
            title="保留作者文字",
            status="open",
            source_kind="world_entity",
            source_id=str(uuid.uuid4()),
        )
    )
    await db_session.flush()
    listing = await async_client.get(
        f"/api/projects/{project_id}/author-tasks",
        params={"scope": "inbox"},
    )
    assert listing.status_code == 200
    item = listing.json()["items"][0]
    assert item["title"] == "保留作者文字"
    assert item["source"]["available"] is False
    assert item["source"]["label"] == "世界对象已失效"


@pytest.mark.asyncio
async def test_author_task_source_boundaries_reject_invalid_ids_and_missing_scene(
    async_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modules.story import facade as story_facade
    from modules.world import facade as world_facade
    from modules.writing import facade as writing_facade

    project_id = await _project(async_client, "来源边界")
    writing_calls: list[list[int]] = []
    scene_calls: list[str] = []

    async def invalid_world_source(*_args, **_kwargs):
        raise ValidationError("无效世界资料来源")

    async def list_chapters(_db, _novel_id, chapter_indices, **_kwargs):
        writing_calls.append(chapter_indices)
        return []

    async def missing_scene(_db, _novel_id, scene_id):
        scene_calls.append(scene_id)
        return None

    monkeypatch.setattr(
        world_facade,
        "get_world_bible_projection_candidates",
        invalid_world_source,
    )
    monkeypatch.setattr(
        writing_facade,
        "list_latest_drafts_for_chapters",
        list_chapters,
    )
    monkeypatch.setattr(story_facade, "get_scene_contract", missing_scene)

    invalid_world = await async_client.post(
        f"/api/projects/{project_id}/author-tasks",
        json={
            "title": "世界资料已失效",
            "source": {"kind": "world_page", "id": str(uuid.uuid4())},
        },
        headers=XHR,
    )
    invalid_chapter = await async_client.post(
        f"/api/projects/{project_id}/author-tasks",
        json={
            "title": "章节编号非法",
            "source": {"kind": "writing_chapter", "id": "１"},
        },
        headers=XHR,
    )

    async def unavailable_chapter(_db, _novel_id, chapter_indices, **_kwargs):
        writing_calls.append(chapter_indices)
        raise ValidationError("章节来源不可用")

    monkeypatch.setattr(
        writing_facade,
        "list_latest_drafts_for_chapters",
        unavailable_chapter,
    )
    missing_chapter = await async_client.post(
        f"/api/projects/{project_id}/author-tasks",
        json={
            "title": "章节已失效",
            "source": {"kind": "writing_chapter", "id": "2"},
        },
        headers=XHR,
    )
    scene_id = str(uuid.uuid4())
    missing_scene_response = await async_client.post(
        f"/api/projects/{project_id}/author-tasks",
        json={
            "title": "Scene 已失效",
            "source": {"kind": "outline_scene", "id": scene_id},
        },
        headers=XHR,
    )

    assert invalid_world.status_code == 404
    assert invalid_chapter.status_code == 404
    assert missing_chapter.status_code == 404
    assert missing_scene_response.status_code == 404
    assert writing_calls == [[2]]
    assert scene_calls == [scene_id]
