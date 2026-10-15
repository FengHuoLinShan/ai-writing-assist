"""Confirmed Assistant operations for the author-owned project vocabulary."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from core.container import get
from core.errors import ConflictError, NotFoundError, ValidationError
from core.service_keys import ASSISTANT_REQUIRE_OPERATION_TARGETS
from infrastructure.stable_hash import stable_hash
from modules.project.facade import (
    get_any_project_context,
    require_active_project_exclusive,
)
from modules.world.project_vocabulary_models import ProjectVocabularyTerm
from modules.world.project_vocabulary_presets import PRESETS
from modules.world.project_vocabulary_schemas import (
    ProjectVocabularyReadResponse,
    VocabularyMergeRequest,
    VocabularyPresetApplyRequest,
    VocabularySplitRequest,
    VocabularyTermCreate,
    VocabularyTermFields,
    VocabularyTermUpdate,
    normalize_vocabulary_key,
)
from modules.world.project_vocabulary_service import (
    apply_vocabulary_presets,
    archive_project_vocabulary_term,
    create_project_vocabulary_term,
    merge_project_vocabulary_terms,
    read_project_vocabulary,
    restore_project_vocabulary_term,
    split_project_vocabulary_term,
    update_project_vocabulary_term,
)


class EditVocabularyTerm(VocabularyTermFields):
    type_ref: UUID
    expected_revision_id: UUID


class VocabularyTermRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type_ref: UUID
    expected_revision_id: UUID


class MergeVocabularyTerms(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: UUID
    source_ids: list[UUID] = Field(min_length=1, max_length=19)
    expected_revision_ids: dict[UUID, UUID]

    @model_validator(mode="after")
    def validate_merge_refs(self):
        VocabularyMergeRequest(confirmed=True, **self.model_dump())
        return self


class SplitVocabularyTerm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type_ref: UUID
    expected_revision_id: UUID
    retained: VocabularyTermFields
    split_off: VocabularyTermFields


class ApplyVocabularyPresets(VocabularyPresetApplyRequest):
    pass


async def _project_scope(db, novel_id: str, context) -> None:
    if context is None or not getattr(context, "run_id", None):
        raise ConflictError("项目词表操作需要绑定当前作者运行")
    project = await get_any_project_context(db, novel_id)
    if (
        project is None
        or project.project_kind != "author"
        or str(project.owner_id) != str(getattr(context, "owner_id", ""))
    ):
        raise NotFoundError("项目词表不可访问")
    await get(ASSISTANT_REQUIRE_OPERATION_TARGETS)(
        db, novel_id, context, [], aggregate=True
    )
    if context.work.scope == "current" and (
        context.work.chapter_index or context.work.scene_id
    ):
        raise ConflictError("项目词表属于全书范围，请切换到项目资料范围后再修改")


async def _baseline(db, novel_id: str, context) -> tuple[dict, dict[str, dict]]:
    await _project_scope(db, novel_id, context)
    if (getattr(context, "internal_meta", None) or {}).get("confirmation_preflight"):
        await _lock_project(db, novel_id)
    response: ProjectVocabularyReadResponse = await read_project_vocabulary(
        db, novel_id, limit=500, include_archived=True
    )
    if response.omitted_count:
        raise ConflictError(
            f"项目词表有 {response.omitted_count} 项未能完整核对，请先在词表工作台整理"
        )
    snapshot = response.model_dump(mode="json")
    by_id = {str(item.id): item.model_dump(mode="json") for item in response.items}
    return {
        "target_key": f"project_vocabulary:{novel_id}",
        "baseline_hash": _fingerprint(snapshot),
        "total_count": response.total_count,
        "omitted_count": response.omitted_count,
        "revision_manifest": [
            {
                "type_ref": str(item.id),
                "kind": item.kind,
                "status": item.status,
                "revision_id": str(item.revision_id),
                "content_hash": item.content_hash,
                "redirect_to_id": str(item.redirect_to_id)
                if item.redirect_to_id
                else None,
            }
            for item in response.items
        ],
    }, by_id


def _fingerprint(value: dict) -> str:
    return stable_hash(value)


def _lookup(by_id: dict[str, dict], type_ref: UUID, expected: UUID) -> dict:
    item = by_id.get(str(type_ref))
    if item is None:
        raise ConflictError("项目词条已变化或不属于当前作品")
    if item["revision_id"] != str(expected):
        raise ConflictError("项目词条修订已变化，请重新查看方案")
    return item


def _keys(fields: VocabularyTermFields | dict) -> set[str]:
    values = fields.model_dump(mode="json") if isinstance(fields, BaseModel) else fields
    return {
        key
        for value in [values["name"], *values.get("aliases", [])]
        if (key := normalize_vocabulary_key(str(value)))
    }


def _ensure_unique(
    by_id: dict[str, dict], kind: str, fields: VocabularyTermFields, ignored: set[str]
) -> None:
    candidate = _keys(fields)
    for item_id, item in by_id.items():
        resolved_id = item_id
        seen = set()
        while item["status"] == "merged":
            redirect = item.get("redirect_to_id")
            if not redirect or redirect in seen or redirect not in by_id:
                raise ConflictError("项目词条的墓碑重定向无效")
            seen.add(redirect)
            resolved_id = redirect
            item = by_id[redirect]
        if (
            item["kind"] == kind
            and item_id not in ignored
            and resolved_id not in ignored
            and candidate & _keys(item)
        ):
            raise ConflictError("同一词表种类中已存在同名或等价别名")


def _preview(
    base: dict,
    *,
    title: str,
    before=None,
    after=None,
    effect: str,
    targets: list[str],
    affected_count: int = 1,
) -> dict:
    return {
        **base,
        "target_key": targets[0],
        "target_keys": targets,
        "affected_count": affected_count,
        "title": title,
        "before": before,
        "after": after,
        "effect": effect,
    }


async def _create_preview(db, novel_id, args, *, context=None):
    base, by_id = await _baseline(db, novel_id, context)
    _ensure_unique(by_id, args.kind, args, set())
    return _preview(
        base,
        title=f"新增项目词条：{args.name}",
        targets=[f"vocabulary_name:{args.kind}:{key}" for key in sorted(_keys(args))],
        after=args.model_dump(mode="json"),
        effect="作者确认后以作者来源创建稳定词条和首个不可变修订。",
    )


async def _edit_preview(db, novel_id, args, *, context=None):
    base, by_id = await _baseline(db, novel_id, context)
    current = _lookup(by_id, args.type_ref, args.expected_revision_id)
    if current["status"] in {"archived", "merged"}:
        raise ConflictError("归档或合并词条需先恢复后再编辑")
    _ensure_unique(by_id, current["kind"], args, {str(args.type_ref)})
    before = {key: current[key] for key in ("name", "description", "aliases", "traits")}
    after = {
        key: getattr(args, key).model_dump(mode="json")
        if key == "traits"
        else getattr(args, key)
        for key in before
    }
    return _preview(
        base,
        title=f"编辑项目词条：{current['name']}",
        targets=[f"vocabulary:{args.type_ref}"],
        before=before,
        after=after,
        effect="作者确认后追加不可变修订；稳定词条身份及旧地图固定引用保持不变。",
    )


async def _archive_preview(db, novel_id, args, *, context=None):
    base, by_id = await _baseline(db, novel_id, context)
    current = _lookup(by_id, args.type_ref, args.expected_revision_id)
    if current["status"] in {"archived", "merged"}:
        raise ConflictError("词条已经归档或合并")
    return _preview(
        base,
        title=f"归档项目词条：{current['name']}",
        targets=[f"vocabulary:{args.type_ref}"],
        before={"status": current["status"], "revision_id": current["revision_id"]},
        after={"status": "archived"},
        effect="作者确认后保留墓碑修订；模型不能以同名重建，可由作者恢复。",
    )


async def _restore_preview(db, novel_id, args, *, context=None):
    base, by_id = await _baseline(db, novel_id, context)
    current = _lookup(by_id, args.type_ref, args.expected_revision_id)
    if current["status"] != "archived":
        raise ConflictError("只有已归档词条可以恢复")
    _ensure_unique(
        by_id,
        current["kind"],
        VocabularyTermFields.model_validate(
            {key: current[key] for key in ("name", "description", "aliases", "traits")}
        ),
        {str(args.type_ref)},
    )
    return _preview(
        base,
        title=f"恢复项目词条：{current['name']}",
        targets=[f"vocabulary:{args.type_ref}"],
        before={"status": current["status"]},
        after={"status": "active"},
        effect="作者确认后追加新修订并恢复原稳定身份；如名称已被占用则拒绝。",
    )


async def _merge_preview(db, novel_id, args, *, context=None):
    base, by_id = await _baseline(db, novel_id, context)
    refs = {args.target_id, *args.source_ids}
    items = {
        ref: _lookup(by_id, ref, args.expected_revision_ids[ref])
        for ref in sorted(refs, key=str)
    }
    target = items[args.target_id]
    if any(item["kind"] != target["kind"] for item in items.values()):
        raise ValidationError("只能合并同一种类的项目词条")
    if any(item["status"] in {"archived", "merged"} for item in items.values()):
        raise ConflictError("归档或已合并词条不能再次合并")
    aliases = list(target["aliases"])
    seen = _keys(target)
    for ref in args.source_ids:
        for alias in [items[ref]["name"], *items[ref]["aliases"]]:
            key = normalize_vocabulary_key(alias)
            if key and key not in seen:
                seen.add(key)
                aliases.append(alias)
    if len(aliases) > 24:
        raise ValidationError("合并后的别名超过 24 个，请先整理别名后重试")
    after = {
        "target_id": str(args.target_id),
        "source_ids": [str(item) for item in args.source_ids],
        "target": {"name": target["name"], "aliases": aliases},
        "redirects": [
            {"type_ref": str(ref), "redirect_to_id": str(args.target_id)}
            for ref in args.source_ids
        ],
    }
    merged_fields = VocabularyTermFields.model_validate(
        {
            "name": target["name"],
            "description": target["description"],
            "aliases": aliases,
            "traits": target["traits"],
        }
    )
    _ensure_unique(by_id, target["kind"], merged_fields, {str(ref) for ref in refs})
    return _preview(
        base,
        title=f"合并 {len(refs)} 个项目词条到「{target['name']}」",
        targets=[f"vocabulary:{ref}" for ref in sorted(refs, key=str)],
        affected_count=len(refs),
        before={
            "terms": [
                {"type_ref": str(ref), "name": item["name"]}
                for ref, item in items.items()
            ]
        },
        after=after,
        effect=(
            "此操作会追加目标修订并为来源词条写入墓碑重定向；"
            "需作者明确确认，最多涉及 20 个词条。"
        ),
    )


async def _split_preview(db, novel_id, args, *, context=None):
    base, by_id = await _baseline(db, novel_id, context)
    current = _lookup(by_id, args.type_ref, args.expected_revision_id)
    if current["status"] in {"archived", "merged"}:
        raise ConflictError("归档或合并词条不能拆分")
    if _keys(args.retained) & _keys(args.split_off):
        raise ConflictError("拆分后的两个词条必须有不同名称和别名")
    ignored = {str(args.type_ref)}
    _ensure_unique(by_id, current["kind"], args.retained, ignored)
    _ensure_unique(by_id, current["kind"], args.split_off, ignored)
    return _preview(
        base,
        title=f"拆分项目词条：{current['name']}",
        targets=[f"vocabulary:{args.type_ref}"],
        affected_count=2,
        before={"type_ref": str(args.type_ref), "name": current["name"]},
        after={
            "retained": args.retained.model_dump(mode="json"),
            "split_off": args.split_off.model_dump(mode="json"),
        },
        effect="作者确认后为原身份追加修订，并创建一个新的作者词条。",
    )


async def _preset_preview(db, novel_id, args, *, context=None):
    base, by_id = await _baseline(db, novel_id, context)
    applied_terms = await db.scalars(
        select(ProjectVocabularyTerm).where(
            ProjectVocabularyTerm.novel_id == UUID(novel_id),
            ProjectVocabularyTerm.preset_id.in_(args.preset_ids),
        )
    )
    applied_keys = {(item.preset_id, item.preset_item_key) for item in applied_terms}
    known: dict[str, set[str]] = {}
    for item in by_id.values():
        known.setdefault(item["kind"], set()).update(_keys(item))
    create_count = 0
    for preset_id in args.preset_ids:
        preset = PRESETS[preset_id]
        for _version, items in ((preset.version, preset.items), *preset.extensions):
            for item in items:
                identity = (preset.id, item.key)
                if identity in applied_keys:
                    continue
                fields = VocabularyTermFields(
                    name=item.name,
                    description=item.description,
                    aliases=list(item.aliases),
                    traits=item.traits or {},
                )
                keys = _keys(fields)
                if keys & known.setdefault(item.kind, set()):
                    continue
                known[item.kind].update(keys)
                applied_keys.add(identity)
                create_count += 1
    if create_count > 20:
        raise ValidationError("一次题材预设确认最多创建 20 个词条，请拆分预设选择")
    return _preview(
        base,
        title=f"复制 {len(args.preset_ids)} 个题材预设",
        targets=[f"vocabulary_preset:{preset_id}" for preset_id in args.preset_ids],
        affected_count=create_count,
        before={"preset_ids": list(args.preset_ids)},
        after={"expected_created_count": create_count},
        effect="只复制当前预设版本；同一项目重复应用幂等，同名或等价名称会跳过。",
    )


async def _apply_create(db, novel_id, args, preview, *, context=None):
    await _confirm_preview(db, novel_id, args, preview, _create_preview, context)
    result = await create_project_vocabulary_term(db, novel_id, args)
    return _term_result(result, "已创建项目词条")


async def _apply_edit(db, novel_id, args, preview, *, context=None):
    await _confirm_preview(db, novel_id, args, preview, _edit_preview, context)
    result = await update_project_vocabulary_term(
        db,
        novel_id,
        str(args.type_ref),
        VocabularyTermUpdate(
            expected_revision_id=args.expected_revision_id,
            name=args.name,
            description=args.description,
            aliases=args.aliases,
            traits=args.traits,
        ),
    )
    return _term_result(result, "已追加项目词条修订")


async def _apply_archive(db, novel_id, args, preview, *, context=None):
    await _confirm_preview(db, novel_id, args, preview, _archive_preview, context)
    result = await archive_project_vocabulary_term(
        db, novel_id, str(args.type_ref), args.expected_revision_id
    )
    return _term_result(result, "已归档并保留词条墓碑")


async def _apply_restore(db, novel_id, args, preview, *, context=None):
    await _confirm_preview(db, novel_id, args, preview, _restore_preview, context)
    result = await restore_project_vocabulary_term(
        db, novel_id, str(args.type_ref), args.expected_revision_id
    )
    return _term_result(result, "已恢复原项目词条身份")


async def _apply_merge(db, novel_id, args, preview, *, context=None):
    await _confirm_preview(db, novel_id, args, preview, _merge_preview, context)
    result = await merge_project_vocabulary_terms(
        db,
        novel_id,
        VocabularyMergeRequest(confirmed=True, **args.model_dump()),
    )
    return _term_result(result, "已合并词条并保留墓碑重定向")


async def _apply_split(db, novel_id, args, preview, *, context=None):
    await _confirm_preview(db, novel_id, args, preview, _split_preview, context)
    retained, split_off = await split_project_vocabulary_term(
        db,
        novel_id,
        str(args.type_ref),
        VocabularySplitRequest(
            expected_revision_id=args.expected_revision_id,
            retained=args.retained,
            split_off=args.split_off,
        ),
    )
    return {
        "type": "project_vocabulary_split",
        "id": str(retained.id),
        "revision_id": str(retained.revision_id),
        "created_type_ref": str(split_off.id),
        "created_revision_id": str(split_off.revision_id),
        "label": "已拆分项目词条",
    }


async def _apply_presets(db, novel_id, args, preview, *, context=None):
    await _confirm_preview(db, novel_id, args, preview, _preset_preview, context)
    if int(preview["after"]["expected_created_count"]) > 20:
        raise ValidationError("题材预设一次最多创建 20 个词条")
    result = await apply_vocabulary_presets(db, novel_id, args.preset_ids)
    if result.applied > 20:
        raise ValidationError("题材预设一次最多创建 20 个词条")
    return {
        "type": "project_vocabulary_presets",
        "applied": result.applied,
        "already_applied": result.already_applied,
        "duplicate_skipped": result.duplicate_skipped,
        "label": "已复制题材预设词条",
    }


async def _lock_project(db, novel_id):
    try:
        async with db.begin_nested():
            await require_active_project_exclusive(db, novel_id, nowait=True)
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) == "55P03":
            raise ConflictError("作品正在更新，请稍后重试词表确认") from None
        raise


async def _confirm_preview(db, novel_id, args, preview, prepare, context):
    await _lock_project(db, novel_id)
    current = await prepare(db, novel_id, args, context=context)
    # Confirmation preflight already checked the complete vocabulary under the
    # project lock. Earlier writes in this batch may change only that guard.
    checked = (getattr(context, "internal_meta", None) or {}).get(
        "confirmed_previews", ()
    )
    if _fingerprint(preview) in checked:
        current = {
            **current,
            **{
                key: preview[key]
                for key in (
                    "baseline_hash",
                    "total_count",
                    "omitted_count",
                    "revision_manifest",
                )
            },
        }
    if current != preview:
        raise ConflictError("项目词表已变化，请重新查看方案")


def _term_result(result, label):
    return {
        "type": "project_vocabulary_term",
        "id": str(result.id),
        "revision_id": str(result.revision_id),
        "label": label,
    }


OPERATIONS_SPEC = {
    "world.vocabulary.create": {
        "label": "新增项目词条",
        "schema": VocabularyTermCreate,
        "prepare": _create_preview,
        "apply": _apply_create,
    },
    "world.vocabulary.edit": {
        "label": "编辑或改名项目词条",
        "schema": EditVocabularyTerm,
        "prepare": _edit_preview,
        "apply": _apply_edit,
    },
    "world.vocabulary.archive": {
        "label": "归档项目词条",
        "schema": VocabularyTermRef,
        "prepare": _archive_preview,
        "apply": _apply_archive,
    },
    "world.vocabulary.restore": {
        "label": "恢复项目词条",
        "schema": VocabularyTermRef,
        "prepare": _restore_preview,
        "apply": _apply_restore,
    },
    "world.vocabulary.merge": {
        "label": "合并项目词条",
        "schema": MergeVocabularyTerms,
        "prepare": _merge_preview,
        "apply": _apply_merge,
    },
    "world.vocabulary.split": {
        "label": "拆分项目词条",
        "schema": SplitVocabularyTerm,
        "prepare": _split_preview,
        "apply": _apply_split,
    },
    "world.vocabulary.apply_presets": {
        "label": "复制题材预设词条",
        "schema": ApplyVocabularyPresets,
        "prepare": _preset_preview,
        "apply": _apply_presets,
    },
}
