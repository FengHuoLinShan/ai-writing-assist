"""Writing 异步任务处理器"""

from __future__ import annotations

import logging

from infrastructure.tasks.registry import task_handler

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3


@task_handler("publish_chapter")
async def handle_publish_chapter(db, task):
    """处理章节发布任务

    三步：RAG 索引 → memory 快照捕获。
    每步失败自动重试 3 次，仍失败则标记任务为 failed。

    Task meta 参数：
    - novel_id: 项目 ID
    - chapter_index: 章节索引
    """
    meta = task.meta or {}
    novel_id = meta.get("novel_id", "")
    chapter_index = int(meta.get("chapter_index", 0))

    if not novel_id:
        raise ValueError("novel_id is required for publish_chapter")
    if chapter_index < 1:
        raise ValueError("chapter_index must be >= 1 for publish_chapter")

    results: dict[str, object] = {}
    errors: list[str] = []

    # Step 1: RAG 索引
    rag_ok = False
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            from modules.rag.facade import index_chapter_with_report

            report = await index_chapter_with_report(db, novel_id, chapter_index)
            results["rag_chunks"] = report.chunks_created
            results["rag_embedding_failed"] = report.embedding_failed_count
            rag_ok = True
            logger.info(
                "Publish chapter %d — RAG done (attempt %d): %d chunks",
                chapter_index, attempt, report.chunks_created,
            )
            break
        except Exception as e:
            logger.warning(
                "Publish chapter %d — RAG attempt %d/%d failed: %s",
                chapter_index, attempt, _MAX_RETRIES, e,
            )
            errors.append(f"RAG attempt {attempt}: {e}")

    if not rag_ok:
        task.update_progress(0.5)
        await db.flush()
        raise RuntimeError(
            f"RAG indexing failed after {_MAX_RETRIES} attempts: "
            + "; ".join(errors),
        )

    task.update_progress(0.5)
    await db.flush()

    # Step 2: Memory 快照
    snapshot_ok = False
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            from modules.memory.facade import capture_snapshot

            snap = await capture_snapshot(db, novel_id, chapter_index)
            results["snapshot_id"] = snap.id
            snapshot_ok = True
            logger.info(
                "Publish chapter %d — snapshot done (attempt %d): %s",
                chapter_index, attempt, snap.id,
            )
            break
        except Exception as e:
            logger.warning(
                "Publish chapter %d — snapshot attempt %d/%d failed: %s",
                chapter_index, attempt, _MAX_RETRIES, e,
            )
            errors.append(f"Snapshot attempt {attempt}: {e}")

    if not snapshot_ok:
        raise RuntimeError(
            f"Memory snapshot failed after {_MAX_RETRIES} attempts: "
            + "; ".join(errors),
        )

    task.update_progress(1.0)
    await db.flush()

    return results
