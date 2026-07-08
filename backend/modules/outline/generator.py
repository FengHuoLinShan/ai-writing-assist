"""AI 剧情结构生成器入口。

`PlotStructureGenerator` 是薄协调层，负责把上下文构建、LLM 解析、持久化
三个深度模块串起来。实际逻辑分别位于 `modules.outline.generation.*`。
"""

import hashlib
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from infrastructure.llm.client import LLMClient
from infrastructure.llm.token_estimation import estimate_token_count
from modules.outline.generation.context_builder import PlotStructureContextBuilder
from modules.outline.generation.parser import PlotStructureParser
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


class PlotStructureGenerator:
    """AI 剧情结构生成器 — 薄协调层。"""

    def __init__(
        self,
        context_builder: PlotStructureContextBuilder | None = None,
        llm_client: LLMClient | None = None,
        persister: PlotStructurePersister | None = None,
    ) -> None:
        self._context_builder = context_builder or PlotStructureContextBuilder()
        self._llm_client = llm_client or LLMClient()
        self._persister = persister or PlotStructurePersister(
            thread_service=PlotThreadService(),
            arc_service=OutlineArcService(),
            scene_service=SceneService(),
            foreshadowing_service=ForeshadowingPlanService(),
            reveal_service=RevealPlanService(),
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
    ) -> dict[str, Any]:
        """为指定章节范围生成剧情结构并持久化。

        接口与重构前保持一致：返回包含 total_threads / total_arcs /
        total_scenes / threads / arcs / scenes / extra_sections / warnings 的字典。
        """
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
        )
        settings = get_settings()
        model = "deepseek-v4-pro" if high_quality else settings.llm_model
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
                await self._mark_structure_snapshot_failed(db, snapshot_id, exc)
                await db.commit()
            raise

        if parsed is None:
            if snapshot_id is not None:
                from modules.context.facade import fail_context_snapshot

                await fail_context_snapshot(
                    db,
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
                "audit_summary": audit_summary,
                "snapshot_health_summary": snapshot_health_summary,
            }

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
                await self._mark_structure_snapshot_failed(db, snapshot_id, exc)
                await db.commit()
            raise
        return data

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
                prompt_name="structure_plot",
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
                    "chapters": [
                        str(i) for i in range(start_chapter, end_chapter + 1)
                    ],
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
                            "hash": hashlib.sha256(
                                markdown.encode("utf-8")
                            ).hexdigest(),
                        }
                    ],
                    "evicted": [],
                    "truncated": [],
                },
                token_metadata={
                    "total_tokens": token_estimate,
                    "budget_tokens": None,
                    "sections": {"structure_context": token_estimate},
                },
                rendered_context=markdown,
            ),
        )
        return snapshot.id

    @staticmethod
    async def _mark_structure_snapshot_failed(
        db: AsyncSession,
        snapshot_id: str,
        exc: Exception,
    ) -> None:
        from modules.context.facade import fail_context_snapshot

        await fail_context_snapshot(
            db,
            snapshot_id=snapshot_id,
            error_kind=exc.__class__.__name__,
            error_message=str(exc)[:300],
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
