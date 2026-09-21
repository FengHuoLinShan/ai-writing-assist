"""Readonly consultation input from the original review scope and source receipts."""

from core.errors import ConflictError, ValidationError
from infrastructure.llm.collaboration import content_hash
from modules.evidence.facade import (
    read_review_resolution_chapters,
    read_review_resolution_sources,
)
from modules.imports.review_resolution import freeze_resolution


async def inspect_scope(db, novel_id, selection):
    try:
        frozen = await freeze_resolution(
            db,
            novel_id=novel_id,
            start_chapter=selection.chapter_from,
            end_chapter=selection.chapter_to,
            asset_keys=selection.asset_keys,
            workflow_id=str(selection.workflow_id) if selection.workflow_id else None,
            repair_scenes=False,
        )
        sources, seen = [], set()
        for row in frozen["items"]:
            scene_id = row["meta"].get("scene_id")
            chapter = row["meta"].get("source_chapter_index")
            if scene_id:
                evidence = await read_review_resolution_sources(
                    db,
                    novel_id=novel_id,
                    scene_id=scene_id,
                    source_manifest=frozen["source_manifest"],
                    chapter_from=selection.chapter_from,
                    chapter_to=selection.chapter_to,
                )
            elif chapter:
                evidence = await read_review_resolution_chapters(
                    db,
                    novel_id=novel_id,
                    chapters=[int(chapter)],
                    source_manifest=frozen["source_manifest"],
                )
            else:
                raise ValidationError("这组资料缺少可重验的原文范围，请先在整理页面核对")
            for source in evidence:
                key = content_hash(source["source_ref"])
                if key not in seen:
                    sources.append(source)
                    seen.add(key)
    except ValueError as error:
        raise ValidationError(str(error)) from error
    payload = {
        "items": frozen["items"],
        "sources": sources,
        "source_manifest": frozen["source_manifest"],
        "scope_hash": frozen["scope_hash"],
        "chapter_from": selection.chapter_from,
        "chapter_to": selection.chapter_to,
    }
    fingerprint = content_hash(payload)
    if selection.expected_hash and selection.expected_hash != fingerprint:
        raise ConflictError(
            "原待决组或原文已变化，请重新选择会诊范围", code="IMPORT_SCOPE_CHANGED"
        )
    return {**payload, "fingerprint": fingerprint, "read_only": True}
