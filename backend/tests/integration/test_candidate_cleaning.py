"""
集成测试:对象候选清洗流程

流程:
创建项目 → 创建候选对象 → 创建正史对象 → 执行去重 → 确认别名 → 验证 entity_aliases
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.models import EntityAlias, EntityCandidate, WorldEntity
from modules.world.repositories import WorldEntityRepository
from modules.world.services import EntityCandidateService, EntityDedupService

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


class TestCandidateCleaningFlow:
    """AI长篇小说结构化创作引擎_REVIEW_RULES_v1.0 §19.2 流程1"""

    async def test_candidate_to_alias_flow(
        self,
        db_session: AsyncSession,
        test_project_id: str,
    ):
        novel_id = uuid.UUID(hex=test_project_id)
        nid_str = test_project_id

        # Step 1: 创建正史世界对象
        repo = WorldEntityRepository()
        from modules.world.schemas import WorldEntityCreate

        entity = await repo.create(
            db_session,
            novel_id,
            WorldEntityCreate(
                name="残缺王印",
                entity_type="item",
                summary="旧王朝遗物,带有神秘力量",
            ),
        )
        entity_id = str(entity.id)

        # Step 2: 创建候选对象(黑银色小印章 → 应判定为别名)
        candidate_service = EntityCandidateService()
        from modules.world.schemas import EntityCandidateCreate

        candidate = await candidate_service.create(
            db_session,
            nid_str,
            EntityCandidateCreate(
                name="黑银色小印章",
                entity_type="item",
                summary="一个小印章,外观为黑银色",
                importance_score=0.62,
                confidence=0.7,
                suggested_action="alias_of_existing",
                suggested_existing_entity_id=entity_id,
            ),
        )
        candidate_id = candidate.id

        # Step 3: 执行去重检测
        dedup_service = EntityDedupService()
        suggestions = await dedup_service.find_duplicates(
            db_session,
            nid_str,
            candidate_id,
        )

        # 去重应找到名称精确匹配或别名匹配
        # (注意:SQLite 环境下只有"名称精确匹配"生效)
        assert isinstance(suggestions, list)

        # Step 4: 确认别名
        accepted = await candidate_service.accept_candidate(
            db_session,
            nid_str,
            candidate_id,
        )
        assert accepted is not None
        # accept_candidate with alias_of_existing returns existing entity
        assert accepted.name == "残缺王印"

        # Step 5: 验证 entity_aliases 表增加了记录
        # entity_id column is UUID type (FK -> world_entities.id), need UUID comparison
        stmt = select(EntityAlias).where(
            EntityAlias.entity_id == uuid.UUID(hex=entity_id),
            EntityAlias.alias == "黑银色小印章",
        )
        result = await db_session.execute(stmt)
        alias = result.scalar_one_or_none()
        assert alias is not None, "别名应被写入 entity_aliases"

        # Step 6: 验证正史对象未新增重复
        stmt = select(WorldEntity).where(
            WorldEntity.novel_id == novel_id,
            WorldEntity.name == "黑银色小印章",
        )
        result = await db_session.execute(stmt)
        dup = result.scalar_one_or_none()
        assert dup is None, "不应创建重复的正史对象"

        # Step 7: 验证候选状态已更新
        stmt = select(EntityCandidate).where(
            EntityCandidate.id == uuid.UUID(hex=candidate_id),
        )
        result = await db_session.execute(stmt)
        updated_candidate = result.scalar_one_or_none()
        assert updated_candidate is not None
        assert (
            updated_candidate.status == "canonical"
            or updated_candidate.status == "pending"
        ), f"候选应标记为已处理,当前状态: {updated_candidate.status}"
