"""World-owned page maintenance; previews do not create or publish working drafts."""

from datetime import datetime
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from core.errors import ConflictError, NotFoundError
from modules.assistant.contracts import AssistantOperation
from modules.assistant.facade import require_operation_targets
from modules.world.models import WorldBiblePageDraft, WorldBiblePageRevision
from modules.world.schemas import WorldBiblePageDraftUpdate, WorldBibleSection
from modules.world.services.worldbuilding.world_authority_service import (
    WorldAuthorityService,
)
from modules.world.services.worldbuilding.world_bible_lifecycle_service import (
    WorldBibleLifecycleService,
)


class EditPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_id: UUID | None = None
    draft_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    free_text: str | None = Field(default=None, max_length=100000)
    sections: list[WorldBibleSection] | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def concrete_edit(self):
        if bool(self.page_id) == bool(self.draft_id):
            raise ValueError("请选择一份资料或工作稿")
        if self.title is None and self.free_text is None and self.sections is None:
            raise ValueError("请说明要修改的标题或正文")
        return self


class PublishPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft_id: UUID
    validation_run_id: UUID | None = None


class RestorePage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_id: UUID
    version_number: int = Field(ge=1)


async def _edit_preview(db, novel_id, args, *, context=None):
    service = WorldBibleLifecycleService()
    kind, target = (
        ("world_bible_page", args.page_id)
        if args.page_id
        else ("world_bible_page_draft", args.draft_id)
    )
    await require_operation_targets(db, novel_id, context, [(kind, target)])
    page = None
    draft_id = args.draft_id
    if args.page_id:
        page = await service.get_page_model(db, novel_id, str(args.page_id))
        draft_id = await db.scalar(
            select(WorldBiblePageDraft.id).where(
                WorldBiblePageDraft.novel_id == UUID(novel_id),
                WorldBiblePageDraft.page_id == args.page_id,
            )
        )
    if draft_id:
        await require_operation_targets(
            db, novel_id, context, [("world_bible_page_draft", draft_id)]
        )
        current = await service.get_draft(db, novel_id, str(draft_id))
    else:
        current = page
    before = {
        "title": current.title,
        "free_text": current.free_text or "",
        "sections_json": [
            section.model_dump(mode="json") if isinstance(section, BaseModel) else section
            for section in current.sections_json
        ],
    }
    after = {
        key: value
        for key, value in args.model_dump().items()
        if key in before and value is not None
    }
    if args.sections is not None:
        after["sections_json"] = [
            section.model_dump(mode="json") for section in args.sections
        ]
    return {
        "title": "编辑资料工作稿",
        "target_key": f"world_page:{args.page_id or draft_id}",
        "draft_id": str(draft_id) if draft_id else None,
        "updated_at": current.updated_at.isoformat() if current.updated_at else None,
        "page_version": page.version_number if page else None,
        "before": before,
        "after": {**before, **after},
        "changes": after,
        "effect": "仅保存预览所列修改；关联引用沿用世界书校验，发布后才改变正式资料",
    }


async def _edit(db, novel_id, args, preview, *, context=None):
    service = WorldBibleLifecycleService()
    if args.page_id:
        await service.get_page_model(db, novel_id, str(args.page_id), for_update=True)
    if await _edit_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("资料已变化，请重新查看修改方案")
    if preview["draft_id"]:
        draft_id, expected = preview["draft_id"], preview["updated_at"]
    else:
        draft = await service.get_or_create_page_draft(
            db, novel_id, str(args.page_id), created_by=context.owner_id
        )
        draft_id, expected = str(draft.id), draft.updated_at
    result = await service.update_draft(
        db,
        novel_id,
        draft_id,
        WorldBiblePageDraftUpdate(**preview["changes"], updated_by=context.owner_id),
        expected_updated_at=datetime.fromisoformat(expected)
        if isinstance(expected, str)
        else expected,
        require_edit_baseline=True,
    )
    return {
        "type": "world_bible_page_draft",
        "id": str(result.id),
        "page_id": result.page_id,
        "label": "资料工作稿已保存，尚未发布",
    }


async def _whole_page_scope(db, novel_id, context, target):
    await require_operation_targets(db, novel_id, context, [target], aggregate=True)
    if (
        context
        and context.work.scope == "current"
        and (context.work.chapter_index or context.work.scene_id)
    ):
        raise ConflictError("发布或恢复需核对完整资料范围，请在世界书中继续")


async def _publish_preview(db, novel_id, args, *, context=None):
    await _whole_page_scope(
        db, novel_id, context, ("world_bible_page_draft", args.draft_id)
    )
    service = WorldBibleLifecycleService()
    draft = await service.get_draft(db, novel_id, str(args.draft_id))
    impact = await service.preview_publish_impact(db, novel_id, str(args.draft_id))
    head = await WorldAuthorityService().get_head(db, novel_id)
    return {
        "title": f"发布 {draft.title}",
        "target_key": f"world_page:{draft.page_id or draft.id}",
        "after": {
            "title": draft.title,
            "free_text": draft.free_text,
            "sections": draft.model_dump(mode="json")["sections_json"],
        },
        "impact": impact.model_dump(mode="json"),
        "expected_canon_head": str(head.current_revision.id),
        "effect": "将工作稿发布为正式资料；沿用世界影响与正式复核门禁",
    }


async def _publish(db, novel_id, args, preview, *, context=None):
    if await _publish_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("资料或发布影响已变化，请重新查看方案")
    result = await WorldBibleLifecycleService().admit_draft(
        db,
        novel_id,
        str(args.draft_id),
        authorizer_id=context.owner_id,
        expected_canon_head=UUID(preview["expected_canon_head"]),
        canon_decision_id=uuid5(
            UUID(context.run_id),
            f"world.publish:{args.draft_id}:{preview['expected_canon_head']}",
        ),
        expected_impact_scope_hash=preview["impact"]["impact_scope_hash"],
        validation_run_id=args.validation_run_id,
    )
    return {
        "type": "world_bible_page",
        "id": str(result.id),
        "version_number": result.version_number,
        "label": "资料已发布",
        "validation_receipt": result.validation_receipt.model_dump(mode="json")
        if result.validation_receipt
        else None,
    }


async def _restore_preview(db, novel_id, args, *, context=None):
    await _whole_page_scope(db, novel_id, context, ("world_bible_page", args.page_id))
    service = WorldBibleLifecycleService()
    page = await service.get_page_model(db, novel_id, str(args.page_id))
    if await service.has_active_draft(db, UUID(novel_id), args.page_id):
        raise ConflictError("当前资料已有工作稿，请先处理它再从历史恢复")
    revision = await db.scalar(
        select(WorldBiblePageRevision).where(
            WorldBiblePageRevision.novel_id == UUID(novel_id),
            WorldBiblePageRevision.page_id == args.page_id,
            WorldBiblePageRevision.version_number == args.version_number,
        )
    )
    if revision is None:
        raise NotFoundError("该资料历史版本不存在")
    return {
        "title": f"从第 {args.version_number} 版继续编辑",
        "target_key": f"world_page:{page.id}",
        "page_version": page.version_number,
        "after": revision.snapshot_json,
        "effect": "从历史新建工作稿，保留当前正式资料；再次发布后才生效",
    }


async def _restore(db, novel_id, args, preview, *, context=None):
    await WorldBibleLifecycleService().get_page_model(
        db, novel_id, str(args.page_id), for_update=True
    )
    if await _restore_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("资料已经变化，请重新查看恢复方案")
    result = await WorldBibleLifecycleService().restore_revision_to_draft(
        db, novel_id, str(args.page_id), args.version_number, restored_by=context.owner_id
    )
    return {
        "type": "world_bible_page_draft",
        "id": str(result.id),
        "page_id": str(args.page_id),
        "restored_from_version": args.version_number,
        "label": "已从历史新建工作稿，尚未发布",
    }


OPERATIONS = {
    "world.edit_page_draft": AssistantOperation(
        "编辑资料标题、正文与条目", EditPage, _edit_preview, _edit
    ),
    "world.publish_page_draft": AssistantOperation(
        "发布资料工作稿", PublishPage, _publish_preview, _publish
    ),
    "world.restore_page_revision": AssistantOperation(
        "从资料历史继续编辑", RestorePage, _restore_preview, _restore
    ),
}


async def inspect_page_history(db, novel_id, page_id, version_number=None):
    page = await WorldBibleLifecycleService().get_page_model(db, novel_id, page_id)
    query = select(WorldBiblePageRevision).where(
        WorldBiblePageRevision.novel_id == UUID(novel_id),
        WorldBiblePageRevision.page_id == UUID(page_id),
    )
    if version_number is not None:
        query = query.where(WorldBiblePageRevision.version_number == version_number)
    rows = list(
        (
            await db.scalars(
                query.order_by(WorldBiblePageRevision.version_number.desc()).limit(21)
            )
        ).all()
    )
    if version_number is not None:
        if not rows:
            raise NotFoundError("资料历史版本不存在")
        row = rows[0]
        snapshot = row.snapshot_json or {}
        text = "\n\n".join(
            [
                str(snapshot.get("free_text") or ""),
                *[
                    f"{section.get('title', '')}\n{section.get('body_markdown', '')}"
                    for section in snapshot.get("sections_json") or []
                ],
            ]
        )
        return {
            "id": str(page.id),
            "title": snapshot.get("title") or page.title,
            "version_number": row.version_number,
            "revision_id": str(row.id),
            "text": text[:16000],
            "excerpted": len(text) > 16000,
            "authority": "历史资料摘录，不代表当前正式设定",
        }
    return {
        "id": str(page.id),
        "title": page.title,
        "current_version": page.version_number,
        "versions": [
            {
                "version_number": row.version_number,
                "reason": row.revision_reason,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows[:20]
        ],
        "has_older": len(rows) > 20,
        "authority": "最近二十个历史版本；更早版本请从世界书历史查看",
    }
