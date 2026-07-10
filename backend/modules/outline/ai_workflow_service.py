"""Internal Outline AI workflow orchestration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from infrastructure.llm.agent_step_harness import (
    run_managed_generate,
    run_managed_structured,
)
from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
from infrastructure.tasks.models import AsyncTask
from modules.context import facade as context_facade
from modules.outline.generator import PlotStructureGenerator
from modules.outline.schemas import SceneCreate
from modules.outline.services import SceneService
from shared.utils import parse_uuid


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
        response = await run_managed_generate(
            LLMClient(),
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
            ),
            step_name="outline.ai_workflow.analyze.generate",
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
            persist=False,
        )
        result.update(
            {
                "source_task_id": task_id,
                "context_confirmation_id": confirmation_id,
            }
        )
        await context_facade.attach_result_ref(
            db,
            confirmation_id=confirmation_id,
            result_type="outline_structure_preview",
            result_id=task_id,
            status="done",
        )
        if progress_callback is not None:
            progress_callback(1.0)
        await db.flush()
        return result

    async def apply_structure_preview(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        confirmation_id: str,
        source_task_id: str,
        draft_structure: dict,
        confirmed: bool,
    ) -> dict:
        """显式采用手动大纲 AI preview，并保持幂等与来源追溯。"""
        if not confirmed:
            raise PermissionError(
                "outline structure preview apply requires confirmed=true"
            )
        task_stmt = (
            select(AsyncTask)
            .where(
                AsyncTask.id == parse_uuid(source_task_id, "source_task_id")
            )
            .with_for_update()
        )
        task = (await db.execute(task_stmt)).scalar_one_or_none()
        if task is None or task.task_type != "outline_generate":
            raise ValueError(
                "source_task_id must reference a confirmed outline preview task"
            )
        task_meta = dict(task.meta or {})
        if task_meta.get("novel_id") != novel_id:
            raise ValueError("outline preview task novel_id mismatch")
        if task_meta.get("context_confirmation_id") != confirmation_id:
            raise ValueError("outline preview task confirmation mismatch")
        if task.status != "done":
            raise ValueError("outline preview task is not complete")

        task_result = dict(task.result or {})
        applied_result = task_result.get("applied_result")
        if isinstance(applied_result, dict) and task_result.get(
            "apply_status"
        ) == "applied":
            return applied_result
        preview_structure = task_result.get("draft_structure")
        if not isinstance(preview_structure, dict) or not task_result.get(
            "requires_apply"
        ):
            raise ValueError("source task has no applicable outline preview")
        self._validate_structure_preview_shape(
            preview_structure,
            draft_structure,
        )
        await context_facade.require_fresh_confirmation(
            db,
            novel_id=novel_id,
            action="outline.generate",
            confirmation_id=confirmation_id,
        )

        start_chapter = int(task_meta.get("start_chapter") or 1)
        end_chapter = int(task_meta.get("end_chapter") or 10)
        if end_chapter < start_chapter:
            raise ValueError("outline preview chapter range is invalid")
        adopted_at = datetime.now(UTC).isoformat()
        generator = PlotStructureGenerator()
        result = await generator.apply_preview(
            db,
            novel_id=novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            draft_structure=draft_structure,
            provenance_meta={
                "source": "ai_generated",
                "needs_review": False,
                "user_edited": True,
                "adopted_at": adopted_at,
                "context_confirmation_id": confirmation_id,
                "adopted_from_preview_task_id": source_task_id,
                "provenance_key": f"outline_structure_preview:{source_task_id}",
            },
        )
        applied_result = {"status": "applied", **result}
        await context_facade.attach_result_refs(
            db,
            confirmation_id=confirmation_id,
            result_refs=generator.result_refs(result),
            status="done",
        )
        task.result = {
            **task_result,
            "requires_apply": False,
            "apply_status": "applied",
            "applied_result": applied_result,
        }
        await db.flush()
        return applied_result

    @staticmethod
    def _validate_structure_preview_shape(
        preview_structure: dict,
        draft_structure: dict,
    ) -> None:
        if not isinstance(draft_structure, dict):
            raise ValueError("draft_structure must be an object")
        list_keys = (
            "threads",
            "arcs",
            "scenes",
            "foreshadowing_plans",
            "reveal_plans",
            "offscreen_progress",
            "risks",
            "questions_for_user",
            "turning_points",
            "uncertain_items",
        )
        for key in list_keys:
            preview_items = preview_structure.get(key, [])
            draft_items = draft_structure.get(key, [])
            if not isinstance(preview_items, list) or not isinstance(
                draft_items, list
            ):
                raise ValueError(f"draft_structure.{key} must be a list")
            if len(draft_items) != len(preview_items):
                raise ValueError(
                    f"draft_structure.{key} must match the preview item count"
                )

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
        extracted = await run_managed_structured(
            LLMClient(),
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
            step_name="outline.ai_workflow.chapter_scenes.structured",
            partial_list_fields={"scenes"},
            format_repair_attempts=1,
        )

        draft_scenes: list[dict] = []
        for scene in extracted.scenes:
            chapter_ids = scene.chapter_ids or [str(chapter_index)]
            draft_scenes.append(
                {
                    "title": scene.title[:255],
                    "goal": scene.goal,
                    "core_conflict": scene.core_conflict,
                    "emotional_beat": scene.emotional_beat,
                    "must_happen": scene.must_happen,
                    "must_not_happen": scene.must_not_happen,
                    "narrative_tag": scene.narrative_tag or "draft",
                    "source": "ai_generated",
                    "scene_chunks": scene.scene_chunks,
                    "chapter_ids": chapter_ids,
                    "status": "draft",
                    "display_state": "review",
                    "structure_meta": {
                        "preview_only": True,
                        "needs_review": True,
                        "context_confirmation_id": confirmation_id,
                        "source_task_id": task_id,
                    },
                }
            )

        await context_facade.attach_result_ref(
            db,
            confirmation_id=confirmation_id,
            result_type="outline_scene_preview",
            result_id=task_id,
            status="done",
        )

        if progress_callback is not None:
            progress_callback(1.0)
        await db.flush()
        return {
            "scene_ids": [],
            "draft_scenes": draft_scenes,
            "total_scenes": len(draft_scenes),
            "requires_apply": True,
        }

    async def apply_chapter_scene_preview(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        confirmation_id: str,
        source_task_id: str,
        draft_scenes: list[dict],
        confirmed: bool,
    ) -> dict:
        if not confirmed:
            raise PermissionError("chapter Scene preview apply requires confirmed=true")
        task_stmt = (
            select(AsyncTask)
            .where(
                AsyncTask.id == parse_uuid(source_task_id, "source_task_id")
            )
            .with_for_update()
        )
        task = (await db.execute(task_stmt)).scalar_one_or_none()
        if task is None or task.task_type != "outline_chapter_scenes_extract":
            raise ValueError("source_task_id must reference a Scene preview task")
        task_meta = dict(task.meta or {})
        if task_meta.get("novel_id") != novel_id:
            raise ValueError("Scene preview task novel_id mismatch")
        if task_meta.get("context_confirmation_id") != confirmation_id:
            raise ValueError("Scene preview task confirmation mismatch")
        if task.status != "done":
            raise ValueError("Scene preview task is not complete")
        task_result = dict(task.result or {})
        applied_ids = task_result.get("applied_scene_ids")
        if isinstance(applied_ids, list) and applied_ids:
            return {
                "status": "applied",
                "scene_ids": [str(scene_id) for scene_id in applied_ids],
                "total_scenes": len(applied_ids),
            }
        preview_scenes = task_result.get("draft_scenes")
        if not isinstance(preview_scenes, list) or not task_result.get(
            "requires_apply"
        ):
            raise ValueError("source task has no applicable Scene preview")
        if len(draft_scenes) != len(preview_scenes):
            raise ValueError("draft_scenes must match the preview item count")
        await context_facade.require_fresh_confirmation(
            db,
            novel_id=novel_id,
            action="outline.chapter_scenes.extract",
            confirmation_id=confirmation_id,
        )

        scene_service = SceneService()
        next_index = await scene_service.get_next_scene_index(db, novel_id)
        adopted_at = datetime.now(UTC).isoformat()
        allowed_fields = {
            "title",
            "goal",
            "core_conflict",
            "emotional_beat",
            "must_happen",
            "must_not_happen",
            "narrative_tag",
            "scene_chunks",
            "chapter_ids",
        }
        payloads: list[dict] = []
        from modules.outline.scene_workbench import SceneWorkbenchService

        mapping_validator = SceneWorkbenchService()
        allowed_chunk_fields = {
            "chapter_index",
            "chapter_id",
            "start_pos",
            "end_pos",
            "start_offset",
            "end_offset",
            "start_paragraph",
            "end_paragraph",
        }
        for offset, raw_scene in enumerate(draft_scenes):
            if not isinstance(raw_scene, dict):
                raise ValueError("draft_scenes items must be objects")
            payload = {
                key: value
                for key, value in raw_scene.items()
                if key in allowed_fields
            }
            raw_chunks = payload.get("scene_chunks")
            if raw_chunks is not None:
                if not isinstance(raw_chunks, list) or not all(
                    isinstance(chunk, dict) for chunk in raw_chunks
                ):
                    raise ValueError("scene_chunks items must be objects")
                payload["scene_chunks"] = [
                    {
                        key: value
                        for key, value in chunk.items()
                        if key in allowed_chunk_fields
                    }
                    for chunk in raw_chunks
                ]
            await mapping_validator.validate_mapping_chapters(
                db,
                novel_id,
                payload.get("chapter_ids"),
                payload.get("scene_chunks"),
            )
            meta = {
                "preview_only": False,
                "needs_review": False,
                "adopted_at": adopted_at,
                "source": "ai_generated",
                "context_confirmation_id": confirmation_id,
                "adopted_from_preview_task_id": source_task_id,
                "provenance_key": f"outline_scene_preview:{source_task_id}:{offset}",
            }
            payload.update(
                {
                    "scene_index": next_index + offset,
                    "source": "ai_generated",
                    "status": "draft",
                    "structure_meta": meta,
                }
            )
            payloads.append(SceneCreate(**payload).model_dump())

        created = await scene_service.batch_create_models_from_dicts(
            db,
            novel_id,
            payloads,
        )
        created_ids = [str(scene.id) for scene in created]
        await context_facade.attach_result_refs(
            db,
            confirmation_id=confirmation_id,
            result_refs=[
                {"type": "outline_scene", "id": scene_id}
                for scene_id in created_ids
            ],
            status="done",
        )
        task.result = {
            **task_result,
            "apply_status": "applied",
            "applied_scene_ids": created_ids,
        }
        await db.flush()
        return {
            "status": "applied",
            "scene_ids": created_ids,
            "total_scenes": len(created_ids),
        }
