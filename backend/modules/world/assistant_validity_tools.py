"""Read-only author relation validity at an exact Story Scene cutoff."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.container import get
from core.errors import ConflictError, NotFoundError
from core.service_keys import ASSISTANT_REQUIRE_OPERATION_TARGETS
from modules.project.facade import get_any_project_context, require_active_project
from modules.world.schemas import RelationKind
from modules.world.services.core.entity_relation_service import EntityRelationService
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


class ReadRelations(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str | None = None
    relation_type: str | None = None
    relation_kind: RelationKind | None = None
    q: str | None = None
    source_chapter_id: UUID | None = None
    as_of_scene_id: UUID | None = None
    strength_min: float | None = Field(default=None, ge=0.0, le=1.0)
    strength_max: float | None = Field(default=None, ge=0.0, le=1.0)
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)


async def _read(db, novel_id, args, *, context=None):
    await require_active_project(db, novel_id)
    if context is None or not getattr(context, "run_id", None):
        raise ConflictError("关系读取需要绑定当前作者运行")
    project = await get_any_project_context(db, novel_id)
    if (
        project is None
        or project.project_kind != "author"
        or str(project.owner_id) != str(context.owner_id)
    ):
        raise NotFoundError("项目关系不可访问")
    await get(ASSISTANT_REQUIRE_OPERATION_TARGETS)(
        db, novel_id, context, [], aggregate=True
    )
    result = await EntityRelationService().list(
        db,
        novel_id,
        **args.model_dump(mode="json", exclude_none=True),
    )
    return result.model_dump(mode="json")


OPERATIONS_SPEC = {
    "world.relations.read": {
        "label": "按场景读取作者关系与有效期",
        "schema": ReadRelations,
        "prepare": _read,
        "permission": "read",
        "op_version": "1",
        "description": "读取本项目关系，可按当前 Scene 核对作者有效期与可信 Story 状态。",
        "risk_level": "R0",
        "fee_category": "free",
        "reversibility": "read_only",
        "preconditions": ("作者拥有当前项目", "仅在原确认范围覆盖整体关系时读取"),
        "produces": ("author_relation_validity_projection",),
        "target_type": "world_relation",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": {
            "parameter_fields": (
                "status",
                "relation_type",
                "relation_kind",
                "q",
                "source_chapter_id",
                "as_of_scene_id",
                "strength_min",
                "strength_max",
                "skip",
                "limit",
            ),
            "mode": "per_call",
            "parameter_policy": "schema_safe",
        },
    }
}
