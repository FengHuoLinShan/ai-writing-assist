"""WorldEntityService — 核心实体 CRUD。继承 BaseCRUDService (ADR-0002)。

list 加 entity_type / status filter + 返 ListResponse (per design B3,
subclass override)。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.models import CoreEntity
from modules.world.repositories import CoreEntityRepository
from modules.world.schemas import (
    CoreEntityCreate,
    CoreEntityListResponse,
    CoreEntityResponse,
    CoreEntityUpdate,
    WorldContextBundle,
    WorldEntityContext,
)
from modules.world.services.base import CrudService
from modules.world.services.helpers import parse_uuid
from shared.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


class WorldEntityService(
    CrudService[
        CoreEntity, CoreEntityCreate, CoreEntityUpdate, CoreEntityResponse,
    ],
):
    """核心实体业务服务。

    5 verb 继承自 base; list 加 filter (entity_type / status) + 返 ListResponse;
    4 个特例方法 (get_entity_context / list_entity_summaries / list_entity_terms /
    find_by_name) 留本地。
    """

    repo = CoreEntityRepository()
    response = CoreEntityResponse
    label = "CoreEntity"
    id_param = "entity_id"

    # ============================================================
    # Override: list 加 filter kwargs + 返 ListResponse 包装
    # ============================================================

    async def list(  # type: ignore[override]
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        entity_type: str | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> CoreEntityListResponse:
        """带 filter 的 list, 返 ListResponse 包装 (不是 tuple)。"""
        nid = parse_uuid(novel_id, "novel_id")
        limit = min(limit, MAX_PAGE_SIZE)
        items, total = await self.repo.get_by_novel(
            db, nid,
            entity_type=entity_type,
            status=status,
            skip=skip,
            limit=limit,
        )
        return CoreEntityListResponse(
            items=[CoreEntityResponse.model_validate(e) for e in items],
            total=total,
        )

    # ============================================================
    # 特例方法
    # ============================================================

    async def get_entity_context(
        self,
        db: AsyncSession,
        novel_id: str,
        entity_ids: list[str] | None = None,
        reveal_mode: str = "author_safe",
        limit: int = 20,
        current_chapter: int | None = None,
    ) -> WorldContextBundle:
        nid = parse_uuid(novel_id, "novel_id")

        if entity_ids:
            eids = [parse_uuid(eid, "entity_id") for eid in entity_ids]
            entities = await self.repo.get_by_ids(db, nid, eids)
        else:
            entities, _ = await self.repo.get_by_novel(db, nid, limit=limit)

        # Filter expired temporary entities
        if current_chapter is not None:
            from modules.project.project import Project

            pid = parse_uuid(novel_id, "novel_id")
            stmt = select(Project).where(Project.id == pid)
            result = await db.execute(stmt)
            project = result.scalar_one_or_none()
            expiry = 30
            if project is not None and project.settings:
                expiry = project.settings.get("temporary_entity_expiry_chapters", 30)

            filtered: list[CoreEntity] = []
            for entity in entities:
                content = entity.content_json or {}
                meta = content.get("_meta", {})
                if (
                    meta.get("temporary") is True
                    and meta.get("source_chapter_index") is not None
                ):
                    src_ch = int(meta["source_chapter_index"])
                    if current_chapter - src_ch > expiry:
                        continue
                filtered.append(entity)
            entities = filtered

        contexts = [
            _entity_to_context(entity, reveal_mode) for entity in entities
        ]

        return WorldContextBundle(
            novel_id=novel_id,
            entities=contexts,
            total_count=len(contexts),
            reveal_mode=reveal_mode,
        )

    async def list_entity_summaries(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        entity_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        nid = parse_uuid(novel_id, "novel_id")
        result = await self.repo.get_by_type_and_status(
            db, nid, entity_type=entity_type, limit=limit,
        )
        return [
            {"id": item.id, "name": item.name, "entity_type": item.entity_type}
            for item in result
        ]

    async def list_entity_terms(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        limit: int = 500,
    ) -> list[dict]:
        """获取正史 + 草稿实体的检索词典项 (name + content_json.aliases)。

        别名存储约定见 core_entities.content_json.aliases (per world/CLAUDE.md)。
        """
        nid = parse_uuid(novel_id, "novel_id")
        entities, _ = await self.repo.get_by_novel(db, nid, limit=limit)
        terms: list[dict] = []
        for item in entities:
            if item.status not in ("canonical", "draft"):
                continue
            item_terms = [item.name]
            aliases = (item.content_json or {}).get("aliases", [])
            item_terms.extend(
                a if isinstance(a, str) else a.get("alias", "")
                for a in aliases
            )
            terms.append({
                "id": str(item.id),
                "name": item.name,
                "entity_type": item.entity_type,
                "terms": [t for t in item_terms if t],
            })
        return terms

    async def find_by_name(
        self,
        db: AsyncSession,
        novel_id: str,
        name: str,
        entity_type: str | None = None,
    ) -> str | None:
        """按名称查正史实体 ID, 返 str 或 None。"""
        nid = parse_uuid(novel_id, "novel_id")
        return await self.repo.find_entity_by_name(
            db, nid, name, entity_type=entity_type,
        )

    async def backfill_embeddings(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        batch_size: int = 64,
    ) -> int:
        """为 novel 中缺少 embedding 的实体生成向量。返回回填数量。"""
        import logging

        _logger = logging.getLogger(__name__)
        nid = parse_uuid(novel_id, "novel_id")

        stmt = (
            select(CoreEntity)
            .where(
                CoreEntity.novel_id == nid,
                CoreEntity.embedding.is_(None),
                CoreEntity.status.in_(["canonical", "draft"]),
            )
        )
        result = await db.execute(stmt)
        entities = list(result.scalars().all())

        if not entities:
            return 0

        try:
            from infrastructure.embedding.client import BgeEmbeddingClient

            bge = await BgeEmbeddingClient.get_instance()
        except Exception:
            _logger.warning("BGE client unavailable, backfill skipped")
            return 0

        total = 0
        # 配对过滤空名实体，避免索引错位 (Bugfix: P0 index mismatch)
        named = [(e, e.name.strip()) for e in entities if e.name and e.name.strip()]

        for i in range(0, len(named), batch_size):
            batch = named[i : i + batch_size]
            batch_entities = [e for e, _ in batch]
            batch_texts = [n for _, n in batch]
            try:
                embeddings = await bge.generate_embedding(batch_texts, is_query=False)
            except Exception:
                _logger.exception("Backfill embedding batch failed at offset %d", i)
                continue

            for entity, emb in zip(batch_entities, embeddings):
                entity.embedding = [float(v) for v in emb]
                entity.embedding_text = entity.name
                total += 1

            await db.flush()

        _logger.info("Backfilled embeddings for %d entities in novel %s", total, novel_id)
        return total


def _entity_to_context(
    entity: CoreEntity,
    reveal_mode: str,
) -> WorldEntityContext:
    hidden = None
    if reveal_mode == "author_only":
        hidden = entity.hidden_truth

    return WorldEntityContext(
        entity_id=str(entity.id),
        entity_type=entity.entity_type,
        name=entity.name,
        summary=entity.summary,
        public_info=entity.public_info,
        hidden_truth=hidden,
        importance=entity.importance,
        importance_level=entity.importance_level,
        reveal_level=entity.reveal_level,
        status=entity.status,
    )
