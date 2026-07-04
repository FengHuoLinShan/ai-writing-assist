"""World state assembler — 读正史全量快照, 给 memory 模块用。

替代 world/facade.py:519-618 的 get_full_state。
ADR-0001: producer 拥有状态形状, TypedDict 而非 Pydantic, DB 异常必须传播。
"""

from __future__ import annotations

import uuid
from typing import Protocol, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

# ============================================================
# Cross-seam shape — TypedDict (与 memory.services._apply_events 的 dict 消费习惯一致)
# ============================================================


class WorldStateDict(
    TotalDict := TypedDict(
        "WorldStateDict",
        {  # type: ignore[misc]
            "entities": list[dict],
            "relations": list[dict],
            "character_locations": dict[str, dict],
            "character_knowledge": list[dict],
        },
    )
):
    pass


# ============================================================
# Source seam — 真 adapter (production + test fake)
# ============================================================


class StateSource(Protocol):
    """assemble() 拉数据的 4 路访问口。

    Adapter 必须满足:
      - list_canonical_entities 返仅 status='canonical' 的实体
      - list_canonical_relations 返仅 status='canonical' 的关系
      - list_characters 返所有 character (location 在 meta 里)
      - list_character_knowledge 返所有 knowledge (不限 status)
    """

    async def list_canonical_entities(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int,
        limit: int,
    ) -> list: ...

    async def list_canonical_relations(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int,
        limit: int,
    ) -> list: ...

    async def list_characters(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int,
        limit: int,
    ) -> list: ...

    async def list_character_knowledge(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int,
        limit: int,
    ) -> list: ...


class SqlAlchemyStateSource:
    """生产 source — 包 4 个真实 repo。canonical 过滤在 source 层统一负责。"""

    def __init__(self) -> None:
        from modules.world.repositories import (
            CharacterKnowledgeRepository,
            CharacterRepository,
            CoreEntityRepository,
            EntityRelationRepository,
        )

        self._entity_repo = CoreEntityRepository()
        self._relation_repo = EntityRelationRepository()
        self._character_repo = CharacterRepository()
        self._knowledge_repo = CharacterKnowledgeRepository()

    async def list_canonical_entities(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int,
        limit: int,
    ) -> list:
        rows = await self._entity_repo.list_by_novel(
            db,
            novel_id,
            status="canonical",
            skip=skip,
            limit=limit,
        )
        return rows

    async def list_canonical_relations(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int,
        limit: int,
    ) -> list:
        # EntityRelationRepository.get_by_novel 不接受 status 参数
        # 必须在 Python 端筛 — 与旧 facade.py:568 行为一致
        rows = await self._relation_repo.list_by_novel(
            db,
            novel_id,
            skip=skip,
            limit=limit,
        )
        return [r for r in rows if r.status == "canonical"]

    async def list_characters(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int,
        limit: int,
    ) -> list:
        # Character 不筛 status — 旧 facade.py:580 行为
        rows = await self._character_repo.list_by_novel(
            db,
            novel_id,
            skip=skip,
            limit=limit,
        )
        return rows

    async def list_character_knowledge(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int,
        limit: int,
    ) -> list:
        # CLAUDE.md §8: DB 异常必须传播, 不允许 try/except: pass
        # 旧 facade.py:595-611 吞掉 knowledge 读失败是 bug, 已修
        rows = await self._knowledge_repo.list_by_novel(
            db,
            novel_id,
            skip=skip,
            limit=limit,
        )
        return rows


def _same_novel_id(value: object, novel_id: uuid.UUID) -> bool:
    """兼容 UUID / str 的 novel_id 比对。"""
    if isinstance(value, uuid.UUID):
        return value == novel_id
    return str(value) == str(novel_id)


class InMemoryStateSource:
    """测试用 source — 直接喂预制 ORM 行, 不走 DB。
    证明 StateSource seam 是真的 (2 个 adapter)。

    行为与 SqlAlchemyStateSource 一致:
    - list_canonical_entities 仅返回 status='canonical' 且 novel_id 匹配的行
    - list_canonical_relations 仅返回 status='canonical' 且 novel_id 匹配的行
    - list_characters / list_character_knowledge 仅过滤 novel_id
    """

    def __init__(
        self,
        *,
        entities: list | None = None,
        relations: list | None = None,
        characters: list | None = None,
        knowledge: list | None = None,
    ) -> None:
        # 用 `is not None` 而非 `or` — 空列表是合法输入, 不该被吞
        self._entities = list(entities) if entities is not None else []
        self._relations = list(relations) if relations is not None else []
        self._characters = list(characters) if characters is not None else []
        self._knowledge = list(knowledge) if knowledge is not None else []

    def _filter(
        self,
        rows: list,
        novel_id: uuid.UUID,
        *,
        status: str | None = None,
    ) -> list:
        result = [
            r for r in rows if _same_novel_id(getattr(r, "novel_id", None), novel_id)
        ]
        if status is not None:
            result = [r for r in result if getattr(r, "status", None) == status]
        return result

    async def list_canonical_entities(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int,
        limit: int,
    ) -> list:
        rows = self._filter(self._entities, novel_id, status="canonical")
        return rows[skip : skip + limit]

    async def list_canonical_relations(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int,
        limit: int,
    ) -> list:
        rows = self._filter(self._relations, novel_id, status="canonical")
        return rows[skip : skip + limit]

    async def list_characters(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int,
        limit: int,
    ) -> list:
        rows = self._filter(self._characters, novel_id)
        return rows[skip : skip + limit]

    async def list_character_knowledge(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int,
        limit: int,
    ) -> list:
        rows = self._filter(self._knowledge, novel_id)
        return rows[skip : skip + limit]


# ============================================================
# Default source factory — 单例, 测试可重置
# ============================================================

_default_source: StateSource | None = None


def default_source() -> StateSource:
    """返回默认 source (生产 = SqlAlchemyStateSource 单例)。"""
    global _default_source
    if _default_source is None:
        _default_source = SqlAlchemyStateSource()
    return _default_source


def set_default_source(source: StateSource | None) -> None:
    """显式设置默认 source。传 None 等价于 reset。

    测试用: `set_default_source(InMemoryStateSource(...))` 走内存路径。
    """
    global _default_source
    _default_source = source


def reset_default_source() -> None:
    """清空默认 source, 下次 default_source() 重建生产实例。"""
    global _default_source
    _default_source = None


# ============================================================
# Public entry — assemble()
# ============================================================

_MAX_ENTITIES_PER_SNAPSHOT = 10_000
_MAX_RELATIONS_PER_SNAPSHOT = 10_000
_MAX_KNOWLEDGE_PER_SNAPSHOT = 50_000


async def assemble(db: AsyncSession, novel_id: str) -> WorldStateDict:
    """装配当前 novel 的正史世界状态。

    Invariants:
      - entities: 仅 status='canonical' 的 CoreEntity
      - relations: 仅 status='canonical' 的 EntityRelation
      - character_locations: 从 Character.meta 提取, 无 location_id 不入 dict
      - character_knowledge: 所有 knowledge 记录, status 不限
      - novel_id 必须传合法 UUID 字符串
      - DB 异常直接向上抛, 不吞 (CLAUDE.md §8)
      - importance=0.0 等零值字段保留 (CLAUDE.md §5)
    """
    nid = uuid.UUID(hex=novel_id)
    source = default_source()

    entity_rows = await source.list_canonical_entities(
        db,
        nid,
        skip=0,
        limit=_MAX_ENTITIES_PER_SNAPSHOT,
    )
    entities = [
        {
            "id": str(e.id),
            "entity_type": e.entity_type,
            "name": e.name,
            "summary": e.summary,
            "public_info": e.public_info,
            "hidden_truth": e.hidden_truth,
            "content_json": e.content_json,
            "importance": e.importance,
            "importance_level": e.importance_level,
            "reveal_level": e.reveal_level,
            "status": e.status,
        }
        for e in entity_rows
    ]

    relation_rows = await source.list_canonical_relations(
        db,
        nid,
        skip=0,
        limit=_MAX_RELATIONS_PER_SNAPSHOT,
    )
    relations = [
        {
            "id": str(r.id),
            "source_id": str(r.source_id),
            "target_id": str(r.target_id),
            "relation_type": r.relation_type,
            "description": r.description,
            "strength": r.strength,
            "status": r.status,
        }
        for r in relation_rows
    ]

    character_rows = await source.list_characters(
        db,
        nid,
        skip=0,
        limit=_MAX_ENTITIES_PER_SNAPSHOT,
    )
    character_locations: dict[str, dict] = {}
    for c in character_rows:
        meta = c.meta or {}
        loc = meta.get("location_id")
        if loc:
            character_locations[str(c.entity_id)] = {
                "location_id": str(loc) if not isinstance(loc, str) else loc,
                "text_state": meta.get("text_state", ""),
                "chapter_index": meta.get("chapter_index"),
            }

    knowledge_rows = await source.list_character_knowledge(
        db,
        nid,
        skip=0,
        limit=_MAX_KNOWLEDGE_PER_SNAPSHOT,
    )
    character_knowledge = [
        {
            "id": str(k.id),
            "character_id": str(k.character_id),
            "target_type": k.target_type,
            "target_id": str(k.target_id) if k.target_id else None,
            "knowledge_level": k.knowledge_level,
            "known_content": k.known_content,
            "source_chapter_index": k.source_chapter_index,
            "status": k.status,
        }
        for k in knowledge_rows
    ]

    return WorldStateDict(
        entities=entities,
        relations=relations,
        character_locations=character_locations,
        character_knowledge=character_knowledge,
    )
