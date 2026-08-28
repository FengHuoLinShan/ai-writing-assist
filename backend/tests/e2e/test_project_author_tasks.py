"""PostgreSQL contract for project-owned author tasks."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from modules.project.models import Project, ProjectAuthorTask

XHR = {"X-Requested-With": "XMLHttpRequest"}


@pytest.mark.asyncio
async def test_author_task_constraints_cas_and_project_cascade(
    async_client,
    db_session,
) -> None:
    project = await async_client.post("/api/projects", json={"title": "PG 作者任务"})
    project_id = project.json()["id"]
    created = await async_client.post(
        f"/api/projects/{project_id}/author-tasks",
        json={"title": "核对港口规则"},
        headers=XHR,
    )
    task = created.json()

    completed = await async_client.patch(
        f"/api/projects/{project_id}/author-tasks/{task['id']}",
        json={"status": "completed", "expected_updated_at": task["updated_at"]},
        headers=XHR,
    )
    repeated = await async_client.patch(
        f"/api/projects/{project_id}/author-tasks/{task['id']}",
        json={"status": "completed", "expected_updated_at": task["updated_at"]},
        headers=XHR,
    )
    assert repeated.status_code == 200
    assert repeated.json()["updated_at"] == completed.json()["updated_at"]
    assert repeated.json()["completed_at"] == completed.json()["completed_at"]

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                ProjectAuthorTask(
                    novel_id=uuid.UUID(project_id),
                    title="   ",
                    status="open",
                )
            )
            await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                ProjectAuthorTask(
                    novel_id=uuid.UUID(project_id),
                    title="过长备注",
                    note="x" * 4001,
                    status="open",
                )
            )
            await db_session.flush()

    await db_session.execute(
        delete(Project).where(Project.id == uuid.UUID(project_id))
    )
    await db_session.flush()
    assert (
        await db_session.scalar(
            select(func.count(ProjectAuthorTask.id)).where(
                ProjectAuthorTask.novel_id == uuid.UUID(project_id)
            )
        )
        == 0
    )
