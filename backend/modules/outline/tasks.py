from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from core.config import get_settings
from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from infrastructure.tasks.registry import task_handler
from modules.context import facade as context_facade
from modules.outline.schemas import SceneCreate
from modules.outline.services import SceneService

logger = logging.getLogger(__name__)


class _ExtractedScene(BaseModel):
    title: str = "未命名 Scene"
    goal: str | None = None
    core_conflict: str | None = None
    emotional_beat: str | None = None
    must_happen: str | None = None
    must_not_happen: str | None = None
    narrative_tag: str = "draft"
    chapter_ids: list[str] = Field(default_factory=list)
    scene_chunks: list[dict] = Field(default_factory=list)


class _ExtractedScenesResponse(BaseModel):
    scenes: list[_ExtractedScene] = Field(default_factory=list)


def _require_str(meta: dict, key: str, task_type: str) -> str:
    value = str(meta.get(key) or "")
    if not value:
        raise ValueError(f"{key} is required for {task_type}")
    return value


def _int_or_default(value: object, default: int) -> int:
    if value is None or value == "":
        return default
    return int(value)


@task_handler("plot_structure_generate")
async def handle_plot_structure_generate(db, task):
    """处理剧情结构生成任务

    根据已有世界对象和人物，AI 生成剧情线和篇章纲。

    Task meta 参数：
    - novel_id: 项目 ID
    - start_chapter: 起始章节（可选，默认 1）
    - end_chapter: 结束章节（可选，默认 10）
    """
    # 延迟导入，避免 infrastructure.tasks 初始化时形成循环依赖
    from modules.outline.generator import PlotStructureGenerator

    generator = PlotStructureGenerator()

    meta = task.meta or {}
    novel_id = meta.get("novel_id", "")
    start_chapter = int(meta.get("start_chapter", 1))
    end_chapter = int(meta.get("end_chapter", 10))

    if not novel_id:
        raise ValueError("novel_id is required for plot_structure_generate")

    task.update_progress(0.1)

    result = await generator.generate(
        db,
        novel_id=novel_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
    )
    task.update_progress(0.85)

    logger.info(
        "Plot structure generation complete: %d threads, %d arcs",
        result["total_threads"],
        result["total_arcs"],
    )
    task.update_progress(0.95)

    return result


@task_handler("chapter_card_extraction")
async def handle_chapter_card_extraction(db, task):
    """兼容旧任务类型：章节卡生成尚未有独立 domain handler。

    当前真实生成入口是 outline 的 plot_structure_generate / /api/outline/generate，
    会生成 scenes。这里注册旧 task type，避免 worker 以“无 handler”失败，并让
    前端轮询可以看到结构化 unsupported 结果。
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
        "chapter_card_extraction is unsupported; use plot_structure_generate "
        "or /api/outline/generate instead (novel_id=%s, chapters=%d-%d)",
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
            "chapter_card_extraction is not implemented as an async task. "
            "Use plot_structure_generate or /api/outline/generate to create scenes."
        ),
    }


@task_handler("chapter_scene_generate")
async def handle_chapter_scene_generate(db, task):
    """兼容任务枚举中的章节/场景生成类型。

    当前还没有独立异步章节卡生成器。复用 chapter_card_extraction 的结构化
    unsupported 响应，确保前端轮询能得到可展示结果，而不是 worker 无 handler。
    """
    result = await handle_chapter_card_extraction(db, task)
    return {
        **result,
        "task_type": "chapter_scene_generate",
        "message": (
            "chapter_scene_generate is not implemented as an async task. "
            "Use plot_structure_generate or /api/outline/generate to create scenes."
        ),
    }


@task_handler("outline_analyze")
async def handle_outline_analyze(db, task):
    """处理确认后的剧情分析任务。"""
    meta = task.meta or {}
    novel_id = _require_str(meta, "novel_id", "outline_analyze")
    confirmation_id = _require_str(
        meta,
        "context_confirmation_id",
        "outline_analyze",
    )

    compiled = await context_facade.compile_from_confirmation(
        db,
        novel_id=novel_id,
        action="outline.analyze",
        confirmation_id=confirmation_id,
    )
    markdown = context_facade.render_compiled_context(compiled)
    instruction = meta.get("instruction") or "分析当前剧情结构、冲突推进和风险。"
    settings = get_settings()
    response = await LLMClient().generate(
        LLMCallRequest(
            model=settings.llm_model,
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        "你是长篇小说结构分析助手。只输出可供作者决策的分析，"
                        "不要改写正文，不要写入正史。"
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=(
                        f"{markdown}\n\n"
                        f"## 本次分析要求\n{instruction}\n\n"
                        "请给出剧情推进、冲突强度、伏笔回收和需要用户确认的问题。"
                    ),
                ),
            ],
            temperature=0.3,
        )
    )

    await context_facade.attach_result_ref(
        db,
        confirmation_id=confirmation_id,
        result_type="outline_analysis",
        result_id=str(task.id),
        status="done",
    )
    task.update_progress(1.0)
    await db.flush()
    return {"analysis": response.content}


@task_handler("outline_generate")
async def handle_outline_generate(db, task):
    """处理确认后的剧情结构生成任务。"""
    meta = task.meta or {}
    novel_id = _require_str(meta, "novel_id", "outline_generate")
    confirmation_id = _require_str(
        meta,
        "context_confirmation_id",
        "outline_generate",
    )
    start_chapter = _int_or_default(meta.get("start_chapter"), 1)
    end_chapter = _int_or_default(meta.get("end_chapter"), 10)

    await context_facade.compile_from_confirmation(
        db,
        novel_id=novel_id,
        action="outline.generate",
        confirmation_id=confirmation_id,
    )

    from modules.outline.generator import PlotStructureGenerator

    result = await PlotStructureGenerator().generate(
        db,
        novel_id=novel_id,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
    )
    await context_facade.attach_result_ref(
        db,
        confirmation_id=confirmation_id,
        result_type="outline_generation",
        result_id=str(task.id),
        status="done",
    )
    task.update_progress(1.0)
    await db.flush()
    logger.info(
        "Outline generation complete: %d threads, %d arcs",
        result["total_threads"],
        result["total_arcs"],
    )
    return result


@task_handler("outline_chapter_scenes_extract")
async def handle_outline_chapter_scenes_extract(db, task):
    """处理确认后的章节/Scene 卡提取任务。"""
    meta = task.meta or {}
    novel_id = _require_str(meta, "novel_id", "outline_chapter_scenes_extract")
    confirmation_id = _require_str(
        meta,
        "context_confirmation_id",
        "outline_chapter_scenes_extract",
    )
    chapter_index = _int_or_default(meta.get("chapter_index"), 1)

    compiled = await context_facade.compile_from_confirmation(
        db,
        novel_id=novel_id,
        action="outline.chapter_scenes.extract",
        confirmation_id=confirmation_id,
    )
    markdown = context_facade.render_compiled_context(compiled)
    instruction = meta.get("instruction") or "从参考资料中提取当前章节的 Scene 卡。"
    settings = get_settings()
    extracted = await LLMClient().generate_structured(
        LLMCallRequest(
            model=settings.llm_model,
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        "你是长篇小说 Scene 卡提取助手。只输出 JSON，"
                        "产物必须是 draft Scene，不要恢复 chapter_cards。"
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=(
                        f"{markdown}\n\n"
                        f"## 本次提取要求\n{instruction}\n\n"
                        "输出格式：{\"scenes\": [{\"title\": \"...\", "
                        "\"goal\": \"...\", \"core_conflict\": \"...\", "
                        "\"emotional_beat\": \"...\", \"must_happen\": \"...\", "
                        "\"must_not_happen\": \"...\", \"narrative_tag\": \"draft\", "
                        "\"chapter_ids\": [\"章节编号\"], \"scene_chunks\": []}]}"
                    ),
                ),
            ],
            temperature=0.2,
        ),
        _ExtractedScenesResponse,
    )

    scene_service = SceneService()
    existing = await scene_service.get_ordered(db, novel_id)
    next_index = max((scene.scene_index for scene in existing), default=-1) + 1
    created_ids: list[str] = []
    for scene in extracted.scenes:
        chapter_ids = scene.chapter_ids or [str(chapter_index)]
        created = await scene_service.create(
            db,
            novel_id,
            SceneCreate(
                scene_index=next_index,
                title=scene.title[:255],
                goal=scene.goal,
                core_conflict=scene.core_conflict,
                emotional_beat=scene.emotional_beat,
                must_happen=scene.must_happen,
                must_not_happen=scene.must_not_happen,
                narrative_tag=scene.narrative_tag or "draft",
                source="ai",
                scene_chunks=scene.scene_chunks,
                chapter_ids=chapter_ids,
                status="draft",
            ),
        )
        created_ids.append(created.id)
        next_index += 1

    for scene_id in created_ids:
        await context_facade.attach_result_ref(
            db,
            confirmation_id=confirmation_id,
            result_type="outline_scene",
            result_id=scene_id,
            status="done",
        )
    if not created_ids:
        await context_facade.attach_result_ref(
            db,
            confirmation_id=confirmation_id,
            result_type="outline_scene_extraction",
            result_id=str(task.id),
            status="done",
        )

    task.update_progress(1.0)
    await db.flush()
    return {"scene_ids": created_ids, "total_scenes": len(created_ids)}
