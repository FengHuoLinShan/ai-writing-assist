"""World Bible draft overlays; no Canon publication or entity mutation."""

from datetime import UTC
from uuid import UUID

from sqlalchemy import select

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.llm.collaboration import content_hash
from modules.collaboration.contracts import CreativeResourcePort, ResourceSnapshot
from modules.world.assistant_page_tools import OPERATIONS, EditPage
from modules.world.models import WorldBiblePageDraft


def _snapshot(row):
    content = {
        "title": row.title,
        "free_text": row.free_text or "",
        "sections_json": row.sections_json or [],
    }
    return ResourceSnapshot(
        kind="world_bible_draft",
        id=row.id,
        revision=content_hash(
            {
                "content": content,
                "updated_at": (
                    row.updated_at.replace(tzinfo=UTC)
                    if row.updated_at.tzinfo is None
                    else row.updated_at.astimezone(UTC)
                ).isoformat(),
            }
        ),
        source_hash=content_hash(content),
        label=row.title,
        content=content,
    )


async def inventory(db, novel_id):
    rows = (
        await db.scalars(
            select(WorldBiblePageDraft).where(
                WorldBiblePageDraft.novel_id == UUID(novel_id)
            )
        )
    ).all()
    return [_snapshot(row) for row in rows]


async def read(db, novel_id, reference):
    row = await db.scalar(
        select(WorldBiblePageDraft)
        .where(
            WorldBiblePageDraft.novel_id == UUID(novel_id),
            WorldBiblePageDraft.id == reference.id,
        )
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise NotFoundError("世界书工作稿不可访问")
    return _snapshot(row)


async def validate(db, novel_id, baseline, patch, *, context):
    if patch.operation == "delete":
        raise ValidationError("世界书废弃需在原领域确认；试验删除覆盖不能直接采用")
    if (await read(db, novel_id, baseline)).revision != baseline.revision:
        raise ConflictError("世界书工作稿已变化", code="SOURCE_STALE")
    if set(patch.value) != {"title", "free_text", "sections_json"}:
        raise ValidationError("世界书覆盖必须保留完整可编辑字段")
    args = EditPage(
        draft_id=baseline.id,
        title=patch.value["title"],
        free_text=patch.value["free_text"],
        sections=patch.value["sections_json"],
    )
    preview = await OPERATIONS["world.edit_page_draft"].prepare(
        db, novel_id, args, context=context
    )
    return {"arguments": args.model_dump(mode="json"), "preview": preview}


async def apply(db, novel_id, prepared, *, context):
    return await OPERATIONS["world.edit_page_draft"].apply(
        db,
        novel_id,
        EditPage.model_validate(prepared["arguments"]),
        prepared["preview"],
        context=context,
    )


PORT = CreativeResourcePort(inventory, read, validate, apply)
