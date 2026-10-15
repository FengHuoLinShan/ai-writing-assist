"""Validity notices must select the first actionable rows, not the first rows."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from modules.world.notice_sources import _paged_rows


@pytest.mark.asyncio
async def test_notice_scan_reaches_rows_after_the_first_page() -> None:
    rows = list(range(101))
    db = AsyncMock()

    def page(statement):
        offset = (
            statement._offset_clause.value if statement._offset_clause is not None else 0
        )
        limit = statement._limit_clause.value
        result = AsyncMock()
        result.all = lambda: rows[offset : offset + limit]
        return result

    db.execute.side_effect = page
    seen = [row async for row in _paged_rows(db, select(1))]
    assert seen == rows
    assert db.execute.await_count == 2
