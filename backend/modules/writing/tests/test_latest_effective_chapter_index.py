"""get_latest_effective_chapter_index — 写作进度查询（路线图阶段 0）。

覆盖：没有正文时返回 0；全空白稿件不算正文；返回最大有实质正文的章节号。
"""

from __future__ import annotations

import pytest

from modules.writing.facade import (
    create_draft_only,
    create_published_draft_only,
    get_latest_effective_chapter_index,
)


@pytest.mark.asyncio
async def test_no_drafts_returns_zero(db_session, test_project_id: str) -> None:
    assert await get_latest_effective_chapter_index(db_session, test_project_id) == 0


@pytest.mark.asyncio
async def test_whitespace_only_drafts_do_not_count(
    db_session, test_project_id: str
) -> None:
    await create_published_draft_only(
        db_session, test_project_id, 1, "第一章", "　\n \t"
    )
    await create_published_draft_only(db_session, test_project_id, 2, "第二章", "")

    assert await get_latest_effective_chapter_index(db_session, test_project_id) == 0


@pytest.mark.asyncio
async def test_returns_largest_substantive_chapter(
    db_session, test_project_id: str
) -> None:
    await create_published_draft_only(
        db_session, test_project_id, 1, "第一章", "第一章的正文"
    )
    await create_published_draft_only(
        db_session, test_project_id, 3, "第三章", "第三章的正文"
    )
    # 第五章的最新工作版本只剩空白，不算有正文。
    await create_published_draft_only(
        db_session, test_project_id, 5, "第五章", "第五章的旧正文"
    )
    await create_draft_only(db_session, test_project_id, 5, "第五章", "  ")

    assert await get_latest_effective_chapter_index(db_session, test_project_id) == 3


@pytest.mark.asyncio
async def test_latest_working_version_decides_substantive(
    db_session, test_project_id: str
) -> None:
    """以最新工作版本为准：最新版空白时不回退到旧版正文。"""
    await create_published_draft_only(
        db_session, test_project_id, 2, "第二章", "第二章的旧正文"
    )
    await create_draft_only(db_session, test_project_id, 2, "第二章", "")

    assert await get_latest_effective_chapter_index(db_session, test_project_id) == 0


@pytest.mark.asyncio
async def test_isolated_by_novel(db_session, test_project_id: str, project_factory) -> None:
    other_project = str(await project_factory.create_project(title="另一本书"))
    await create_published_draft_only(
        db_session, test_project_id, 4, "第四章", "本书正文"
    )

    assert await get_latest_effective_chapter_index(db_session, other_project) == 0
    assert await get_latest_effective_chapter_index(db_session, test_project_id) == 4
