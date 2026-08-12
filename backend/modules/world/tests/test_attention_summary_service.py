"""World author-attention summary projection tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.world.services.attention_summary_service import (
    WorldAttentionSummaryService,
)


@pytest.mark.asyncio
async def test_attention_summary_uses_review_queues_for_one_novel() -> None:
    db = SimpleNamespace()
    entity_service = SimpleNamespace(
        list=AsyncMock(return_value=SimpleNamespace(total=2))
    )
    alias_service = SimpleNamespace(
        list_review_groups=AsyncMock(return_value=SimpleNamespace(item_total=3))
    )
    relation_service = SimpleNamespace(
        list_review_groups=AsyncMock(return_value=SimpleNamespace(item_total=4))
    )
    service = WorldAttentionSummaryService(
        entity_service=entity_service,
        alias_service=alias_service,
        relation_service=relation_service,
    )

    result = await service.get_summary(db, "novel-1")

    assert result.novel_id == "novel-1"
    assert result.total == 9
    entity_service.list.assert_awaited_once_with(
        db,
        "novel-1",
        display_state="review",
        skip=0,
        limit=1,
    )
    alias_service.list_review_groups.assert_awaited_once_with(
        db, "novel-1", skip=0, limit=1
    )
    relation_service.list_review_groups.assert_awaited_once_with(
        db, "novel-1", skip=0, limit=1
    )
