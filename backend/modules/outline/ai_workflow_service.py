"""Internal Outline AI workflow orchestration."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from modules.context import facade as context_facade
from modules.outline.generator import PlotStructureGenerator
from modules.outline.schemas import SceneCreate
from modules.outline.services import SceneService


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


class OutlineAIWorkflowService:
    """Owns confirmed Outline AI workflows used by async task handlers."""

    async def analyze(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        confirmation_id: str,
        task_id: str,
        instruction: str | None = None,
        progress_callback: Callable[[float], None] | None = None,
    ) -> dict:
        compiled = await context_facade.compile_from_confirmation(
            db,
            novel_id=novel_id,
            action="outline.analyze",
            confirmation_id=confirmation_id,
        )
        markdown = context_facade.render_compiled_context(compiled)
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
                            f"## 本次分析要求\n"
                            f"{instruction or '分析当前剧情结构、冲突推进和风险。'}\n\n"
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
            result_id=task_id,
            status="done",
        )
        if progress_callback is not None:
            progress_callback(1.0)
        await db.flush()
        return {"analysis": response.content}

    async def generate(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        confirmation_id: str,
        task_id: str,
        start_chapter: int,
        end_chapter: int,
        progress_callback: Callable[[float], None] | None = None,
    ) -> dict:
        await context_facade.compile_from_confirmation(
            db,
            novel_id=novel_id,
            action="outline.generate",
            confirmation_id=confirmation_id,
        )
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
            result_id=task_id,
            status="done",
        )
        if progress_callback is not None:
            progress_callback(1.0)
        await db.flush()
        return result

    async def extract_chapter_scenes(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        confirmation_id: str,
        task_id: str,
        chapter_index: int,
        instruction: str | None = None,
        progress_callback: Callable[[float], None] | None = None,
    ) -> dict:
        compiled = await context_facade.compile_from_confirmation(
            db,
            novel_id=novel_id,
            action="outline.chapter_scenes.extract",
            confirmation_id=confirmation_id,
        )
        markdown = context_facade.render_compiled_context(compiled)
        scene_instruction = instruction or "从参考资料中提取当前章节的 Scene 卡。"
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
                            f"## 本次提取要求\n"
                            f"{scene_instruction}\n\n"
                            "输出格式：{\"scenes\": [{\"title\": \"...\", "
                            "\"goal\": \"...\", \"core_conflict\": \"...\", "
                            "\"emotional_beat\": \"...\", \"must_happen\": \"...\", "
                            "\"must_not_happen\": \"...\", \"narrative_tag\": "
                            "\"draft\", \"chapter_ids\": [\"章节编号\"], "
                            "\"scene_chunks\": []}]}"
                        ),
                    ),
                ],
                temperature=0.2,
            ),
            _ExtractedScenesResponse,
        )

        scene_service = SceneService()
        next_index = await scene_service.get_next_scene_index(db, novel_id)
        scene_payloads: list[dict] = []
        for scene in extracted.scenes:
            chapter_ids = scene.chapter_ids or [str(chapter_index)]
            scene_payloads.append(
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
                ).model_dump()
            )
            next_index += 1
        created_scenes = []
        if scene_payloads:
            created_scenes = await scene_service.batch_create_models_from_dicts(
                db,
                novel_id,
                scene_payloads,
            )
        created_ids = [str(scene.id) for scene in created_scenes]

        if created_ids:
            await context_facade.attach_result_refs(
                db,
                confirmation_id=confirmation_id,
                result_refs=[
                    {"type": "outline_scene", "id": scene_id}
                    for scene_id in created_ids
                ],
                status="done",
            )
        else:
            await context_facade.attach_result_ref(
                db,
                confirmation_id=confirmation_id,
                result_type="outline_scene_extraction",
                result_id=task_id,
                status="done",
            )

        if progress_callback is not None:
            progress_callback(1.0)
        await db.flush()
        return {"scene_ids": created_ids, "total_scenes": len(created_ids)}
