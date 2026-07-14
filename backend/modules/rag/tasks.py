"""RAG 任务处理器"""

from __future__ import annotations

import logging
import uuid

from core.container import get as _container_get
from infrastructure.tasks.registry import task_handler

logger = logging.getLogger(__name__)


@task_handler("rag_index_chapter", recovery_policy="auto_requeue", max_attempts=2)
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
    content_mode = str(meta.get("content_mode") or "canonical")

    if not novel_id:
        raise ValueError("novel_id is required for rag_index_chapter")
    if chapter_index < 1:
        raise ValueError("chapter_index must be >= 1 for rag_index_chapter")

    outcome = await _container_get("rag.index_chapter_for_task")(
        db,
        novel_id,
        chapter_index,
        content_mode=content_mode,
    )
    report = outcome.report
    if outcome.status == "coalesced":
        return {
            "chapter_index": chapter_index,
            "content_mode": content_mode,
            "chunks_created": 0,
            "embedding_failed_count": 0,
            "warnings": ["索引任务已合并或当前版本已是最新"],
            "coalesced": True,
        }

    logger.info(
        "Indexed chapter %d: %d chunks created",
        chapter_index,
        report.chunks_created,
    )

    return {
        "chapter_index": chapter_index,
        "content_mode": content_mode,
        "source_draft_id": report.source_draft_id,
        "source_content_hash": report.source_content_hash,
        "chunks_created": report.chunks_created,
        "embedding_failed_count": report.embedding_failed_count,
        "warnings": report.warnings,
        "followup_task_id": outcome.followup_task_id,
    }


@task_handler("rag_reindex_novel", recovery_policy="auto_requeue", max_attempts=2)
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
    content_mode = str(meta.get("content_mode") or "canonical")

    if not novel_id:
        raise ValueError("novel_id is required for rag_reindex_novel")

    _list_chapter_indices = _container_get("writing.list_chapter_indices")

    chapter_indices = await _list_chapter_indices(db, novel_id)
    if start_chapter is not None:
        chapter_indices = [idx for idx in chapter_indices if idx >= int(start_chapter)]
    if end_chapter is not None:
        chapter_indices = [idx for idx in chapter_indices if idx <= int(end_chapter)]

    total = len(chapter_indices)
    _index_chapter_for_task = (
        _container_get("rag.index_chapter_for_task") if chapter_indices else None
    )
    chapters: list[dict] = []
    warnings: list[str] = []
    chunks_created = 0
    embedding_failed_count = 0
    for pos, chapter_index in enumerate(chapter_indices, start=1):
        if total:
            task.update_progress((pos - 1) / total)
            await db.flush()

        outcome = await _index_chapter_for_task(  # type: ignore[misc]
            db,
            novel_id,
            chapter_index,
            content_mode=content_mode,
            force=True,
        )
        report = outcome.report
        if outcome.status == "coalesced":
            warning = f"第 {chapter_index} 章已有索引任务执行中，本次重建已合并"
            warnings.append(warning)
            chapters.append(
                {
                    "chapter_index": chapter_index,
                    "chunks_created": 0,
                    "embedding_failed_count": 0,
                    "warnings": [warning],
                    "coalesced": True,
                }
            )
            continue
        chunks_created += report.chunks_created
        embedding_failed_count += report.embedding_failed_count
        warnings.extend(report.warnings)
        chapters.append(
            {
                "chapter_index": chapter_index,
                "chunks_created": report.chunks_created,
                "embedding_failed_count": report.embedding_failed_count,
                "warnings": report.warnings,
            }
        )

    task.update_progress(1.0)
    await db.flush()

    return {
        "total_chapters": total,
        "content_mode": content_mode,
        "chunks_created": chunks_created,
        "embedding_failed_count": embedding_failed_count,
        "warnings": warnings,
        "chapters": chapters,
    }


@task_handler("rag_retry_embeddings", recovery_policy="auto_requeue", max_attempts=2)
async def handle_rag_retry_embeddings(db, task):
    """重试 failed / pending_vectorization chunk 的 embedding。"""
    meta = task.meta or {}
    novel_id = meta.get("novel_id", "")
    start_chapter = meta.get("start_chapter")
    end_chapter = meta.get("end_chapter")
    statuses = meta.get("statuses") or ["failed", "pending_vectorization"]

    if not novel_id:
        raise ValueError("novel_id is required for rag_retry_embeddings")

    from modules.rag.indexing import IndexingService

    nid = uuid.UUID(hex=novel_id)
    start_chapter_value = int(start_chapter) if start_chapter is not None else None
    end_chapter_value = int(end_chapter) if end_chapter is not None else None
    return await IndexingService().retry_embeddings_for_task(
        db,
        nid,
        start_chapter=start_chapter_value,
        end_chapter=end_chapter_value,
        statuses=statuses,
        progress_callback=task.update_progress,
    )
