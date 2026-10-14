"""Synthetic PostgreSQL provenance and SAVEPOINT behavior for map notices."""

import pytest
from sqlalchemy import select, text

from core.container import container_scope
from core.service_keys import WORLD_READ_MAP_CHAPTER_CONSUMERS
from modules.evolution.tests.test_map_consumption import changed_receipt, saved_map
from modules.writing.facade import create_published_draft_only

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_map_saved_head_is_reported_and_query_failure_does_not_abort_save_pg(
    db_session,
    test_project_id,
):
    old = await create_published_draft_only(
        db_session, test_project_id, 1, "旧", "东岸是港口"
    )
    node, revision = await saved_map(db_session, test_project_id, old)
    await create_published_draft_only(db_session, test_project_id, 1, "新", "东岸是山地")
    receipt = await changed_receipt(db_session, test_project_id)
    assert receipt.invalidated_consumers["map_atlas"]["maps"][0]["node_id"] == str(
        node.id
    )
    assert revision.status == "saved"

    async def failed_query(db, *args, **kwargs):
        await db.execute(text("SELECT * FROM g8_synthetic_missing_table"))

    with container_scope({WORLD_READ_MAP_CHAPTER_CONSUMERS: failed_query}):
        failed = await changed_receipt(db_session, test_project_id)
    assert failed.invalidated_consumers["map_atlas"]["checked"] is False
    assert "地图册未核对" in failed.coverage_note
    assert "story_state" in failed.invalidated_consumers
    assert await db_session.scalar(select(1)) == 1
    await db_session.flush()
