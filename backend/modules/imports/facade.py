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


async def get_active_organization(db, novel_id: str) -> dict | None:
    """Read the stable organization owner, without checkpoints or credentials."""
    from modules.imports.workflow_runs import ImportWorkflowRunService

    run = await ImportWorkflowRunService().get_active_for_novel(db, novel_id=novel_id)
    if run is None:
        return None
    return {
        "id": str(run.id),
        "task_id": str(run.task_id),
        "status": run.status,
        "recovery_required": run.recovery_required,
        "start_chapter": run.start_chapter,
        "end_chapter": run.end_chapter,
    }


async def inspect_organization_status(db, novel_id, task_id=None):
    from modules.imports.assistant_tools import read_organization_status

    return await read_organization_status(db, novel_id, task_id)


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
    targeted_completion: dict[str, Any] | None = None,
    review_resolution: dict[str, Any] | None = None,
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
        **(
            {"review_resolution": review_resolution}
            if review_resolution is not None
            else {}
        ),
        **(
            {"targeted_completion": targeted_completion}
            if targeted_completion is not None
            else {}
        ),
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
    targeted_completion: dict[str, Any] | None = None,
    review_resolution: dict[str, Any] | None = None,
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
        **(
            {"review_resolution": review_resolution}
            if review_resolution is not None
            else {}
        ),
        **(
            {"targeted_completion": targeted_completion}
            if targeted_completion is not None
            else {}
        ),
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
    *,
    stage: str | None = None,
) -> dict[str, Any]:
    """恢复被中断的 deep_import 任务，复用原 task_id。"""
    _parse_uuid(prev_task_id)
    return await _orchestrator.resume_interrupted(
        db, prev_task_id, **({"stage": stage} if stage else {})
    )


async def abandon_deep_import(
    db: AsyncSession,
    task_id: str,
) -> dict[str, Any]:
    """放弃被中断的 deep_import 任务，并返回清理摘要。"""
    _parse_uuid(task_id)
    return await _orchestrator.abandon_recovery(db, task_id)


async def preview_cancelled_import_cleanup(
    db: AsyncSession,
    *,
    novel_id: str,
    task_id: str,
) -> dict[str, Any]:
    _parse_uuid(task_id)
    return await _orchestrator.preview_cancelled_cleanup(
        db,
        novel_id=novel_id,
        task_id=task_id,
    )


async def cleanup_cancelled_import(
    db: AsyncSession,
    *,
    novel_id: str,
    task_id: str,
    expected_fingerprint: str,
) -> dict[str, Any]:
    _parse_uuid(task_id)
    return await _orchestrator.cleanup_cancelled_run(
        db,
        novel_id=novel_id,
        task_id=task_id,
        expected_fingerprint=expected_fingerprint,
    )


async def reconcile_workflow_task_owners(db: AsyncSession) -> int:
    """Converge imports-owned owners after queue startup recovery."""
    from modules.imports.workflow_runs import ImportWorkflowRunService

    return await ImportWorkflowRunService().reconcile_task_owners(db)


async def drain_understanding_owner(db, novel_id, *, stop_active=False):
    from modules.imports.workflow_runs import ImportWorkflowRunService

    return await ImportWorkflowRunService().drain_for_engine_switch(
        db, novel_id, stop_active=stop_active
    )


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


async def start_targeted_completion(
    db: AsyncSession,
    *,
    novel_id: str,
    targets: list[dict],
    start_chapter: int,
    end_chapter: int,
    authorization_confirmed: bool,
) -> dict[str, Any]:
    return await _orchestrator.start_targeted_completion(
        db,
        novel_id=novel_id,
        targets=targets,
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        authorization_confirmed=authorization_confirmed,
    )


async def rollback_targeted_completion(
    db: AsyncSession, *, novel_id: str, task_id: str
) -> dict:
    from modules.imports.targeted_completion import (
        rollback_targeted_completion as rollback,
    )

    return await rollback(db, novel_id=novel_id, task_id=task_id)


async def start_review_resolution(db, request):
    return await _orchestrator.start_review_resolution(db, request)


async def get_review_summary(db, novel_id, **kwargs):
    from modules.imports.review_resolution import review_summary

    return await review_summary(db, novel_id, **kwargs)


async def inspect_review_resolution(db, **kwargs):
    from modules.imports.review_resolution import inspect_resolution

    return await inspect_resolution(db, **kwargs)


async def get_review_dispositions(db, novel_id):
    from modules.imports.review_resolution import review_dispositions

    return await review_dispositions(db, novel_id)


async def inspect_consultation_scope(db, novel_id, selection):
    from modules.imports.consultation import inspect_scope

    return await inspect_scope(db, novel_id, selection)


def plan_scene_boundaries(chapters, boundary_chapters=()):
    from modules.imports.scene_preparation import plan_boundaries

    return plan_boundaries(chapters, boundary_chapters)


def build_scene_boundary_request(payload):
    from modules.imports.scene_preparation import boundary_request

    return boundary_request(payload)


async def slice_scene_boundaries(plan, chapters, call):
    from modules.imports.scene_preparation import slice_boundaries

    return await slice_boundaries(plan, chapters, call)


async def commit_scene_boundaries(db, novel_id, result, **kwargs):
    from modules.imports.scene_preparation import commit_boundaries

    return await commit_boundaries(db, novel_id, result, **kwargs)


def prepare_scene_enrichment(scene, source_parts, scene_text, input_manifest):
    from modules.imports.scene_preparation import scene_enrichment_input

    return scene_enrichment_input(scene, source_parts, scene_text, input_manifest)


def build_scene_enrichment_request(payload):
    from modules.imports.scene_preparation import enrichment_request

    return enrichment_request(payload)


def materialize_scene_enrichment(payload, result):
    from modules.imports.scene_preparation import materialize_enrichment

    return materialize_enrichment(payload, result)


def scene_enrichment_update(scene, result, workflow_id):
    from modules.imports.scene_preparation import enrichment_update

    return enrichment_update(scene, result, workflow_id)


def build_scene_world_request(scene_text, context):
    from modules.imports.entity_extraction.scene_entity_llm_adapters import (
        build_entity_extraction_request,
    )
    from modules.imports.llm_schemas import Phase2aSceneExtractionOutput

    return build_entity_extraction_request(
        scene_text, context_bundle=context
    ), Phase2aSceneExtractionOutput


def materialize_scene_world(scene_text, context, result):
    from modules.imports.entity_extraction.scene_entity_llm_adapters import (
        _materialize_phase2a_output,
    )
    from modules.imports.llm_schemas import Phase2aSceneExtractionOutput

    return _materialize_phase2a_output(
        Phase2aSceneExtractionOutput.model_validate(result),
        current_scene_text=scene_text,
        context_bundle=context,
    ).model_dump(mode="json")


def build_scene_relations_request(scene_text, context):
    from modules.imports.entity_extraction.scene_entity_llm_adapters import (
        build_alias_relation_request,
    )
    from modules.imports.llm_schemas import AliasRelationExtractionOutput

    return build_alias_relation_request(
        scene_text, context_bundle=context
    ), AliasRelationExtractionOutput


async def prepare_scene_world_context(db, novel_id, terms):
    from modules.imports.scene_world import identity_context

    return await identity_context(db, novel_id, terms)


def prepare_scene_relations_context(context, world):
    from modules.imports.scene_world import relation_context

    return relation_context(context, world)


async def apply_scene_world_candidates(db, novel_id, **inputs):
    from modules.imports.scene_world import apply_world_candidates

    return await apply_world_candidates(db, novel_id, **inputs)
