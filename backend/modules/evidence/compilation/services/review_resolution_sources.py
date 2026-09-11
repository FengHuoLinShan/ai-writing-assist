"""Exact, manifest-fenced Scene sources for authorized import review."""

from dataclasses import asdict, fields

from modules.evidence.compilation.services.import_activation import (
    ImportContextActivationService,
)
from modules.story.facade import get_scene_contract
from modules.writing.contracts import SourceRangeRefContract
from modules.writing.facade import read_manuscript_range


async def read_sources(
    db, *, novel_id, scene_id, source_manifest, chapter_from, chapter_to
):
    scene = await get_scene_contract(db, novel_id, scene_id)
    if scene is None:
        raise ValueError("来源场景不存在")
    meta = scene.structure_meta
    if meta.get("needs_review") and (
        meta.get("review_issues_version") != 1
        or any(
            issue.get("required") and issue.get("kind") != "semantic_field"
            for issue in meta.get("review_issues", [])
        )
    ):
        raise ValueError("来源场景的边界仍需核实")
    refs = await ImportContextActivationService().source_refs(
        db, novel_id=novel_id, scene_id=scene_id, content_mode="working"
    )
    if not refs:
        raise ValueError("来源场景没有精确正文定位")
    evidence = []
    for index, raw in enumerate(refs):
        ref = SourceRangeRefContract(
            **{
                key: value
                for key, value in raw.items()
                if key in {field.name for field in fields(SourceRangeRefContract)}
            }
        )
        if (
            source_manifest.get(ref.draft_id) != ref.source_hash
            or not chapter_from <= ref.chapter_index <= chapter_to
        ):
            raise ValueError("来源已变化或超出授权章节")
        read = await read_manuscript_range(db, novel_id, ref, before=0, after=0)
        evidence.append(
            {
                "key": f"scene-{scene_id}-{index}",
                "text": read.text[read.highlight_start : read.highlight_end],
                "source_ref": asdict(read.source_ref),
            }
        )
    return evidence


async def read_chapters(db, *, novel_id, chapters, source_manifest):
    from modules.writing.facade import (
        build_manuscript_range_ref,
        list_latest_drafts_for_chapters,
    )

    drafts = await list_latest_drafts_for_chapters(db, novel_id, chapters)
    if {draft.chapter_index for draft in drafts} != set(chapters):
        raise ValueError("所选章节来源不完整")
    evidence = []
    for draft in drafts:
        if source_manifest.get(str(draft.id)) != draft.content_hash:
            raise ValueError("章节来源已变化")
        ref = await build_manuscript_range_ref(
            db,
            novel_id,
            draft_id=str(draft.id),
            start_offset=0,
            end_offset=len(draft.content),
            content_mode="working",
        )
        evidence.append(
            {
                "key": f"chapter-{draft.chapter_index}",
                "text": draft.content,
                "source_ref": asdict(ref),
            }
        )
    if sum(len(item["text"]) for item in evidence) > 100000:
        raise ValueError("场景修复范围超过预算，需拆分处理")
    return evidence
