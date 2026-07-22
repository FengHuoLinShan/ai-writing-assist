"""EntityEmbeddingService — 实体向量回填服务。"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.embedding.client import BgeEmbeddingClient
from infrastructure.llm.redaction import redact_diagnostic
from modules.world.models import CoreEntity
from modules.world.services.common import parse_uuid

_logger = logging.getLogger(__name__)


class EntityEmbeddingService:
    """为缺少 embedding 的实体生成向量。"""

    async def backfill_embeddings(
        self,
        db: AsyncSession,
        novel_id: str,
        *,
        batch_size: int = 64,
    ) -> int:
        """为 novel 中缺少 embedding 的实体生成向量。返回回填数量。"""
        nid = parse_uuid(novel_id, "novel_id")

        stmt = select(CoreEntity).where(
            CoreEntity.novel_id == nid,
            CoreEntity.embedding.is_(None),
            CoreEntity.status.in_(["canonical", "draft"]),
        )
        result = await db.execute(stmt)
        entities = list(result.scalars().all())

        if not entities:
            return 0

        try:
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
            except Exception as exc:
                _logger.error(
                    "Backfill embedding batch failed at offset %d: %s",
                    i,
                    redact_diagnostic(exc, limit=300),
                )
                continue

            for entity, emb in zip(batch_entities, embeddings):
                entity.embedding = [float(v) for v in emb]
                entity.embedding_text = entity.name
                total += 1

            await db.flush()

        _logger.info("Backfilled embeddings for %d entities in novel %s", total, novel_id)
        return total
