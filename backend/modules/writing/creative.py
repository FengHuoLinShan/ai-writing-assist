"""Writing's exact working-version adapter for isolated creative revisions."""

from __future__ import annotations

from core.errors import ConflictError, NotFoundError, ValidationError
from infrastructure.llm.collaboration import content_hash
from modules.collaboration.contracts import CreativeResourcePort, ResourceSnapshot
from modules.writing.assistant_tools import OPERATIONS, ReviseChapter
from modules.writing.facade import (
    get_draft,
    get_latest_draft_for_chapter,
    list_manuscript_sources,
)


def _snapshot(draft):
    content = {"title": draft.title or "", "content": draft.content or ""}
    return ResourceSnapshot(
        kind="writing_draft",
        id=draft.id,
        revision=f"{draft.version_number}:{draft.content_hash}",
        source_hash=content_hash(content),
        label=draft.title or f"第 {draft.chapter_index} 章",
        content=content,
        chapter_index=draft.chapter_index,
    )


async def inventory(db, novel_id):
    return [
        _snapshot(draft)
        for draft in await list_manuscript_sources(db, novel_id, content_mode="working")
    ]


async def read(db, novel_id, reference):
    draft = await get_draft(db, novel_id, str(reference.id))
    if draft is None:
        raise NotFoundError("正文不可访问")
    latest = await get_latest_draft_for_chapter(db, novel_id, draft.chapter_index)
    if latest is None or latest.id != draft.id:
        raise ConflictError("工作稿版本已变化", code="SOURCE_STALE")
    return _snapshot(draft)


async def validate(db, novel_id, baseline, patch, *, context):
    if patch.operation == "delete":
        raise ValidationError("正文删除仍需在原领域处理；试验中的删除覆盖不能直接采用")
    if set(patch.value) != {"title", "content"} or not all(
        isinstance(v, str) for v in patch.value.values()
    ):
        raise ValidationError("正文试改只接受完整标题与正文")
    if patch.value["title"] != baseline.content["title"]:
        raise ValidationError("本次正文试改保留章节标题")
    if (await read(db, novel_id, baseline)).source_hash != baseline.source_hash:
        raise ConflictError("正文已变化", code="SOURCE_STALE")
    draft = await get_draft(db, novel_id, str(baseline.id))
    args = ReviseChapter(
        draft_id=baseline.id,
        source_hash=draft.content_hash,
        replacements=[
            {
                "start": 0,
                "end": len(baseline.content["content"]),
                "original": baseline.content["content"],
                "replacement": patch.value["content"],
            }
        ],
    )
    preview = await OPERATIONS["writing.revise"].prepare(
        db, novel_id, args, context=context
    )
    return {"arguments": args.model_dump(mode="json"), "preview": preview}


async def apply(db, novel_id, prepared, *, context):
    return await OPERATIONS["writing.revise"].apply(
        db,
        novel_id,
        ReviseChapter.model_validate(prepared["arguments"]),
        prepared["preview"],
        context=context,
    )


PORT = CreativeResourcePort(inventory, read, validate, apply)
