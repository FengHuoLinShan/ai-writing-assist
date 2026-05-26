"""RAG 任务处理器"""

from __future__ import annotations

import logging

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

    from modules.rag.facade import index_chapter

    chunk_count = await index_chapter(db, novel_id, chapter_index)

    logger.info("Indexed chapter %d: %d chunks created", chapter_index, chunk_count)

    return {
        "chapter_index": chapter_index,
        "chunks_created": chunk_count,
    }
