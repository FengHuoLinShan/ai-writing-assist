"""Character 任务处理器"""

from __future__ import annotations

import asyncio
import logging

from infrastructure.tasks.registry import task_handler
from shared.constants import LLM_RETRY_BASE_DELAY, LLM_RETRY_MAX_ATTEMPTS

logger = logging.getLogger(__name__)

# 人物档案字段中可由 AI 抽取的部分
_EXTRACTABLE_FIELDS = [
    "desire", "fear", "secret", "weakness",
    "current_goal", "current_state", "current_emotion",
    "stance", "voice_style", "role",
]

# 每个字段的意图查询关键词
_FIELD_QUERIES = {
    "role": "角色定位 主角 反派 配角",
    "desire": "渴望 目标 欲望 追求 动机",
    "fear": "恐惧 害怕 软肋 畏惧 担忧",
    "secret": "秘密 隐藏 隐瞒 不为人知",
    "weakness": "弱点 缺陷 不足 短板 致命伤",
    "current_goal": "当前目标 短期目标 计划 下一步",
    "current_state": "当前状态 处境 状况 现状",
    "current_emotion": "情绪 心情 感受 态度",
    "stance": "立场 态度 看法 观点 倾向",
    "voice_style": "语言风格 说话方式 口吻 语气",
}


async def _collect_character_chunks(
    db,
    novel_id: str,
    character_id: str,
    character_name: str,
) -> tuple[list[str], list[str]]:
    """按人物和字段意图从 RAG 收集正文片段。"""
    from modules.rag.facade import retrieve as _rag_retrieve

    all_chunks_text: list[str] = []
    warnings: list[str] = []
    for query_keywords in _FIELD_QUERIES.values():
        query = f"{character_name} {query_keywords}"
        try:
            result = await _rag_retrieve(
                db, novel_id, query,
                character_ids=[character_id],
                mode="extraction",
                top_k=5,
            )
            if result.total == 0:
                result = await _rag_retrieve(
                    db, novel_id, query,
                    mode="extraction",
                    top_k=5,
                )
            warnings.extend(result.warnings or [])
            for chunk in result.chunks:
                if chunk.text not in all_chunks_text:
                    all_chunks_text.append(chunk.text)
        except Exception as exc:
            logger.warning("RAG retrieve for %s failed: %s", query, exc)
            warnings.append(f"RAG 检索失败，本次抽取可能不准确: {exc}")
    return all_chunks_text, warnings


async def _index_existing_drafts_for_character(
    db,
    novel_id: str,
    character_name: str,
) -> int:
    """历史导入缺 RAG 时，按角色名补建已有草稿的章节索引。"""
    from modules.rag.facade import index_chapter as _index_chapter
    from modules.writing.facade import (
        get_latest_draft_for_chapter,
        list_chapter_indices,
    )

    indexed = 0
    for chapter_index in await list_chapter_indices(db, novel_id):
        draft = await get_latest_draft_for_chapter(db, novel_id, chapter_index)
        if not draft or not draft.content or character_name not in draft.content:
            continue
        indexed += await _index_chapter(db, novel_id, chapter_index)
    return indexed


@task_handler("character_extract")
async def handle_character_extract(db, task):
    """处理人物档案抽取任务

    对指定角色：
    1. 用 RAG 检索含该角色的章节 chunk
    2. 调用 LLM 按字段抽取档案
    3. 结果写入 characters.meta.ai_suggestions

    Task meta 参数：
    - novel_id: 项目 ID
    - character_id: 角色 ID
    """
    meta = task.meta or {}
    novel_id = meta.get("novel_id", "")
    character_id = meta.get("character_id", "")

    if not novel_id:
        raise ValueError("novel_id is required for character_extract")
    if not character_id:
        raise ValueError("character_id is required for character_extract")

    # 1. 获取角色信息
    from modules.character.facade import list_characters as _list_chars
    from modules.world.facade import get_entity as _get_entity

    chars, _ = await _list_chars(db, novel_id, limit=999)
    character = next((c for c in chars if c.entity_id == character_id), None)
    if not character:
        raise ValueError(f"Character {character_id} not found")

    # 从 CoreEntity 获取 name（Character 扩展表不再持有 name）
    try:
        core = await _get_entity(db, character_id, novel_id)
        character_name = core.name
    except Exception:
        character_name = str(character_id)

    # 2. 用 RAG 检索含该角色的 chunk（逐字段意图查询）
    all_chunks_text, rag_warnings = await _collect_character_chunks(
        db, novel_id, character_id, character_name,
    )

    if not all_chunks_text:
        indexed = await _index_existing_drafts_for_character(
            db, novel_id, character_name,
        )
        if indexed:
            logger.info(
                "Backfilled %d RAG chunks for character %s before extraction",
                indexed, character_name,
            )
            all_chunks_text, retry_warnings = await _collect_character_chunks(
                db, novel_id, character_id, character_name,
            )
            rag_warnings.extend(retry_warnings)

    if not all_chunks_text:
        logger.info("No RAG chunks found for character %s", character_name)
        return {
            "character_id": character_id,
            "status": "no_chunks",
            "fields": [],
            "warnings": rag_warnings,
        }

    chunk_context = "\n\n---\n\n".join(all_chunks_text)

    # 3. 调用 LLM 结构化抽取
    from core.config import get_settings
    from infrastructure.llm.client import LLMClient
    from infrastructure.llm.schemas import LLMCallRequest
    from pydantic import BaseModel

    class _CharacterExtractOutput(BaseModel):
        role: str | None = None
        desire: str | None = None
        fear: str | None = None
        secret: str | None = None
        weakness: str | None = None
        current_goal: str | None = None
        current_state: str | None = None
        current_emotion: str | None = None
        stance: str | None = None
        voice_style: str | None = None

    existing_info = "\n".join(
        f"{f}: {getattr(character, f, '') or '(空)'}"
        for f in _EXTRACTABLE_FIELDS
    )

    from infrastructure.llm.prompt_loader import load_prompt

    system_prompt = load_prompt("extract_character",
        character_name=character_name,
        existing_info=existing_info,
    )

    settings = get_settings()
    request = LLMCallRequest(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": chunk_context},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )

    llm = LLMClient()
    extract_result = None
    for attempt in range(LLM_RETRY_MAX_ATTEMPTS):
        try:
            extract_result = await llm.generate_structured(request, _CharacterExtractOutput)
            break
        except Exception as exc:
            if attempt < LLM_RETRY_MAX_ATTEMPTS - 1:
                delay = LLM_RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "LLM extraction attempt %d/%d failed for %s, retrying in %.1fs: %s",
                    attempt + 1, LLM_RETRY_MAX_ATTEMPTS, character_name, delay, exc,
                )
                await asyncio.sleep(delay)
            else:
                logger.error("LLM extraction failed for %s after %d attempts: %s", character_name, LLM_RETRY_MAX_ATTEMPTS, exc)
                return {
                    "character_id": character_id,
                    "status": "llm_failed",
                    "error": str(exc),
                    "warnings": rag_warnings + ["LLM 抽取失败，本次生成人物档案可能不准确"],
                }

    if extract_result is None:
        return {
            "character_id": character_id,
            "status": "llm_failed",
            "error": "No result after retries",
            "warnings": rag_warnings + ["LLM 抽取失败，本次生成人物档案可能不准确"],
        }

    # 4. 构建 ai_suggestions
    suggestions = {}
    for field in _EXTRACTABLE_FIELDS:
        value = getattr(extract_result, field, None)
        if value:
            suggestions[field] = value

    # 5. 保存到 characters.meta.ai_suggestions
    from modules.character.services import CharacterService

    char_service = CharacterService()
    from modules.character.schemas import CharacterUpdate

    # 读取当前 meta
    char = await char_service.get_character(db, character_id, novel_id=novel_id)
    current_meta = dict(char.meta or {})
    current_meta["ai_suggestions"] = suggestions
    current_meta["ai_suggestions_at"] = (await _now_iso())

    update_data = CharacterUpdate(meta=current_meta)
    await char_service.update_character(db, character_id, update_data, novel_id=novel_id)
    await db.flush()

    logger.info(
        "Extracted %d fields for character %s: %s",
        len(suggestions), character_name, list(suggestions.keys()),
    )

    return {
        "character_id": character_id,
        "status": "ok",
        "fields": list(suggestions.keys()),
        "warnings": rag_warnings,
    }


async def _now_iso() -> str:
    """返回当前时间的 ISO 格式字符串"""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
