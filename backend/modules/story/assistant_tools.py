"""Story-owned structure editing through the existing services."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from core.errors import ConflictError, ValidationError
from modules.assistant.contracts import AssistantOperation
from modules.story.outline_state.models import Scene
from modules.story.outline_state.schemas import SceneCreate, SceneUpdate
from modules.story.outline_state.services import SceneService
from modules.story.outline_state.story_outline_schemas import (
    StoryOutlineContent,
    StoryOutlineProvenance,
    StoryOutlineRevisionCreate,
)
from modules.story.outline_state.story_outline_service import (
    StoryOutlineConflictError,
    StoryOutlineService,
)
from modules.story.schemas import CharacterCardContent, LongStoryText, StoryKey
from modules.story.service import StoryConflictError, StoryNotFoundError, StoryService


class EditScene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: UUID
    changes: dict[str, Any] = Field(min_length=1)


class SaveCard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: UUID
    character_id: UUID
    content: CharacterCardContent


class SaveScript(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: UUID
    file_key: StoryKey
    title: str = Field(min_length=1, max_length=255)
    content: LongStoryText
    adopt: bool = False


class SceneIdea(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=255)
    goal: str = Field(min_length=1, max_length=12000)
    core_conflict: str | None = Field(default=None, max_length=12000)
    emotional_beat: str | None = Field(default=None, max_length=12000)
    must_happen: str | None = Field(default=None, max_length=12000)
    must_not_happen: str | None = Field(default=None, max_length=12000)
    pov_character_id: UUID | None = None


class CreateScenes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenes: list[SceneIdea] = Field(min_length=1, max_length=20)


async def _scenes_preview(db, novel_id, args, *, context=None):
    from modules.assistant.facade import require_operation_targets

    await require_operation_targets(
        db,
        novel_id,
        context,
        [
            ("core_entity", item.pov_character_id)
            for item in args.scenes
            if item.pov_character_id
        ],
    )
    maximum = await db.scalar(
        select(func.max(Scene.scene_index)).where(Scene.novel_id == UUID(novel_id))
    )
    names = {}
    for item in args.scenes:
        if item.pov_character_id and item.pov_character_id not in names:
            character = await StoryService()._require_character(
                db, UUID(novel_id), item.pov_character_id
            )
            names[item.pov_character_id] = character.name
    return {
        "target_key": "story:append_scenes",
        "title": "追加场景规划",
        "start_index": int(maximum) + 1 if maximum is not None else 0,
        "after": [
            {
                **item.model_dump(mode="json", exclude={"pov_character_id"}),
                "pov_character": names.get(item.pov_character_id),
            }
            for item in args.scenes
        ],
        "effect": "在现有场景之后添加可编辑规划，不改写已有场景或正文",
    }


async def _scenes_apply(db, novel_id, args, preview, *, context=None):
    from modules.project.facade import require_active_project_exclusive

    await require_active_project_exclusive(db, novel_id)
    if await _scenes_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("场景顺序已变化，请重新查看方案")
    results = []
    for index, item in enumerate(args.scenes, preview["start_index"]):
        row = await SceneService().create(
            db,
            novel_id,
            SceneCreate(
                **item.model_dump(mode="json"),
                scene_index=index,
                source="assistant",
                structure_meta={
                    "assistant_run_id": context.run_id,
                    "approved_by": context.owner_id,
                },
            ),
        )
        results.append(str(row.id))
    return {
        "type": "scene",
        "id": results[0],
        "scene_ids": results,
        "label": f"已追加 {len(results)} 个场景规划",
    }


async def _outline_preview(db, novel_id, args, *, context=None):
    from modules.assistant.facade import require_operation_targets

    await require_operation_targets(db, novel_id, context, [], aggregate=True)
    current = await StoryOutlineService().get_current(db, novel_id)
    revision = current.revision
    return {
        "target_key": "story:outline",
        "title": args.title,
        "base_revision_id": str(revision.id) if revision else None,
        "before": {
            key: value
            for key, value in revision.model_dump(mode="json").items()
            if key in StoryOutlineContent.model_fields
        }
        if revision
        else None,
        "after": args.model_dump(mode="json"),
        "effect": "保存总纲新版本并供后续规划使用；历史版本可恢复，不自动重写场景或正文",
    }


async def _outline_apply(db, novel_id, args, preview, *, context=None):
    if await _outline_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("总纲版本已变化")
    try:
        result = await StoryOutlineService().create_revision(
            db,
            novel_id,
            StoryOutlineRevisionCreate(
                **args.model_dump(mode="json"),
                base_revision_id=preview["base_revision_id"],
                idempotency_key=f"assistant:{context.run_id}",
                provenance=StoryOutlineProvenance(
                    actor=context.owner_id,
                    note="作者确认项目助手的总纲方案",
                    client_ref=context.run_id,
                ),
            ),
        )
    except StoryOutlineConflictError as error:
        raise ConflictError("总纲版本已变化") from error
    return {
        "type": "story_outline",
        "id": str(result.id),
        "revision_id": str(result.id),
        "label": "已保存总纲新版本",
    }


async def _card_preview(db, novel_id, args, *, context=None):
    from modules.assistant.facade import require_operation_targets

    await require_operation_targets(
        db,
        novel_id,
        context,
        [
            ("outline_scene", args.scene_id),
            ("core_entity", args.character_id),
        ],
        aggregate=True,
    )
    service = StoryService()
    scene = await service._require_scene(db, UUID(novel_id), args.scene_id)
    character = await service._require_character(db, UUID(novel_id), args.character_id)
    cards = await service.list_cards(
        db, novel_id, scene_id=str(args.scene_id), character_ids=[str(args.character_id)]
    )
    card = cards[0] if cards else None
    return {
        "target_key": f"story_card:{args.scene_id}:{args.character_id}",
        "title": f"{scene.title or '当前场景'} · {character.name}",
        "before": card.revision.content.model_dump(mode="json")
        if card and card.revision
        else None,
        "after": args.content.model_dump(mode="json"),
        "expected_revision_id": str(card.current_revision_id)
        if card and card.current_revision_id
        else None,
        "effect": "保存场景人物卡版本；不改写世界人物或其长期知识记录",
    }


async def _card_apply(db, novel_id, args, preview, *, context=None):
    if await _card_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("人物卡已变化")
    try:
        result = await StoryService().create_manual_card(
            db,
            novel_id=novel_id,
            scene_id=str(args.scene_id),
            character_id=str(args.character_id),
            content=args.content,
            expected_revision_id=UUID(preview["expected_revision_id"])
            if preview["expected_revision_id"]
            else None,
            source="assistant_confirmed",
            authorization_ref=f"assistant:{context.run_id}",
            source_manifest={
                "workflow": "assistant.character_card.v1",
                "approved_by": context.owner_id,
            },
        )
    except (StoryConflictError, StoryNotFoundError) as error:
        raise ConflictError("人物卡或关联资料已变化") from error
    return {
        "type": "story_character_card",
        "id": str(result.id),
        "revision_id": str(result.current_revision_id),
        "scene_id": str(args.scene_id),
        "label": "已保存场景人物卡",
    }


async def _script_preview(db, novel_id, args, *, context=None):
    from modules.assistant.facade import require_operation_targets

    await require_operation_targets(
        db, novel_id, context, [("outline_scene", args.scene_id)], aggregate=True
    )
    service = StoryService()
    await service._require_scene(db, UUID(novel_id), args.scene_id)
    files = await service.list_script_files(db, novel_id, str(args.scene_id))
    file = next((item for item in files if item.file_key == args.file_key), None)
    return {
        "target_key": f"story_script:{args.scene_id}:{args.file_key}",
        "title": args.title,
        "file_exists": file is not None,
        "before": file.revision.content if file and file.revision else None,
        "after": args.content,
        "expected_revision_id": str(file.current_revision_id)
        if file and file.current_revision_id
        else None,
        "expected_adopted_revision_id": str(file.adopted_revision_id)
        if file and file.adopted_revision_id
        else None,
        "effect": "保存并用于后续正文" if args.adopt else "保存剧本新版本，尚未用于正文",
    }


async def _script_apply(db, novel_id, args, preview, *, context=None):
    service = StoryService()
    if await _script_preview(db, novel_id, args, context=context) != preview:
        raise ConflictError("场景剧本已变化")
    try:
        if not preview["file_exists"]:
            await service.create_script_file(
                db,
                novel_id=novel_id,
                scene_id=str(args.scene_id),
                file_key=args.file_key,
                title=args.title,
            )
        result = await service.create_script_revision(
            db,
            novel_id=novel_id,
            scene_id=str(args.scene_id),
            file_key=args.file_key,
            content=args.content,
            content_json=None,
            adopt=args.adopt,
            expected_revision_id=UUID(preview["expected_revision_id"])
            if preview["expected_revision_id"]
            else None,
            expected_adopted_revision_id=UUID(preview["expected_adopted_revision_id"])
            if preview["expected_adopted_revision_id"]
            else None,
            provenance={
                "workflow": "assistant.scene_script.v1",
                "assistant_run_id": context.run_id,
                "approved_by": context.owner_id,
            },
        )
    except (StoryConflictError, StoryNotFoundError) as error:
        raise ConflictError("场景剧本或关联资料已变化") from error
    return {
        "type": "story_scene_script",
        "id": str(result.id),
        "revision_id": str(result.current_revision_id),
        "scene_id": str(args.scene_id),
        "label": "已保存场景剧本",
    }


async def _prepare(db, novel_id, args, *, context=None):
    from modules.assistant.facade import require_operation_targets

    await require_operation_targets(
        db, novel_id, context, [("outline_scene", args.scene_id)]
    )
    allowed = set(SceneUpdate.model_fields) - {
        "novel_id",
        "scene_chunks",
        "chapter_ids",
        "status",
        "scene_index",
        "structure_meta",
        "source",
        "workflow_id",
        "source_hash",
    }
    if not set(args.changes).issubset(allowed):
        raise ValidationError("场景提案不能改写来源映射或内部工作流")
    data = SceneUpdate.model_validate(args.changes)
    row = await SceneService().get(db, str(args.scene_id), novel_id=novel_id)
    values = row.model_dump(mode="json")
    return {
        "target_key": f"scene:{args.scene_id}",
        "title": values.get("title") or "场景",
        "before": {key: values.get(key) for key in args.changes},
        "after": data.model_dump(mode="json", exclude_unset=True),
        "updated_at": values.get("updated_at"),
        "effect": "更新场景结构，不改写正文",
    }


async def _apply(db, novel_id, args, preview, *, context=None):
    await db.scalar(
        select(Scene)
        .where(Scene.novel_id == UUID(novel_id), Scene.id == args.scene_id)
        .with_for_update()
    )
    if await _prepare(db, novel_id, args, context=context) != preview:
        raise ConflictError("场景已变化", code="assistant_source_stale")
    row = await SceneService().update(
        db,
        str(args.scene_id),
        SceneUpdate.model_validate(args.changes),
        novel_id=novel_id,
    )
    return {"type": "scene", "id": str(row.id), "label": "已更新场景"}


OPERATIONS = {
    "story.save_outline": AssistantOperation(
        "保存并采用总纲方案", StoryOutlineContent, _outline_preview, _outline_apply
    ),
    "story.create_scenes": AssistantOperation(
        "追加场景规划", CreateScenes, _scenes_preview, _scenes_apply
    ),
    "story.save_card": AssistantOperation(
        "保存场景人物卡", SaveCard, _card_preview, _card_apply
    ),
    "story.save_script": AssistantOperation(
        "保存场景剧本", SaveScript, _script_preview, _script_apply
    ),
    "story.edit_scene": AssistantOperation("修改场景结构", EditScene, _prepare, _apply),
}
