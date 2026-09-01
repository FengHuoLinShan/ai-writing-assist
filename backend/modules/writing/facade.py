"""
Writing Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from modules.writing.contracts import (
    ManuscriptReadContract,
    ManuscriptSearchHitContract,
    SourceRangeRefContract,
    WritingAuthorAttentionItemContract,
    WritingDraftContract,
    WritingProjectStatsContract,
)
from modules.writing.manuscript_source import ManuscriptSourceService
from modules.writing.schemas import WritingDraftCreate
from modules.writing.services import WritingConflictCheckService, WritingDraftService

__all__ = [
    "adopt_candidate_to_working",
    "build_manuscript_range_ref",
    "create_draft",
    "create_draft_only",
    "create_published_draft_only",
    "create_published_drafts_only",
    "deprecate_chapter_versions",
    "get_author_attention_items",
    "get_draft",
    "get_latest_draft_for_chapter",
    "get_project_writing_stats",
    "grep_manuscript",
    "list_chapter_indices",
    "list_effective_chapter_indices",
    "list_latest_drafts_for_chapters",
    "list_manuscript_sources",
    "list_project_writing_stats",
    "lock_chapter_versions_for_revalidation",
    "read_manuscript_range",
]

_service = WritingDraftService()
_conflict_service = WritingConflictCheckService()
_manuscript_source = ManuscriptSourceService()


async def create_draft_only(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
    title: str | None = None,
    content: str = "",
) -> WritingDraftContract:
    """创建正文草稿（纯持久化，不入队任务）"""
    data = WritingDraftCreate(
        novel_id=novel_id,
        chapter_index=chapter_index,
        title=title or f"第{chapter_index}章",
        content=content,
    )
    return await _service.create_draft_contract(db, data)


async def create_published_draft_only(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
    title: str | None = None,
    content: str = "",
) -> WritingDraftContract:
    """创建已发布正文版本（纯持久化，不入队任务）"""
    data = WritingDraftCreate(
        novel_id=novel_id,
        chapter_index=chapter_index,
        title=title or f"第{chapter_index}章",
        content=content,
    )
    return await _service.create_published_draft_contract(db, data)


async def create_published_drafts_only(
    db: AsyncSession,
    novel_id: str,
    chapters: list[dict[str, object]],
) -> list[WritingDraftContract]:
    """批量创建已发布正文版本（纯持久化，不入队任务）。"""
    data_items = [
        WritingDraftCreate(
            novel_id=novel_id,
            chapter_index=int(chapter["chapter_index"]),
            title=chapter.get("title") or f"第{chapter['chapter_index']}章",
            content=str(chapter.get("content") or ""),
        )
        for chapter in chapters
    ]
    return await _service.create_published_draft_contracts(db, data_items)


async def deprecate_chapter_versions(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
) -> int:
    """Soft-delete every version of one chapter for a confirmed source update."""
    return await _service.delete_chapter(db, novel_id, chapter_index)


async def create_draft(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
    title: str | None = None,
    content: str = "",
) -> tuple[WritingDraftContract, str]:
    """创建正文草稿并触发发布流程（兼容旧接口，新代码优先用 create_draft_only）

    Returns:
        (WritingDraftContract, task_id) — 草稿契约 + 发布任务 ID
    """
    from infrastructure.tasks.enqueuer import enqueue_task

    draft = await create_published_draft_only(db, novel_id, chapter_index, title, content)
    task_id = enqueue_task(
        db,
        "publish_chapter",
        meta={"novel_id": novel_id, "chapter_index": chapter_index},
        novel_id=novel_id,
    )
    return draft, task_id


async def get_draft(
    db: AsyncSession,
    novel_id: str,
    draft_id: str,
) -> WritingDraftContract | None:
    """获取单个草稿的契约信息"""
    return await _service.get_draft_contract(db, novel_id, draft_id)


async def list_drafts_by_ids(
    db: AsyncSession,
    novel_id: str,
    draft_ids: list[str],
) -> list[WritingDraftContract]:
    """按 ID 批量获取草稿契约;隔离语义与 get_draft 一致。"""
    return await _service.list_draft_contracts(db, novel_id, draft_ids)


async def adopt_candidate_to_working(
    db: AsyncSession,
    novel_id: str,
    draft_id: str,
    *,
    adopted_by: str = "author",
) -> WritingDraftContract:
    """Adopt an AI writing suggestion into the normal working-draft lifecycle."""
    return await _service.adopt_candidate_to_working_contract(
        db,
        draft_id,
        novel_id,
        adopted_by=adopted_by,
    )


async def get_latest_draft_for_chapter(
    db: AsyncSession,
    novel_id: str,
    chapter_index: int,
) -> WritingDraftContract | None:
    """获取指定章节的最新草稿"""
    return await _service.get_latest_draft_contract(db, novel_id, chapter_index)


async def list_latest_drafts_for_chapters(
    db: AsyncSession,
    novel_id: str,
    chapter_indices: list[int],
    *,
    content_limit: int | None = None,
) -> list[WritingDraftContract]:
    """批量获取指定章节的最新草稿契约。"""
    return await _service.list_latest_draft_contracts(
        db,
        novel_id,
        chapter_indices,
        content_limit=content_limit,
    )


async def list_chapter_indices(
    db: AsyncSession,
    novel_id: str,
) -> list[int]:
    """列出该小说所有有草稿的章节索引（去重、升序）"""
    return await _service.list_chapter_indices(db, novel_id)


async def list_effective_chapter_indices(
    db: AsyncSession,
    novel_id: str,
) -> list[int]:
    """列出最新工作版本含实质正文的章节索引（去重、升序）。"""
    return await _service.list_effective_chapter_indices(db, novel_id)


async def lock_chapter_versions_for_revalidation(
    db: AsyncSession,
    novel_id: str,
    chapter_indices: list[int],
) -> None:
    """Lock chapter version/content writes until the current transaction ends."""
    await _service.lock_chapter_versions_for_revalidation(
        db,
        novel_id,
        chapter_indices,
    )


async def get_project_writing_stats(
    db: AsyncSession,
    novel_id: str,
) -> WritingProjectStatsContract:
    """获取项目正文统计（每章只统计最新版本）。"""
    return await _service.get_project_stats(db, novel_id)


async def list_project_writing_stats(
    db: AsyncSession,
    novel_ids: list[str],
) -> dict[str, WritingProjectStatsContract]:
    """批量获取项目正文统计（每章只统计最新版本）。"""
    return await _service.list_project_stats(db, novel_ids)


async def get_author_attention_items(
    db: AsyncSession,
    novel_id: str,
) -> list[WritingAuthorAttentionItemContract]:
    """Project read projection of current actionable Writing checks."""
    return await _conflict_service.get_author_attention_items(db, novel_id)


async def list_manuscript_sources(
    db: AsyncSession,
    novel_id: str,
    chapter_indices: list[int] | None = None,
    *,
    content_mode: str = "canonical",
) -> list[WritingDraftContract]:
    return await _manuscript_source.list_sources(
        db,
        novel_id,
        chapter_indices,
        content_mode=content_mode,
    )


async def grep_manuscript(
    db: AsyncSession,
    novel_id: str,
    pattern: str,
    **kwargs,
) -> tuple[list[ManuscriptSearchHitContract], int, list[int]]:
    return await _manuscript_source.grep(db, novel_id, pattern, **kwargs)


async def read_manuscript_range(
    db: AsyncSession,
    novel_id: str,
    source_ref: SourceRangeRefContract,
    *,
    before: int = 3,
    after: int = 3,
    max_end_offset: int | None = None,
) -> ManuscriptReadContract:
    return await _manuscript_source.read(
        db,
        novel_id,
        source_ref,
        before=before,
        after=after,
        max_end_offset=max_end_offset,
    )


async def build_manuscript_range_ref(
    db: AsyncSession,
    novel_id: str,
    *,
    draft_id: str,
    start_offset: int,
    end_offset: int,
    content_mode: str,
) -> SourceRangeRefContract:
    return await _manuscript_source.build_range_ref(
        db,
        novel_id,
        draft_id=draft_id,
        start_offset=start_offset,
        end_offset=end_offset,
        content_mode=content_mode,
    )
