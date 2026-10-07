"""
Project Facade — 对外入口

其他模块只能从 facade 或 contracts 导入。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from core.errors import ConflictError, NotFoundError
from core.logging_context import bind_validated_novel_id
from modules.account.contracts import ProjectOwnerRef
from modules.project.account_lifecycle_service import (
    list_active_project_summaries as _list_active_project_summaries,
)
from modules.project.account_lifecycle_service import (
    list_project_ids_for_owner as _list_project_ids_for_owner,
)
from modules.project.account_lifecycle_service import (
    lock_project_ids_for_owner as _lock_project_ids_for_owner,
)
from modules.project.account_lifecycle_service import (
    purge_projects_for_owner as _purge_projects_for_owner,
)
from modules.project.author_examples import (
    read_author_examples as read_author_examples,
)
from modules.project.author_examples import (
    read_author_examples_for_writing as read_author_examples_for_writing,
)
from modules.project.author_examples import (
    read_author_examples_writing_toggle as read_author_examples_writing_toggle,
)
from modules.project.author_examples import (
    save_author_examples as save_author_examples,
)
from modules.project.author_examples import (
    set_author_examples_for_writing as set_author_examples_for_writing,
)
from modules.project.contracts import InteractionProjectContract, ProjectSummary
from modules.project.editorial_brief import (
    read_editorial_brief as read_editorial_brief,
)
from modules.project.editorial_brief import (
    read_editorial_brief_for_writing as read_editorial_brief_for_writing,
)
from modules.project.editorial_brief import (
    save_editorial_brief as save_editorial_brief,
)
from modules.project.editorial_brief import (
    set_editorial_brief_for_writing as set_editorial_brief_for_writing,
)
from modules.project.repositories import ProjectRepository
from modules.project.schemas import ProjectContext, ProjectCreate
from modules.project.services import ProjectService
from modules.project.settings_schemas import (
    EffectiveAuthorPrefsResponse,
    EffectiveLLMSettingsResponse,
    FieldResetResponse,
    ProjectAuthorPrefsResponse,
    ProjectsUsingDefaultsResponse,
)
from modules.project.settings_service import ProjectSettingsService

_service = ProjectService()
_repo = ProjectRepository()
_settings_service = ProjectSettingsService()


async def inspect_project_workspace(
    db: AsyncSession,
    novel_id: str,
    *,
    task_scope: str | None = None,
    on_date=None,
    skip: int = 0,
) -> dict:
    """Bounded workspace/task projections, without account configuration."""
    from modules.project.author_task_service import AuthorTaskService
    from modules.project.workspace_service import ProjectWorkspaceSummaryService

    if task_scope is not None:
        from core.errors import ValidationError

        if (
            task_scope not in {"today", "inbox", "later", "completed", "archived"}
            or not 0 <= skip <= 10000
            or on_date is None
        ):
            raise ValidationError("待办查询范围无效")
        tasks = await AuthorTaskService(_service).list_tasks(
            db, novel_id, scope=task_scope, on_date=on_date, skip=skip, limit=30
        )
        return tasks.model_dump(mode="json")
    service = ProjectWorkspaceSummaryService(
        project_reader=_service.get_project,
        author_task_summary_reader=AuthorTaskService(_service).get_workspace_summary,
    )
    summary = await service.get_summary(db, novel_id)
    return summary.model_dump(mode="json")


# Imported after service/repository setup so callers get one stable project seam
# without exposing llm_runtime implementation details.
from modules.project.image_runtime import (  # noqa: E402,F401
    build_project_image_execution_snapshot,
    open_project_image_client,
    restore_project_image_runtime_profile,
)
from modules.project.llm_runtime import (  # noqa: E402,F401
    build_project_llm_execution_snapshot,
    create_project_snapshot_llm_client,
    open_project_llm_client,
    open_project_snapshot_llm_client,
    restore_project_llm_execution_settings,
)


async def get_project_context(
    db: AsyncSession,
    novel_id: str,
) -> ProjectContext | None:
    """Return a secret-free project context for cross-module consumers."""
    context = await _service.get_project_context(db, novel_id)
    if context is None:
        return None
    bind_validated_novel_id(novel_id)
    return context


async def get_any_project_context(
    db: AsyncSession,
    novel_id: str,
    *,
    for_update: bool = False,
) -> ProjectContext | None:
    """Secret-free context for either project kind; lock only for DB mutations."""
    context = await _service.get_project_context(
        db,
        novel_id,
        project_kind=None,
        **({"for_update": True} if for_update else {}),
    )
    if context is not None:
        bind_validated_novel_id(novel_id)
    return context


async def validate_configured_public_demo_project(
    db: AsyncSession,
    novel_id: str,
    owner_id: str,
    *,
    configured_project_id: uuid.UUID,
) -> None:
    """Validate the exact deployment-published author project without caller scope."""
    from modules.account.facade import require_account_active

    project_id = uuid.UUID(novel_id)
    if configured_project_id != project_id:
        raise NotFoundError("Demo unavailable")
    project = await _repo.get(
        db,
        project_id,
        uuid.UUID(owner_id),
        project_kind="author",
    )
    if project is None:
        raise NotFoundError("Demo unavailable")
    await require_account_active(db, project.owner_id)


async def get_effective_llm_settings(
    db: AsyncSession,
    project_id: uuid.UUID | str,
) -> EffectiveLLMSettingsResponse:
    await require_active_project(db, str(project_id))
    context = await get_project_context(db, str(project_id))
    if context is None:
        raise NotFoundError(f"Project {project_id} not found")
    owner_id = uuid.UUID(context.owner_id) if context.owner_id else None
    return await _settings_service.get_effective_llm_settings(
        db,
        context.settings,
        owner_id=owner_id,
    )


async def get_effective_author_prefs(
    db: AsyncSession,
    project_id: uuid.UUID | str,
) -> EffectiveAuthorPrefsResponse:
    await require_active_project(db, str(project_id))
    context = await get_project_context(db, str(project_id))
    owner_id = uuid.UUID(context.owner_id) if context and context.owner_id else None
    return await _settings_service.get_effective_author_prefs(
        db,
        project_id,
        owner_id=owner_id,
    )


async def resolve_effective_llm_settings_for_project_settings(
    db: AsyncSession,
    project_settings: dict | None,
    owner_id: uuid.UUID | None = None,
) -> EffectiveLLMSettingsResponse:
    return await _settings_service.get_effective_llm_settings(
        db,
        project_settings,
        owner_id=owner_id,
    )


async def get_project_author_preferences(
    db: AsyncSession,
    project_id: uuid.UUID | str,
) -> ProjectAuthorPrefsResponse:
    await require_active_project(db, str(project_id))
    return await _settings_service.get_project_author_prefs(db, project_id)


async def upsert_project_author_preferences(
    db: AsyncSession,
    project_id: uuid.UUID | str,
    payload: dict,
) -> ProjectAuthorPrefsResponse:
    await require_active_project(db, str(project_id))
    return await _settings_service.upsert_project_author_prefs(
        db,
        project_id,
        payload,
    )


async def reset_project_author_preferences_field(
    db: AsyncSession,
    project_id: uuid.UUID | str,
    field_name: str,
) -> FieldResetResponse:
    await require_active_project(db, str(project_id))
    return await _settings_service.reset_project_author_prefs_field(
        db,
        project_id,
        field_name,
    )


async def list_projects_using_defaults(
    db: AsyncSession,
    limit: int = 50,
    offset: int = 0,
) -> ProjectsUsingDefaultsResponse:
    projects, total = await list_active_project_summaries(
        db,
        limit=limit,
        offset=offset,
        exclude_project_ids=_settings_service.fully_overridden_project_ids_subquery(),
    )
    return _settings_service.build_projects_using_defaults_response(projects, total)


async def require_active_project(
    db: AsyncSession,
    novel_id: str,
) -> None:
    """Require an active project, hiding missing and recycled projects as 404.

    Authenticated browser callers always resolve an owner filter; the unowned
    worker/system identity is accepted only inside the worker execution scope.
    """
    await _service.require_active_project(db, novel_id)
    bind_validated_novel_id(novel_id)


async def save_agent_executor_settings(
    db, novel_id, owner_id, selection, *, only_if_device=None
):
    """Project-owned executor mutation inside the caller's transaction."""
    await _service.save_agent_executor_settings(
        db, novel_id, owner_id, selection, only_if_device=only_if_device
    )


async def require_interaction_project(
    db: AsyncSession,
    novel_id: str,
) -> None:
    """Require the current owner's active hidden interaction project."""
    await _service.require_active_project(
        db,
        novel_id,
        project_kind="interaction",
    )
    bind_validated_novel_id(novel_id)


async def project_task_preflight(db: AsyncSession, task) -> None:
    """Require the active project kind owned by one queued task."""
    novel_id = str(task.novel_id or "").strip()
    if not novel_id:
        return
    if str(task.task_type).startswith("interaction_"):
        context = await get_any_project_context(db, novel_id)
        if context is not None and context.project_kind != "interaction":
            context = None
    else:
        context = await get_project_context(db, novel_id)
    if context is None:
        raise NotFoundError(f"Project {novel_id} not found")
    from modules.project.understanding import check_task

    await check_task(db, task)


async def project_task_commit_guard(db: AsyncSession, task) -> bool:
    """Return whether terminal task state may commit for its active project."""
    novel_id = str(task.novel_id or "").strip()
    if not novel_id:
        return True
    try:
        if str(task.task_type).startswith("interaction_"):
            await require_interaction_project(db, novel_id)
        else:
            await require_active_project(db, novel_id)
        from modules.project.understanding import check_task

        await check_task(db, task)
    except (NotFoundError, ConflictError):
        return False
    return True


async def get_understanding_engine(db, novel_id):
    from modules.project.understanding import state

    return await state(db, uuid.UUID(str(novel_id)))


async def require_understanding_writer(db, novel_id, *, engine, epoch=None):
    from modules.project.understanding import require_writer

    return await require_writer(db, uuid.UUID(str(novel_id)), engine=engine, epoch=epoch)


async def validate_understanding_owner(db, novel_id, *, engine, token):
    from modules.project.understanding import validate_token

    return await validate_token(db, uuid.UUID(str(novel_id)), engine=engine, token=token)


async def advance_understanding_engine(db, novel_id, *, engine, expected_epoch):
    from modules.project.understanding import advance

    return await advance(
        db, uuid.UUID(str(novel_id)), engine=engine, expected_epoch=expected_epoch
    )


async def require_any_active_project(
    db: AsyncSession,
    novel_id: str,
) -> None:
    """Infrastructure-only guard for either project kind."""
    await _service.require_active_project(
        db,
        novel_id,
        project_kind=None,
    )
    bind_validated_novel_id(novel_id)


async def create_interaction_project(
    db: AsyncSession,
    *,
    title: str,
) -> InteractionProjectContract:
    return await _service.create_interaction_project(db, title=title)


async def create_author_project(
    db: AsyncSession,
    *,
    title: str,
) -> ProjectSummary:
    """Create a normal author project for a cross-module user workflow."""
    project = await _service.create_project(db, ProjectCreate(title=title))
    return ProjectSummary(project_id=uuid.UUID(str(project.id)), title=project.title)


async def archive_interaction_project(db: AsyncSession, novel_id: str) -> None:
    await _service.archive_interaction_project(db, novel_id)


async def restore_interaction_project(db: AsyncSession, novel_id: str) -> None:
    await _service.restore_interaction_project(db, novel_id)


async def permanently_delete_interaction_project(
    db: AsyncSession,
    novel_id: str,
) -> None:
    await _service.permanently_delete_interaction_project(db, novel_id)


async def require_active_project_exclusive(
    db: AsyncSession,
    novel_id: str,
    *,
    nowait: bool = False,
) -> None:
    """Exclusively fence a short DB-only finalizer for one active project.

    Normal business operations must keep using ``require_active_project``.
    This seam must never be held across LLM/provider I/O.
    """
    await _service.require_active_project_exclusive(
        db, novel_id, **({"nowait": True} if nowait else {})
    )
    bind_validated_novel_id(novel_id)


async def list_active_project_summaries(
    db: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    exclude_project_ids: Select[tuple[Any, ...]] | None = None,
) -> tuple[list[ProjectSummary], int]:
    """List active project summaries; SQL lives in account_lifecycle_service."""
    return await _list_active_project_summaries(
        db,
        limit=limit,
        offset=offset,
        exclude_project_ids=exclude_project_ids,
    )


async def list_project_ids_for_owner(
    db: AsyncSession,
    owner_id: uuid.UUID,
) -> list[uuid.UUID]:
    """Return only project IDs for account lifecycle task fencing."""
    return await _list_project_ids_for_owner(db, owner_id)


async def lock_project_ids_for_owner(
    db: AsyncSession,
    owner_id: uuid.UUID,
) -> list[uuid.UUID]:
    """Serialize account-wide asset quota checks; see account_lifecycle_service."""
    return await _lock_project_ids_for_owner(db, owner_id)


async def purge_projects_for_owner(
    db: AsyncSession,
    owner_id: uuid.UUID,
) -> int:
    """Permanently remove every owner project; see account_lifecycle_service."""
    return await _purge_projects_for_owner(db, owner_id)


async def get_project_owner_ref(
    db: AsyncSession,
    novel_id: str,
) -> ProjectOwnerRef | None:
    """Account-facing owner reference for either project kind (AO-4 DI port).

    Routes through :func:`get_any_project_context` so the caller inherits the
    same owner/demo gates; ``None`` means the project is absent or inaccessible.
    """
    context = await get_any_project_context(db, novel_id)
    if context is None:
        return None
    return ProjectOwnerRef(owner_id=context.owner_id)
