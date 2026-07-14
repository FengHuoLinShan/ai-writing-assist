"""Internal Outline AI workflow orchestration."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.agent_step_harness import (
    run_managed_generate,
    run_managed_structured,
)
from infrastructure.llm.client import LLMClient
from infrastructure.llm.schemas import LLMCallRequest, LLMMessage
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


@dataclass(frozen=True)
class _ConfirmedTaskPrompt:
    novel_id: str
    action: str
    confirmation_id: str
    rendered_markdown: str
    source_fingerprint: str


class OutlineAIWorkflowService:
    """Owns confirmed Outline AI workflows used by async task handlers."""

    def __init__(self, *, llm_client: LLMClient | None = None) -> None:
        self._llm_client = llm_client

    @asynccontextmanager
    async def _open_llm_client(
        self,
        db: AsyncSession,
        novel_id: str,
    ) -> AsyncIterator[LLMClient]:
        if self._llm_client is not None:
            yield self._llm_client
            return

        from modules.project.facade import open_project_llm_client

        async with open_project_llm_client(db, novel_id) as client:
            yield client

    @asynccontextmanager
    async def _open_task_llm_client(
        self,
        db: AsyncSession,
        novel_id: str,
        llm_execution_snapshot: dict[str, Any],
    ) -> AsyncIterator[LLMClient]:
        """Restore one frozen task profile before the transaction checkpoint."""
        if self._llm_client is not None:
            yield self._llm_client
            return
        if not isinstance(llm_execution_snapshot, dict) or not llm_execution_snapshot:
            raise ValueError("llm_execution_snapshot is required for outline tasks")

        from modules.project.facade import (
            create_project_snapshot_llm_client,
            restore_project_llm_execution_settings,
        )

        project_settings = await restore_project_llm_execution_settings(
            db,
            novel_id,
            llm_execution_snapshot,
        )
        client = create_project_snapshot_llm_client(
            project_settings,
            novel_id=novel_id,
        )
        try:
            yield client
        finally:
            await client.close()

    async def analyze_for_task(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        confirmation_id: str,
        task_id: str,
        llm_execution_snapshot: dict[str, Any],
        instruction: str | None = None,
        progress_callback: Callable[[float], None] | None = None,
    ) -> dict:
        """Run confirmed analysis with the provider wait outside a transaction."""
        self._require_task_session(db)
        await self._require_active_project(db, novel_id)
        plan = await self._prepare_confirmed_task_prompt(
            db,
            novel_id=novel_id,
            action="outline.analyze",
            confirmation_id=confirmation_id,
        )
        async with self._open_task_llm_client(
            db,
            novel_id,
            llm_execution_snapshot,
        ) as client:
            await self._checkpoint_before_external_call(db)
            response = await self._run_analysis_llm(
                client,
                markdown=plan.rendered_markdown,
                instruction=instruction,
            )

        await self._finalize_confirmed_task_result(
            db,
            plan=plan,
            result_type="outline_analysis",
            result_id=task_id,
        )
        if progress_callback is not None:
            progress_callback(1.0)
        await db.flush()
        return {"analysis": response.content}

    async def generate_for_task(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        confirmation_id: str,
        task_id: str,
        start_chapter: int,
        end_chapter: int,
        llm_execution_snapshot: dict[str, Any],
        progress_callback: Callable[[float], None] | None = None,
    ) -> dict:
        """Generate a confirmed structure preview without a long DB transaction."""
        self._require_task_session(db)
        await self._require_active_project(db, novel_id)
        confirmation_plan = await self._prepare_confirmed_task_prompt(
            db,
            novel_id=novel_id,
            action="outline.generate",
            confirmation_id=confirmation_id,
        )
        generator = PlotStructureGenerator()
        generator_plan = await generator.prepare_task_preview(
            db,
            novel_id=novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            project_settings_snapshot=self._frozen_generator_settings(
                llm_execution_snapshot
            ),
        )
        async with self._open_task_llm_client(
            db,
            novel_id,
            llm_execution_snapshot,
        ) as client:
            await self._checkpoint_before_external_call(db)
            result = await generator.execute_task_preview(
                generator_plan,
                llm_client=client,
            )

        await self._require_active_project(db, novel_id)
        await self._require_confirmed_task_prompt_fresh(db, confirmation_plan)
        await generator.require_task_preview_fresh(db, generator_plan)
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

    async def extract_chapter_scenes_for_task(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        confirmation_id: str,
        task_id: str,
        chapter_index: int,
        llm_execution_snapshot: dict[str, Any],
        instruction: str | None = None,
        progress_callback: Callable[[float], None] | None = None,
    ) -> dict:
        """Extract Scene preview cards with no transaction during the LLM call."""
        self._require_task_session(db)
        await self._require_active_project(db, novel_id)
        plan = await self._prepare_confirmed_task_prompt(
            db,
            novel_id=novel_id,
            action="outline.chapter_scenes.extract",
            confirmation_id=confirmation_id,
        )
        scene_instruction = instruction or "从参考资料中提取当前章节的 Scene 卡。"
        async with self._open_task_llm_client(
            db,
            novel_id,
            llm_execution_snapshot,
        ) as client:
            await self._checkpoint_before_external_call(db)
            extracted = await self._run_scene_extraction_llm(
                client,
                markdown=plan.rendered_markdown,
                instruction=scene_instruction,
            )

        draft_scenes = self._scene_preview_payloads(
            extracted,
            confirmation_id=confirmation_id,
            task_id=task_id,
            chapter_index=chapter_index,
        )
        await self._finalize_confirmed_task_result(
            db,
            plan=plan,
            result_type="outline_scene_preview",
            result_id=task_id,
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

    async def generate_legacy_preview_for_task(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        llm_execution_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """Run the legacy preview-only task with the same checkpoint protocol."""
        self._require_task_session(db)
        await self._require_active_project(db, novel_id)
        generator = PlotStructureGenerator()
        plan = await generator.prepare_task_preview(
            db,
            novel_id=novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            project_settings_snapshot=self._frozen_generator_settings(
                llm_execution_snapshot
            ),
        )
        async with self._open_task_llm_client(
            db,
            novel_id,
            llm_execution_snapshot,
        ) as client:
            await self._checkpoint_before_external_call(db)
            result = await generator.execute_task_preview(plan, llm_client=client)

        await self._require_active_project(db, novel_id)
        await generator.require_task_preview_fresh(db, plan)
        return result

    @staticmethod
    def _require_task_session(db: AsyncSession) -> None:
        from infrastructure.tasks.facade import require_task_checkpoint_session

        require_task_checkpoint_session(db)

    @staticmethod
    def _frozen_generator_settings(
        llm_execution_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """Project the secret-free task snapshot into generator settings."""
        from shared.deep_import_settings import (
            DEEP_IMPORT_FROZEN_SETTINGS_KEY,
            DEEP_IMPORT_SETTINGS_KEY,
        )

        deep_import = llm_execution_snapshot.get(DEEP_IMPORT_SETTINGS_KEY)
        return {
            DEEP_IMPORT_SETTINGS_KEY: deepcopy(
                deep_import if isinstance(deep_import, dict) else {}
            ),
            DEEP_IMPORT_FROZEN_SETTINGS_KEY: True,
        }

    @staticmethod
    async def _require_active_project(db: AsyncSession, novel_id: str) -> None:
        from modules.project.facade import require_active_project

        await require_active_project(db, novel_id)

    @staticmethod
    async def _checkpoint_before_external_call(db: AsyncSession) -> None:
        await db.commit()
        if db.in_transaction():
            raise RuntimeError(
                "outline task LLM execution requires a transaction-free checkpoint"
            )
        # TaskHandlerSession deliberately uses expire_on_commit=False so the
        # detached task object can survive handler checkpoints.  Outline source
        # validation must not inherit that cache policy: confirmation/context/
        # generator ORM rows loaded during prepare could otherwise be reused by
        # the final SELECTs after a concurrent commit.  The external phase only
        # owns plain DTOs, so expiring the identity map here is both safe and
        # required for the post-LLM fingerprint rebuild to observe current data.
        db.expire_all()

    @classmethod
    async def _prepare_confirmed_task_prompt(
        cls,
        db: AsyncSession,
        *,
        novel_id: str,
        action: str,
        confirmation_id: str,
    ) -> _ConfirmedTaskPrompt:
        prepared = await context_facade.prepare_confirmed_ai_action(
            db,
            novel_id=novel_id,
            action=action,
            confirmation_id=confirmation_id,
        )
        markdown = str(prepared.rendered_markdown)
        confirmation = prepared.confirmation
        fingerprint = cls._stable_fingerprint(
            {
                "novel_id": novel_id,
                "action": action,
                "confirmation_id": confirmation_id,
                "compile_options": dict(prepared.compile_options),
                "selected_asset_ids": dict(confirmation.selected_asset_ids),
                "excluded_asset_ids": dict(confirmation.excluded_asset_ids),
                "confirmation_warnings": list(confirmation.warnings),
                "rendered_markdown": markdown,
                # Rendered text is the provider input, while this projection
                # preserves evidence identity and deterministic retrieval
                # decisions.  Equal text from a replaced asset must not make a
                # stale result look current.
                "compiled_context": cls._compiled_context_fingerprint(prepared.compiled),
            }
        )
        return _ConfirmedTaskPrompt(
            novel_id=novel_id,
            action=action,
            confirmation_id=confirmation_id,
            rendered_markdown=markdown,
            source_fingerprint=fingerprint,
        )

    @classmethod
    async def _require_confirmed_task_prompt_fresh(
        cls,
        db: AsyncSession,
        plan: _ConfirmedTaskPrompt,
    ) -> None:
        current = await cls._prepare_confirmed_task_prompt(
            db,
            novel_id=plan.novel_id,
            action=plan.action,
            confirmation_id=plan.confirmation_id,
        )
        if current.source_fingerprint != plan.source_fingerprint:
            raise ValueError(
                "outline confirmation context changed while the task was running; "
                "discarded stale result"
            )

    @classmethod
    async def _finalize_confirmed_task_result(
        cls,
        db: AsyncSession,
        *,
        plan: _ConfirmedTaskPrompt,
        result_type: str,
        result_id: str,
    ) -> None:
        await cls._require_active_project(db, plan.novel_id)
        await cls._require_confirmed_task_prompt_fresh(db, plan)
        await context_facade.attach_result_ref(
            db,
            confirmation_id=plan.confirmation_id,
            result_type=result_type,
            result_id=result_id,
            status="done",
        )

    @staticmethod
    def _stable_fingerprint(value: Any) -> str:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _compiled_context_fingerprint(compiled: Any) -> dict[str, Any]:
        sections: list[dict[str, Any]] = []
        for section in compiled.sections:
            retrieval_metadata = dict(section.retrieval_metadata or {})
            # Timings vary on every compile and do not describe provider input
            # or evidence provenance.
            retrieval_metadata.pop("latency_metadata", None)
            sections.append(
                {
                    "key": section.key,
                    "tier": int(section.tier),
                    "content": section.content,
                    "token_count": section.token_count,
                    "status": section.status,
                    "sources": list(section.sources or []),
                    "excluded": section.excluded,
                    "truncated_reason": section.truncated_reason,
                    "retrieval_metadata": retrieval_metadata,
                }
            )
        return {
            "sections": sections,
            "total_tokens": compiled.total_tokens,
            "budget_tokens": compiled.budget_tokens,
            "evicted_keys": list(compiled.evicted_keys),
            "truncated_keys": list(compiled.truncated_keys),
            "budget_events": [
                event.model_dump(mode="json") for event in compiled.budget_events
            ],
            "warnings": list(compiled.warnings),
        }

    @staticmethod
    async def _run_analysis_llm(
        client: LLMClient,
        *,
        markdown: str,
        instruction: str | None,
    ):
        return await run_managed_generate(
            client,
            LLMCallRequest(
                model=client.model_name,
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
                            f"{instruction or '分析当前剧情结构、冲突推进和风险。'}"
                            "\n\n"
                            "请给出剧情推进、冲突强度、伏笔回收和需要用户确认的问题。"
                        ),
                    ),
                ],
                temperature=0.3,
            ),
            step_name="outline.ai_workflow.analyze.generate",
        )

    @staticmethod
    async def _run_scene_extraction_llm(
        client: LLMClient,
        *,
        markdown: str,
        instruction: str,
    ) -> _ExtractedScenesResponse:
        return await run_managed_structured(
            client,
            LLMCallRequest(
                model=client.model_name,
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
                            f"{instruction}\n\n"
                            '输出格式：{"scenes": [{"title": "...", '
                            '"goal": "...", "core_conflict": "...", '
                            '"emotional_beat": "...", '
                            '"must_happen": "...", '
                            '"must_not_happen": "...", '
                            '"narrative_tag": "draft", '
                            '"chapter_ids": ["章节编号"], '
                            '"scene_chunks": []}]}'
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

    @staticmethod
    def _scene_preview_payloads(
        extracted: _ExtractedScenesResponse,
        *,
        confirmation_id: str,
        task_id: str,
        chapter_index: int,
    ) -> list[dict]:
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
        return draft_scenes

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
        async with self._open_llm_client(db, novel_id) as client:
            response = await self._run_analysis_llm(
                client,
                markdown=markdown,
                instruction=instruction,
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
        async with self._open_llm_client(db, novel_id) as client:
            result = await PlotStructureGenerator(llm_client=client).generate(
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
        parse_uuid(source_task_id, "source_task_id")
        from infrastructure.tasks.facade import (
            get_completed_task_payload,
            replace_completed_task_result,
        )

        task = await get_completed_task_payload(
            db,
            task_id=source_task_id,
            task_type="outline_generate",
            novel_id=novel_id,
            for_update=True,
        )
        if task is None:
            raise ValueError(
                "source_task_id must reference a confirmed outline preview task"
            )
        if task.context_confirmation_id != confirmation_id:
            raise ValueError("outline preview task confirmation mismatch")

        task_result = task.result
        applied_result = task_result.get("applied_result")
        if (
            isinstance(applied_result, dict)
            and task_result.get("apply_status") == "applied"
        ):
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

        start_chapter = task.start_chapter or 1
        end_chapter = task.end_chapter or 10
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
        replaced = await replace_completed_task_result(
            db,
            task_id=source_task_id,
            task_type="outline_generate",
            novel_id=novel_id,
            expected_revision_token=task.revision_token,
            result={
                **task_result,
                "requires_apply": False,
                "apply_status": "applied",
                "applied_result": applied_result,
            },
        )
        if not replaced:
            raise ValueError("outline preview task is no longer applicable")
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
            if not isinstance(preview_items, list) or not isinstance(draft_items, list):
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
        async with self._open_llm_client(db, novel_id) as client:
            extracted = await self._run_scene_extraction_llm(
                client,
                markdown=markdown,
                instruction=scene_instruction,
            )

        draft_scenes = self._scene_preview_payloads(
            extracted,
            confirmation_id=confirmation_id,
            task_id=task_id,
            chapter_index=chapter_index,
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
        parse_uuid(source_task_id, "source_task_id")
        from infrastructure.tasks.facade import (
            get_completed_task_payload,
            replace_completed_task_result,
        )

        task = await get_completed_task_payload(
            db,
            task_id=source_task_id,
            task_type="outline_chapter_scenes_extract",
            novel_id=novel_id,
            for_update=True,
        )
        if task is None:
            raise ValueError("source_task_id must reference a Scene preview task")
        if task.context_confirmation_id != confirmation_id:
            raise ValueError("Scene preview task confirmation mismatch")
        task_result = task.result
        applied_ids = task_result.get("applied_scene_ids")
        if isinstance(applied_ids, list) and applied_ids:
            return {
                "status": "applied",
                "scene_ids": [str(scene_id) for scene_id in applied_ids],
                "total_scenes": len(applied_ids),
            }
        preview_scenes = task_result.get("draft_scenes")
        if not isinstance(preview_scenes, list) or not task_result.get("requires_apply"):
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
                key: value for key, value in raw_scene.items() if key in allowed_fields
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
                {"type": "outline_scene", "id": scene_id} for scene_id in created_ids
            ],
            status="done",
        )
        replaced = await replace_completed_task_result(
            db,
            task_id=source_task_id,
            task_type="outline_chapter_scenes_extract",
            novel_id=novel_id,
            expected_revision_token=task.revision_token,
            result={
                **task_result,
                "apply_status": "applied",
                "applied_scene_ids": created_ids,
            },
        )
        if not replaced:
            raise ValueError("Scene preview task is no longer applicable")
        return {
            "status": "applied",
            "scene_ids": created_ids,
            "total_scenes": len(created_ids),
        }
