"""
Import Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.adoption_policy import DEFAULT_ADOPTION_POLICY
from modules.imports.contracts import (
    SourceUpdateApplyContract,
    SourceUpdatePreviewContract,
)
from modules.imports.orchestrator import DeepImportOrchestrator
from modules.imports.schemas import ImportResponse
from modules.imports.services import ImportService
from modules.imports.source_update import SourceUpdateService
from shared.utils import parse_uuid as _parse_uuid

_service = ImportService()
_orchestrator = DeepImportOrchestrator()
_source_updates = SourceUpdateService()


async def import_file(
    db: AsyncSession,
    novel_id: str,
    file_name: str,
    file_content: bytes,
) -> ImportResponse:
    return await _service.upload_and_import(db, novel_id, file_name, file_content)


async def start_deep_import(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
    force: bool = False,
    high_quality: bool = False,
    adoption_policy: str = DEFAULT_ADOPTION_POLICY,
    authorization_confirmed: bool = False,
) -> dict[str, Any]:
    """提交深度导入任务（异步）

    自动执行三阶段流水线：Scene 切分 → 实体增量提取 → 剧情结构分析。
    """
    return await _orchestrator.start(
        db,
        novel_id,
        start_chapter,
        end_chapter,
        force=force,
        high_quality=high_quality,
        adoption_policy=adoption_policy,
        authorization_confirmed=authorization_confirmed,
    )


async def start_deep_import_stage(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
    *,
    stage: str,
    force: bool = False,
    high_quality: bool = False,
    adoption_policy: str = DEFAULT_ADOPTION_POLICY,
    authorization_confirmed: bool = False,
) -> dict[str, Any]:
    """提交分阶段自动提取任务。"""
    return await _orchestrator.start_stage(
        db,
        novel_id,
        start_chapter,
        end_chapter,
        stage=stage,
        force=force,
        high_quality=high_quality,
        adoption_policy=adoption_policy,
        authorization_confirmed=authorization_confirmed,
    )


async def run_submitted_deep_import_stage(
    db: AsyncSession,
    task_id: str,
    *,
    stage: str,
) -> dict[str, Any]:
    """Run an already-submitted stage inline for an isolated/manual harness."""
    return await _orchestrator.run_submitted_stage_inline(
        db,
        task_id,
        stage=stage,
    )


async def resume_deep_import(
    db: AsyncSession,
    prev_task_id: str,
) -> dict[str, Any]:
    """恢复被中断的 deep_import 任务，复用原 task_id。"""
    _parse_uuid(prev_task_id)
    return await _orchestrator.resume_interrupted(db, prev_task_id)


async def abandon_deep_import(
    db: AsyncSession,
    task_id: str,
) -> dict[str, Any]:
    """放弃被中断的 deep_import 任务，并返回清理摘要。"""
    _parse_uuid(task_id)
    return await _orchestrator.abandon_recovery(db, task_id)


async def reconcile_workflow_task_owners(db: AsyncSession) -> int:
    """Converge imports-owned owners after queue startup recovery."""
    from modules.imports.workflow_runs import ImportWorkflowRunService

    return await ImportWorkflowRunService().reconcile_task_owners(db)


async def preview_source_update(
    db: AsyncSession,
    *,
    project_id: str | None,
    title: str,
    file_name: str,
    file_content: bytes,
    mode: str,
) -> tuple[SourceUpdatePreviewContract, list[dict]]:
    """Parse and diff one RP source upload without persisting manuscript text."""
    return await _source_updates.preview(
        db,
        project_id=project_id,
        title=title,
        file_name=file_name,
        file_content=file_content,
        mode=mode,
    )


async def apply_source_update(
    db: AsyncSession,
    *,
    project_id: str,
    title: str,
    file_name: str,
    file_content: bytes,
    mode: str,
    expected_preview_hash: str,
    destructive_confirmed: bool,
) -> SourceUpdateApplyContract:
    """Re-parse, revalidate the preview hash, and write one source version."""
    return await _source_updates.apply(
        db,
        project_id=project_id,
        title=title,
        file_name=file_name,
        file_content=file_content,
        mode=mode,
        expected_preview_hash=expected_preview_hash,
        destructive_confirmed=destructive_confirmed,
    )
