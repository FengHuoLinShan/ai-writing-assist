"""
World 数据访问层 — v3 因果时空网

封装所有表的基本数据库操作。
只处理 ORM ↔ DB 的基本 CRUD，不含业务逻辑。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections import OrderedDict
from collections.abc import Sequence
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import Text, and_, case, delete, exists, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

_RELATION_UPSERT_LOCK_MAXSIZE = 4096
_RELATION_UPSERT_LOCKS: OrderedDict[
    tuple[str, str, str, str, str],
    asyncio.Lock,
] = OrderedDict()


def _relation_upsert_lock(key: tuple[str, str, str, str, str]) -> asyncio.Lock:
    lock = _RELATION_UPSERT_LOCKS.get(key)
    if lock is not None:
        _RELATION_UPSERT_LOCKS.move_to_end(key)
        return lock

    lock = asyncio.Lock()
    _RELATION_UPSERT_LOCKS[key] = lock
    while len(_RELATION_UPSERT_LOCKS) > _RELATION_UPSERT_LOCK_MAXSIZE:
        old_key, old_lock = next(iter(_RELATION_UPSERT_LOCKS.items()))
        if old_lock.locked():
            _RELATION_UPSERT_LOCKS.move_to_end(old_key)
            if all(item.locked() for item in _RELATION_UPSERT_LOCKS.values()):
                break
            continue
        _RELATION_UPSERT_LOCKS.popitem(last=False)
    return lock


from modules.world.models import (  # noqa: E402
    Character,
    CharacterKnowledge,
    CoreEntity,
    EntityRelation,
    EntityRevision,
    Event,
)
from modules.world.schemas import (  # noqa: E402
    CharacterCreate,
    CharacterKnowledgeCreate,
    CharacterKnowledgeUpdate,
    CharacterUpdate,
    CoreEntityCreate,
    CoreEntityUpdate,
    EntityRelationCreate,
    EntityRelationUpdate,
    EventCreate,
    EventUpdate,
)
from shared.constants import DEFAULT_PAGE_SIZE  # noqa: E402
from shared.utils import parse_uuid  # noqa: E402

# ============================================================
# CoreEntityRepository
# ============================================================


class CoreEntityRepository:
    """核心实体数据访问"""

    @staticmethod
    def _aliases_text_expression():
        """只搜索别名，不能让导入证据等任意 JSON 元数据污染结果。"""
        return CoreEntity.content_json["aliases"].cast(Text)

    def _entity_search_rank(self, query: str | None):
        """将名称和别名命中稳定排在描述命中之前。"""
        if not query or not (normalized := query.strip()):
            return None
        like_expr = f"%{normalized}%"
        aliases_text = self._aliases_text_expression()
        description_match = or_(
            CoreEntity.summary.ilike(like_expr),
            CoreEntity.public_info.ilike(like_expr),
            CoreEntity.hidden_truth.ilike(like_expr),
        )
        return case(
            (CoreEntity.name == normalized, 4),
            (CoreEntity.name.ilike(like_expr), 3),
            (aliases_text.ilike(like_expr), 2),
            (description_match, 1),
            else_=0,
        )

    @staticmethod
    def _alias_texts(entity: CoreEntity) -> list[str]:
        aliases = (entity.content_json or {}).get("aliases") or []
        texts: list[str] = []
        for alias in aliases:
            value = alias.get("alias") if isinstance(alias, dict) else alias
            if value is not None and str(value).strip():
                texts.append(str(value).strip())
        return texts

    async def _fuzzy_entities_by_novel(
        self,
        db: AsyncSession,
        *,
        conditions: list[Any],
        query: str,
        skip: int,
        limit: int,
    ) -> tuple[list[CoreEntity], int]:
        """没有直接命中时，按名称/别名提供容错检索。"""
        normalized = query.strip()
        if len(normalized) < 2:
            return [], 0

        aliases_text = self._aliases_text_expression()
        min_similarity = 0.6 if len(normalized) == 2 else 0.45
        bind = db.get_bind()
        if bind.dialect.name == "postgresql":
            name_similarity = func.similarity(CoreEntity.name, normalized)
            alias_similarity = func.similarity(
                func.coalesce(aliases_text, ""), normalized
            )
            similarity = func.greatest(name_similarity, alias_similarity)
            fuzzy_conditions = [*conditions, similarity >= min_similarity]
            try:
                connection = await db.connection()
                async with connection.begin_nested():
                    count_result = await db.execute(
                        select(func.count(CoreEntity.id)).where(*fuzzy_conditions)
                    )
                    total = count_result.scalar() or 0
                    stmt = (
                        select(CoreEntity)
                        .where(*fuzzy_conditions)
                        .order_by(
                            similarity.desc(),
                            CoreEntity.importance.desc(),
                            CoreEntity.name,
                            CoreEntity.id,
                        )
                        .offset(skip)
                        .limit(limit)
                    )
                    result = await db.execute(stmt)
                    items = list(result.scalars().all())
                return items, total
            except (OperationalError, ProgrammingError):
                logger.warning(
                    "pg_trgm fuzzy entity search unavailable, falling back to Python"
                )

        result = await db.execute(select(CoreEntity).where(*conditions))
        candidates: Sequence[CoreEntity] = result.scalars().all()
        scored: list[tuple[CoreEntity, float]] = []
        normalized_casefold = normalized.casefold()
        for entity in candidates:
            score = max(
                (
                    SequenceMatcher(None, normalized_casefold, value.casefold()).ratio()
                    for value in [entity.name, *self._alias_texts(entity)]
                    if value
                ),
                default=0.0,
            )
            if score >= min_similarity:
                scored.append((entity, score))
        scored.sort(
            key=lambda item: (
                -item[1],
                -(
                    item[0].importance
                    if item[0].importance is not None
                    else 0
                ),
                item[0].name,
                str(item[0].id),
            )
        )
        return [entity for entity, _score in scored[skip : skip + limit]], len(scored)

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: CoreEntityCreate,
    ) -> CoreEntity:
        entity = CoreEntity(
            novel_id=novel_id,
            entity_type=data.entity_type,
            name=data.name,
            summary=data.summary,
            public_info=data.public_info,
            hidden_truth=data.hidden_truth,
            content_json=data.content_json or {},
            importance=data.importance if data.importance is not None else 0.5,
            importance_level=data.importance_level or "normal",
            reveal_level=data.reveal_level or "author_only",
            status=data.status or "canonical",
            created_by=data.created_by,
            approved_by=data.approved_by,
        )
        db.add(entity)
        await db.flush()
        return entity

    async def create_raw(
        self,
        db: AsyncSession,
        *,
        novel_id: uuid.UUID,
        entity_type: str,
        name: str,
        summary: str | None = None,
        content_json: dict | None = None,
        status: str = "canonical",
    ) -> CoreEntity:
        entity = CoreEntity(
            novel_id=novel_id,
            entity_type=entity_type,
            name=name,
            summary=summary,
            content_json=content_json or {},
            status=status,
        )
        db.add(entity)
        await db.flush()
        return entity

    async def get(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
    ) -> CoreEntity | None:
        stmt = select(CoreEntity).where(CoreEntity.id == entity_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_for_update(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
        *,
        novel_id: uuid.UUID | None = None,
    ) -> CoreEntity | None:
        conditions = [CoreEntity.id == entity_id]
        if novel_id is not None:
            conditions.append(CoreEntity.novel_id == novel_id)
        result = await db.execute(
            select(CoreEntity)
            .where(*conditions)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def get_many_for_update(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_ids: Sequence[uuid.UUID],
    ) -> list[CoreEntity]:
        """Lock project entities in one deterministic UUID order."""
        unique_ids = sorted(set(entity_ids), key=str)
        if not unique_ids:
            return []
        result = await db.execute(
            select(CoreEntity)
            .where(
                CoreEntity.novel_id == novel_id,
                CoreEntity.id.in_(unique_ids),
            )
            .order_by(CoreEntity.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    def _entity_conditions(
        self,
        novel_id: uuid.UUID,
        *,
        entity_type: str | None = None,
        status: str | None = None,
        display_state: str | None = None,
        q: str | None = None,
        source: str | None = None,
        workflow_id: str | None = None,
        needs_review: bool | None = None,
        auto_ingested: bool | None = None,
        suggested_action: str | None = None,
        scene_id: str | None = None,
        scene_index: int | None = None,
        source_chapter_index: int | None = None,
        confidence_min: float | None = None,
        confidence_max: float | None = None,
        include_archived: bool = False,
    ) -> list[Any]:
        conditions = [CoreEntity.novel_id == novel_id]
        if entity_type:
            conditions.append(CoreEntity.entity_type == entity_type)
        if status:
            conditions.append(CoreEntity.status == status)
        elif display_state is None and not include_archived:
            from modules.world.asset_state import ARCHIVED_DISPLAY_STATUSES

            conditions.append(CoreEntity.status.not_in(tuple(ARCHIVED_DISPLAY_STATUSES)))
        if display_state is not None:
            from modules.world.asset_state import statuses_for_display_state

            display_statuses = statuses_for_display_state(display_state)
            if display_statuses:
                conditions.append(CoreEntity.status.in_(tuple(display_statuses)))
        if q:
            query = q.strip()
            if query:
                like_expr = f"%{query}%"
                aliases_text = self._aliases_text_expression()
                conditions.append(
                    or_(
                        CoreEntity.name.ilike(like_expr),
                        aliases_text.ilike(like_expr),
                        CoreEntity.summary.ilike(like_expr),
                        CoreEntity.public_info.ilike(like_expr),
                        CoreEntity.hidden_truth.ilike(like_expr),
                    )
                )
        if source:
            conditions.append(
                CoreEntity.content_json["_meta"]["source"].as_string() == source
            )
        if workflow_id:
            conditions.append(
                CoreEntity.content_json["_meta"]["workflow_id"].as_string() == workflow_id
            )
        if needs_review is not None:
            conditions.append(
                CoreEntity.content_json["_meta"]["needs_review"].as_boolean()
                == needs_review
            )
        if auto_ingested is not None:
            conditions.append(
                CoreEntity.content_json["_meta"]["auto_ingested"].as_boolean()
                == auto_ingested
            )
        if suggested_action:
            conditions.append(
                CoreEntity.content_json["_meta"]["suggested_action"].as_string()
                == suggested_action
            )
        if scene_id:
            conditions.append(
                CoreEntity.content_json["_meta"]["scene_id"].as_string() == scene_id
            )
        if scene_index is not None:
            conditions.append(
                CoreEntity.content_json["_meta"]["scene_index"].as_integer()
                == scene_index
            )
        if source_chapter_index is not None:
            conditions.append(
                CoreEntity.content_json["_meta"]["source_chapter_index"].as_integer()
                == source_chapter_index
            )
        if confidence_min is not None:
            conditions.append(
                CoreEntity.content_json["_meta"]["confidence"].as_float()
                >= confidence_min
            )
        if confidence_max is not None:
            conditions.append(
                CoreEntity.content_json["_meta"]["confidence"].as_float()
                <= confidence_max
            )
        return conditions

    async def list_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        entity_type: str | None = None,
        status: str | None = None,
        display_state: str | None = None,
        q: str | None = None,
        source: str | None = None,
        workflow_id: str | None = None,
        needs_review: bool | None = None,
        auto_ingested: bool | None = None,
        suggested_action: str | None = None,
        scene_id: str | None = None,
        scene_index: int | None = None,
        source_chapter_index: int | None = None,
        confidence_min: float | None = None,
        confidence_max: float | None = None,
        include_archived: bool = False,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[CoreEntity]:
        conditions = self._entity_conditions(
            novel_id,
            entity_type=entity_type,
            status=status,
            display_state=display_state,
            q=q,
            source=source,
            workflow_id=workflow_id,
            needs_review=needs_review,
            auto_ingested=auto_ingested,
            suggested_action=suggested_action,
            scene_id=scene_id,
            scene_index=scene_index,
            source_chapter_index=source_chapter_index,
            confidence_min=confidence_min,
            confidence_max=confidence_max,
            include_archived=include_archived,
        )
        stmt = select(CoreEntity).where(*conditions).offset(skip).limit(limit)
        rank = self._entity_search_rank(q)
        if rank is not None:
            stmt = stmt.order_by(rank.desc())
        stmt = stmt.order_by(CoreEntity.importance.desc(), CoreEntity.name, CoreEntity.id)
        result = await db.execute(stmt)
        items: Sequence[CoreEntity] = result.scalars().all()
        return list(items)

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        entity_type: str | None = None,
        status: str | None = None,
        display_state: str | None = None,
        q: str | None = None,
        source: str | None = None,
        workflow_id: str | None = None,
        needs_review: bool | None = None,
        auto_ingested: bool | None = None,
        suggested_action: str | None = None,
        scene_id: str | None = None,
        scene_index: int | None = None,
        source_chapter_index: int | None = None,
        confidence_min: float | None = None,
        confidence_max: float | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[CoreEntity], int]:
        conditions = self._entity_conditions(
            novel_id,
            entity_type=entity_type,
            status=status,
            display_state=display_state,
            q=q,
            source=source,
            workflow_id=workflow_id,
            needs_review=needs_review,
            auto_ingested=auto_ingested,
            suggested_action=suggested_action,
            scene_id=scene_id,
            scene_index=scene_index,
            source_chapter_index=source_chapter_index,
            confidence_min=confidence_min,
            confidence_max=confidence_max,
        )

        count_stmt = select(func.count(CoreEntity.id)).where(*conditions)
        count_result = await db.execute(count_stmt)
        total = count_result.scalar() or 0
        if total == 0 and q and q.strip():
            fuzzy_conditions = self._entity_conditions(
                novel_id,
                entity_type=entity_type,
                status=status,
                display_state=display_state,
                source=source,
                workflow_id=workflow_id,
                needs_review=needs_review,
                auto_ingested=auto_ingested,
                suggested_action=suggested_action,
                scene_id=scene_id,
                scene_index=scene_index,
                source_chapter_index=source_chapter_index,
                confidence_min=confidence_min,
                confidence_max=confidence_max,
            )
            return await self._fuzzy_entities_by_novel(
                db,
                conditions=fuzzy_conditions,
                query=q,
                skip=skip,
                limit=limit,
            )

        items = await self.list_by_novel(
            db,
            novel_id,
            entity_type=entity_type,
            status=status,
            display_state=display_state,
            q=q,
            source=source,
            workflow_id=workflow_id,
            needs_review=needs_review,
            auto_ingested=auto_ingested,
            suggested_action=suggested_action,
            scene_id=scene_id,
            scene_index=scene_index,
            source_chapter_index=source_chapter_index,
            confidence_min=confidence_min,
            confidence_max=confidence_max,
            skip=skip,
            limit=limit,
        )
        return items, total

    async def list_ranking_candidates(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        entity_type: str | None = None,
        status: str | None = None,
        display_state: str | None = None,
        q: str | None = None,
        source: str | None = None,
        workflow_id: str | None = None,
        needs_review: bool | None = None,
        auto_ingested: bool | None = None,
        suggested_action: str | None = None,
        scene_id: str | None = None,
        scene_index: int | None = None,
        source_chapter_index: int | None = None,
        confidence_min: float | None = None,
        confidence_max: float | None = None,
    ) -> list[dict[str, Any]]:
        """Load only scalar fields needed for project-wide smart ranking."""
        conditions = self._entity_conditions(
            novel_id,
            entity_type=entity_type,
            status=status,
            display_state=display_state,
            q=q,
            source=source,
            workflow_id=workflow_id,
            needs_review=needs_review,
            auto_ingested=auto_ingested,
            suggested_action=suggested_action,
            scene_id=scene_id,
            scene_index=scene_index,
            source_chapter_index=source_chapter_index,
            confidence_min=confidence_min,
            confidence_max=confidence_max,
        )
        rank = self._entity_search_rank(q)
        columns = [
            CoreEntity.id.label("id"),
            CoreEntity.entity_type.label("entity_type"),
            CoreEntity.name.label("name"),
            CoreEntity.importance.label("importance"),
            CoreEntity.importance_level.label("importance_level"),
        ]
        if rank is not None:
            columns.append(rank.label("search_rank"))
        stmt = select(*columns).where(*conditions)
        result = await db.execute(stmt)
        rows = [dict(row) for row in result.mappings().all()]
        if rows or not q or not q.strip():
            return rows

        fuzzy_conditions = self._entity_conditions(
            novel_id,
            entity_type=entity_type,
            status=status,
            display_state=display_state,
            source=source,
            workflow_id=workflow_id,
            needs_review=needs_review,
            auto_ingested=auto_ingested,
            suggested_action=suggested_action,
            scene_id=scene_id,
            scene_index=scene_index,
            source_chapter_index=source_chapter_index,
            confidence_min=confidence_min,
            confidence_max=confidence_max,
        )
        fuzzy, _total = await self._fuzzy_entities_by_novel(
            db,
            conditions=fuzzy_conditions,
            query=q,
            skip=0,
            limit=10000,
        )
        size = len(fuzzy)
        return [
            {
                "id": entity.id,
                "entity_type": entity.entity_type,
                "name": entity.name,
                "importance": entity.importance,
                "importance_level": entity.importance_level,
                "search_rank": size - index,
            }
            for index, entity in enumerate(fuzzy)
        ]

    async def get_by_ids(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_ids: list[uuid.UUID],
        *,
        statuses: Sequence[str] | None = None,
    ) -> list[CoreEntity]:
        if not entity_ids:
            return []
        conditions = [
            CoreEntity.novel_id == novel_id,
            CoreEntity.id.in_(entity_ids),
        ]
        if statuses:
            conditions.append(CoreEntity.status.in_(tuple(statuses)))
        stmt = select(CoreEntity).where(*conditions)
        result = await db.execute(stmt)
        items: Sequence[CoreEntity] = result.scalars().all()
        return list(items)

    async def get_by_type_and_status(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_type: str | None = None,
        status: str | None = None,
        statuses: Sequence[str] | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[CoreEntity]:
        conditions = [CoreEntity.novel_id == novel_id]
        if entity_type:
            conditions.append(CoreEntity.entity_type == entity_type)
        if status:
            conditions.append(CoreEntity.status == status)
        if statuses:
            conditions.append(CoreEntity.status.in_(tuple(statuses)))

        stmt = (
            select(CoreEntity)
            .where(*conditions)
            .limit(limit)
            .order_by(CoreEntity.importance.desc(), CoreEntity.id)
        )
        result = await db.execute(stmt)
        items: Sequence[CoreEntity] = result.scalars().all()
        return list(items)

    async def list_distinct_entity_types(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> list[str]:
        result = await db.execute(
            select(CoreEntity.entity_type)
            .where(CoreEntity.novel_id == novel_id)
            .distinct()
            .order_by(CoreEntity.entity_type)
        )
        return [value for value in result.scalars().all() if value]

    async def update(
        self,
        db: AsyncSession,
        entity_or_id: CoreEntity | uuid.UUID,
        data: CoreEntityUpdate,
    ) -> CoreEntity | None:
        entity = (
            await self.get(db, entity_or_id)
            if isinstance(entity_or_id, uuid.UUID)
            else entity_or_id
        )
        if entity is None:
            return None

        update_values: dict[str, Any] = {}
        for field in (
            "entity_type",
            "name",
            "summary",
            "public_info",
            "hidden_truth",
            "importance",
            "importance_level",
            "reveal_level",
            "status",
            "approved_by",
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        if data.content_json is not None:
            update_values["content_json"] = data.content_json

        if update_values:
            for field, value in update_values.items():
                setattr(entity, field, value)
            db.add(entity)
            await db.flush()

        return entity

    async def delete(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
    ) -> bool:
        stmt = delete(CoreEntity).where(CoreEntity.id == entity_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

    async def count_entities(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        status_filter: list[str] | None = None,
    ) -> int:
        """统计指定 novel 的 CoreEntity 数量。"""
        conditions = [CoreEntity.novel_id == novel_id]
        if status_filter:
            conditions.append(CoreEntity.status.in_(status_filter))
        stmt = select(func.count(CoreEntity.id)).where(*conditions)
        result = await db.execute(stmt)
        return result.scalar() or 0

    async def deprecate_deep_import_entities_by_workflow(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        workflow_id: str,
    ) -> int:
        """Soft-deprecate auto-ingested entities from one deep import workflow."""
        stmt = select(CoreEntity).where(
            CoreEntity.novel_id == novel_id,
            CoreEntity.status.in_(["candidate", "proposal", "draft", "canonical"]),
            CoreEntity.content_json["_meta"]["source"].as_string() == "deep_import",
            CoreEntity.content_json["_meta"]["workflow_id"].as_string() == workflow_id,
            CoreEntity.content_json["_meta"]["auto_ingested"].as_boolean().is_(True),
            CoreEntity.content_json["_meta"]["user_edited"].as_boolean().is_not(True),
        )
        result = await db.execute(stmt)
        entities: Sequence[CoreEntity] = result.scalars().all()

        deprecated = 0
        for entity in entities:
            content_json = entity.content_json or {}
            meta = content_json.get("_meta") or {}
            if not (
                meta.get("workflow_id") == workflow_id
                and meta.get("auto_ingested") is True
                and meta.get("source") == "deep_import"
                and meta.get("user_edited") is not True
            ):
                continue
            updated_content_json = {
                **content_json,
                "_meta": {
                    **meta,
                    "cleanup_status": "deprecated",
                    "cleanup_reason": "abandoned_deep_import_recovery",
                },
            }
            entity.status = "deprecated"
            entity.content_json = updated_content_json
            db.add(entity)
            deprecated += 1

        if deprecated:
            await db.flush()
        return deprecated

    async def find_entity_by_name(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        name: str,
        entity_type: str | None = None,
    ) -> str | None:
        conditions = [
            CoreEntity.novel_id == novel_id,
            CoreEntity.name == name,
            CoreEntity.status == "canonical",
        ]
        if entity_type:
            conditions.append(CoreEntity.entity_type == entity_type)
        stmt = select(CoreEntity.id).where(*conditions).limit(1)
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()
        if row is not None:
            return str(row)
        return None

    async def find_by_name_fuzzy(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        name: str,
        entity_type: str | None = None,
    ) -> list[CoreEntity]:
        """模糊名称搜索（使用 LIKE）"""
        conditions = [
            CoreEntity.novel_id == novel_id,
            CoreEntity.name.ilike(f"%{name}%"),
            CoreEntity.status == "canonical",
        ]
        if entity_type:
            conditions.append(CoreEntity.entity_type == entity_type)
        stmt = (
            select(CoreEntity)
            .where(*conditions)
            .limit(10)
            .order_by(CoreEntity.importance.desc(), CoreEntity.id)
        )
        result = await db.execute(stmt)
        items: Sequence[CoreEntity] = result.scalars().all()
        return list(items)

    async def find_similar_by_search_text(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        query_name: str,
        *,
        entity_type: str | None = None,
        status_filter: list[str] | None = None,
        min_similarity: float = 0.4,
        top_k: int = 50,
    ) -> list[tuple[CoreEntity, float]]:
        """使用 pg_trgm similarity() 对 search_text 虚拟列做模糊匹配。

        search_text 是虚拟生成列（name + content_json->>'aliases'），
        一行 similarity() 同时匹配 name 和所有 JSONB 别名。

        SQLite 环境自动回退为 ILIKE + Python 端 difflib 评分。
        """
        statuses = status_filter or ["canonical", "draft"]
        conditions = [
            CoreEntity.novel_id == novel_id,
            CoreEntity.status.in_(statuses),
        ]
        if entity_type:
            conditions.append(CoreEntity.entity_type == entity_type)

        if db.get_bind().dialect.name == "postgresql":
            try:
                connection = await db.connection()
                async with connection.begin_nested():
                    sim_expr = func.similarity(CoreEntity.search_text, query_name)
                    pg_conditions = [*conditions, sim_expr >= min_similarity]
                    stmt = (
                        select(CoreEntity, sim_expr.label("similarity"))
                        .where(*pg_conditions)
                        .order_by(text("similarity DESC"), CoreEntity.id)
                        .limit(top_k)
                    )
                    result = await db.execute(stmt)
                    rows = result.all()
                return [(row[0], float(row[1])) for row in rows]
            except (OperationalError, ProgrammingError):
                logger.warning(
                    "pg_trgm similarity() unavailable, falling back to ILIKE"
                )

        # SQLite / 缺失 pg_trgm 回退：ILIKE name + JSON alias 粗筛
        fallback_conditions = [
            CoreEntity.novel_id == novel_id,
            CoreEntity.status.in_(statuses),
            or_(
                CoreEntity.name.ilike(f"%{query_name}%"),
                # JSON 别名也做 LIKE 匹配（content_json 在 SQLite 中为 Text）
                CoreEntity.content_json.cast(Text).ilike(f"%{query_name}%"),
            ),
        ]
        if entity_type:
            fallback_conditions.append(CoreEntity.entity_type == entity_type)
        stmt = (
            select(CoreEntity)
            .where(*fallback_conditions)
            .limit(top_k)
            .order_by(CoreEntity.importance.desc(), CoreEntity.id)
        )
        result = await db.execute(stmt)
        items: Sequence[CoreEntity] = result.scalars().all()
        return [(entity, 0.0) for entity in items]

    async def find_similar_by_embedding(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        query_embedding: list[float],
        *,
        entity_type: str | None = None,
        status_filter: list[str] | None = None,
        top_k: int = 50,
    ) -> list[tuple[CoreEntity, float]]:
        """使用 pgvector <=> 余弦距离做向量相似度搜索。

        返回余弦相似度（1=完全相同，0=完全无关）。
        无 embedding 的实体自动跳过。
        SQLite 环境返回空列表。
        """
        try:
            statuses = status_filter or ["canonical", "draft"]
            conditions = [
                CoreEntity.novel_id == novel_id,
                CoreEntity.status.in_(statuses),
                CoreEntity.embedding.isnot(None),
            ]
            if entity_type:
                conditions.append(CoreEntity.entity_type == entity_type)

            # Use pgvector's SQLAlchemy comparator so the bind is typed and the
            # selected expression can be labelled on current SQLAlchemy.
            distance = CoreEntity.embedding.cosine_distance(query_embedding)
            stmt = (
                select(
                    CoreEntity,
                    (1.0 - distance).label("similarity"),
                )
                .where(*conditions)
                .order_by(distance, CoreEntity.id)
                .limit(top_k)
            )
            result = await db.execute(stmt)
            rows = result.all()
            return [(row[0], max(0.0, float(row[1]))) for row in rows]
        except (OperationalError, ProgrammingError):
            logger.warning("pgvector embedding search unavailable, returning empty")
            return []

    async def has_embeddings(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> bool:
        """检查该 novel 是否有任何实体已生成 embedding。"""
        try:
            stmt = select(
                exists().where(
                    CoreEntity.novel_id == novel_id,
                    CoreEntity.embedding.isnot(None),
                )
            )
            result = await db.execute(stmt)
            return bool(result.scalar())
        except (OperationalError, ProgrammingError):
            logger.warning("pgvector has_embeddings check failed, returning False")
            return False

    async def get_recent_auto_ingested(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        since: str | None = None,
        limit: int = 50,
    ) -> list[CoreEntity]:
        """查询最近自动入库的实体

        通过 content_json['_meta']['auto_ingested'] 过滤。
        支持 PostgreSQL JSONB 和 SQLite。
        """
        conditions = [
            CoreEntity.novel_id == novel_id,
            CoreEntity.status == "canonical",
            CoreEntity.content_json["_meta"]["auto_ingested"].as_boolean().is_(True),
        ]

        if since:
            conditions.append(CoreEntity.created_at >= since)

        stmt = (
            select(CoreEntity)
            .where(*conditions)
            .order_by(CoreEntity.created_at.desc(), CoreEntity.id.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        items: Sequence[CoreEntity] = result.scalars().all()
        return list(items)

    async def get_entity_batches(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """按批次分组查询自动入库的实体

        返回每个 batch 的概要信息及实体列表。
        SQLite 兼容模式 — 在内存中分组。
        """
        recent = await self.get_recent_auto_ingested(db, novel_id, limit=200)
        batches: dict[str, dict[str, Any]] = {}
        for entity in recent:
            meta = entity.content_json.get("_meta", {}) if entity.content_json else {}
            batch_id = meta.get("batch_id", "_unknown")
            if batch_id not in batches:
                batches[batch_id] = {
                    "batch_id": batch_id,
                    "ingested_at": meta.get("ingested_at", ""),
                    "entity_count": 0,
                    "entities": [],
                }
            batches[batch_id]["entity_count"] += 1
            batches[batch_id]["entities"].append(
                {
                    "id": str(entity.id),
                    "name": entity.name,
                    "entity_type": entity.entity_type,
                }
            )

        sorted_batches = sorted(
            batches.values(),
            key=lambda b: b["ingested_at"],
            reverse=True,
        )
        return sorted_batches[:limit]


# ============================================================
# EventRepository
# ============================================================


class EventRepository:
    """事件数据访问"""

    @staticmethod
    def _active_conditions() -> list[Any]:
        """只返回挂在已采用事件与地点下的扩展记录。"""
        canonical_event = exists().where(
            CoreEntity.id == Event.entity_id,
            CoreEntity.novel_id == Event.novel_id,
            CoreEntity.entity_type == "event",
            CoreEntity.status == "canonical",
        )
        canonical_location = exists().where(
            CoreEntity.id == Event.location_entity_id,
            CoreEntity.novel_id == Event.novel_id,
            CoreEntity.entity_type == "location",
            CoreEntity.status == "canonical",
        )
        return [canonical_event, canonical_location]

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: EventCreate,
    ) -> Event:
        event = Event(
            entity_id=parse_uuid(data.entity_id),
            novel_id=novel_id,
            source_chapter_id=parse_uuid(data.source_chapter_id),
            location_entity_id=parse_uuid(data.location_entity_id),
            timeline_order=data.timeline_order,
            occurrence_time_label=data.occurrence_time_label,
        )
        db.add(event)
        await db.flush()
        return event

    async def get(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
    ) -> Event | None:
        stmt = select(Event).where(Event.entity_id == entity_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[Event], int]:
        conditions = [Event.novel_id == novel_id, *self._active_conditions()]
        count_stmt = select(func.count(Event.entity_id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0

        stmt = (
            select(Event)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(Event.timeline_order, Event.entity_id)
        )
        result = await db.execute(stmt)
        items: Sequence[Event] = result.scalars().all()
        return list(items), total

    async def get_events_for_chapter(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_id: uuid.UUID,
    ) -> list[Event]:
        stmt = (
            select(Event)
            .where(
                Event.novel_id == novel_id,
                Event.source_chapter_id == chapter_id,
                *self._active_conditions(),
            )
            .order_by(Event.timeline_order, Event.entity_id)
        )
        result = await db.execute(stmt)
        items: Sequence[Event] = result.scalars().all()
        return list(items)

    async def get_events_in_order(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        limit: int = 50,
    ) -> list[Event]:
        stmt = (
            select(Event)
            .where(Event.novel_id == novel_id, *self._active_conditions())
            .order_by(Event.timeline_order, Event.entity_id)
            .limit(limit)
        )
        result = await db.execute(stmt)
        items: Sequence[Event] = result.scalars().all()
        return list(items)

    async def update(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
        data: EventUpdate,
    ) -> Event | None:
        event = await self.get(db, entity_id)
        if event is None:
            return None

        update_values: dict[str, Any] = {}
        if data.source_chapter_id is not None:
            update_values["source_chapter_id"] = parse_uuid(data.source_chapter_id)
        if data.location_entity_id is not None:
            update_values["location_entity_id"] = parse_uuid(data.location_entity_id)
        if data.timeline_order is not None:
            update_values["timeline_order"] = data.timeline_order
        if data.occurrence_time_label is not None:
            update_values["occurrence_time_label"] = data.occurrence_time_label

        if update_values:
            for field, value in update_values.items():
                setattr(event, field, value)
            db.add(event)
            await db.flush()

        return event

    async def delete(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
    ) -> bool:
        stmt = delete(Event).where(Event.entity_id == entity_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0


# ============================================================
# EntityRelationRepository
# ============================================================


class EntityRelationRepository:
    """关系数据访问"""

    def _with_endpoint_loads(self, stmt):
        return stmt.options(
            selectinload(EntityRelation.source),
            selectinload(EntityRelation.target),
        )

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: EntityRelationCreate,
    ) -> EntityRelation:
        rel = EntityRelation(
            novel_id=novel_id,
            source_id=parse_uuid(data.source_id),
            target_id=parse_uuid(data.target_id),
            relation_type=data.relation_type,
            description=data.description,
            strength=data.strength if data.strength is not None else 0.5,
            source_chapter_id=parse_uuid(data.source_chapter_id)
            if data.source_chapter_id
            else None,
            caused_by_event_id=parse_uuid(data.caused_by_event_id)
            if data.caused_by_event_id
            else None,
            quote=data.quote,
            review_meta=data.review_meta or {},
            status=data.status or "canonical",
        )
        db.add(rel)
        await db.flush()
        return rel

    async def get(
        self,
        db: AsyncSession,
        rel_id: uuid.UUID,
    ) -> EntityRelation | None:
        stmt = self._with_endpoint_loads(
            select(EntityRelation).where(EntityRelation.id == rel_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_many_for_update(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        relation_ids: list[uuid.UUID],
    ) -> list[EntityRelation]:
        if not relation_ids:
            return []
        result = await db.execute(
            select(EntityRelation)
            .where(
                EntityRelation.novel_id == novel_id,
                EntityRelation.id.in_(relation_ids),
            )
            .order_by(EntityRelation.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def get_candidate_pair_for_update(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
    ) -> list[EntityRelation]:
        """Lock one complete directed candidate group in stable UUID order."""
        result = await db.execute(
            select(EntityRelation)
            .where(
                EntityRelation.novel_id == novel_id,
                EntityRelation.source_id == source_id,
                EntityRelation.target_id == target_id,
                EntityRelation.status == "candidate",
            )
            .order_by(EntityRelation.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def list_review_candidates(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
    ) -> list[EntityRelation]:
        """Return the complete candidate queue without a silent safety cap."""
        result = await db.execute(
            self._with_endpoint_loads(select(EntityRelation))
            .where(
                EntityRelation.novel_id == novel_id,
                EntityRelation.status == "candidate",
            )
            .order_by(EntityRelation.created_at.desc(), EntityRelation.id.desc())
        )
        return list(result.scalars().all())

    async def list_candidate_pairs(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        pairs: Sequence[tuple[uuid.UUID, uuid.UUID]],
    ) -> list[EntityRelation]:
        unique_pairs = sorted(set(pairs), key=lambda item: (str(item[0]), str(item[1])))
        if not unique_pairs:
            return []
        pair_conditions = [
            and_(
                EntityRelation.source_id == source_id,
                EntityRelation.target_id == target_id,
            )
            for source_id, target_id in unique_pairs
        ]
        result = await db.execute(
            select(EntityRelation)
            .where(
                EntityRelation.novel_id == novel_id,
                EntityRelation.status == "candidate",
                or_(*pair_conditions),
            )
            .order_by(EntityRelation.id)
        )
        return list(result.scalars().all())

    async def list_canonical_pairs(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        pairs: Sequence[tuple[uuid.UUID, uuid.UUID]],
    ) -> list[EntityRelation]:
        unique_pairs = sorted(set(pairs), key=lambda item: (str(item[0]), str(item[1])))
        if not unique_pairs:
            return []
        pair_conditions = [
            and_(
                EntityRelation.source_id == source_id,
                EntityRelation.target_id == target_id,
            )
            for source_id, target_id in unique_pairs
        ]
        result = await db.execute(
            self._with_endpoint_loads(select(EntityRelation))
            .where(
                EntityRelation.novel_id == novel_id,
                EntityRelation.status == "canonical",
                or_(*pair_conditions),
            )
            .order_by(EntityRelation.id)
        )
        return list(result.scalars().all())

    async def list_canonical_targets(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        targets: Sequence[tuple[uuid.UUID, uuid.UUID, str]],
    ) -> list[EntityRelation]:
        unique_targets = sorted(
            set(targets),
            key=lambda item: (str(item[0]), str(item[1]), item[2]),
        )
        if not unique_targets:
            return []
        target_conditions = [
            and_(
                EntityRelation.source_id == source_id,
                EntityRelation.target_id == target_id,
                EntityRelation.relation_type == relation_type,
            )
            for source_id, target_id, relation_type in unique_targets
        ]
        result = await db.execute(
            select(EntityRelation)
            .where(
                EntityRelation.novel_id == novel_id,
                EntityRelation.status == "canonical",
                or_(*target_conditions),
            )
            .order_by(EntityRelation.id)
        )
        return list(result.scalars().all())

    async def find_canonical_relation(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        relation_type: str,
    ) -> EntityRelation | None:
        result = await db.execute(
            select(EntityRelation)
            .where(
                EntityRelation.novel_id == novel_id,
                EntityRelation.source_id == source_id,
                EntityRelation.target_id == target_id,
                EntityRelation.relation_type == relation_type,
                EntityRelation.status == "canonical",
            )
            .order_by(EntityRelation.id)
            .limit(1)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        status: str | None = None,
        relation_type: str | None = None,
        q: str | None = None,
        source_chapter_id: uuid.UUID | None = None,
        strength_min: float | None = None,
        strength_max: float | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[EntityRelation]:
        conditions = [
            EntityRelation.novel_id == novel_id,
            EntityRelation.status != "deprecated",
        ]
        if status:
            conditions[-1] = EntityRelation.status == status
        if relation_type:
            conditions.append(EntityRelation.relation_type == relation_type)
        if q:
            query = q.strip()
            if query:
                like_expr = f"%{query}%"
                conditions.append(
                    or_(
                        EntityRelation.relation_type.ilike(like_expr),
                        EntityRelation.description.ilike(like_expr),
                        EntityRelation.quote.ilike(like_expr),
                        CoreEntity.name.ilike(like_expr),
                    )
                )
        if source_chapter_id:
            conditions.append(EntityRelation.source_chapter_id == source_chapter_id)
        if strength_min is not None:
            conditions.append(EntityRelation.strength >= strength_min)
        if strength_max is not None:
            conditions.append(EntityRelation.strength <= strength_max)
        stmt = self._with_endpoint_loads(select(EntityRelation))
        if q and q.strip():
            stmt = stmt.join(
                CoreEntity,
                or_(
                    EntityRelation.source_id == CoreEntity.id,
                    EntityRelation.target_id == CoreEntity.id,
                ),
            ).distinct()
        stmt = (
            stmt.where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(EntityRelation.created_at.desc(), EntityRelation.id.desc())
        )
        result = await db.execute(stmt)
        items: Sequence[EntityRelation] = result.scalars().all()
        return list(items)

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        status: str | None = None,
        relation_type: str | None = None,
        q: str | None = None,
        source_chapter_id: uuid.UUID | None = None,
        strength_min: float | None = None,
        strength_max: float | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[EntityRelation], int]:
        conditions = [
            EntityRelation.novel_id == novel_id,
            EntityRelation.status != "deprecated",
        ]
        if status:
            conditions[-1] = EntityRelation.status == status
        if relation_type:
            conditions.append(EntityRelation.relation_type == relation_type)
        if q:
            query = q.strip()
            if query:
                like_expr = f"%{query}%"
                conditions.append(
                    or_(
                        EntityRelation.relation_type.ilike(like_expr),
                        EntityRelation.description.ilike(like_expr),
                        EntityRelation.quote.ilike(like_expr),
                        CoreEntity.name.ilike(like_expr),
                    )
                )
        if source_chapter_id:
            conditions.append(EntityRelation.source_chapter_id == source_chapter_id)
        if strength_min is not None:
            conditions.append(EntityRelation.strength >= strength_min)
        if strength_max is not None:
            conditions.append(EntityRelation.strength <= strength_max)
        count_stmt = select(func.count(EntityRelation.id))
        if q and q.strip():
            count_stmt = (
                select(func.count(func.distinct(EntityRelation.id)))
                .select_from(EntityRelation)
                .join(
                    CoreEntity,
                    or_(
                        EntityRelation.source_id == CoreEntity.id,
                        EntityRelation.target_id == CoreEntity.id,
                    ),
                )
                .distinct()
            )
        count_stmt = count_stmt.where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0
        items = await self.list_by_novel(
            db,
            novel_id,
            status=status,
            relation_type=relation_type,
            q=q,
            source_chapter_id=source_chapter_id,
            strength_min=strength_min,
            strength_max=strength_max,
            skip=skip,
            limit=limit,
        )
        return items, total

    async def get_by_source(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        source_id: uuid.UUID,
        *,
        relation_type: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[EntityRelation]:
        conditions = [
            EntityRelation.novel_id == novel_id,
            EntityRelation.source_id == source_id,
            EntityRelation.status != "deprecated",
        ]
        if relation_type:
            conditions.append(EntityRelation.relation_type == relation_type)

        stmt = (
            self._with_endpoint_loads(select(EntityRelation))
            .where(*conditions)
            .limit(limit)
            .order_by(EntityRelation.strength.desc(), EntityRelation.id.asc())
        )
        result = await db.execute(stmt)
        items: Sequence[EntityRelation] = result.scalars().all()
        return list(items)

    async def get_by_target(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        target_id: uuid.UUID,
        *,
        relation_type: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[EntityRelation]:
        conditions = [
            EntityRelation.novel_id == novel_id,
            EntityRelation.target_id == target_id,
            EntityRelation.status != "deprecated",
        ]
        if relation_type:
            conditions.append(EntityRelation.relation_type == relation_type)

        stmt = (
            self._with_endpoint_loads(select(EntityRelation))
            .where(*conditions)
            .limit(limit)
            .order_by(EntityRelation.strength.desc(), EntityRelation.id.asc())
        )
        result = await db.execute(stmt)
        items: Sequence[EntityRelation] = result.scalars().all()
        return list(items)

    async def get_traceable_relations(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        chapter_id: uuid.UUID,
    ) -> list[EntityRelation]:
        """获取某章节建立的所有可追溯关系"""
        stmt = (
            self._with_endpoint_loads(select(EntityRelation))
            .where(
                EntityRelation.novel_id == novel_id,
                EntityRelation.source_chapter_id == chapter_id,
                EntityRelation.status != "deprecated",
            )
            .order_by(EntityRelation.created_at, EntityRelation.id)
        )
        result = await db.execute(stmt)
        items: Sequence[EntityRelation] = result.scalars().all()
        return list(items)

    async def get_related_entity_ids(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: uuid.UUID,
        depth: int = 1,
        limit: int = 20,
    ) -> set[uuid.UUID]:
        return await self.get_related_entity_ids_for_seeds(
            db,
            novel_id,
            [entity_id],
            depth=depth,
            limit=limit,
        )

    async def get_related_entity_ids_for_seeds(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_ids: list[uuid.UUID],
        depth: int = 1,
        limit: int = 20,
    ) -> set[uuid.UUID]:
        seed_ids = list(dict.fromkeys(entity_ids))
        if not seed_ids or limit <= 0:
            return set()

        related = await self._get_one_hop_ids_for_entities(db, novel_id, seed_ids)

        if depth >= 2 and len(related) < limit:
            frontier = list(related)
            second_hop = await self._get_one_hop_ids_for_entities(
                db,
                novel_id,
                frontier,
            )
            related.update(second_hop)

        return set(list(related)[:limit])

    async def _get_one_hop_ids(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: uuid.UUID,
    ) -> set[uuid.UUID]:
        from sqlalchemy import union_all

        src_stmt = select(EntityRelation.target_id.label("related_id")).where(
            EntityRelation.novel_id == novel_id,
            EntityRelation.source_id == entity_id,
            EntityRelation.status != "deprecated",
        )
        tgt_stmt = select(EntityRelation.source_id.label("related_id")).where(
            EntityRelation.novel_id == novel_id,
            EntityRelation.target_id == entity_id,
            EntityRelation.status != "deprecated",
        )
        combined = union_all(src_stmt, tgt_stmt)
        result = await db.execute(combined)
        return {row[0] for row in result.all()}

    async def _get_one_hop_ids_for_entities(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_ids: list[uuid.UUID],
    ) -> set[uuid.UUID]:
        from sqlalchemy import union_all

        unique_ids = list(dict.fromkeys(entity_ids))
        if not unique_ids:
            return set()

        src_stmt = select(EntityRelation.target_id.label("related_id")).where(
            EntityRelation.novel_id == novel_id,
            EntityRelation.source_id.in_(unique_ids),
            EntityRelation.status != "deprecated",
        )
        tgt_stmt = select(EntityRelation.source_id.label("related_id")).where(
            EntityRelation.novel_id == novel_id,
            EntityRelation.target_id.in_(unique_ids),
            EntityRelation.status != "deprecated",
        )
        combined = union_all(src_stmt, tgt_stmt)
        result = await db.execute(combined)
        return {row[0] for row in result.all()}

    async def update(
        self,
        db: AsyncSession,
        relation_or_id: EntityRelation | uuid.UUID,
        data: EntityRelationUpdate,
    ) -> EntityRelation | None:
        rel = (
            await self.get(db, relation_or_id)
            if isinstance(relation_or_id, uuid.UUID)
            else relation_or_id
        )
        if rel is None:
            return None

        update_values: dict[str, Any] = {}
        for field in ("relation_type", "description", "strength", "status"):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        if update_values:
            for field, value in update_values.items():
                setattr(rel, field, value)
            db.add(rel)
            await db.flush()

        return rel

    async def deprecate_many(
        self,
        db: AsyncSession,
        relation_ids: Sequence[uuid.UUID],
    ) -> int:
        """批量标记关系为 deprecated，返回实际更新数。"""
        unique_ids = list(dict.fromkeys(relation_ids))
        if not unique_ids:
            return 0
        stmt = (
            update(EntityRelation)
            .where(EntityRelation.id.in_(unique_ids))
            .values(status="deprecated")
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount or 0

    async def delete(
        self,
        db: AsyncSession,
        rel_id: uuid.UUID,
    ) -> bool:
        stmt = delete(EntityRelation).where(EntityRelation.id == rel_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

    async def upsert(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        relation_type: str,
        description: str | None = None,
    ) -> EntityRelation:
        bind = db.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            insert_stmt = pg_insert(EntityRelation).values(
                novel_id=novel_id,
                source_id=source_id,
                target_id=target_id,
                relation_type=relation_type,
                description=description,
                status="canonical",
            )
            stmt = insert_stmt.on_conflict_do_update(
                index_elements=[
                    EntityRelation.novel_id,
                    EntityRelation.source_id,
                    EntityRelation.target_id,
                    EntityRelation.relation_type,
                ],
                index_where=EntityRelation.status == "canonical",
                set_={
                    "description": func.coalesce(
                        insert_stmt.excluded.description,
                        EntityRelation.description,
                    ),
                    "updated_at": func.timezone("utc", func.now()),
                },
            ).returning(EntityRelation.id)
            rel_id = (await db.execute(stmt)).scalar_one()
            await db.flush()
            rel = await self.get(db, rel_id)
            if rel is None:
                raise RuntimeError("EntityRelation upsert returned missing relation")
            return rel

        lock_key = (
            str(novel_id),
            str(source_id),
            str(target_id),
            relation_type,
            "canonical",
        )
        async with _relation_upsert_lock(lock_key):
            return await self._manual_upsert(
                db,
                novel_id,
                source_id,
                target_id,
                relation_type,
                description,
            )

    async def _manual_upsert(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        relation_type: str,
        description: str | None,
    ) -> EntityRelation:

        stmt = (
            select(EntityRelation)
            .where(
                EntityRelation.novel_id == novel_id,
                EntityRelation.source_id == source_id,
                EntityRelation.target_id == target_id,
                EntityRelation.relation_type == relation_type,
                EntityRelation.status == "canonical",
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is not None:
            if description:
                existing.description = description
            await db.flush()
            return existing

        rel = EntityRelation(
            novel_id=novel_id,
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            description=description,
            status="canonical",
        )
        db.add(rel)
        await db.flush()
        return rel

    async def get_all_for_entity(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: uuid.UUID,
    ) -> list[EntityRelation]:
        """获取某实体参与的所有关系（作为 source 或 target）。"""
        stmt = self._with_endpoint_loads(
            select(EntityRelation).where(
                EntityRelation.novel_id == novel_id,
                or_(
                    EntityRelation.source_id == entity_id,
                    EntityRelation.target_id == entity_id,
                ),
            )
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_all_for_entities(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_ids: list[uuid.UUID],
    ) -> list[EntityRelation]:
        """Batch-load relations touching any requested entity in one novel."""
        unique_ids = list(dict.fromkeys(entity_ids))
        if not unique_ids:
            return []
        stmt = select(EntityRelation).where(
            EntityRelation.novel_id == novel_id,
            or_(
                EntityRelation.source_id.in_(unique_ids),
                EntityRelation.target_id.in_(unique_ids),
            ),
        )
        return list((await db.execute(stmt)).scalars().all())

    async def update_endpoint(
        self,
        db: AsyncSession,
        rel_id: uuid.UUID,
        *,
        source_id: uuid.UUID | None = None,
        target_id: uuid.UUID | None = None,
    ) -> None:
        """重定向关系端点。绕过 EntityRelationUpdate 不含 source_id/target_id 的限制。"""
        values: dict[str, Any] = {}
        if source_id is not None:
            values["source_id"] = source_id
        if target_id is not None:
            values["target_id"] = target_id
        if values:
            stmt = (
                update(EntityRelation).where(EntityRelation.id == rel_id).values(**values)
            )
            await db.execute(stmt)

    async def find_duplicate_relation(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        relation_type: str,
        *,
        exclude_rel_id: uuid.UUID | None = None,
    ) -> EntityRelation | None:
        """查找已存在的同类型同方向关系。"""
        conditions = [
            EntityRelation.novel_id == novel_id,
            EntityRelation.source_id == source_id,
            EntityRelation.target_id == target_id,
            EntityRelation.relation_type == relation_type,
            EntityRelation.status != "deprecated",
        ]
        if exclude_rel_id is not None:
            conditions.append(EntityRelation.id != exclude_rel_id)
        stmt = (
            self._with_endpoint_loads(select(EntityRelation))
            .where(*conditions)
            .order_by(EntityRelation.status.desc(), EntityRelation.id.asc())
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_self_loops(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        entity_id: uuid.UUID,
    ) -> int:
        """删除自环关系（source == target），返回删除数。"""
        stmt = delete(EntityRelation).where(
            EntityRelation.novel_id == novel_id,
            EntityRelation.source_id == entity_id,
            EntityRelation.target_id == entity_id,
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount or 0


# ============================================================
# EntityRevisionRepository
# ============================================================


class EntityRevisionRepository:
    """版本快照数据访问"""

    async def create(
        self,
        db: AsyncSession,
        *,
        entity_id: uuid.UUID,
        novel_id: uuid.UUID,
        snapshot: dict,
        source_chapter_id: uuid.UUID | None = None,
        revision_reason: str = "ai_import",
    ) -> EntityRevision:
        revision = EntityRevision(
            entity_id=entity_id,
            novel_id=novel_id,
            snapshot=snapshot,
            source_chapter_id=source_chapter_id,
            revision_reason=revision_reason,
        )
        db.add(revision)
        await db.flush()
        return revision

    async def get_revisions(
        self,
        db: AsyncSession,
        entity_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[EntityRevision], int]:
        conditions = [EntityRevision.entity_id == entity_id]
        count_stmt = select(func.count(EntityRevision.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0

        stmt = (
            select(EntityRevision)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(EntityRevision.created_at.desc(), EntityRevision.id.desc())
        )
        result = await db.execute(stmt)
        items: Sequence[EntityRevision] = result.scalars().all()
        return list(items), total

    async def get_revision(
        self,
        db: AsyncSession,
        revision_id: uuid.UUID,
    ) -> EntityRevision | None:
        stmt = select(EntityRevision).where(EntityRevision.id == revision_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()


# ============================================================
# CharacterRepository（从 character 模块迁入）
# ============================================================


class CharacterRepository:
    """人物数据访问"""

    @staticmethod
    def _canonical_owner_condition():
        return exists().where(
            CoreEntity.id == Character.entity_id,
            CoreEntity.novel_id == Character.novel_id,
            CoreEntity.entity_type == "character",
            CoreEntity.status == "canonical",
        )

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: CharacterCreate,
    ) -> Character:
        character = Character(
            entity_id=parse_uuid(data.entity_id),
            novel_id=novel_id,
            name=data.name,
            aliases=data.aliases or [],
            role=data.role,
            appearance=data.appearance,
            personality=data.personality,
            desire=data.desire,
            fear=data.fear,
            secret=data.secret,
            weakness=data.weakness,
            current_goal=data.current_goal,
            current_state=data.current_state,
            current_emotion=data.current_emotion,
            stance=data.stance,
            voice_style=data.voice_style,
            behavior_rules=data.behavior_rules or [],
            relationship_summary=data.relationship_summary,
            meta=data.meta or {},
            status=data.status or "canonical",
        )
        db.add(character)
        await db.flush()
        return character

    async def get(
        self,
        db: AsyncSession,
        character_id: uuid.UUID,
    ) -> Character | None:
        stmt = select(Character).where(Character.entity_id == character_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[Character]:
        conditions = [
            Character.novel_id == novel_id,
            self._canonical_owner_condition(),
        ]
        stmt = (
            select(Character)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(Character.name, Character.entity_id)
        )
        result = await db.execute(stmt)
        items: Sequence[Character] = result.scalars().all()
        return list(items)

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[Character], int]:
        conditions = [
            Character.novel_id == novel_id,
            self._canonical_owner_condition(),
        ]
        count_stmt = select(func.count(Character.entity_id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0
        items = await self.list_by_novel(db, novel_id, skip=skip, limit=limit)
        return items, total

    async def get_by_ids(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        character_ids: list[uuid.UUID],
    ) -> list[Character]:
        if not character_ids:
            return []
        stmt = select(Character).where(
            Character.novel_id == novel_id,
            Character.entity_id.in_(character_ids),
            self._canonical_owner_condition(),
        )
        result = await db.execute(stmt)
        items: Sequence[Character] = result.scalars().all()
        return list(items)

    async def update(
        self,
        db: AsyncSession,
        character_or_id: Character | uuid.UUID,
        data: CharacterUpdate,
    ) -> Character | None:
        character = (
            await self.get(db, character_or_id)
            if isinstance(character_or_id, uuid.UUID)
            else character_or_id
        )
        if character is None:
            return None

        update_values: dict[str, Any] = {}
        for field in (
            "name",
            "role",
            "appearance",
            "personality",
            "desire",
            "fear",
            "secret",
            "weakness",
            "current_goal",
            "current_state",
            "current_emotion",
            "stance",
            "voice_style",
            "relationship_summary",
            "status",
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        if data.aliases is not None:
            update_values["aliases"] = data.aliases
        if data.behavior_rules is not None:
            update_values["behavior_rules"] = data.behavior_rules
        if data.meta is not None:
            update_values["meta"] = data.meta

        if update_values:
            for field, value in update_values.items():
                setattr(character, field, value)
            db.add(character)
            await db.flush()

        return character

    async def migrate_entity_id(
        self,
        db: AsyncSession,
        source_entity_id: uuid.UUID,
        target_entity_id: uuid.UUID,
    ) -> bool:
        """将 Character 行从 source_entity_id 迁移到 target_entity_id（用于合并）。"""
        stmt = (
            update(Character)
            .where(Character.entity_id == source_entity_id)
            .values(entity_id=target_entity_id)
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

    async def delete(
        self,
        db: AsyncSession,
        character_id: uuid.UUID,
    ) -> bool:
        stmt = delete(Character).where(Character.entity_id == character_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0

    async def find_character_by_name(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        name: str,
    ) -> str | None:
        stmt = (
            select(Character.entity_id)
            .where(
                Character.novel_id == novel_id,
                Character.name == name,
                Character.status == "canonical",
                self._canonical_owner_condition(),
            )
            .limit(1)
        )
        result = await db.execute(stmt)
        row = result.scalar_one_or_none()
        return str(row) if row is not None else None

    async def update_character_meta_location(
        self,
        db: AsyncSession,
        character_id: uuid.UUID,
        location_id: uuid.UUID,
        text_state: str,
        chapter_index: int,
    ) -> None:
        meta = {}
        meta["location_id"] = str(location_id)
        meta["text_state"] = text_state
        meta["chapter_index"] = chapter_index

        stmt = (
            update(Character).where(Character.entity_id == character_id).values(meta=meta)
        )
        await db.execute(stmt)
        await db.flush()

    async def find_characters_by_location(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        location_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """获取当前位于某地点的活跃人物列表"""
        stmt = select(Character).where(
            Character.novel_id == novel_id,
            Character.status == "canonical",
            Character.meta["location_id"].as_string() == str(location_id),
            self._canonical_owner_condition(),
        )
        result = await db.execute(stmt)
        characters: Sequence[Character] = result.scalars().all()

        return [
            {
                "id": str(c.entity_id),
                "name": c.name,
                "current_state": c.current_state,
            }
            for c in characters
        ]

    async def get_character_location_id(
        self,
        db: AsyncSession,
        character_id: uuid.UUID,
    ) -> str | None:
        char = await self.get(db, character_id)
        if char is None:
            return None
        meta = char.meta or {}
        return meta.get("location_id")


# ============================================================
# CharacterKnowledgeRepository（从 character 模块迁入）
# ============================================================


class CharacterKnowledgeRepository:
    """人物知识数据访问"""

    _GENERIC_CORE_TARGET_TYPES = {"entity", "world_entity", "object"}
    _TYPED_CORE_TARGET_TYPES = {"character", "event", "location", "item", "faction"}

    @staticmethod
    def _canonical_character_condition():
        return exists().where(
            CoreEntity.id == CharacterKnowledge.character_id,
            CoreEntity.novel_id == CharacterKnowledge.novel_id,
            CoreEntity.entity_type == "character",
            CoreEntity.status == "canonical",
        )

    @classmethod
    def _canonical_target_condition(cls):
        """已知 CoreEntity 目标只在已采用时可进入默认上下文。"""
        known_types = cls._GENERIC_CORE_TARGET_TYPES | cls._TYPED_CORE_TARGET_TYPES
        generic_target = and_(
            CharacterKnowledge.target_type.in_(cls._GENERIC_CORE_TARGET_TYPES),
            exists().where(
                CoreEntity.id == CharacterKnowledge.target_id,
                CoreEntity.novel_id == CharacterKnowledge.novel_id,
                CoreEntity.status == "canonical",
            ),
        )
        typed_targets = [
            and_(
                CharacterKnowledge.target_type == target_type,
                exists().where(
                    CoreEntity.id == CharacterKnowledge.target_id,
                    CoreEntity.novel_id == CharacterKnowledge.novel_id,
                    CoreEntity.entity_type == target_type,
                    CoreEntity.status == "canonical",
                ),
            )
            for target_type in cls._TYPED_CORE_TARGET_TYPES
        ]
        return or_(
            CharacterKnowledge.target_type.not_in(known_types),
            generic_target,
            *typed_targets,
        )

    @classmethod
    def _active_conditions(cls) -> list[Any]:
        return [
            cls._canonical_character_condition(),
            cls._canonical_target_condition(),
        ]

    async def create(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        data: CharacterKnowledgeCreate,
    ) -> CharacterKnowledge:
        knowledge = CharacterKnowledge(
            novel_id=novel_id,
            character_id=parse_uuid(data.character_id),
            target_type=data.target_type,
            target_id=parse_uuid(data.target_id),
            knowledge_level=data.knowledge_level,
            known_content=data.known_content,
            misconception=data.misconception,
            source_chapter_index=data.source_chapter_index,
            is_public_baseline=data.is_public_baseline,
            source_memory_id=parse_uuid(data.source_memory_id)
            if data.source_memory_id
            else None,
            status=data.status or "canonical",
        )
        db.add(knowledge)
        await db.flush()
        return knowledge

    async def get(
        self,
        db: AsyncSession,
        knowledge_id: uuid.UUID,
    ) -> CharacterKnowledge | None:
        stmt = select(CharacterKnowledge).where(CharacterKnowledge.id == knowledge_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_character(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        character_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[CharacterKnowledge], int]:
        conditions = [
            CharacterKnowledge.novel_id == novel_id,
            CharacterKnowledge.character_id == character_id,
            *self._active_conditions(),
        ]
        count_stmt = select(func.count(CharacterKnowledge.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0

        stmt = (
            select(CharacterKnowledge)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(CharacterKnowledge.target_type, CharacterKnowledge.id)
        )
        result = await db.execute(stmt)
        items: Sequence[CharacterKnowledge] = result.scalars().all()
        return list(items), total

    async def list_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> list[CharacterKnowledge]:
        conditions = [
            CharacterKnowledge.novel_id == novel_id,
            *self._active_conditions(),
        ]
        stmt = (
            select(CharacterKnowledge)
            .where(*conditions)
            .offset(skip)
            .limit(limit)
            .order_by(CharacterKnowledge.character_id, CharacterKnowledge.id)
        )
        result = await db.execute(stmt)
        items: Sequence[CharacterKnowledge] = result.scalars().all()
        return list(items)

    async def get_by_novel(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[CharacterKnowledge], int]:
        conditions = [
            CharacterKnowledge.novel_id == novel_id,
            *self._active_conditions(),
        ]
        count_stmt = select(func.count(CharacterKnowledge.id)).where(*conditions)
        total = (await db.execute(count_stmt)).scalar() or 0
        items = await self.list_by_novel(db, novel_id, skip=skip, limit=limit)
        return items, total

    async def get_by_target(
        self,
        db: AsyncSession,
        novel_id: uuid.UUID,
        character_id: uuid.UUID,
        target_ids: list[uuid.UUID] | None = None,
        visible_until_chapter: int | None = None,
    ) -> list[CharacterKnowledge]:
        conditions = [
            CharacterKnowledge.novel_id == novel_id,
            CharacterKnowledge.character_id == character_id,
            *self._active_conditions(),
        ]
        if target_ids:
            conditions.append(CharacterKnowledge.target_id.in_(target_ids))
        if visible_until_chapter is not None:
            conditions.append(
                or_(
                    and_(
                        CharacterKnowledge.source_chapter_index.is_not(None),
                        CharacterKnowledge.source_chapter_index < visible_until_chapter,
                    ),
                    and_(
                        CharacterKnowledge.source_chapter_index.is_(None),
                        CharacterKnowledge.is_public_baseline.is_(True),
                    ),
                )
            )

        stmt = select(CharacterKnowledge).where(*conditions)
        result = await db.execute(stmt)
        items: Sequence[CharacterKnowledge] = result.scalars().all()
        return list(items)

    async def update(
        self,
        db: AsyncSession,
        knowledge_id: uuid.UUID,
        data: CharacterKnowledgeUpdate,
    ) -> CharacterKnowledge | None:
        knowledge = await self.get(db, knowledge_id)
        if knowledge is None:
            return None

        update_values: dict[str, Any] = {}
        for field in (
            "knowledge_level",
            "known_content",
            "misconception",
            "source_chapter_index",
            "is_public_baseline",
            "status",
        ):
            value = getattr(data, field, None)
            if value is not None:
                update_values[field] = value

        if data.source_memory_id is not None:
            update_values["source_memory_id"] = parse_uuid(data.source_memory_id)

        if update_values:
            for field, value in update_values.items():
                setattr(knowledge, field, value)
            db.add(knowledge)
            await db.flush()

        return knowledge

    async def delete(
        self,
        db: AsyncSession,
        knowledge_id: uuid.UUID,
    ) -> bool:
        stmt = delete(CharacterKnowledge).where(CharacterKnowledge.id == knowledge_id)
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount > 0


RelationshipRepository = EntityRelationRepository
