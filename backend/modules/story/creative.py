"""Story's Scene and information-plan overlay/merge adapters."""

from datetime import UTC
from uuid import UUID

from sqlalchemy import select

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.llm.collaboration import content_hash
from modules.collaboration.contracts import CreativeResourcePort, ResourceSnapshot
from modules.story.assistant_information_tools import KINDS, EditInformationPlan
from modules.story.assistant_information_tools import OPERATIONS as INFORMATION
from modules.story.assistant_tools import OPERATIONS as SCENES
from modules.story.assistant_tools import EditScene
from modules.story.outline_state.models import Scene
from modules.story.outline_state.schemas import SceneUpdate


def _snapshot(row, kind):
    allowed = (
        set(SceneUpdate.model_fields)
        - {
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
        if kind == "scene"
        else set(KINDS[kind][1].model_fields)
        - {
            "novel_id",
            "provenance_meta",
            "related_entity_ids",
            "target_id",
            "target_type",
            "status",
        }
    )
    content = {key: getattr(row, key) for key in sorted(allowed) if hasattr(row, key)}
    # JSON-mode schemas normalize UUIDs and other domain value objects.
    schema = SceneUpdate if kind == "scene" else KINDS[kind][1]
    content = schema.model_validate(content).model_dump(mode="json", exclude_unset=True)
    revision = content_hash(
        {
            "content": content,
            "updated_at": (
                row.updated_at.replace(tzinfo=UTC)
                if row.updated_at.tzinfo is None
                else row.updated_at.astimezone(UTC)
            ).isoformat(),
        }
    )
    return ResourceSnapshot(
        kind=kind,
        id=row.id,
        revision=revision,
        source_hash=content_hash(content),
        label=str(
            getattr(row, "title", None) or getattr(row, "name", None) or "信息计划"
        ),
        content=content,
        chapter_index=getattr(row, "chapter_index", None)
        or getattr(row, "chapter_start", None),
    )


def _model(kind):
    return Scene if kind == "scene" else KINDS[kind][0]


async def inventory(db, novel_id, *, kind):
    model = _model(kind)
    rows = (await db.scalars(select(model).where(model.novel_id == UUID(novel_id)))).all()
    return [
        _snapshot(row, kind)
        for row in rows
        if row.status not in {"deprecated", "archived"}
    ]


async def read(db, novel_id, reference):
    model = _model(reference.kind)
    row = await db.scalar(
        select(model)
        .where(model.novel_id == UUID(novel_id), model.id == reference.id)
        .execution_options(populate_existing=True)
    )
    if row is None or row.status in {"deprecated", "archived"}:
        raise NotFoundError("规划不可访问")
    return _snapshot(row, reference.kind)


async def validate(db, novel_id, baseline, patch, *, context):
    if patch.operation == "delete":
        raise ValidationError("规划废弃需在原领域确认；试验删除覆盖不能直接采用")
    current = await read(db, novel_id, baseline)
    if current.revision != baseline.revision:
        raise ConflictError("规划已变化", code="SOURCE_STALE")
    if set(patch.value) != set(baseline.content):
        raise ValidationError("规划覆盖必须保留完整可编辑字段")
    changes = {
        key: value for key, value in patch.value.items() if baseline.content[key] != value
    }
    if not changes:
        raise ValidationError("此规划没有修改")
    name = (
        "story.edit_scene" if baseline.kind == "scene" else "story.edit_information_plan"
    )
    operation = (SCENES if baseline.kind == "scene" else INFORMATION)[name]
    args = (
        EditScene(scene_id=baseline.id, changes=changes)
        if baseline.kind == "scene"
        else EditInformationPlan(kind=baseline.kind, plan_id=baseline.id, changes=changes)
    )
    preview = await operation.prepare(db, novel_id, args, context=context)
    return {
        "operation": name,
        "arguments": args.model_dump(mode="json"),
        "preview": preview,
    }


async def apply(db, novel_id, prepared, *, context):
    operation = (SCENES | INFORMATION)[prepared["operation"]]
    return await operation.apply(
        db,
        novel_id,
        operation.schema.model_validate(prepared["arguments"]),
        prepared["preview"],
        context=context,
    )


def ports():
    from functools import partial

    return {
        kind: CreativeResourcePort(partial(inventory, kind=kind), read, validate, apply)
        for kind in ("scene", *KINDS)
    }
