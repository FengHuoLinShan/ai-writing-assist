from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from infrastructure.tasks.models import AsyncTask
from modules.project.models import Project
from modules.project.smart_dedup import SmartDedupService
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_smart_dedup_groups_use_independent_postgresql_savepoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=2, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    project_id = uuid.uuid4()
    task_id = uuid.uuid4()
    groups = [
        _server_group("failed-group", "source-a", "primary-a"),
        _server_group("successful-group", "source-b", "primary-b"),
    ]

    async def fake_apply(
        db,
        novel_id,
        *,
        primary_entity_id,
        operations,
        validate_only=False,
        execution_fingerprints_prevalidated=False,
    ):
        if validate_only:
            return []
        assert execution_fingerprints_prevalidated is True
        project = (
            await db.execute(select(Project).where(Project.id == project_id))
        ).scalar_one()
        if primary_entity_id == "primary-a":
            project.settings = {"must_rollback": True}
            await db.flush()
            raise RuntimeError("forced PostgreSQL group failure")
        project.title = "successful group committed"
        await db.flush()
        return [{"action": "merge"}]

    monkeypatch.setattr(
        "modules.world.facade.apply_entity_fusion_group",
        fake_apply,
    )
    try:
        async with sessions.begin() as setup_db:
            setup_db.add(
                Project(
                    id=project_id,
                    title="before",
                    language="zh",
                    default_reveal_policy="author_safe",
                    settings={},
                )
            )
            await setup_db.flush()
            setup_db.add(
                AsyncTask(
                    id=task_id,
                    task_type="smart_dedup_scan",
                    status="done",
                    meta={"novel_id": str(project_id)},
                    result={"schema_version": 2, "groups": groups},
                )
            )

        async with sessions.begin() as db:
            result = await SmartDedupService().apply_groups(
                db,
                novel_id=str(project_id),
                scan_task_id=str(task_id),
                groups=[
                    _request_group("failed-group", "source-a", "primary-a"),
                    _request_group("successful-group", "source-b", "primary-b"),
                ],
                confirmed=True,
            )

        async with sessions() as verify_db:
            project = await verify_db.get(Project, project_id)
            assert project is not None
            assert project.settings == {}
            assert project.title == "successful group committed"
            assert [item["status"] for item in result["group_results"]] == [
                "failed",
                "success",
            ]
    finally:
        async with sessions.begin() as cleanup_db:
            await cleanup_db.execute(delete(AsyncTask).where(AsyncTask.id == task_id))
            await cleanup_db.execute(delete(Project).where(Project.id == project_id))
        await engine.dispose()


def _server_group(group_id: str, source: str, primary: str) -> dict:
    return {
        "group_id": group_id,
        "asset_type": "world_entity",
        "members": [
            {"asset_id": source, "title": source},
            {"asset_id": primary, "title": primary},
        ],
        "eligible_primary_asset_ids": [primary],
        "edges": [
            {
                "source_asset_id": source,
                "target_asset_id": primary,
                "allowed_actions": ["merge"],
                "source_execution_fingerprint": "a" * 64,
                "target_execution_fingerprint": "b" * 64,
            }
        ],
    }


def _request_group(group_id: str, source: str, primary: str) -> dict:
    return {
        "group_id": group_id,
        "asset_type": "world_entity",
        "primary_asset_id": primary,
        "operations": [
            {
                "source_asset_id": source,
                "action": "merge",
                "expected_source_execution_fingerprint": "a" * 64,
                "expected_target_execution_fingerprint": "b" * 64,
            }
        ],
    }
