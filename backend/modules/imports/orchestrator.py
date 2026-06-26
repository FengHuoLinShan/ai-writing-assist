"""Deep import orchestration policy.

Owns duplicate detection, replacement/deprecation policy, task submission, and
task progress shaping for the user-confirmed deep import pipeline.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.workflow import DeepImportWorkflow
from modules.imports.workflow_schemas import DeepImportProgress


class DeepImportOrchestrator:
    """Stable implementation behind imports facade and task handler."""

    def __init__(self, workflow: DeepImportWorkflow | None = None) -> None:
        self.workflow = workflow or DeepImportWorkflow()

    async def start(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
        force: bool = False,
    ) -> dict[str, Any]:
        warning = await self._check_duplicate_import(
            db, novel_id, start_chapter, end_chapter
        )
        if warning and not force:
            return {
                "workflow_id": None,
                "task_id": None,
                "status": "requires_confirmation",
                "requires_confirmation": True,
                "warning": warning,
                "message": warning,
            }

        if force:
            await self._deprecate_derived_data(db, novel_id, start_chapter, end_chapter)

        task_id = self._enqueue_deep_import(db, novel_id, start_chapter, end_chapter)
        await db.flush()
        return {
            "workflow_id": str(task_id),
            "task_id": str(task_id),
            "status": "pending",
            "requires_confirmation": False,
            "message": f"深度导入任务已提交（第{start_chapter}-{end_chapter}章）",
        }

    async def run_task(self, db: AsyncSession, task: Any) -> dict[str, Any]:
        meta = task.meta or {}
        novel_id = meta.get("novel_id", "")
        start_chapter = int(meta.get("start_chapter", 1))
        end_chapter = int(meta.get("end_chapter", 5))
        if not novel_id:
            raise ValueError("novel_id is required for deep_import")

        progress = DeepImportProgress(workflow_id=str(task.id))

        async def _record_progress(
            updated: DeepImportProgress,
            progress_value: float,
        ) -> None:
            task.result = updated.model_dump(mode="json")
            task.update_progress(progress_value)
            await db.commit()

        progress = await self.workflow.run_step(
            db,
            novel_id=novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
            progress=progress,
            workflow_id=str(task.id),
            on_progress=_record_progress,
        )
        return self._result_from_progress(progress)

    async def _check_duplicate_import(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> str | None:
        """检查指定章节范围内是否已有派生 Scene 或实体数据。"""
        from modules.outline.facade import get_scenes_by_novel
        from modules.world.facade import list_auto_ingested_entities

        scenes = await get_scenes_by_novel(
            db, novel_id, status_filter=["draft", "canonical"]
        )
        overlapping_scenes = [
            s for s in scenes if self._scene_overlaps_range(s, start_chapter, end_chapter)
        ]
        overlapping_entities = await list_auto_ingested_entities(
            db,
            novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )

        if overlapping_scenes or overlapping_entities:
            return (
                f"第 {start_chapter}-{end_chapter} 章已有 "
                f"{len(overlapping_scenes)} 个 Scene、"
                f"{len(overlapping_entities)} 个实体。"
                f"重新导入将覆盖/刷新该范围数据。是否继续？"
            )
        return None

    async def _deprecate_derived_data(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> dict[str, int]:
        """将指定章节范围内的旧派生 Scene 和自动实体标记为 deprecated。"""
        from modules.outline.facade import get_scenes_by_novel, update_scene
        from modules.world.facade import list_auto_ingested_entities, update_entity

        deprecated_scenes = 0
        scenes = await get_scenes_by_novel(
            db, novel_id, status_filter=["draft", "canonical"]
        )
        for scene in scenes:
            if self._scene_overlaps_range(scene, start_chapter, end_chapter):
                await update_scene(db, novel_id, scene["id"], {"status": "deprecated"})
                deprecated_scenes += 1

        deprecated_entities = 0
        entities = await list_auto_ingested_entities(
            db,
            novel_id,
            start_chapter=start_chapter,
            end_chapter=end_chapter,
        )
        for entity in entities:
            await update_entity(db, novel_id, entity["id"], {"status": "deprecated"})
            deprecated_entities += 1

        return {
            "deprecated_scenes": deprecated_scenes,
            "deprecated_entities": deprecated_entities,
        }

    @staticmethod
    def _enqueue_deep_import(
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ):
        from infrastructure.tasks.enqueuer import enqueue_task

        return enqueue_task(
            db,
            "deep_import",
            meta={
                "novel_id": novel_id,
                "start_chapter": start_chapter,
                "end_chapter": end_chapter,
            },
        )

    @staticmethod
    def _scene_overlaps_range(scene: dict[str, Any], start: int, end: int) -> bool:
        chapter_ids = scene.get("chapter_ids") or []
        try:
            indices = [int(x) for x in chapter_ids if x is not None]
        except (ValueError, TypeError):
            return False
        if not indices:
            return False
        return any(start <= idx <= end for idx in indices)

    @staticmethod
    def _result_from_progress(progress: DeepImportProgress) -> dict[str, Any]:
        return {
            "phase": progress.phase,
            "current_step": (
                progress.current_step.value if progress.current_step else None
            ),
            "completed_steps": progress.completed_steps,
            "message": progress.message,
            "degraded": progress.degraded,
            "degraded_batches": progress.degraded_batches,
        }
