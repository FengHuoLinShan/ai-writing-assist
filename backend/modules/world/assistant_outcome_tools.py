"""Prepare proposed World packages and adopt whole-page suggestions as drafts."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from core.errors import ConflictError
from modules.assistant.contracts import AssistantOperation
from modules.assistant.facade import require_operation_targets, run_discussion_scope
from modules.world.schemas import (
    WorldAdoptionPackageItem,
    WorldAdoptionPackagePayload,
    WorldAdoptionPackageSaveRequest,
    WorldBiblePageDraftSuggestionPayload,
    WorldGenerationApplyPageDraftRequest,
)
from modules.world.services.worldbuilding.adoption_package_service import (
    WorldAdoptionPackageService,
)
from modules.world.services.worldbuilding.suggestion_queue_service import (
    SuggestionQueueService,
)


class PackageEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_key: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    kind: Literal["core_entity", "entity_relation", "world_bible_page", "entity_alias"]
    disposition: Literal["include", "open", "rejected"] = "open"
    payload: dict[str, Any]


class PreparePackage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[PackageEntry] = Field(min_length=1, max_length=32)


class ApplyPageSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suggestion_id: UUID


async def _package_preview(db, novel_id, args, *, context=None):
    await require_operation_targets(db, novel_id, context, [], aggregate=True)
    if context.work.scope == "current" and (
        context.work.chapter_index or context.work.scene_id
    ):
        raise ConflictError("世界采用包需要独立世界资料范围，请在原共创工作台核对")
    scope = await run_discussion_scope(db, novel_id, context.run_id, context.owner_id)
    items = []
    for entry in args.items:
        # Only the server describes provenance. Creating a package is not a
        # claim that model-generated links are canonical evidence.
        items.append(
            WorldAdoptionPackageItem(
                **entry.model_dump(),
                authority_kind="generated_bridge",
                source_refs=[
                    {
                        "source_type": "conversation",
                        "source_id": scope["session_id"],
                        "source_version": context.run_id,
                        "source_hash": scope["conversation_hash"],
                    }
                ],
            )
        )
    package = WorldAdoptionPackagePayload(
        schema_version="world_adoption_package.v1",
        source_manifest_hash=scope["source_manifest_hash"],
        items=items,
    )
    return {
        "title": "准备世界资料采用包",
        "scope": scope,
        "package": package.model_dump(mode="json"),
        "after": [
            item.model_dump(mode="json", exclude={"source_refs", "authority_kind"})
            for item in items
        ],
        "effect": "保存待审阅的成组世界提案；仍需 World 校验与独立采用，尚未成为正史",
    }


async def _save_package(db, novel_id, args, preview, *, context=None):
    if await _package_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("讨论或提案依据已变化")
    result = await WorldAdoptionPackageService().save(
        db,
        WorldAdoptionPackageSaveRequest(
            novel_id=novel_id,
            package=WorldAdoptionPackagePayload.model_validate(preview["package"]),
        ),
    )
    return {
        "type": "world_adoption_package",
        "id": result.id,
        "label": "已保存待审阅的世界采用包",
    }


async def _page_preview(db, novel_id, args, *, context=None):
    await require_operation_targets(db, novel_id, context, [], aggregate=True)
    service = SuggestionQueueService()
    suggestion = await service._get_pending(db, novel_id, str(args.suggestion_id))
    if suggestion.target_type != "world_bible_page_draft":
        raise ConflictError("此成果不是整页工作稿建议")
    payload = WorldBiblePageDraftSuggestionPayload.model_validate(suggestion.payload_json)
    before = None
    if payload.operation == "replace_existing":
        page, draft = await service._lock_and_validate_page_baseline(
            db, novel_id=novel_id, payload=payload
        )
        before = {"title": (draft or page).title, "free_text": (draft or page).free_text}
    return {
        "title": "将整页建议保存为工作稿",
        "target_key": f"world_page:{payload.target_page_id or args.suggestion_id}",
        "before": before,
        "after": payload.page.model_dump(mode="json"),
        "payload": payload.model_dump(mode="json"),
        "effect": "按原生成基线保存可编辑工作稿，尚不发布",
    }


async def _apply_page(db, novel_id, args, preview, *, context=None):
    if await _page_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("整页建议或原工作稿已经变化")
    result = await SuggestionQueueService().apply_world_generation_page_draft(
        db,
        novel_id,
        str(args.suggestion_id),
        WorldGenerationApplyPageDraftRequest(updated_by=context.owner_id),
    )
    return {
        "type": "world_bible_page_draft",
        "id": result.draft.id,
        "label": "已保存整页建议为工作稿",
    }


OPERATIONS = {
    "world.prepare_package": AssistantOperation(
        "准备可独立校验和采用的世界资料包",
        PreparePackage,
        _package_preview,
        _save_package,
    ),
    "world.apply_page_suggestion": AssistantOperation(
        "将整页建议保存为工作稿", ApplyPageSuggestion, _page_preview, _apply_page
    ),
}
