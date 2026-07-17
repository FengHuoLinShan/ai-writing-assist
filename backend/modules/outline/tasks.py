from __future__ import annotations

import asyncio
import logging

from infrastructure.tasks.registry import task_handler

logger = logging.getLogger(__name__)


async def _mark_confirmation_task_terminal(
    db,
    *,
    confirmation_id: str,
    task_id: str,
    status: str,
) -> None:
    """Close manual context tracking without hiding the task's real failure."""
    try:
        await db.rollback()
        from modules.context.facade import attach_result_ref

        await attach_result_ref(
            db,
            confirmation_id=confirmation_id,
            result_type="task",
            result_id=task_id,
            status=status,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.exception(
            "Failed to close outline context confirmation after task terminal state"
        )


def _require_str(meta: dict, key: str, task_type: str) -> str:
    value = str(meta.get(key) or "")
    if not value:
        raise ValueError(f"{key} is required for {task_type}")
    return value


def _int_or_default(value: object, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


async def _require_llm_execution_snapshot(db, task, meta: dict, novel_id: str) -> dict:
    from infrastructure.tasks.facade import require_task_checkpoint_session

    require_task_checkpoint_session(db)
    snapshot = meta.get("llm_execution_snapshot")
    if isinstance(snapshot, dict) and snapshot:
        return dict(snapshot)

    # Compatibility for tasks created before submission-time snapshots existed.
    # Freeze and lease-fence the profile before any provider call.
    from modules.project.facade import (
        build_project_llm_execution_snapshot,
        require_active_project,
    )

    await require_active_project(db, novel_id)
    snapshot = await build_project_llm_execution_snapshot(db, novel_id)
    task.meta = {**meta, "llm_execution_snapshot": snapshot}
    await db.commit()
    return snapshot


@task_handler("story_outline_generate", recovery_policy="restart_origin")
async def handle_story_outline_generate(db, task):
    """Generate one strict StoryOutline preview without writing domain assets."""
    from modules.outline.story_outline_generation import (
        STORY_OUTLINE_GENERATE_ACTION,
        StoryOutlineGenerationService,
    )
    from modules.outline.story_outline_schemas import StoryOutlineGenerateRequest

    meta = task.meta or {}
    if meta.get("action") != STORY_OUTLINE_GENERATE_ACTION:
        raise ValueError("invalid action for story_outline_generate")
    request_payload = {
        field_name: meta[field_name]
        for field_name in StoryOutlineGenerateRequest.model_fields
        if field_name in meta
    }
    data = StoryOutlineGenerateRequest.model_validate(request_payload)
    submission_context_hash = _require_str(
        meta,
        "submission_context_hash",
        "story_outline_generate",
    )
    if len(submission_context_hash) != 64 or any(
        character not in "0123456789abcdef" for character in submission_context_hash
    ):
        raise ValueError(
            "submission_context_hash must be a lowercase SHA-256 digest for "
            "story_outline_generate"
        )
    snapshot = await _require_llm_execution_snapshot(
        db,
        task,
        meta,
        data.novel_id,
    )

    def _checkpoint_context(provenance: dict) -> None:
        task.meta = {
            **(task.meta or {}),
            "context_provenance": provenance,
        }

    result = await StoryOutlineGenerationService().generate_for_task(
        db,
        data=data,
        llm_execution_snapshot=snapshot,
        submission_context_hash=submission_context_hash,
        progress_callback=task.update_progress,
        context_checkpoint=_checkpoint_context,
    )
    logger.info("StoryOutline preview task complete")
    return result


@task_handler("plot_structure_generate", recovery_policy="restart_origin")
async def handle_plot_structure_generate(db, task):
    """Fail closed: the legacy monolithic creative task has no production path."""
    meta = task.meta or {}
    novel_id = meta.get("novel_id", "")
    start_chapter = int(meta.get("start_chapter", 1))
    end_chapter = int(meta.get("end_chapter", 10))

    if not novel_id:
        raise ValueError("novel_id is required for plot_structure_generate")

    task.update_progress(1.0)
    logger.warning(
        "plot_structure_generate is retired (novel_id=%s, chapters=%d-%d)",
        novel_id,
        start_chapter,
        end_chapter,
    )
    return {
        "status": "unsupported",
        "task_type": "plot_structure_generate",
        "novel_id": novel_id,
        "message": (
            "旧的一次性剧情结构生成已停用。请在剧情线、篇章纲或场景工作台"
            "重新发起当前层 AI 创作。"
        ),
    }


@task_handler("chapter_card_extraction", recovery_policy="restart_origin")
async def handle_chapter_card_extraction(db, task):
    """兼容旧任务类型：章节卡生成尚未有独立 domain handler。

    当前 Planned Scene 创作入口是 Scene 工作台的 P20 v2，正文 Scene 提取入口是
    imports 深度导入。这里仅让存量 task 得到可展示的 unsupported 结果。
    """
    meta = task.meta or {}
    novel_id = meta.get("novel_id", "")
    start_chapter = int(meta.get("start_chapter", 1))
    end_chapter = int(meta.get("end_chapter", 10))

    if not novel_id:
        raise ValueError("novel_id is required for chapter_card_extraction")

    task.update_progress(0.1)
    task.update_progress(1.0)

    logger.warning(
        "chapter_card_extraction is unsupported; use the page-local P20 workflow "
        "or imports Scene extraction (novel_id=%s, chapters=%d-%d)",
        novel_id,
        start_chapter,
        end_chapter,
    )

    return {
        "status": "unsupported",
        "task_type": "chapter_card_extraction",
        "novel_id": novel_id,
        "start_chapter": start_chapter,
        "end_chapter": end_chapter,
        "message": (
            "旧章节卡生成已停用。请在场景工作台创作 Planned Scene，"
            "或使用 imports 从正文提取 Scene。"
        ),
    }


@task_handler("chapter_scene_generate", recovery_policy="restart_origin")
async def handle_chapter_scene_generate(db, task):
    """兼容任务枚举中的章节/场景生成类型。

    复用 chapter_card_extraction 的结构化 unsupported 响应，确保旧任务可诊断。
    """
    result = await handle_chapter_card_extraction(db, task)
    return {
        **result,
        "task_type": "chapter_scene_generate",
        "message": (
            "旧章节/Scene 整套生成已停用。请使用当前层 P20 或 imports Scene 提取。"
        ),
    }


@task_handler("outline_analyze", recovery_policy="restart_origin")
async def handle_outline_analyze(db, task):
    """处理确认后的剧情分析任务。"""
    from modules.outline.ai_workflow_service import OutlineAIWorkflowService

    meta = task.meta or {}
    novel_id = _require_str(meta, "novel_id", "outline_analyze")
    confirmation_id = _require_str(
        meta,
        "context_confirmation_id",
        "outline_analyze",
    )
    llm_execution_snapshot = await _require_llm_execution_snapshot(
        db,
        task,
        meta,
        novel_id,
    )
    return await OutlineAIWorkflowService().analyze_for_task(
        db,
        novel_id=novel_id,
        confirmation_id=confirmation_id,
        task_id=str(task.id),
        instruction=meta.get("instruction"),
        start_chapter=_optional_int(meta.get("start_chapter")),
        end_chapter=_optional_int(meta.get("end_chapter")),
        llm_execution_snapshot=llm_execution_snapshot,
        progress_callback=task.update_progress,
    )


@task_handler("outline_generate", recovery_policy="restart_origin")
async def handle_outline_generate(db, task):
    """Generate one P20 v2 current-layer preview."""
    from modules.outline.ai_workflow_service import OutlineAIWorkflowService
    from modules.outline.p20_schemas import OutlineLayerGenerateRequest

    meta = task.meta or {}
    novel_id = _require_str(meta, "novel_id", "outline_generate")
    confirmation_id = _require_str(
        meta,
        "context_confirmation_id",
        "outline_generate",
    )
    try:
        if meta.get("contract_version") != "outline_layer_v2":
            raise ValueError(
                "未完成的旧版大纲生成任务不能由 P20 v2 恢复；请在对应大纲页面重新提交"
            )
        request_payload = {
            field_name: meta[field_name]
            for field_name in OutlineLayerGenerateRequest.model_fields
            if field_name in meta
        }
        data = OutlineLayerGenerateRequest.model_validate(request_payload)
        submission_fingerprint = _require_str(
            meta,
            "submission_fingerprint",
            "outline_generate",
        )
        llm_execution_snapshot = await _require_llm_execution_snapshot(
            db,
            task,
            meta,
            novel_id,
        )

        result = await OutlineAIWorkflowService().generate_layer_for_task(
            db,
            data=data,
            task_id=str(task.id),
            submission_fingerprint=submission_fingerprint,
            llm_execution_snapshot=llm_execution_snapshot,
            progress_callback=task.update_progress,
        )
    except asyncio.CancelledError:
        await _mark_confirmation_task_terminal(
            db,
            confirmation_id=confirmation_id,
            task_id=str(task.id),
            status="cancelled",
        )
        raise
    except Exception:
        await _mark_confirmation_task_terminal(
            db,
            confirmation_id=confirmation_id,
            task_id=str(task.id),
            status="failed",
        )
        raise
    logger.info(
        "P20 preview complete: target=%s mode=%s",
        data.target,
        data.mode,
    )
    return result
