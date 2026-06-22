"""跨模块共享测试工厂函数。

供测试文件直接导入的轻量级工厂，不依赖 pytest fixture。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import StructureContextBundle
from modules.project.models import Project
from modules.world.models import CoreEntity


async def _create_project(db_session: AsyncSession, novel_id: str | uuid.UUID) -> None:
    """创建测试项目（外键约束需要）。

    novel_id 支持 hex 字符串或 uuid.UUID 对象。
    """
    if isinstance(novel_id, uuid.UUID):
        pid = novel_id
    else:
        pid = uuid.UUID(hex=novel_id)
    project = Project(
        id=pid,
        title="测试项目",
        genre="fantasy",
        language="zh",
        target_length="novel",
        current_stage="worldbuilding",
    )
    db_session.add(project)
    await db_session.flush()


async def _create_entity(
    db_session: AsyncSession,
    novel_id: str | uuid.UUID,
    entity_type: str,
    name: str,
    *,
    status: str = "canonical",
    summary: str | None = None,
) -> CoreEntity:
    """创建一个任意类型的 CoreEntity，返回对象。

    novel_id 支持 hex 字符串或 uuid.UUID 对象。
    """
    if isinstance(novel_id, uuid.UUID):
        nid = novel_id
    else:
        nid = uuid.UUID(hex=novel_id)
    entity = CoreEntity(
        id=uuid.uuid4(),
        novel_id=nid,
        entity_type=entity_type,
        name=name,
        status=status,
        summary=summary,
    )
    db_session.add(entity)
    await db_session.flush()
    return entity


def _make_bundle(novel_id: str) -> StructureContextBundle:
    """构造 outline 结构上下文 bundle。"""
    return StructureContextBundle(
        novel_id=novel_id,
        task="测试生成",
        scope="full",
        project={
            "id": novel_id,
            "title": "测试小说",
            "genre": "仙侠",
            "tone": "正剧",
        },
        world_entities=[
            {"name": "霜华剑", "entity_type": "item", "summary": "上古神剑"},
        ],
        characters=[
            {"name": "白砚", "role": "protagonist", "desire": "寻找真相"},
        ],
    )


async def _mock_segment(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
    **kwargs: Any,
) -> dict[str, Any]:
    """DeepImportWorkflow Phase 1 mock（成功）。"""
    return {"total_scenes": 5, "failed_batches": [], "degraded": False}


async def _mock_extract(
    db: AsyncSession,
    novel_id: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """DeepImportWorkflow Phase 2 mock（成功）。"""
    return {"total_created": 3, "total_deltas": 2}


async def _mock_extract_fail(
    db: AsyncSession,
    novel_id: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """DeepImportWorkflow Phase 2 mock（失败降级）。"""
    return {"total_created": 0, "total_deltas": 0}


async def _mock_analyze(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
) -> dict[str, Any]:
    """DeepImportWorkflow Phase 3 mock（成功）。"""
    return {
        "total_threads": 2,
        "total_arcs": 1,
        "threads": [],
        "arcs": [],
        "extra_sections": {},
    }
