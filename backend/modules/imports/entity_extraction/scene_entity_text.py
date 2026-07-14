"""Scene loading and text preparation helpers for Phase 2."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.entity_extraction.scene_entity_config import (
    PHASE2_SCENE_TIMEOUT_GRACE_SECONDS,
    PHASE2_SMALL_SAMPLE_SUPPLEMENT_CHAPTER_CHAR_LIMIT,
    PHASE2_SMALL_SAMPLE_SUPPLEMENT_TOTAL_CHAR_LIMIT,
)
from modules.imports.llm_schemas import SceneEntityExtractionOutput
from modules.writing.contracts import WritingDraftContract


async def get_scenes(db: AsyncSession, nid) -> list[dict[str, Any]]:
    from modules.outline.facade import get_scenes_by_novel

    return await get_scenes_by_novel(
        db,
        str(nid),
        status_filter=["draft", "canonical"],
        exclude_narrative_tags=["valley", "transition"],
    )


async def load_small_sample_chapters_text(
    service,
    db: AsyncSession,
    scenes: list[dict[str, Any]],
) -> str:
    from modules.writing.facade import list_latest_drafts_for_chapters

    if not scenes:
        return ""
    chapter_indices = service._small_sample_chapter_indices(scenes)
    if not chapter_indices:
        return ""
    novel_id = scenes[0]["novel_id"]
    drafts = await list_latest_drafts_for_chapters(db, novel_id, chapter_indices)
    draft_by_chapter = {draft.chapter_index: draft for draft in drafts}
    parts: list[str] = []
    for chapter_index in chapter_indices:
        draft = draft_by_chapter.get(chapter_index)
        if draft and draft.content:
            parts.append(
                f"## 第{chapter_index}章\n\n"
                f"{service._trim_supplement_chapter_text(draft.content)}"
            )
    return "\n\n".join(parts)[:PHASE2_SMALL_SAMPLE_SUPPLEMENT_TOTAL_CHAR_LIMIT]


def trim_supplement_chapter_text(content: str) -> str:
    text = str(content or "").strip()
    if len(text) <= PHASE2_SMALL_SAMPLE_SUPPLEMENT_CHAPTER_CHAR_LIMIT:
        return text
    half = PHASE2_SMALL_SAMPLE_SUPPLEMENT_CHAPTER_CHAR_LIMIT // 2
    head = text[:half].rstrip()
    tail = text[-half:].lstrip()
    return f"{head}\n\n[...章节中段已压缩...]\n\n{tail}"


def small_sample_chapter_indices(scenes: list[dict[str, Any]]) -> list[int]:
    chapters: set[int] = set()
    for scene in scenes:
        for raw in scene.get("chapter_ids") or []:
            try:
                chapters.add(int(raw))
            except (TypeError, ValueError):
                continue
    return sorted(chapter for chapter in chapters if chapter > 0)


def scene_source_chapter_index(scene: dict[str, Any]) -> int:
    """取 Scene 关联的最大章节号作为来源章节；没有则回退到 scene_index。"""
    chapter_ids = scene.get("chapter_ids") or []
    indices: list[int] = []
    for raw in chapter_ids:
        try:
            indices.append(int(raw))
        except (ValueError, TypeError):
            continue
    return max(indices) if indices else scene.get("scene_index", 0)


async def load_scene_chapters(service, db: AsyncSession, scene: dict[str, Any]) -> str:
    from modules.writing.facade import list_latest_drafts_for_chapters

    chunk_by_chapter = service._scene_chunks_by_chapter(scene)
    chapter_ids = service._scene_chapter_ids(scene, chunk_by_chapter)
    chapter_indices = scene_chapter_indices(chapter_ids)

    drafts = await list_latest_drafts_for_chapters(
        db,
        scene["novel_id"],
        chapter_indices,
    )
    draft_by_chapter = {draft.chapter_index: draft for draft in drafts}
    return scene_text_from_drafts(
        service,
        scene,
        chapter_indices,
        chunk_by_chapter,
        draft_by_chapter,
    )


def scene_chapter_indices(chapter_ids: list[str] | tuple[str, ...]) -> list[int]:
    chapter_indices: list[int] = []
    for ch_id_str in chapter_ids:
        try:
            ch_idx = int(ch_id_str)
        except (ValueError, TypeError):
            continue
        chapter_indices.append(ch_idx)
    return chapter_indices


def scene_text_from_drafts(
    service,
    scene: dict[str, Any],
    chapter_indices: list[int],
    chunk_by_chapter: dict[int, list[dict[str, Any]]],
    draft_by_chapter: dict[int, WritingDraftContract],
) -> str:
    parts: list[str] = []
    for ch_idx in chapter_indices:
        draft = draft_by_chapter.get(ch_idx)
        if draft and draft.content:
            selected = service._select_scene_text(
                draft.content,
                chunk_by_chapter.get(ch_idx, []),
            )
            parts.append(f"## 第{ch_idx}章\n\n{selected}")
    if not parts:
        return ""
    scene_context = service._scene_context_header(scene)
    return scene_context + "\n\n" + "\n\n".join(parts)


def phase2_scene_llm_timeout_seconds() -> int:
    from core.config import get_settings

    return max(
        30,
        int(get_settings().llm_timeout) + PHASE2_SCENE_TIMEOUT_GRACE_SECONDS,
    )


def scene_context_header(scene: dict[str, Any]) -> str:
    fields = [
        ("Scene", scene.get("scene_index")),
        ("标题", scene.get("title")),
        ("目标", scene.get("goal")),
        ("核心冲突", scene.get("core_conflict")),
        ("情绪节拍", scene.get("emotional_beat")),
    ]
    lines = [
        f"- {label}: {value}"
        for label, value in fields
        if value is not None and str(value).strip()
    ]
    return "## Scene 上下文\n" + ("\n".join(lines) if lines else "- 无")


def scene_chunks_by_chapter(
    scene: dict[str, Any],
) -> dict[int, list[dict[str, Any]]]:
    result: dict[int, list[dict[str, Any]]] = {}
    for raw_chunk in scene.get("scene_chunks") or []:
        if not isinstance(raw_chunk, dict):
            continue
        try:
            chapter_index = int(raw_chunk.get("chapter_index"))
        except (TypeError, ValueError):
            continue
        if chapter_index < 1:
            continue
        result.setdefault(chapter_index, []).append(raw_chunk)
    return result


def scene_chapter_ids(
    scene: dict[str, Any],
    chunk_by_chapter: dict[int, list[dict[str, Any]]],
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in scene.get("chapter_ids") or []:
        value = str(raw)
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    for chapter_index in sorted(chunk_by_chapter):
        value = str(chapter_index)
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def select_scene_text(
    chapter_text: str,
    chunks: list[dict[str, Any]],
) -> str:
    if not chunks:
        return chapter_text
    selected: list[str] = []
    paragraphs: list[str] | None = None
    for chunk in chunks:
        if not isinstance(chunk, dict):
            return chapter_text
        raw_start_offset = chunk.get("start_offset")
        raw_end_offset = chunk.get("end_offset")
        try:
            if isinstance(raw_start_offset, bool) or isinstance(raw_end_offset, bool):
                raise ValueError("boolean offsets are not valid boundaries")
            start_offset = int(raw_start_offset)
            end_offset = int(raw_end_offset)
        except (TypeError, ValueError):
            start_offset = end_offset = -1
        if 0 <= start_offset < end_offset <= len(chapter_text):
            selected.append(chapter_text[start_offset:end_offset])
            continue

        if paragraphs is None:
            paragraphs = [
                part.strip() for part in chapter_text.split("\n\n") if part.strip()
            ]
        if not paragraphs:
            continue
        raw_start = chunk.get("start_paragraph")
        raw_end = chunk.get("end_paragraph")
        try:
            if isinstance(raw_start, bool) or isinstance(raw_end, bool):
                raise ValueError("boolean paragraph indices are not valid boundaries")
            start = int(raw_start)
            end = int(raw_end)
        except (TypeError, ValueError):
            return chapter_text
        if not (0 <= start <= end < len(paragraphs)):
            return chapter_text
        selected.extend(paragraphs[start : end + 1])

    compact = "\n\n".join(dict.fromkeys(part for part in selected if part))
    return compact or chapter_text


def build_memory_context(memory: list[dict]) -> str:
    if not memory:
        return "无前序 Scene 上下文"
    recent = memory[-5:]
    lines = ["## 前序 Scene 摘要"]
    for m in recent:
        lines.append(f"- Scene {m['scene_index']}: 包含 {m['entities']} 个实体")
    return "\n".join(lines)


def parallel_scene_memory_context(scene: dict[str, Any], scene_idx: int) -> str:
    scene_index = scene.get("scene_index", scene_idx)
    return (
        "小样本并发 Phase 2：当前 Scene 会与同批其他 Scene 并发抽取，"
        "请只依据本 Scene 正文和已有对象判断长期创作资产。"
        f"\n- 当前 Scene: {scene_index}"
        f"\n- 标题: {scene.get('title') or '未命名'}"
    )


def append_extracted_entities_to_context(
    existing_context: str,
    extraction: SceneEntityExtractionOutput,
) -> str:
    new_entities_text = "\n".join(
        f"- {entity.name} ({entity.entity_type})"
        for entity in extraction.entities
        if entity.suggested_action == "create_new" and entity.name
    )
    if not new_entities_text:
        return existing_context
    return f"{existing_context}\n{new_entities_text}"


def result_ref_ids(result_refs: list[dict[str, str]], result_type: str) -> list[str]:
    return [item["id"] for item in result_refs if item.get("type") == result_type]
