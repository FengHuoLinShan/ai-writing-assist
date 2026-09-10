"""Project-owned author task operations; no model-supplied owner or authorization."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from core.errors import ConflictError, NotFoundError
from modules.assistant.contracts import AssistantOperation
from modules.project.author_task_service import AuthorTaskService
from modules.project.models import ProjectAuthorTask
from modules.project.schemas import AuthorTaskCreateRequest, AuthorTaskPatchRequest


class UpdateAuthorTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: UUID
    changes: dict = Field(min_length=1)

    @model_validator(mode="after")
    def validate_changes(self):
        if "expected_updated_at" in self.changes:
            raise ValueError("版本基线由服务端读取")
        AuthorTaskPatchRequest.model_validate(self.changes)
        return self


async def _update_preview(db, novel_id, args, *, context=None):
    from modules.assistant.facade import require_operation_targets

    await require_operation_targets(
        db, novel_id, context, [("author_task", args.task_id)]
    )
    task = await db.scalar(
        select(ProjectAuthorTask)
        .where(
            ProjectAuthorTask.novel_id == UUID(novel_id),
            ProjectAuthorTask.id == args.task_id,
        )
        .execution_options(populate_existing=True)
    )
    if task is None:
        raise NotFoundError("作者待办不存在")
    patch = AuthorTaskPatchRequest.model_validate(args.changes)
    if patch.source:
        await AuthorTaskService()._require_source(db, novel_id, patch.source)
    before = {key: getattr(task, key) for key in ("title", "note", "due_date", "status")}
    before["due_date"] = task.due_date.isoformat() if task.due_date else None
    before["source"] = (
        {"kind": task.source_kind, "id": task.source_id} if task.source_kind else None
    )
    return {
        "target_key": f"author_task:{task.id}",
        "title": task.title,
        "before": before,
        "after": {**before, **patch.model_dump(mode="json", exclude_unset=True)},
        "expected_updated_at": task.updated_at.isoformat(),
        "effect": "更新作者待办，不改变作品事实或领域问题状态",
    }


async def _update_apply(db, novel_id, args, preview, *, context=None):
    if await _update_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("待办已在其他位置更新，请重新查看方案")
    result = await AuthorTaskService().patch_task(
        db,
        novel_id,
        str(args.task_id),
        AuthorTaskPatchRequest.model_validate(
            {
                **args.changes,
                "expected_updated_at": preview["expected_updated_at"],
            }
        ),
    )
    return {"type": "author_task", "id": str(result.id), "label": "已更新待办"}


async def _prepare(db, novel_id, args, *, context=None):
    if args.source:
        await AuthorTaskService()._require_source(db, novel_id, args.source)
    return {
        "title": args.title,
        "after": args.model_dump(mode="json"),
        "effect": "加入作者待办；不会修改作品事实",
    }


async def _apply(db, novel_id, args, preview, *, context=None):
    result = await AuthorTaskService().create_task(db, novel_id, args)
    return {"type": "author_task", "id": str(result.id), "label": "已加入待办"}


OPERATIONS = {
    "project.update_task": AssistantOperation(
        "更新或完成作者待办", UpdateAuthorTask, _update_preview, _update_apply
    ),
    "project.add_task": AssistantOperation(
        "记录作者待办", AuthorTaskCreateRequest, _prepare, _apply
    ),
}
