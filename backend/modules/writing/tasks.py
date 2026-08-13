"""Writing 异步任务处理器"""

from __future__ import annotations

import logging

from core.container import get as _container_get
from infrastructure.llm.redaction import redact_diagnostic
from infrastructure.tasks.registry import task_handler

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_LEGACY_UNOWNED_AI_REVIEW_KEY = "_legacy_unowned_ai_review"


async def _require_llm_execution_snapshot(
    db,
    task,
    meta: dict,
    novel_id: str,
    *,
    legacy_meta_key: str | None = _LEGACY_UNOWNED_AI_REVIEW_KEY,
) -> tuple[dict, bool]:
    """Return the frozen profile and whether this is an owner-less legacy task."""
    from infrastructure.tasks.facade import require_task_checkpoint_session

    require_task_checkpoint_session(db)
    snapshot = meta.get("llm_execution_snapshot")
    if isinstance(snapshot, dict) and snapshot:
        return dict(snapshot), bool(legacy_meta_key and meta.get(legacy_meta_key, False))

    from modules.project.facade import (
        build_project_llm_execution_snapshot,
        require_active_project,
    )

    await require_active_project(db, novel_id)
    snapshot = await build_project_llm_execution_snapshot(db, novel_id)
    task_meta = {**meta, "llm_execution_snapshot": snapshot}
    if legacy_meta_key:
        task_meta[legacy_meta_key] = True
    task.meta = task_meta
    await db.commit()
    if db.in_transaction():
        raise RuntimeError("writing task snapshot checkpoint must close the transaction")
    db.expire_all()
    return snapshot, bool(legacy_meta_key)


@task_handler("publish_chapter", recovery_policy="restart_origin")
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

    # Step 1: RAG 索引
    rag_ok = False
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            outcome = await _container_get("rag.index_chapter_for_task")(
                db,
                novel_id,
                chapter_index,
                content_mode="canonical",
                task_id=str(task.id),
                task_type=str(task.task_type),
                task_attempt=int(task.attempt),
                task_lease_id=str(task.lease_id),
            )
            report = outcome.report
            results["rag_chunks"] = report.chunks_created
            results["rag_embedding_failed"] = report.embedding_failed_count
            if outcome.status == "coalesced":
                results["rag_index_status"] = "coalesced"
            rag_ok = True
            logger.info(
                "Publish chapter %d — RAG done (attempt %d): %d chunks",
                chapter_index,
                attempt,
                report.chunks_created,
            )
            break
        except Exception as e:
            await db.rollback()
            safe_error = redact_diagnostic(e, limit=500)
            logger.warning(
                "Publish chapter %d — RAG attempt %d/%d failed: %s",
                chapter_index,
                attempt,
                _MAX_RETRIES,
                safe_error,
            )

    if not rag_ok:
        raise RuntimeError(
            "发布失败：章节索引暂时不可用，请稍后重试。",
        )

    task.update_progress(0.5)
    from modules.project.facade import require_active_project

    # RAG committed and released its locks. Start the memory transaction in
    # deletion-safe order: project FOR SHARE before any memory child write.
    await require_active_project(db, novel_id)
    await db.flush()

    # Step 2: Memory 快照
    snapshot_ok = False
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            async with db.begin_nested():
                _memory = _container_get("memory.service")
                snap = await _memory.capture_snapshot(db, novel_id, chapter_index)
            results["snapshot_id"] = snap.id
            snapshot_ok = True
            logger.info(
                "Publish chapter %d — snapshot done (attempt %d): %s",
                chapter_index,
                attempt,
                snap.id,
            )
            break
        except Exception as e:
            safe_error = redact_diagnostic(e, limit=500)
            logger.warning(
                "Publish chapter %d — snapshot attempt %d/%d failed: %s",
                chapter_index,
                attempt,
                _MAX_RETRIES,
                safe_error,
            )

    if not snapshot_ok:
        raise RuntimeError(
            "发布失败：历史状态暂时不可用，请稍后重试。",
        )

    task.update_progress(1.0)
    await db.flush()

    return results


@task_handler(
    "writing_generate",
    recovery_policy="auto_requeue",
    max_attempts=2,
    retry_transient_llm_errors=True,
)
async def handle_writing_generate(db, task):
    """处理 AI 正文建议生成任务。"""
    from modules.writing.services import WritingGenerationService

    meta = task.meta or {}
    task_id = str(task.id)
    novel_id = meta.get("novel_id", "")
    chapter_index = int(meta.get("chapter_index", 0))
    context_confirmation_id = meta.get("context_confirmation_id", "")

    if not novel_id:
        raise ValueError("novel_id is required for writing_generate")
    if chapter_index < 1:
        raise ValueError("chapter_index must be >= 1 for writing_generate")
    if not context_confirmation_id:
        raise ValueError("context_confirmation_id is required for writing_generate")

    llm_execution_snapshot, _legacy = await _require_llm_execution_snapshot(
        db,
        task,
        meta,
        novel_id,
        legacy_meta_key=None,
    )
    task.update_progress(0.1)
    service = WritingGenerationService()
    draft = await service.generate_candidate_for_task(
        db,
        novel_id=novel_id,
        chapter_index=chapter_index,
        title=meta.get("title"),
        instruction=meta.get("instruction"),
        context_confirmation_id=context_confirmation_id,
        source_task_id=task_id,
        llm_execution_snapshot=llm_execution_snapshot,
        generation_mode=str(meta.get("generation_mode") or "draft"),
        base_draft_id=meta.get("base_draft_id"),
    )
    task.update_progress(1.0)
    await db.flush()
    return {"draft_id": draft.id, "chapter_index": draft.chapter_index}


@task_handler(
    "writing_conflict_ai_review",
    recovery_policy="auto_requeue",
    max_attempts=2,
    retry_transient_llm_errors=True,
)
async def handle_writing_conflict_ai_review(db, task):
    """处理写作冲突检查的 AI 软复核任务。"""
    from modules.writing.services import WritingConflictCheckService

    meta = task.meta or {}
    task_id = str(task.id)
    novel_id = meta.get("novel_id", "")
    check_id = meta.get("check_id", "")
    context_confirmation_id = meta.get("context_confirmation_id", "")

    if not novel_id:
        raise ValueError("novel_id is required for writing_conflict_ai_review")
    if not check_id:
        raise ValueError("check_id is required for writing_conflict_ai_review")
    if not context_confirmation_id:
        raise ValueError(
            "context_confirmation_id is required for writing_conflict_ai_review",
        )

    llm_execution_snapshot, allow_unowned_legacy = await _require_llm_execution_snapshot(
        db, task, meta, novel_id
    )
    task.update_progress(0.1)
    service = WritingConflictCheckService()
    from modules.writing.schemas import WritingConflictAiReviewRequest

    check = await service.run_ai_review_for_task(
        db,
        check_id=check_id,
        data=WritingConflictAiReviewRequest(
            novel_id=novel_id,
            context_confirmation_id=context_confirmation_id,
        ),
        task_id=task_id,
        llm_execution_snapshot=llm_execution_snapshot,
        allow_unowned_legacy=allow_unowned_legacy,
        finalize_transient_failure=(
            int(task.attempt or 0) >= int(task.max_attempts or 1)
        ),
    )
    task.update_progress(1.0)
    await db.flush()
    ai_judgment_count = len(
        [item for item in check.items if item.is_ai_judgment],
    )
    return {
        "check_id": check.id,
        "chapter_index": check.chapter_index,
        "ai_review_status": check.ai_review_status,
        "ai_judgment_count": ai_judgment_count,
    }


@task_handler(
    "writing_conflict_item_ai_suggestion",
    recovery_policy="auto_requeue",
    max_attempts=2,
    retry_transient_llm_errors=True,
)
async def handle_writing_conflict_item_ai_suggestion(db, task):
    from modules.writing.schemas import WritingConflictAiSuggestionRequest
    from modules.writing.services import WritingConflictCheckService

    meta = dict(task.meta or {})
    novel_id = str(meta.get("novel_id") or "")
    item_id = str(meta.get("item_id") or "")
    if not novel_id or not item_id:
        raise ValueError("novel_id and item_id are required")
    snapshot, _legacy = await _require_llm_execution_snapshot(
        db,
        task,
        meta,
        novel_id,
        legacy_meta_key=None,
    )
    task.update_progress(0.1)
    item = await WritingConflictCheckService().run_ai_suggestion_for_task(
        db,
        item_id=item_id,
        data=WritingConflictAiSuggestionRequest(
            novel_id=novel_id,
            context_confirmation_id=str(meta.get("context_confirmation_id") or ""),
        ),
        llm_execution_snapshot=snapshot,
        finalize_transient_failure=(
            int(task.attempt or 0) >= int(task.max_attempts or 1)
        ),
    )
    task.update_progress(1.0)
    return item.model_dump(mode="json")
