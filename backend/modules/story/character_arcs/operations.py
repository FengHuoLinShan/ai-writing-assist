"""Pure Assistant operation declarations for the author-plan directory."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from core.container import get
from core.errors import ConflictError, NotFoundError
from core.service_keys import ASSISTANT_REQUIRE_OPERATION_TARGETS
from modules.story.models import CharacterArcPlanRevision

from .schemas import (
    ArchiveArcPlanInput,
    CharacterArcReadInput,
    ConfirmArcPlanInput,
    RestoreArcPlanInput,
    SceneCharacterReadInput,
)


async def _prior_revision(db, novel_id, character_id, operation_id):
    return await db.scalar(
        select(CharacterArcPlanRevision).where(
            CharacterArcPlanRevision.novel_id == UUID(str(novel_id)),
            CharacterArcPlanRevision.character_id == character_id,
            CharacterArcPlanRevision.operation_id == operation_id,
        )
    )


async def _require_scope(db, novel_id, args, context):
    if context is None:
        return
    # An arc plan belongs to a character across the whole work. Even a preview
    # can reveal future author-only plans, so a Scene-limited work cannot read it.
    if context.work.scope != "project":
        raise PermissionError("人物弧计划需要完整作品工作范围")
    await get(ASSISTANT_REQUIRE_OPERATION_TARGETS)(
        db,
        novel_id,
        context,
        [
            ("outline_scene", str(args.scene_id)),
            ("core_entity", str(args.character_id)),
        ],
        aggregate=True,
    )


async def _read_scene_characters(db, novel_id, args, *, context=None):
    if context is not None:
        if context.work.scope == "current" and str(context.work.scene_id) != str(
            args.scene_id
        ):
            raise PermissionError("人物列表 Scene 超出当前作者工作范围")
        await get(ASSISTANT_REQUIRE_OPERATION_TARGETS)(
            db, novel_id, context, [("outline_scene", str(args.scene_id))]
        )
    from .service import scene_character_options

    return (await scene_character_options(db, novel_id, str(args.scene_id))).model_dump(
        mode="json"
    )


async def _read_history(db, novel_id, args, *, context=None):
    await _require_scope(db, novel_id, args, context)
    from .service import plan_history

    return await plan_history(db, novel_id, str(args.scene_id), str(args.character_id))


async def _read_comparison(db, novel_id, args, *, context=None):
    await _require_scope(db, novel_id, args, context)
    from .service import compare_character_arc

    return (
        await compare_character_arc(
            db, novel_id, str(args.scene_id), str(args.character_id)
        )
    ).model_dump(mode="json")


async def _preview_save(db, novel_id, args, *, context=None):
    await _require_scope(db, novel_id, args, context)
    from .service import preview_plan_save

    return (await preview_plan_save(db, novel_id, args)).model_dump(mode="json")


async def _apply_save(db, novel_id, args, preview, *, context=None):
    await _require_scope(db, novel_id, args, context)
    if not args.preview_fingerprint:
        raise ConflictError("确认保存前需要提交预览指纹", code="PREVIEW_REQUIRED")
    from .schemas import ArcPlanWriteInput
    from .service import preview_plan_save, save_plan

    current = await preview_plan_save(db, novel_id, args)
    if current.model_dump(mode="json") != preview:
        raise ConflictError("人物弧计划预览已变化，请重新核对", code="PREVIEW_STALE")
    return await save_plan(
        db,
        novel_id,
        ArcPlanWriteInput.model_validate(
            args.model_dump(exclude={"preview_fingerprint"})
        ),
        args.preview_fingerprint,
    )


async def _preview_restore(db, novel_id, args, *, context=None):
    await _require_scope(db, novel_id, args, context)
    from infrastructure.llm.collaboration import content_hash

    from .service import (
        _assert_owner,
        _head,
        _owned_project,
        _revision,
        _validated_plan_target,
    )

    project = await _owned_project(db, novel_id)
    _scene, _character = await _validated_plan_target(
        db, novel_id, str(args.scene_id), str(args.character_id)
    )
    request_hash = content_hash(
        [
            str(args.scene_id),
            str(args.character_id),
            str(args.revision_id),
            args.expected_version,
        ]
    )
    prior = await _prior_revision(db, novel_id, args.character_id, args.operation_id)
    if prior is not None:
        if str(prior.owner_id) != str(project.owner_id):
            raise NotFoundError("人物弧计划不可访问")
        if prior.request_hash != request_hash or prior.source != "author_restore":
            raise ConflictError("操作标识已用于另一份恢复请求", code="OPERATION_MISMATCH")
        base = await _revision(
            db, novel_id, str(prior.base_revision_id), head_id=str(prior.head_id)
        )
        revision = await _revision(
            db, novel_id, str(prior.restored_from_revision_id), head_id=str(prior.head_id)
        )
        if base is None or revision is None:
            raise NotFoundError("人物弧历史修订来源不可访问")
        version = prior.version_number - 1
        return {
            "head_id": str(prior.head_id),
            "current_version": version,
            "current_revision_id": str(base.id),
            "restore_revision_id": str(revision.id),
            "restore_hash": revision.content_hash,
            "fingerprint": content_hash(
                [
                    str(prior.head_id),
                    version,
                    str(base.id),
                    str(revision.id),
                    revision.content_hash,
                ]
            ),
            "effect": "该恢复请求已成功写入；重试将返回原版本，不会新增修订。",
        }
    head = await _head(db, novel_id, str(args.character_id))
    _assert_owner(head, project)
    if head is None or head.deleted_at is not None:
        raise NotFoundError("人物弧计划不存在或已归档")
    if head.version_number != args.expected_version:
        raise ConflictError("人物弧计划版本已变化", code="STALE_VERSION")
    revision = await _revision(db, novel_id, str(args.revision_id), head_id=str(head.id))
    if revision is None or revision.source == "author_archive":
        raise NotFoundError("人物弧历史版本不可访问")
    return {
        "head_id": str(head.id),
        "current_version": head.version_number,
        "current_revision_id": str(head.current_revision_id),
        "restore_revision_id": str(revision.id),
        "restore_hash": revision.content_hash,
        "fingerprint": content_hash(
            [
                str(head.id),
                head.version_number,
                str(head.current_revision_id),
                str(revision.id),
                revision.content_hash,
            ]
        ),
        "effect": "从所选历史生成新的作者确认修订，保留完整版本历史。",
    }


async def _apply_restore(db, novel_id, args, preview, *, context=None):
    await _require_scope(db, novel_id, args, context)
    if not args.preview_fingerprint:
        raise ConflictError("确认恢复前需要提交预览指纹", code="PREVIEW_REQUIRED")
    current = await _preview_restore(db, novel_id, args, context=context)
    if current != preview or current["fingerprint"] != args.preview_fingerprint:
        raise ConflictError("人物弧历史或当前版本已变化", code="PREVIEW_STALE")
    from .service import restore_revision

    return await restore_revision(db, novel_id, args)


async def _preview_archive(db, novel_id, args, *, context=None):
    await _require_scope(db, novel_id, args, context)
    from infrastructure.llm.collaboration import content_hash

    from .service import _assert_owner, _head, _owned_project, _validated_plan_target

    project = await _owned_project(db, novel_id)
    _scene, _character = await _validated_plan_target(
        db, novel_id, str(args.scene_id), str(args.character_id)
    )
    request_hash = content_hash(
        [str(args.scene_id), str(args.character_id), args.expected_version, "archive"]
    )
    prior = await _prior_revision(db, novel_id, args.character_id, args.operation_id)
    if prior is not None:
        if str(prior.owner_id) != str(project.owner_id):
            raise NotFoundError("人物弧计划不可访问")
        if prior.request_hash != request_hash or prior.source != "author_archive":
            raise ConflictError(
                "操作标识已用于另一项人物弧操作", code="OPERATION_MISMATCH"
            )
        if prior.base_revision_id is None:
            raise NotFoundError("人物弧归档来源不可访问")
        version = prior.version_number - 1
        return {
            "head_id": str(prior.head_id),
            "version": version,
            "current_revision_id": str(prior.base_revision_id),
            "fingerprint": content_hash(
                [str(prior.head_id), version, str(prior.base_revision_id)]
            ),
            "effect": "该归档请求已成功执行；重试将返回原结果。",
        }
    head = await _head(db, novel_id, str(args.character_id))
    _assert_owner(head, project)
    if head is None or head.deleted_at is not None:
        raise NotFoundError("人物弧计划不存在或已归档")
    if head.version_number != args.expected_version:
        raise ConflictError("人物弧计划版本已变化", code="STALE_VERSION")
    return {
        "head_id": str(head.id),
        "version": head.version_number,
        "current_revision_id": str(head.current_revision_id),
        "fingerprint": content_hash(
            [str(head.id), head.version_number, str(head.current_revision_id)]
        ),
        "effect": "将计划移入项目内归档；历史修订保留，可由作者恢复。",
    }


async def _apply_archive(db, novel_id, args, preview, *, context=None):
    await _require_scope(db, novel_id, args, context)
    if not args.preview_fingerprint:
        raise ConflictError("确认归档前需要提交预览指纹", code="PREVIEW_REQUIRED")
    current = await _preview_archive(db, novel_id, args, context=context)
    if current != preview or current["fingerprint"] != args.preview_fingerprint:
        raise ConflictError("人物弧计划已变化", code="PREVIEW_STALE")
    from .service import archive_plan

    return await archive_plan(db, novel_id, args)


async def _preview_unarchive(db, novel_id, args, *, context=None):
    await _require_scope(db, novel_id, args, context)
    from infrastructure.llm.collaboration import content_hash

    from .service import _assert_owner, _head, _owned_project, _validated_plan_target

    project = await _owned_project(db, novel_id)
    _scene, _character = await _validated_plan_target(
        db, novel_id, str(args.scene_id), str(args.character_id)
    )
    request_hash = content_hash(
        [str(args.scene_id), str(args.character_id), args.expected_version, "unarchive"]
    )
    prior = await _prior_revision(db, novel_id, args.character_id, args.operation_id)
    if prior is not None:
        if str(prior.owner_id) != str(project.owner_id):
            raise NotFoundError("人物弧计划不可访问")
        if prior.request_hash != request_hash or prior.source != "author_unarchive":
            raise ConflictError(
                "操作标识已用于另一项人物弧操作", code="OPERATION_MISMATCH"
            )
        if prior.base_revision_id is None:
            raise NotFoundError("人物弧恢复来源不可访问")
        version = prior.version_number - 1
        return {
            "head_id": str(prior.head_id),
            "version": version,
            "current_revision_id": str(prior.base_revision_id),
            "fingerprint": content_hash(
                [str(prior.head_id), version, str(prior.base_revision_id), "restore"]
            ),
            "effect": "该恢复请求已成功执行；重试将返回原结果。",
        }
    head = await _head(db, novel_id, str(args.character_id))
    _assert_owner(head, project)
    if head is None or head.deleted_at is None:
        raise NotFoundError("已归档人物弧计划不存在")
    if head.version_number != args.expected_version:
        raise ConflictError("人物弧计划版本已变化", code="STALE_VERSION")
    return {
        "head_id": str(head.id),
        "version": head.version_number,
        "current_revision_id": str(head.current_revision_id),
        "fingerprint": content_hash(
            [str(head.id), head.version_number, str(head.current_revision_id), "restore"]
        ),
        "effect": "恢复已归档的当前计划；历史与内容版本不变。",
    }


async def _apply_unarchive(db, novel_id, args, preview, *, context=None):
    await _require_scope(db, novel_id, args, context)
    if not args.preview_fingerprint:
        raise ConflictError("确认恢复前需要提交预览指纹", code="PREVIEW_REQUIRED")
    current = await _preview_unarchive(db, novel_id, args, context=context)
    if current != preview or current["fingerprint"] != args.preview_fingerprint:
        raise ConflictError("人物弧计划已变化", code="PREVIEW_STALE")
    from .service import unarchive_plan

    return await unarchive_plan(db, novel_id, args)


def _trace_rule(schema):
    return {
        "mode": "per_call",
        "parameter_policy": "schema_safe",
        "parameter_fields": tuple(schema.model_fields),
    }


_SAVE = {
    "label": "确认保存人物弧计划",
    "schema": ConfirmArcPlanInput,
    "prepare": _preview_save,
    "apply": _apply_save,
    "permission": "confirm",
    "op_id": "story.character_arc_plan.save",
    "op_version": "1",
    "description": "保存作者确认的 director-only 人物弧计划修订",
    "risk_level": "R3",
    "fee_category": "free",
    "reversibility": "history_restore",
    "preconditions": (
        "当前作者拥有的活动作品",
        "人物属于所选有效 Scene 的可信 Story/World 角色列表",
        "expected_version 与最新计划版本一致",
        "预览指纹与确认内容完全一致",
    ),
    "produces": ("story.character_arc_plan_revision",),
    "target_type": "story.character_arc_plan",
    "ai_available": True,
    "transaction_mode": "single_transaction",
    "trace_rule": _trace_rule(ConfirmArcPlanInput),
}
_RESTORE = {
    **_SAVE,
    "label": "恢复人物弧计划历史版本",
    "schema": RestoreArcPlanInput,
    "prepare": _preview_restore,
    "apply": _apply_restore,
    "op_id": "story.character_arc_plan.restore",
    "description": "基于历史版本追加一份新的作者确认人物弧计划修订",
    "trace_rule": _trace_rule(RestoreArcPlanInput),
}
_ARCHIVE = {
    **_SAVE,
    "label": "归档人物弧计划",
    "schema": ArchiveArcPlanInput,
    "prepare": _preview_archive,
    "apply": _apply_archive,
    "op_id": "story.character_arc_plan.archive",
    "description": "软归档作者确认人物弧计划，保留修订历史并可恢复",
    "trace_rule": _trace_rule(ArchiveArcPlanInput),
}
_UNARCHIVE = {
    **_ARCHIVE,
    "label": "恢复归档人物弧计划",
    "prepare": _preview_unarchive,
    "apply": _apply_unarchive,
    "op_id": "story.character_arc_plan.unarchive",
    "description": "恢复项目内归档的人物弧计划，不改动其修订内容",
    "trace_rule": _trace_rule(ArchiveArcPlanInput),
}


def _read_operation(op_id, label, schema, prepare, description, produces):
    return {
        "label": label,
        "schema": schema,
        "prepare": prepare,
        "apply": None,
        "permission": "read",
        "op_id": op_id,
        "op_version": "1",
        "description": description,
        "risk_level": "R0",
        "fee_category": "free",
        "reversibility": "read_only",
        "preconditions": ("作者可访问活动作品及可信 Story Scene",),
        "produces": (produces,),
        "target_type": "story.character_arc_plan",
        "ai_available": True,
        "transaction_mode": "single_transaction",
        "trace_rule": _trace_rule(schema),
    }


OPERATIONS_SPEC = {
    "story.character_arc_plan.scene_characters": _read_operation(
        "story.character_arc_plan.scene_characters",
        "读取 Scene 人物",
        SceneCharacterReadInput,
        _read_scene_characters,
        "读取所选 Scene 的可信角色，不读取作者未来人物弧计划。",
        "story.scene_character_options",
    ),
    "story.character_arc_plan.history": _read_operation(
        "story.character_arc_plan.history",
        "读取人物弧历史",
        CharacterArcReadInput,
        _read_history,
        "在完整作品工作范围内读取作者确认的人物弧修订历史。",
        "story.character_arc_plan_history",
    ),
    "story.character_arc_plan.compare": _read_operation(
        "story.character_arc_plan.compare",
        "对照人物弧计划与已发生事实",
        CharacterArcReadInput,
        _read_comparison,
        "按所选 Scene 截止点对照作者计划和可核验正文，不替作者裁定人物弧完成。",
        "story.character_arc_plan_comparison",
    ),
    "story.character_arc_plan.save": _SAVE,
    "story.character_arc_plan.restore": _RESTORE,
    "story.character_arc_plan.archive": _ARCHIVE,
    "story.character_arc_plan.unarchive": _UNARCHIVE,
}
