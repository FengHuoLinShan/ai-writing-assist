from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from core.dependencies import get_db
from infrastructure.tasks.models import AsyncTask
from infrastructure.tasks.registry import TaskRegistry
from modules.project.models import Project


class _GenericSubmitMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    novel_id: uuid.UUID
    key: str


async def _add_project(
    db_session: AsyncSession,
    novel_id: str,
    *,
    deleted: bool = False,
) -> None:
    db_session.add(
        Project(
            id=uuid.UUID(novel_id),
            title="Task API project",
            deleted_at=datetime.now(UTC) if deleted else None,
        )
    )
    await db_session.flush()


@pytest_asyncio.fixture
async def async_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Requested-With": "XMLHttpRequest"},
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "task_type",
    ["world_entity_extraction", "world_bible_synopsis_refresh"],
)
async def test_submit_task_rejects_dangerous_domain_task(
    async_client: AsyncClient,
    task_type: str,
) -> None:
    resp = await async_client.post(
        "/api/tasks",
        json={
            "task_type": task_type,
            "meta": {
                "novel_id": "00000000-0000-0000-0000-000000000701",
                "start_chapter": 1,
                "end_chapter": 3,
            },
        },
    )

    assert resp.status_code == 403
    assert "module API" in resp.text


@pytest.mark.asyncio
async def test_task_status_requires_matching_novel_id(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner_novel = str(uuid.uuid4())
    other_novel = str(uuid.uuid4())
    await _add_project(db_session, owner_novel)
    await _add_project(db_session, other_novel)
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="test_safe_task",
        status="done",
        meta={"novel_id": owner_novel, "secret": "only-owner"},
        result={"ok": True},
    )
    db_session.add(task)
    await db_session.flush()

    missing = await async_client.get(f"/api/tasks/{task.id}")
    assert missing.status_code == 422

    wrong = await async_client.get(
        f"/api/tasks/{task.id}",
        params={"novel_id": other_novel},
    )
    assert wrong.status_code == 404
    assert "only-owner" not in wrong.text

    ok = await async_client.get(
        f"/api/tasks/{task.id}",
        params={"novel_id": owner_novel},
    )
    assert ok.status_code == 200
    assert ok.json()["meta"]["secret"] == "only-owner"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["running", "failed", "done"])
async def test_task_status_hides_private_top_level_result_checkpoints(
    async_client: AsyncClient,
    db_session: AsyncSession,
    status: str,
) -> None:
    novel_id = str(uuid.uuid4())
    await _add_project(db_session, novel_id)
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="world_alias_relation_extraction",
        status=status,
        meta={"novel_id": novel_id},
        result={
            "_alias_relation_task_v1": {
                "stage": "llm_complete",
                "receipt": {"quote": "private-provider-receipt"},
            },
            "public_summary": {"total_aliases": 1},
        },
    )
    db_session.add(task)
    await db_session.flush()

    response = await async_client.get(
        f"/api/tasks/{task.id}",
        params={"novel_id": novel_id},
    )

    assert response.status_code == 200
    assert response.json()["result"] == {"public_summary": {"total_aliases": 1}}
    assert "private-provider-receipt" not in response.text
    assert "_alias_relation_task_v1" in (task.result or {})


@pytest.mark.asyncio
async def test_cancel_task_requires_matching_novel_id(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner_novel = str(uuid.uuid4())
    other_novel = str(uuid.uuid4())
    await _add_project(db_session, owner_novel)
    await _add_project(db_session, other_novel)
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="test_safe_task",
        status="pending",
        meta={"novel_id": owner_novel},
    )
    db_session.add(task)
    await db_session.flush()

    wrong = await async_client.post(
        f"/api/tasks/{task.id}/cancel",
        params={"novel_id": other_novel},
    )
    assert wrong.status_code == 404

    ok = await async_client.post(
        f"/api/tasks/{task.id}/cancel",
        params={"novel_id": owner_novel},
    )
    assert ok.status_code == 200
    assert ok.json()["cancelled"] is True


@pytest.mark.asyncio
async def test_retry_task_is_novel_isolated_and_policy_limited(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner_novel = str(uuid.uuid4())
    other_novel = str(uuid.uuid4())
    await _add_project(db_session, owner_novel)
    await _add_project(db_session, other_novel)
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="rag_reindex_novel",
        status="failed",
        meta={"novel_id": owner_novel},
        recovery_policy="auto_requeue",
        attempt=1,
        max_attempts=2,
    )
    db_session.add(task)
    await db_session.flush()

    wrong = await async_client.post(
        f"/api/tasks/{task.id}/retry",
        params={"novel_id": other_novel},
    )
    assert wrong.status_code == 404

    retried = await async_client.post(
        f"/api/tasks/{task.id}/retry",
        params={"novel_id": owner_novel},
    )
    assert retried.status_code == 200
    assert retried.json()["status"] == "pending"

    rejected = await async_client.post(
        f"/api/tasks/{task.id}/retry",
        params={"novel_id": owner_novel},
    )
    assert rejected.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["status", "cancel", "retry"])
async def test_task_operations_hide_recycled_project_tasks(
    async_client: AsyncClient,
    db_session: AsyncSession,
    action: str,
) -> None:
    novel_id = str(uuid.uuid4())
    await _add_project(db_session, novel_id, deleted=True)
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="rag_reindex_novel",
        status="failed" if action == "retry" else "pending",
        meta={"novel_id": novel_id, "secret": "must-not-leak"},
        result={"private": "must-not-leak"},
        recovery_policy="auto_requeue",
        attempt=0,
        max_attempts=2,
    )
    db_session.add(task)
    await db_session.flush()

    path = f"/api/tasks/{task.id}"
    if action != "status":
        path = f"{path}/{action}"
    response = await async_client.request(
        "GET" if action == "status" else "POST",
        path,
        params={"novel_id": novel_id},
    )

    assert response.status_code == 404
    assert "must-not-leak" not in response.text
    assert task.status == ("failed" if action == "retry" else "pending")


@pytest.mark.asyncio
async def test_generic_submit_validates_type_before_optional_project_guard(
    async_client: AsyncClient,
) -> None:
    deleted_novel_id = "00000000-0000-0000-0000-000000000709"
    response = await async_client.post(
        "/api/tasks",
        json={
            "task_type": "unknown-task",
            "meta": {"novel_id": deleted_novel_id},
        },
    )

    assert response.status_code == 400
    assert "Unknown task type" in response.text


@pytest.mark.asyncio
async def test_generic_submit_rejects_known_module_task_before_project_guard(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    deleted_novel_id = str(uuid.uuid4())
    await _add_project(db_session, deleted_novel_id, deleted=True)

    response = await async_client.post(
        "/api/tasks",
        json={
            "task_type": "rag_reindex_novel",
            "meta": {"novel_id": deleted_novel_id},
        },
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_generic_submit_keeps_explicit_custom_task_available_and_guarded(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    active_novel_id = str(uuid.uuid4())
    deleted_novel_id = str(uuid.uuid4())
    await _add_project(db_session, active_novel_id)
    await _add_project(db_session, deleted_novel_id, deleted=True)

    async def handler(db, task):
        return {"ok": True}

    registry = TaskRegistry()
    registry.register(
        "test_generic_submit",
        handler,
        generic_submit_schema=_GenericSubmitMeta,
    )
    try:
        private_key = "PRIVATE_DYNAMIC_META_KEY"
        invalid = await async_client.post(
            "/api/tasks",
            json={
                "task_type": "test_generic_submit",
                "meta": {
                    "novel_id": active_novel_id,
                    "key": "safe",
                    private_key: "must-not-echo",
                },
            },
        )
        assert invalid.status_code == 422
        assert private_key not in invalid.text
        assert "must-not-echo" not in invalid.text

        accepted = await async_client.post(
            "/api/tasks",
            json={
                "task_type": "test_generic_submit",
                "meta": {"novel_id": active_novel_id, "key": "safe"},
            },
        )
        assert accepted.status_code == 201, accepted.text
        task = await db_session.get(AsyncTask, uuid.UUID(accepted.json()["task_id"]))
        assert task is not None
        assert task.meta == {"novel_id": active_novel_id, "key": "safe"}

        guarded = await async_client.post(
            "/api/tasks",
            json={
                "task_type": "test_generic_submit",
                "meta": {"novel_id": deleted_novel_id, "key": "safe"},
            },
        )
        assert guarded.status_code == 404
    finally:
        registry.unregister("test_generic_submit")
