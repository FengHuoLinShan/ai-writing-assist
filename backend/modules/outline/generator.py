"""AI 剧情结构生成器入口。

`PlotStructureGenerator` 是薄协调层，负责把上下文构建、LLM 解析、持久化
三个深度模块串起来。实际逻辑分别位于 `modules.outline.generation.*`。
"""

import hashlib
import json
import logging
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.llm.client import LLMClient
from infrastructure.llm.redaction import redact_diagnostic
from infrastructure.llm.token_estimation import estimate_token_count
from modules.outline.generation.context_builder import (
    PlotStructureContext,
    PlotStructureContextBuilder,
)
from modules.outline.generation.models import (
    ForeshadowingPlan,
    GeneratedArc,
    GeneratedScene,
    GeneratedThread,
    OffscreenProgress,
    Question,
    RevealPlan,
    Risk,
)
from modules.outline.generation.parser import ParsedPlotStructure, PlotStructureParser
from modules.outline.generation.persister import PlotStructurePersister
from modules.outline.services import (
    ForeshadowingPlanService,
    OutlineArcService,
    PlotThreadService,
    RevealPlanService,
    SceneService,
)
from shared.utils import parse_uuid

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlotStructureTaskPreviewPlan:
    """Detached generator input used only by the TaskWorker workflow."""

    novel_id: str
    start_chapter: int
    end_chapter: int
    context_mode: str
    include_pending_objects: bool
    include_chapter_texts: bool
    include_existing_scenes: bool
    generate_scenes: bool
    fast_structured: bool
    high_quality: bool
    max_tokens: int
    context: PlotStructureContext
    source_fingerprint: str


class PlotStructureGenerator:
    """AI 剧情结构生成器 — 薄协调层。"""

    def __init__(
        self,
        context_builder: PlotStructureContextBuilder | None = None,
        llm_client: LLMClient | None = None,
        persister: PlotStructurePersister | None = None,
    ) -> None:
        self._context_builder = context_builder or PlotStructureContextBuilder()
        self._llm_client = llm_client
        self._persister = persister or PlotStructurePersister(
            thread_service=PlotThreadService(),
            arc_service=OutlineArcService(),
            scene_service=SceneService(),
            foreshadowing_service=ForeshadowingPlanService(),
            reveal_service=RevealPlanService(),
        )

    async def prepare_task_preview(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        context_mode: str = "canonical",
        include_pending_objects: bool = False,
        include_chapter_texts: bool = True,
        include_existing_scenes: bool = False,
        generate_scenes: bool = True,
        fast_structured: bool = False,
        high_quality: bool = False,
        project_settings_snapshot: dict[str, Any] | None = None,
    ) -> PlotStructureTaskPreviewPlan:
        """Materialize plain generator input before a task releases its DB locks."""
        context = await self._context_builder.build(
            db,
            novel_id,
            start_chapter,
            end_chapter,
            context_mode=context_mode,
            include_pending_objects=include_pending_objects,
            include_chapter_texts=include_chapter_texts,
            include_existing_scenes=include_existing_scenes,
        )
        detached_context = self._detach_context(context)
        max_tokens = self._structure_max_tokens(project_settings_snapshot)
        source_fingerprint = self._task_preview_fingerprint(
            detached_context,
            novel_id=novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            context_mode=context_mode,
            include_pending_objects=include_pending_objects,
            include_chapter_texts=include_chapter_texts,
            include_existing_scenes=include_existing_scenes,
            generate_scenes=generate_scenes,
            fast_structured=fast_structured,
            high_quality=high_quality,
            max_tokens=max_tokens,
        )
        return PlotStructureTaskPreviewPlan(
            novel_id=novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            context_mode=context_mode,
            include_pending_objects=include_pending_objects,
            include_chapter_texts=include_chapter_texts,
            include_existing_scenes=include_existing_scenes,
            generate_scenes=generate_scenes,
            fast_structured=fast_structured,
            high_quality=high_quality,
            max_tokens=max_tokens,
            context=detached_context,
            source_fingerprint=source_fingerprint,
        )

    async def execute_task_preview(
        self,
        plan: PlotStructureTaskPreviewPlan,
        *,
        llm_client: LLMClient | None = None,
    ) -> dict[str, Any]:
        """Run only the external LLM phase for a prepared task preview."""
        client = llm_client or self._llm_client
        if client is None:
            raise RuntimeError("task preview execution requires a prepared LLM client")
        parsed = await PlotStructureParser(
            plan.context,
            include_scenes=plan.generate_scenes,
            fast_structured=plan.fast_structured,
            max_tokens=plan.max_tokens,
            high_quality=plan.high_quality,
        ).parse(
            client,
            client.model_name,
            plan.start_chapter,
            plan.end_chapter,
        )
        if parsed is None:
            logger.error(
                "All generation attempts returned empty or failed for novel %s",
                plan.novel_id,
            )
            return self._empty_task_preview_result()
        return self._preview_result(parsed, warnings=plan.context.warnings)

    async def require_task_preview_fresh(
        self,
        db: AsyncSession,
        plan: PlotStructureTaskPreviewPlan,
    ) -> None:
        """Rebuild task input and reject an LLM result derived from stale sources."""
        context = await self._context_builder.build(
            db,
            plan.novel_id,
            plan.start_chapter,
            plan.end_chapter,
            context_mode=plan.context_mode,
            include_pending_objects=plan.include_pending_objects,
            include_chapter_texts=plan.include_chapter_texts,
            include_existing_scenes=plan.include_existing_scenes,
        )
        current_fingerprint = self._task_preview_fingerprint(
            self._detach_context(context),
            novel_id=plan.novel_id,
            start_chapter=plan.start_chapter,
            end_chapter=plan.end_chapter,
            context_mode=plan.context_mode,
            include_pending_objects=plan.include_pending_objects,
            include_chapter_texts=plan.include_chapter_texts,
            include_existing_scenes=plan.include_existing_scenes,
            generate_scenes=plan.generate_scenes,
            fast_structured=plan.fast_structured,
            high_quality=plan.high_quality,
            max_tokens=plan.max_tokens,
        )
        if current_fingerprint != plan.source_fingerprint:
            raise ValueError(
                "outline generation sources changed while the task was running; "
                "discarded stale preview"
            )

    async def generate(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        *,
        context_mode: str = "canonical",
        include_pending_objects: bool = False,
        workflow_id: str | None = None,
        audit_context_snapshot: bool = False,
        include_chapter_texts: bool = True,
        include_existing_scenes: bool = False,
        generate_scenes: bool = True,
        fast_structured: bool = False,
        high_quality: bool = False,
        project_settings_snapshot: dict[str, Any] | None = None,
        persist: bool = False,
    ) -> dict[str, Any]:
        """为指定章节范围生成剧情结构。

        默认只返回可编辑 preview；只有已授权自动流水线才应显式
        传入 ``persist=True``。
        """
        if self._llm_client is None:
            if project_settings_snapshot is not None:
                from modules.project.facade import create_project_snapshot_llm_client

                client = create_project_snapshot_llm_client(
                    project_settings_snapshot,
                    novel_id=novel_id,
                )
                try:
                    return await PlotStructureGenerator(
                        context_builder=self._context_builder,
                        llm_client=client,
                        persister=self._persister,
                    ).generate(
                        db,
                        novel_id,
                        start_chapter,
                        end_chapter,
                        context_mode=context_mode,
                        include_pending_objects=include_pending_objects,
                        workflow_id=workflow_id,
                        audit_context_snapshot=audit_context_snapshot,
                        include_chapter_texts=include_chapter_texts,
                        include_existing_scenes=include_existing_scenes,
                        generate_scenes=generate_scenes,
                        fast_structured=fast_structured,
                        high_quality=high_quality,
                        project_settings_snapshot=project_settings_snapshot,
                        persist=persist,
                    )
                finally:
                    await client.close()

            from modules.project.facade import open_project_llm_client

            async with open_project_llm_client(db, novel_id) as client:
                return await PlotStructureGenerator(
                    context_builder=self._context_builder,
                    llm_client=client,
                    persister=self._persister,
                ).generate(
                    db,
                    novel_id,
                    start_chapter,
                    end_chapter,
                    context_mode=context_mode,
                    include_pending_objects=include_pending_objects,
                    workflow_id=workflow_id,
                    audit_context_snapshot=audit_context_snapshot,
                    include_chapter_texts=include_chapter_texts,
                    include_existing_scenes=include_existing_scenes,
                    generate_scenes=generate_scenes,
                    fast_structured=fast_structured,
                    high_quality=high_quality,
                    persist=persist,
                )
        nid = parse_uuid(novel_id, "novel_id")

        context = await self._context_builder.build(
            db,
            novel_id,
            start_chapter,
            end_chapter,
            context_mode=context_mode,
            include_pending_objects=include_pending_objects,
            include_chapter_texts=include_chapter_texts,
            include_existing_scenes=include_existing_scenes,
        )

        parser = PlotStructureParser(
            context,
            include_scenes=generate_scenes,
            fast_structured=fast_structured,
            max_tokens=self._structure_max_tokens(project_settings_snapshot),
            high_quality=high_quality,
        )
        model = self._llm_client.model_name
        snapshot_id: str | None = None
        if audit_context_snapshot:
            snapshot_id = await self._create_structure_snapshot(
                db,
                novel_id,
                start_chapter,
                end_chapter,
                context.markdown,
                warnings=context.warnings,
                model=model,
                workflow_id=workflow_id,
                context_mode=context_mode,
                include_pending_objects=include_pending_objects,
                max_tokens=self._structure_max_tokens(project_settings_snapshot),
            )
        try:
            parsed = await parser.parse(
                self._llm_client,
                model,
                start_chapter,
                end_chapter,
            )
        except Exception as exc:
            if snapshot_id is not None:
                await self._mark_structure_snapshot_failed(
                    db, novel_id, snapshot_id, exc
                )
                await db.commit()
            raise

        if parsed is None:
            if snapshot_id is not None:
                from modules.context.facade import fail_context_snapshot

                await fail_context_snapshot(
                    db,
                    novel_id=novel_id,
                    snapshot_id=snapshot_id,
                    error_kind="empty_output",
                    error_message="LLM returned empty structure output",
                )
            logger.error(
                "All generation attempts returned empty or failed for novel %s",
                novel_id,
            )
            audit_summary = self._audit_summary(
                snapshot_count=1 if snapshot_id else 0,
                succeeded=0,
                failed=1 if snapshot_id else 0,
            )
            snapshot_health_summary = await self._snapshot_health_summary(
                db,
                novel_id,
                workflow_id=workflow_id,
            )
            data = {
                "total_threads": 0,
                "total_arcs": 0,
                "total_scenes": 0,
                "existing_threads_count": 0,
                "existing_arcs_count": 0,
                "threads": [],
                "arcs": [],
                "scenes": [],
                "extra_sections": {},
                "warnings": ["LLM 多次返回空结果，请重试"],
                "audit_summary": audit_summary,
                "snapshot_health_summary": snapshot_health_summary,
            }
            if not persist:
                data.update(
                    {
                        "draft_structure": self._empty_draft_structure(),
                        "requires_apply": False,
                        "display_state": "review",
                    }
                )
            return data

        if not persist:
            data = self._preview_result(parsed, warnings=context.warnings)
            if snapshot_id is not None:
                from modules.context.facade import succeed_context_snapshot

                await succeed_context_snapshot(
                    db,
                    novel_id=novel_id,
                    snapshot_id=snapshot_id,
                    result_refs=[],
                )
                data["audit_summary"] = self._audit_summary(
                    snapshot_count=1,
                    succeeded=1,
                    failed=0,
                )
                data["snapshot_health_summary"] = await self._snapshot_health_summary(
                    db,
                    novel_id,
                    workflow_id=workflow_id,
                )
            return data

        try:
            if snapshot_id is not None:
                async with db.begin_nested():
                    result = await self._persister.persist(
                        db,
                        nid,
                        start_chapter,
                        end_chapter,
                        parsed,
                        entity_name_to_id=context.entity_name_to_id,
                        character_name_to_id=context.character_name_to_id,
                        workflow_id=workflow_id,
                    )
            else:
                result = await self._persister.persist(
                    db,
                    nid,
                    start_chapter,
                    end_chapter,
                    parsed,
                    entity_name_to_id=context.entity_name_to_id,
                    character_name_to_id=context.character_name_to_id,
                    workflow_id=workflow_id,
                )
            data = result.to_dict()
            if snapshot_id is not None:
                refs = self._result_refs(data)
                from modules.context.facade import succeed_context_snapshot

                await succeed_context_snapshot(
                    db,
                    novel_id=novel_id,
                    snapshot_id=snapshot_id,
                    result_refs=refs,
                )
                data["audit_summary"] = self._audit_summary(
                    snapshot_count=1,
                    succeeded=1,
                    failed=0,
                )
                data["snapshot_health_summary"] = await self._snapshot_health_summary(
                    db,
                    novel_id,
                    workflow_id=workflow_id,
                )
        except Exception as exc:
            if snapshot_id is not None:
                await self._mark_structure_snapshot_failed(
                    db, novel_id, snapshot_id, exc
                )
                await db.commit()
            raise
        return data

    async def apply_preview(
        self,
        db: AsyncSession,
        *,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        draft_structure: dict[str, Any],
        provenance_meta: dict[str, Any],
    ) -> dict[str, Any]:
        """校验并将作者确认过的结构 preview 写入普通工作资产。"""
        nid = parse_uuid(novel_id, "novel_id")
        parsed = self._parse_preview_structure(draft_structure)
        context = await self._context_builder.build(
            db,
            novel_id,
            start_chapter,
            end_chapter,
            context_mode="canonical",
            include_pending_objects=False,
            include_chapter_texts=False,
            include_existing_scenes=False,
        )
        async with db.begin_nested():
            result = await self._persister.persist(
                db,
                nid,
                start_chapter,
                end_chapter,
                parsed,
                entity_name_to_id=context.entity_name_to_id,
                character_name_to_id=context.character_name_to_id,
                provenance_meta_override=provenance_meta,
                strict=True,
            )
        return result.to_dict()

    @staticmethod
    def result_refs(data: dict[str, Any]) -> list[dict[str, str]]:
        """返回已持久化结构的稳定结果引用。"""
        return PlotStructureGenerator._result_refs(data)

    @staticmethod
    def _preview_result(
        parsed: ParsedPlotStructure,
        *,
        warnings: list[str],
    ) -> dict[str, Any]:
        draft = {
            "threads": PlotStructureGenerator._preview_items(parsed.threads),
            "arcs": PlotStructureGenerator._preview_items(parsed.arcs),
            "scenes": PlotStructureGenerator._preview_items(parsed.scenes),
            "foreshadowing_plans": PlotStructureGenerator._preview_items(
                parsed.foreshadowing_plans
            ),
            "reveal_plans": PlotStructureGenerator._preview_items(parsed.reveal_plans),
            "offscreen_progress": PlotStructureGenerator._preview_items(
                parsed.offscreen_progress
            ),
            "risks": PlotStructureGenerator._preview_items(parsed.risks),
            "questions_for_user": PlotStructureGenerator._preview_items(
                parsed.questions_for_user
            ),
            "turning_points": list(parsed.turning_points or []),
            "uncertain_items": list(parsed.uncertain_items or []),
            "diagnostics": dict(parsed.diagnostics or {}),
        }
        return {
            "total_threads": len(draft["threads"]),
            "total_arcs": len(draft["arcs"]),
            "total_scenes": len(draft["scenes"]),
            "existing_threads_count": 0,
            "existing_arcs_count": 0,
            "threads": draft["threads"],
            "arcs": draft["arcs"],
            "scenes": draft["scenes"],
            "extra_sections": {
                "foreshadowing_plans": draft["foreshadowing_plans"],
                "reveal_plans": draft["reveal_plans"],
                "offscreen_progress": draft["offscreen_progress"],
                "risks": draft["risks"],
                "questions_for_user": draft["questions_for_user"],
                "turning_points": draft["turning_points"],
                "uncertain_items": draft["uncertain_items"],
                "structure_diagnostics": draft["diagnostics"],
            },
            "warnings": list(warnings),
            "draft_structure": draft,
            "requires_apply": any(
                bool(draft[key])
                for key in (
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
            ),
            "display_state": "review",
        }

    @staticmethod
    def _preview_items(items: list[Any]) -> list[dict[str, Any]]:
        return [
            {
                **item.model_dump(mode="json"),
                "display_state": "review",
                "source": "ai_generated",
                "needs_review": True,
            }
            for item in items
        ]

    @staticmethod
    def _detach_context(context: PlotStructureContext) -> PlotStructureContext:
        """Copy context values so the external phase cannot retain ORM state."""
        return PlotStructureContext(
            markdown=str(context.markdown),
            warnings=list(context.warnings),
            entity_name_to_id=dict(context.entity_name_to_id),
            character_name_to_id=dict(context.character_name_to_id),
            scenes=deepcopy(context.scenes),
        )

    @staticmethod
    def _task_preview_fingerprint(
        context: PlotStructureContext,
        **configuration: Any,
    ) -> str:
        payload = {
            "configuration": configuration,
            "context": {
                "markdown": context.markdown,
                "warnings": context.warnings,
                "entity_name_to_id": context.entity_name_to_id,
                "character_name_to_id": context.character_name_to_id,
                "scenes": context.scenes,
            },
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def _empty_task_preview_result(cls) -> dict[str, Any]:
        return {
            "total_threads": 0,
            "total_arcs": 0,
            "total_scenes": 0,
            "existing_threads_count": 0,
            "existing_arcs_count": 0,
            "threads": [],
            "arcs": [],
            "scenes": [],
            "extra_sections": {},
            "warnings": ["LLM 多次返回空结果，请重试"],
            "audit_summary": cls._audit_summary(
                snapshot_count=0,
                succeeded=0,
                failed=0,
            ),
            "snapshot_health_summary": {},
            "draft_structure": cls._empty_draft_structure(),
            "requires_apply": False,
            "display_state": "review",
        }

    @staticmethod
    def _empty_draft_structure() -> dict[str, Any]:
        return {
            "threads": [],
            "arcs": [],
            "scenes": [],
            "foreshadowing_plans": [],
            "reveal_plans": [],
            "offscreen_progress": [],
            "risks": [],
            "questions_for_user": [],
            "turning_points": [],
            "uncertain_items": [],
            "diagnostics": {},
        }

    @staticmethod
    def _parse_preview_structure(
        draft_structure: dict[str, Any],
    ) -> ParsedPlotStructure:
        if not isinstance(draft_structure, dict):
            raise ValueError("draft_structure must be an object")

        def parse_items(key: str, model: type[Any]) -> list[Any]:
            raw_items = draft_structure.get(key, [])
            if not isinstance(raw_items, list):
                raise ValueError(f"draft_structure.{key} must be a list")
            if not all(isinstance(item, dict) for item in raw_items):
                raise ValueError(f"draft_structure.{key} items must be objects")
            return [model.model_validate(item) for item in raw_items]

        turning_points = draft_structure.get("turning_points", [])
        uncertain_items = draft_structure.get("uncertain_items", [])
        diagnostics = draft_structure.get("diagnostics", {})
        if not isinstance(turning_points, list):
            raise ValueError("draft_structure.turning_points must be a list")
        if not isinstance(uncertain_items, list):
            raise ValueError("draft_structure.uncertain_items must be a list")
        if not isinstance(diagnostics, dict):
            raise ValueError("draft_structure.diagnostics must be an object")

        threads = parse_items("threads", GeneratedThread)
        arcs = parse_items("arcs", GeneratedArc)
        scenes = parse_items("scenes", GeneratedScene)
        foreshadowing_plans = parse_items("foreshadowing_plans", ForeshadowingPlan)
        reveal_plans = parse_items("reveal_plans", RevealPlan)
        required_text_fields = (
            ("threads", threads, "name"),
            ("arcs", arcs, "title"),
            ("scenes", scenes, "title"),
            ("foreshadowing_plans", foreshadowing_plans, "name"),
            ("reveal_plans", reveal_plans, "target_name"),
        )
        for key, items, field in required_text_fields:
            if any(not str(getattr(item, field, "") or "").strip() for item in items):
                raise ValueError(f"draft_structure.{key} items require non-empty {field}")

        return ParsedPlotStructure(
            threads=threads,
            arcs=arcs,
            scenes=scenes,
            foreshadowing_plans=foreshadowing_plans,
            reveal_plans=reveal_plans,
            offscreen_progress=parse_items("offscreen_progress", OffscreenProgress),
            risks=parse_items("risks", Risk),
            questions_for_user=parse_items("questions_for_user", Question),
            turning_points=turning_points,
            uncertain_items=uncertain_items,
            diagnostics=diagnostics,
        )

    async def _create_structure_snapshot(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        markdown: str,
        *,
        warnings: list[str],
        model: str,
        workflow_id: str | None,
        context_mode: str,
        include_pending_objects: bool,
        max_tokens: int,
    ) -> str:
        from modules.context.contracts import ContextSnapshotRequest
        from modules.context.facade import open_context_snapshot

        token_estimate = estimate_token_count(markdown, model=model)
        snapshot = await open_context_snapshot(
            db,
            ContextSnapshotRequest(
                novel_id=novel_id,
                task_id=workflow_id,
                workflow_id=workflow_id,
                phase="structure_analysis",
                operation="plot_structure_generation",
                chapter_index=start_chapter,
                context_mode=context_mode,
                include_pending_objects=include_pending_objects,
                prompt_name="phase3_structure_simple",
                model=model,
                compile_options={
                    "source": "deep_import_phase3_structure_context",
                    "scope": "full",
                    "start_chapter": start_chapter,
                    "end_chapter": end_chapter,
                    "context_mode": context_mode,
                    "include_pending_objects": include_pending_objects,
                },
                included_asset_ids={
                    "context_sections": ["structure_context"],
                    "chapters": [str(i) for i in range(start_chapter, end_chapter + 1)],
                },
                context_summary={
                    "chapter_range": {"start": start_chapter, "end": end_chapter},
                    "context_mode": context_mode,
                    "include_pending_objects": include_pending_objects,
                    "section_count": 1,
                    "total_tokens": token_estimate,
                    "evicted": [],
                    "truncated": [],
                    "warnings_count": len(warnings),
                },
                section_metadata={
                    "asset_id_visibility": (
                        "current structure context does not expose complete asset ids"
                    ),
                    "warnings": warnings,
                    "sections": [
                        {
                            "key": "structure_context",
                            "tier": 0,
                            "token_count": token_estimate,
                            "truncated": False,
                            "hash": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
                        }
                    ],
                    "evicted": [],
                    "truncated": [],
                },
                token_metadata={
                    "total_tokens": token_estimate,
                    "budget_tokens": max_tokens,
                    "sections": {"structure_context": token_estimate},
                },
                rendered_context=markdown,
            ),
        )
        return snapshot.id

    @staticmethod
    def _structure_max_tokens(
        project_settings_snapshot: dict[str, Any] | None,
    ) -> int:
        from shared.deep_import_settings import deep_import_int_setting

        return deep_import_int_setting(
            project_settings_snapshot,
            "phase3",
            "structure_max_tokens",
            env_name="PHASE3_STRUCTURE_MAX_TOKENS",
            default=32_768,
        )

    @staticmethod
    async def _mark_structure_snapshot_failed(
        db: AsyncSession,
        novel_id: str,
        snapshot_id: str,
        exc: Exception,
    ) -> None:
        from modules.context.facade import fail_context_snapshot

        await fail_context_snapshot(
            db,
            novel_id=novel_id,
            snapshot_id=snapshot_id,
            error_kind=exc.__class__.__name__,
            error_message=redact_diagnostic(exc, limit=300),
        )

    @staticmethod
    def _result_refs(data: dict[str, Any]) -> list[dict[str, str]]:
        refs: list[dict[str, str]] = []
        for item in data.get("threads", []):
            if item.get("id"):
                refs.append({"type": "plot_thread", "id": str(item["id"])})
        for item in data.get("arcs", []):
            if item.get("id"):
                refs.append({"type": "outline_arc", "id": str(item["id"])})
        for item in data.get("scenes", []):
            if item.get("id"):
                refs.append({"type": "scene", "id": str(item["id"])})
        extra = data.get("extra_sections", {}) or {}
        for item in extra.get("foreshadowing_plans", []):
            if item.get("id"):
                refs.append({"type": "foreshadowing_plan", "id": str(item["id"])})
        for item in extra.get("reveal_plans", []):
            if item.get("id"):
                refs.append({"type": "reveal_plan", "id": str(item["id"])})
        return refs

    @staticmethod
    def _audit_summary(
        *,
        snapshot_count: int,
        succeeded: int,
        failed: int,
    ) -> dict[str, Any]:
        return {
            "structure_analysis": {
                "snapshot_count": snapshot_count,
                "succeeded": succeeded,
                "failed": failed,
            }
        }

    async def _snapshot_health_summary(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        workflow_id: str | None,
    ) -> dict[str, Any]:
        if not workflow_id:
            return {}
        from modules.context.facade import build_snapshot_health_summary

        return await build_snapshot_health_summary(
            db,
            novel_id=novel_id,
            workflow_id=workflow_id,
        )
