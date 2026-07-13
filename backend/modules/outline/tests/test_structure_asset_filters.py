from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.foreshadowing_repository import ForeshadowingPlanRepository
from modules.outline.repositories import OutlineArcRepository, PlotThreadRepository
from modules.outline.reveal_repository import RevealPlanRepository
from modules.outline.schemas import OutlineArcCreate, PlotThreadCreate
from modules.project.models import Project

pytestmark = [pytest.mark.asyncio, pytest.mark.api]


async def _create_project(db_session: AsyncSession, title: str) -> str:
    project_id = uuid.uuid4()
    db_session.add(
        Project(
            id=project_id,
            title=title,
            genre="fantasy",
            tone="dark",
            language="zh",
            current_stage="outline",
        )
    )
    await db_session.flush()
    return str(project_id)


async def _create_thread(
    db_session: AsyncSession,
    novel_id: str,
    *,
    name: str,
    status: str,
    provenance_meta: dict,
) -> str:
    thread = await PlotThreadRepository().create(
        db_session,
        uuid.UUID(hex=novel_id),
        PlotThreadCreate(
            name=name,
            thread_type="main",
            start_chapter=1,
            status=status,
            provenance_meta=provenance_meta,
        ),
    )
    return str(thread.id)


async def _create_arc(
    db_session: AsyncSession,
    novel_id: str,
    *,
    title: str,
    status: str,
    provenance_meta: dict,
) -> str:
    arc = await OutlineArcRepository().create(
        db_session,
        uuid.UUID(hex=novel_id),
        OutlineArcCreate(
            title=title,
            arc_index=1,
            start_chapter=1,
            end_chapter=3,
            status=status,
            provenance_meta=provenance_meta,
        ),
    )
    return str(arc.id)


async def _create_foreshadowing(
    db_session: AsyncSession,
    novel_id: str,
    *,
    name: str,
    status: str,
    provenance_meta: dict,
) -> str:
    plan = await ForeshadowingPlanRepository().create(
        db_session,
        uuid.UUID(hex=novel_id),
        {
            "name": name,
            "planned_seed_chapter": 1,
            "status": status,
            "provenance_meta": provenance_meta,
        },
    )
    return str(plan.id)


async def _create_reveal(
    db_session: AsyncSession,
    novel_id: str,
    *,
    secret_summary: str,
    status: str,
    provenance_meta: dict,
) -> str:
    plan = await RevealPlanRepository().create(
        db_session,
        uuid.UUID(hex=novel_id),
        {
            "target_type": "world_entity",
            "target_id": uuid.uuid4(),
            "secret_summary": secret_summary,
            "status": status,
            "provenance_meta": provenance_meta,
        },
    )
    return str(plan.id)


Creator = Callable[
    [AsyncSession, str, str, str, dict],
    Awaitable[str],
]


async def _thread_creator(
    db_session: AsyncSession,
    novel_id: str,
    label: str,
    status: str,
    provenance_meta: dict,
) -> str:
    return await _create_thread(
        db_session,
        novel_id,
        name=label,
        status=status,
        provenance_meta=provenance_meta,
    )


async def _arc_creator(
    db_session: AsyncSession,
    novel_id: str,
    label: str,
    status: str,
    provenance_meta: dict,
) -> str:
    return await _create_arc(
        db_session,
        novel_id,
        title=label,
        status=status,
        provenance_meta=provenance_meta,
    )


async def _foreshadowing_creator(
    db_session: AsyncSession,
    novel_id: str,
    label: str,
    status: str,
    provenance_meta: dict,
) -> str:
    return await _create_foreshadowing(
        db_session,
        novel_id,
        name=label,
        status=status,
        provenance_meta=provenance_meta,
    )


async def _reveal_creator(
    db_session: AsyncSession,
    novel_id: str,
    label: str,
    status: str,
    provenance_meta: dict,
) -> str:
    return await _create_reveal(
        db_session,
        novel_id,
        secret_summary=label,
        status=status,
        provenance_meta=provenance_meta,
    )


@pytest.mark.parametrize(
    ("endpoint", "creator"),
    [
        ("/api/outline/threads", _thread_creator),
        ("/api/outline/arcs", _arc_creator),
        ("/api/outline/foreshadowing", _foreshadowing_creator),
        ("/api/outline/reveals", _reveal_creator),
    ],
    ids=["threads", "arcs", "foreshadowing", "reveals"],
)
async def test_structure_asset_lists_filter_by_status_and_provenance(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_project_id: str,
    endpoint: str,
    creator: Creator,
) -> None:
    other_project_id = await _create_project(db_session, "Other novel")
    matching_meta = {
        "source": "deep_import",
        "workflow_id": "wf-structure-a",
        "needs_review": True,
    }
    matching_id = await creator(
        db_session,
        test_project_id,
        "matching",
        "deprecated",
        matching_meta,
    )
    await creator(
        db_session,
        test_project_id,
        "wrong workflow",
        "deprecated",
        {
            "source": "deep_import",
            "workflow_id": "wf-structure-b",
            "needs_review": True,
        },
    )
    await creator(
        db_session,
        test_project_id,
        "wrong review",
        "deprecated",
        {
            "source": "deep_import",
            "workflow_id": "wf-structure-a",
            "needs_review": False,
        },
    )
    await creator(
        db_session,
        test_project_id,
        "wrong status",
        "draft",
        matching_meta,
    )
    await creator(
        db_session,
        other_project_id,
        "other novel",
        "deprecated",
        matching_meta,
    )
    await db_session.flush()

    resp = await async_client.get(
        endpoint,
        params={
            "novel_id": test_project_id,
            "status": "deprecated",
            "source": "deep_import",
            "workflow_id": "wf-structure-a",
            "needs_review": True,
            "skip": 0,
            "limit": 10,
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert [item["id"] for item in data["items"]] == [matching_id]


@pytest.mark.parametrize(
    ("endpoint", "creator"),
    [
        ("/api/outline/threads", _thread_creator),
        ("/api/outline/arcs", _arc_creator),
        ("/api/outline/foreshadowing", _foreshadowing_creator),
        ("/api/outline/reveals", _reveal_creator),
    ],
    ids=["threads", "arcs", "foreshadowing", "reveals"],
)
async def test_structure_asset_lists_exclude_deprecated_before_pagination(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_project_id: str,
    endpoint: str,
    creator: Creator,
) -> None:
    other_project_id = await _create_project(db_session, "Other novel")
    active_ids = {
        await creator(db_session, test_project_id, "active a", "draft", {}),
        await creator(db_session, test_project_id, "active b", "canonical", {}),
    }
    deprecated_id = await creator(
        db_session,
        test_project_id,
        "deprecated",
        "deprecated",
        {},
    )
    await creator(db_session, other_project_id, "other novel", "draft", {})
    await db_session.flush()

    first_page = await async_client.get(
        endpoint,
        params={"novel_id": test_project_id, "skip": 0, "limit": 1},
    )
    second_page = await async_client.get(
        endpoint,
        params={"novel_id": test_project_id, "skip": 1, "limit": 1},
    )

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    first_data = first_page.json()
    second_data = second_page.json()
    assert first_data["total"] == second_data["total"] == 2
    returned_ids = {first_data["items"][0]["id"], second_data["items"][0]["id"]}
    assert returned_ids == active_ids
    assert deprecated_id not in returned_ids
