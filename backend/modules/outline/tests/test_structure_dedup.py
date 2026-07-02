from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.repositories import PlotThreadRepository
from modules.outline.schemas import PlotThreadCreate
from modules.outline.structure_dedup import OutlineStructureDedupService

pytestmark = [pytest.mark.asyncio]


async def _create_thread(
    db: AsyncSession,
    novel_id: str,
    *,
    name: str,
    status: str = "draft",
    start_chapter: int = 1,
) -> str:
    thread = await PlotThreadRepository().create(
        db,
        uuid.UUID(hex=novel_id),
        PlotThreadCreate(
            name=name,
            thread_type="main",
            summary=f"{name} 的主线",
            visible_goal="查明真相",
            start_chapter=start_chapter,
            status=status,
        ),
    )
    return str(thread.id)


async def test_structure_dedup_suggests_exact_duplicate_thread(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    await _create_thread(db_session, test_project_id, name="旧日调查线", status="draft")
    await _create_thread(
        db_session,
        test_project_id,
        name="旧日调查线",
        status="candidate",
        start_chapter=2,
    )

    result = await OutlineStructureDedupService().suggest(
        db_session,
        novel_id=test_project_id,
        asset_types=["plot_thread"],
    )

    assert result["suggestion_count"] == 1
    suggestion = result["suggestions"][0]
    assert suggestion["asset_type"] == "plot_thread"
    assert suggestion["action"] == "merge"
    assert suggestion["target_status"] == "draft"
    assert suggestion["source_status"] == "candidate"


async def test_structure_dedup_apply_deprecates_duplicate_thread(
    db_session: AsyncSession,
    test_project_id: str,
) -> None:
    target_id = await _create_thread(
        db_session,
        test_project_id,
        name="王都暗线",
        status="draft",
    )
    source_id = await _create_thread(
        db_session,
        test_project_id,
        name="王都暗线",
        status="candidate",
        start_chapter=2,
    )

    result = await OutlineStructureDedupService().apply(
        db_session,
        novel_id=test_project_id,
        confirmed=True,
        suggestions=[
            {
                "asset_type": "plot_thread",
                "action": "deprecate_duplicate",
                "source_asset_id": source_id,
                "target_asset_id": target_id,
            }
        ],
    )

    assert result["applied"] == 1
    source = await PlotThreadRepository().get(db_session, uuid.UUID(hex=source_id))
    assert source is not None
    assert source.status == "deprecated"
    assert source.provenance_meta["merged_into_asset_id"] == target_id
    assert source.provenance_meta["dedup_source"] == "smart_dedup"
