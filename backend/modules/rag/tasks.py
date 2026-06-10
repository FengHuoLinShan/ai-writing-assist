"""RAG 任务处理器"""

from __future__ import annotations

import logging

from core.container import get as _container_get
from infrastructure.tasks.registry import task_handler

logger = logging.getLogger(__name__)


@task_handler("rag_index_chapter")
async def handle_rag_index_chapter(db, task):
    """处理 RAG 章节索引任务

    将指定章节的正文分割为 chunk 并存入 RAG 库。
    自动匹配已有角色名标记 character_ids。

    Task meta 参数：
    - novel_id: 项目 ID
    - chapter_index: 章节索引
    """
    meta = task.meta or {}
    novel_id = meta.get("novel_id", "")
    chapter_index = int(meta.get("chapter_index", 0))

    if not novel_id:
        raise ValueError("novel_id is required for rag_index_chapter")
    if chapter_index < 1:
        raise ValueError("chapter_index must be >= 1 for rag_index_chapter")

    from modules.rag.facade import index_chapter_with_report

    report = await index_chapter_with_report(db, novel_id, chapter_index)

    logger.info(
        "Indexed chapter %d: %d chunks created",
        chapter_index,
        report.chunks_created,
    )

    return {
        "chapter_index": chapter_index,
        "chunks_created": report.chunks_created,
        "embedding_failed_count": report.embedding_failed_count,
        "warnings": report.warnings,
    }


@task_handler("rag_reindex_novel")
async def handle_rag_reindex_novel(db, task):
    """处理项目级 RAG 全量重建任务。

    Task meta 参数：
    - novel_id: 项目 ID
    - start_chapter: 起始章节（可选）
    - end_chapter: 结束章节（可选）
    - force: 是否强制重建（当前索引器总是替换章节 chunk）
    """
    meta = task.meta or {}
    novel_id = meta.get("novel_id", "")
    start_chapter = meta.get("start_chapter")
    end_chapter = meta.get("end_chapter")

    if not novel_id:
        raise ValueError("novel_id is required for rag_reindex_novel")

    from modules.rag.facade import index_chapter_with_report

    _list_chapter_indices = _container_get("writing.list_chapter_indices")

    chapter_indices = await _list_chapter_indices(db, novel_id)
    if start_chapter is not None:
        chapter_indices = [idx for idx in chapter_indices if idx >= int(start_chapter)]
    if end_chapter is not None:
        chapter_indices = [idx for idx in chapter_indices if idx <= int(end_chapter)]

    total = len(chapter_indices)
    chapters: list[dict] = []
    warnings: list[str] = []
    chunks_created = 0
    embedding_failed_count = 0

    for pos, chapter_index in enumerate(chapter_indices, start=1):
        if total:
            task.update_progress((pos - 1) / total)
            await db.flush()

        report = await index_chapter_with_report(db, novel_id, chapter_index)
        chunks_created += report.chunks_created
        embedding_failed_count += report.embedding_failed_count
        warnings.extend(report.warnings)
        chapters.append({
            "chapter_index": chapter_index,
            "chunks_created": report.chunks_created,
            "embedding_failed_count": report.embedding_failed_count,
            "warnings": report.warnings,
        })

    task.update_progress(1.0)
    await db.flush()

    return {
        "total_chapters": total,
        "chunks_created": chunks_created,
        "embedding_failed_count": embedding_failed_count,
        "warnings": warnings,
        "chapters": chapters,
    }
