"""生成提示词模板路由。"""

from __future__ import annotations

from fastapi import Query

from core.dependencies import DbSession
from modules.project.facade import require_active_project
from modules.world.api._shared import (
    ActiveNovelIdQuery,
    _generation_template_service,
    _template_version_conflict,
    router,
)
from modules.world.schemas import (
    GenerationPromptTemplateCreate,
    GenerationPromptTemplateListResponse,
    GenerationPromptTemplateResponse,
    GenerationPromptTemplateRevisionResponse,
    GenerationPromptTemplateUpdate,
    PromptTemplateCopyRequest,
    PromptTemplatePreviewRequest,
    PromptTemplatePreviewResponse,
    PromptTemplateValidateRequest,
    PromptTemplateValidateResponse,
)
from modules.world.services.worldbuilding.generation_prompt_template_service import (
    TemplateVersionConflictError,
)


@router.get(
    "/generation-prompt-templates",
    response_model=GenerationPromptTemplateListResponse,
)
async def list_generation_prompt_templates(
    db: DbSession,
    *,
    novel_id: ActiveNovelIdQuery,
    target_kind: str = Query(default="world_object"),
    include_archived: bool = Query(default=False),
) -> GenerationPromptTemplateListResponse:
    return await _generation_template_service.list(
        db,
        novel_id,
        target_kind=target_kind,
        include_archived=include_archived,
    )


@router.post(
    "/generation-prompt-templates",
    response_model=GenerationPromptTemplateResponse,
    status_code=201,
)
async def create_generation_prompt_template(
    db: DbSession,
    data: GenerationPromptTemplateCreate,
) -> GenerationPromptTemplateResponse:
    await require_active_project(db, data.novel_id)
    return await _generation_template_service.create(db, data)


@router.post(
    "/generation-prompt-templates/validate",
    response_model=PromptTemplateValidateResponse,
)
async def validate_generation_prompt_template(
    db: DbSession,
    data: PromptTemplateValidateRequest,
) -> PromptTemplateValidateResponse:
    if data.novel_id is not None:
        await require_active_project(db, data.novel_id)
    return _generation_template_service.validate(data)


@router.post(
    "/generation-prompt-templates/preview",
    response_model=PromptTemplatePreviewResponse,
)
async def preview_generation_prompt_template(
    db: DbSession,
    data: PromptTemplatePreviewRequest,
) -> PromptTemplatePreviewResponse:
    await require_active_project(db, data.novel_id)
    try:
        return await _generation_template_service.preview(db, data)
    except TemplateVersionConflictError as exc:
        raise _template_version_conflict(exc) from exc


@router.get(
    "/generation-prompt-templates/{template_id}",
    response_model=GenerationPromptTemplateResponse,
)
async def get_generation_prompt_template(
    db: DbSession,
    template_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> GenerationPromptTemplateResponse:
    return await _generation_template_service.get(db, novel_id, template_id)


@router.put(
    "/generation-prompt-templates/{template_id}",
    response_model=GenerationPromptTemplateResponse,
)
async def update_generation_prompt_template(
    db: DbSession,
    template_id: str,
    data: GenerationPromptTemplateUpdate,
    *,
    novel_id: ActiveNovelIdQuery,
) -> GenerationPromptTemplateResponse:
    try:
        return await _generation_template_service.update(db, novel_id, template_id, data)
    except TemplateVersionConflictError as exc:
        raise _template_version_conflict(exc) from exc


@router.delete("/generation-prompt-templates/{template_id}", status_code=204)
async def archive_generation_prompt_template(
    db: DbSession,
    template_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> None:
    await _generation_template_service.archive(db, novel_id, template_id)


@router.get(
    "/generation-prompt-templates/{template_id}/revisions",
    response_model=list[GenerationPromptTemplateRevisionResponse],
)
async def list_generation_prompt_template_revisions(
    db: DbSession,
    template_id: str,
    *,
    novel_id: ActiveNovelIdQuery,
) -> list[GenerationPromptTemplateRevisionResponse]:
    return await _generation_template_service.revisions(db, novel_id, template_id)


@router.post(
    "/generation-prompt-templates/{template_id}/copy",
    response_model=GenerationPromptTemplateResponse,
    status_code=201,
)
async def copy_builtin_generation_prompt_template(
    db: DbSession,
    template_id: str,
    data: PromptTemplateCopyRequest,
) -> GenerationPromptTemplateResponse:
    await require_active_project(db, data.novel_id)
    try:
        return await _generation_template_service.copy_builtin(db, template_id, data)
    except TemplateVersionConflictError as exc:
        raise _template_version_conflict(exc) from exc
