"""World-owned editable previews; existing validation and Canon gates stay active."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.errors import ConflictError, ValidationError
from modules.assistant.contracts import AssistantOperation
from modules.assistant.facade import require_operation_targets
from modules.world.schemas import (
    CoreEntityCreate,
    CoreEntityUpdate,
    RelationKind,
    WorldBiblePageDraftCreate,
)
from modules.world.services.core.entity_service import WorldEntityService
from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
    WorldBibleLifecycleService,
)


class CreateEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_type: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=200)
    summary: str = Field(default="", max_length=10000)
    public_info: str = Field(default="", max_length=30000)
    hidden_truth: str = Field(default="", max_length=30000)
    content_json: dict[str, Any] = Field(default_factory=dict)


class EditEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: UUID
    changes: dict[str, Any]


class CreatePageDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    page_type: str = Field(default="background", max_length=32)
    free_text: str = Field(default="", max_length=100000)
    sections_json: list[dict] = Field(default_factory=list, max_length=64)


class AdoptPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suggestion_id: UUID
    validation_run_id: UUID | None = None


class AddAlias(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: UUID
    alias: str = Field(min_length=1, max_length=255)
    alias_type: str = Field(default="name", max_length=20)


class AddRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: UUID
    target_id: UUID
    relation_type: str = Field(min_length=1, max_length=64)
    relation_kind: RelationKind
    description: str = Field(default="", max_length=12000)
    strength: float = Field(default=0.5, ge=0, le=1)


async def _alias_preview(db, novel_id, args, *, context=None):
    await require_operation_targets(
        db, novel_id, context, [("core_entity", args.entity_id)]
    )
    entity = await WorldEntityService().get(db, str(args.entity_id), novel_id=novel_id)
    return {
        "target_key": f"world_entity:{entity.id}",
        "title": f"为{entity.name}添加别名",
        "before": (entity.content_json or {}).get("aliases", []),
        "after": {"alias": args.alias, "alias_type": args.alias_type},
        "updated_at": str(entity.updated_at),
        "effect": "把别名附着到已有对象，不创建重复实体；遵守 World 正式采用门禁",
    }


async def _alias_apply(db, novel_id, args, preview, *, context=None):
    from modules.world.services.core.entity_alias_service import EntityAliasService

    if await _alias_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("对象或别名已变化")
    await EntityAliasService().create_alias(
        db,
        novel_id,
        str(args.entity_id),
        args.alias,
        args.alias_type,
        source="assistant",
        reviewed_by=context.owner_id,
    )
    return {"type": "world_entity", "id": str(args.entity_id), "label": "已附加别名"}


async def _relation_preview(db, novel_id, args, *, context=None):
    await require_operation_targets(
        db,
        novel_id,
        context,
        [
            ("core_entity", args.source_id),
            ("core_entity", args.target_id),
        ],
    )
    if args.source_id == args.target_id:
        raise ValidationError("关系两端须为不同对象")
    source = await WorldEntityService().get(db, str(args.source_id), novel_id=novel_id)
    target = await WorldEntityService().get(db, str(args.target_id), novel_id=novel_id)
    return {
        "target_key": f"relation:{source.id}:{target.id}:{args.relation_type}",
        "title": f"{source.name}与{target.name}的关系",
        "after": {
            "source": source.name,
            "target": target.name,
            "relation": args.relation_type,
            "relation_kind": args.relation_kind,
            "description": args.description,
            "strength": args.strength,
        },
        "source_version": str(source.updated_at),
        "target_version": str(target.updated_at),
        "effect": "添加明确关系并保留来源；遵守 World 正式采用门禁",
    }


async def _relation_apply(db, novel_id, args, preview, *, context=None):
    from modules.world.schemas import EntityRelationCreate
    from modules.world.services.core.entity_relation_service import EntityRelationService

    if await _relation_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("关系两端资料已变化")
    row = await EntityRelationService().create(
        db,
        novel_id,
        EntityRelationCreate(
            **args.model_dump(mode="json"),
            review_meta={
                "assistant_run_id": context.run_id,
                "reviewed_by": context.owner_id,
            },
        ),
    )
    return {
        "type": "world_relation",
        "id": str(row.id),
        "target": {"type": "world_entity", "id": str(args.source_id)},
        "label": "已添加对象关系",
    }


async def _package_preview(db, novel_id, args, *, context=None):
    from modules.world.services.worldbuilding.adoption_package_service import (
        WorldAdoptionPackageService,
    )

    if context and (
        context.work.excluded_targets or context.work.context_confirmation_id
    ):
        raise ConflictError("采用包有独立的来源与校验范围，请在世界复核入口核对后采用")
    result = await WorldAdoptionPackageService().preview(
        db, novel_id, str(args.suggestion_id)
    )
    return {
        "target_key": f"world_package:{args.suggestion_id}",
        "title": "采用世界资料方案",
        "before": result.canon_diff,
        "after": result.suggestion.payload_json,
        "omissions": result.omissions,
        "expected_preview_hash": result.expected_preview_hash,
        "effect": "仅采用方案中明确包含的条目；保留 World 来源、版本、校验与历史门禁",
    }


async def _package_apply(db, novel_id, args, preview, *, context=None):
    from modules.world.schemas import WorldAdoptionPackageApplyRequest
    from modules.world.services.worldbuilding.adoption_package_service import (
        WorldAdoptionPackageService,
    )

    if await _package_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("采用范围或基线已变化，请重新查看方案")
    result = await WorldAdoptionPackageService().apply(
        db,
        novel_id,
        str(args.suggestion_id),
        WorldAdoptionPackageApplyRequest(
            expected_preview_hash=preview["expected_preview_hash"],
            validation_run_id=args.validation_run_id,
        ),
    )
    return {
        "type": "world_adoption_package",
        "id": str(result.id),
        "label": "已采用世界资料方案",
        "result": result.result_ref_json,
    }


async def _create_preview(db, novel_id, args, *, context=None):
    data = CoreEntityCreate.model_validate(args.model_dump())
    return {
        "title": args.name,
        "after": data.model_dump(
            mode="json", exclude={"created_by", "approved_by", "force_create"}
        ),
        "effect": "确认后创建世界对象；保留现有去重与采用门禁",
    }


async def _create_apply(db, novel_id, args, preview, *, context=None):
    row = await WorldEntityService().create(
        db,
        novel_id,
        CoreEntityCreate.model_validate(
            {
                **args.model_dump(),
                "created_by": f"assistant:{context.run_id}",
                "approved_by": context.owner_id,
            }
        ),
    )
    return {"type": "world_entity", "id": str(row.id), "label": "已创建世界对象"}


async def _edit_preview(db, novel_id, args, *, context=None):
    await require_operation_targets(
        db, novel_id, context, [("core_entity", args.entity_id)]
    )
    allowed = {
        "name",
        "summary",
        "public_info",
        "hidden_truth",
        "content_json",
        "importance",
        "importance_level",
        "reveal_level",
    }
    if not args.changes or not set(args.changes).issubset(allowed):
        raise ValidationError("只能修改对象内容，不能通过普通编辑改变采用状态或身份")
    CoreEntityUpdate.model_validate(args.changes)
    row = await WorldEntityService().get(db, str(args.entity_id), novel_id=novel_id)
    return {
        "target_key": f"world_entity:{row.id}",
        "title": row.name,
        "before": {key: getattr(row, key) for key in args.changes},
        "after": args.changes,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "effect": "更新对象并保留历史版本",
    }


async def _edit_apply(db, novel_id, args, preview, *, context=None):
    if await _edit_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("对象已变化", code="assistant_source_stale")
    baseline = (
        datetime.fromisoformat(preview["updated_at"]) if preview["updated_at"] else None
    )
    row = await WorldEntityService().update(
        db,
        str(args.entity_id),
        CoreEntityUpdate.model_validate(args.changes),
        novel_id=novel_id,
        expected_updated_at=baseline,
        require_edit_baseline=True,
    )
    return {"type": "world_entity", "id": str(row.id), "label": "已更新世界对象"}


async def _page_preview(db, novel_id, args, *, context=None):
    data = WorldBiblePageDraftCreate.model_validate(
        {"novel_id": novel_id, **args.model_dump()}
    )
    return {
        "title": args.title,
        "after": data.model_dump(mode="json", exclude={"novel_id", "created_by"}),
        "effect": "保存为资料工作稿，尚未发布或采用",
    }


async def _page_apply(db, novel_id, args, preview, *, context=None):
    row = await WorldBibleLifecycleService().create_draft(
        db,
        WorldBiblePageDraftCreate.model_validate(
            {
                "novel_id": novel_id,
                **args.model_dump(),
                "created_by": f"assistant:{context.run_id}",
            }
        ),
    )
    return {
        "type": "world_bible_page_draft",
        "id": str(row.id),
        "label": "已保存资料工作稿",
    }


OPERATIONS = {
    "world.add_alias": AssistantOperation(
        "附加对象别名", AddAlias, _alias_preview, _alias_apply
    ),
    "world.add_relation": AssistantOperation(
        "连接已有对象", AddRelation, _relation_preview, _relation_apply
    ),
    "world.adopt_package": AssistantOperation(
        "采用已核对的世界资料方案", AdoptPackage, _package_preview, _package_apply
    ),
    "world.create_entity": AssistantOperation(
        "创建世界对象", CreateEntity, _create_preview, _create_apply
    ),
    "world.edit_entity": AssistantOperation(
        "修改世界对象", EditEntity, _edit_preview, _edit_apply
    ),
    "world.create_page_draft": AssistantOperation(
        "保存世界资料工作稿", CreatePageDraft, _page_preview, _page_apply
    ),
}
