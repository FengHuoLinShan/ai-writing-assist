"""
Memory Facade — 对外入口

其他模块只能从 facade 导入。
Facade 不写复杂业务逻辑，只做稳定的对外代理。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.memory.schemas import (
    MemoryRecordContext,
    MemoryUpdateProposalContext,
)
from modules.memory.services import MemoryService

_service = MemoryService()


async def get_recent_story_memory(
    db: AsyncSession,
    novel_id: str,
    before_chapter_index: int | None = None,
    limit: int = 8,
    reveal_mode: str = "author_safe",
) -> list[MemoryRecordContext]:
    """获取最近的故事记忆

    用于 Context Compiler 提供当前剧情前的记忆摘要。
    只返回 status='canonical' 的记忆记录，按章节倒序排列。
    在 author_safe 模式下过滤 reader_know 级别的条目。

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        before_chapter_index: 只返回该章节之前的记忆
        limit: 最大返回条数（默认 8）
        reveal_mode: author_only / author_safe（默认 author_safe）

    Returns:
        list[MemoryRecordContext]: 记忆记录上下文列表
    """
    records = await _service.get_recent_story_memory(
        db, novel_id, before_chapter_index, limit
    )
    # author_safe 模式下过滤 visibility 为 author_only 的记录
    if reveal_mode == "author_safe":
        records = [
            r
            for r in records
            if getattr(r, "visibility", "reader_known") != "author_only"
        ]
    return records


async def get_entity_memory(
    db: AsyncSession,
    novel_id: str,
    entity_id: str,
    limit: int = 20,
) -> list[MemoryRecordContext]:
    """获取与某实体关联的记忆记录

    通过 related_entity_ids JSONB 字段匹配。

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        entity_id: 世界对象 ID
        limit: 最大返回条数（默认 20）

    Returns:
        list[MemoryRecordContext]: 关联的记忆记录列表
    """
    return await _service.get_entity_memory(db, novel_id, entity_id, limit)


async def create_memory_update_proposals(
    db: AsyncSession,
    novel_id: str,
    source_type: str,
    source_id: str,
    extraction_result: dict[str, Any],
) -> list[MemoryUpdateProposalContext]:
    """从 AI 抽取结果创建记忆更新提案

    典型流程：用户写正文 → 状态抽取 Prompt → 本函数 → proposals 待确认

    Args:
        db: 数据库 session
        novel_id: 项目 ID
        source_type: 来源类型（如 chapter_text, outline_change）
        source_id: 来源 ID
        extraction_result: AI 抽取结果，格式见 services.py

    Returns:
        list[MemoryUpdateProposalContext]: 创建的记忆提案列表
    """
    return await _service.create_memory_update_proposals(
        db, novel_id, source_type, source_id, extraction_result
    )


async def confirm_memory_proposal(
    db: AsyncSession,
    proposal_id: str,
    novel_id: str,
    edited_payload: dict[str, Any] | None = None,
    decided_by: str | None = None,
) -> MemoryRecordContext:
    """确认记忆提案，写入 canonical memory

    Args:
        db: 数据库 session
        proposal_id: 提案 ID
        novel_id: 项目 ID
        edited_payload: 编辑后的 payload（可选）
        decided_by: 决策者标识

    Returns:
        MemoryRecordContext: 创建的正史记忆记录
    """
    return await _service.confirm_memory_proposal(
        db, proposal_id, novel_id, edited_payload, decided_by
    )
