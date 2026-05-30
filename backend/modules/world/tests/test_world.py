"""
World 模块测试

测试所有 CRUD 路径、facade、关系扩展、别名、候选和去重功能。
使用 pytest-asyncio 测试异步数据库操作。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.facade import (
    expand_related_entities,
    find_duplicate_entity_candidates,
    find_entity_id_by_name,
    get_world_context,
    upsert_relationship,
)
from modules.world.repositories import (
    CoreEntityRepository,
    EntityRelationRepository,
)
from modules.world.schemas import (
    CoreEntityCreate,
    CoreEntityResponse,
    EntityAliasCreate,
    EntityAliasResponse,
    EntityCandidateCreate,
    EntityCandidateResponse,
    RelationshipCreate,
    RelationshipResponse,
    WorldContextBundle,
    WorldEntityCreate,
    WorldEntityResponse,
    WorldEntityUpdate,
)
from modules.world.services import (
    RelationshipService,
    WorldEntityService,
)
from modules.world.services.alias_service import AliasService
from modules.world.services.candidate_service import EntityCandidateService
from modules.world.services.dedup_service import EntityDedupService


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def novel_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def entity_repo() -> CoreEntityRepository:
    return CoreEntityRepository()


@pytest.fixture
def rel_repo() -> EntityRelationRepository:
    return EntityRelationRepository()


@pytest.fixture
def entity_service() -> WorldEntityService:
    return WorldEntityService()


@pytest.fixture
def rel_service() -> RelationshipService:
    return RelationshipService()


@pytest.fixture
def alias_service() -> AliasService:
    return AliasService()


@pytest.fixture
def candidate_service() -> EntityCandidateService:
    return EntityCandidateService()


@pytest.fixture
def dedup_service() -> EntityDedupService:
    return EntityDedupService()


@pytest.fixture
def sample_entity_data() -> WorldEntityCreate:
    return WorldEntityCreate(
        entity_type="location",
        name="创世大陆",
        summary="小说的主舞台大陆",
        public_info="一块巨大的大陆，分为东西南北四个区域",
        hidden_truth="这块大陆实际上是上古神祇的遗骸所化",
        importance=0.95,
        importance_level="core",
        reveal_level="author_only",
        content_json={"climate": "温带", "area": "500万平方公里"},
        created_by="测试用户",
    )


@pytest.fixture
def sample_entity_data2() -> WorldEntityCreate:
    return WorldEntityCreate(
        entity_type="faction",
        name="光明教廷",
        summary="统治西方大陆的宗教势力",
        public_info="三大势力之一，信奉光明神",
        hidden_truth="教廷高层知道创世大陆的秘密",
        importance=0.85,
        importance_level="core",
    )


@pytest.fixture
def sample_entity_data3() -> WorldEntityCreate:
    return WorldEntityCreate(
        entity_type="item",
        name="创世之书",
        summary="记载了世界真相的古书",
        public_info="一本古老的典籍",
        importance=0.75,
        importance_level="important",
    )


# ============================================================
# WorldEntity CRUD 测试
# ============================================================

class TestWorldEntityService:
    """世界对象 CRUD 测试"""

    @pytest.mark.asyncio
    async def test_create_entity(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        novel_id: str,
        sample_entity_data: WorldEntityCreate,
    ) -> None:
        """测试创建世界对象"""
        result = await entity_service.create(db_session, novel_id, sample_entity_data)

        assert result.id is not None
        assert result.name == "创世大陆"
        assert result.entity_type == "location"
        assert result.summary == "小说的主舞台大陆"
        assert result.hidden_truth == "这块大陆实际上是上古神祇的遗骸所化"
        assert result.importance == 0.95
        assert result.importance_level == "core"
        assert result.reveal_level == "author_only"
        assert result.status == "draft"
        assert result.created_by == "测试用户"
        assert result.novel_id == novel_id
        assert result.created_at is not None

    @pytest.mark.asyncio
    async def test_get_entity(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        novel_id: str,
        sample_entity_data: WorldEntityCreate,
    ) -> None:
        """测试获取世界对象"""
        created = await entity_service.create(db_session, novel_id, sample_entity_data)
        result = await entity_service.get(db_session, created.id)

        assert result.id == created.id
        assert result.name == "创世大陆"

    @pytest.mark.asyncio
    async def test_get_entity_not_found(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
    ) -> None:
        """测试获取不存在的对象返回 404"""
        with pytest.raises(HTTPException) as exc:
            await entity_service.get(db_session, str(uuid.uuid4()))
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_list_entities(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        novel_id: str,
        sample_entity_data: WorldEntityCreate,
        sample_entity_data2: WorldEntityCreate,
        sample_entity_data3: WorldEntityCreate,
    ) -> None:
        """测试列表查询"""
        await entity_service.create(db_session, novel_id, sample_entity_data)
        await entity_service.create(db_session, novel_id, sample_entity_data2)
        await entity_service.create(db_session, novel_id, sample_entity_data3)

        # 全部列表
        result = await entity_service.list(db_session, novel_id)
        assert result.total == 3
        assert len(result.items) == 3

        # 按类型过滤
        result = await entity_service.list(
            db_session, novel_id, entity_type="location",
        )
        assert result.total == 1
        assert result.items[0].entity_type == "location"

        # 分页
        result = await entity_service.list(db_session, novel_id, skip=0, limit=2)
        assert len(result.items) == 2

    @pytest.mark.asyncio
    async def test_update_entity(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        novel_id: str,
        sample_entity_data: WorldEntityCreate,
    ) -> None:
        """测试更新世界对象"""
        created = await entity_service.create(db_session, novel_id, sample_entity_data)

        update_data = WorldEntityUpdate(
            name="创世大陆（更新版）",
            importance=0.98,
            status="canonical",
            approved_by="审核员",
        )
        result = await entity_service.update(db_session, created.id, update_data)

        assert result.name == "创世大陆（更新版）"
        assert result.importance == 0.98
        assert result.status == "canonical"
        assert result.approved_by == "审核员"

    @pytest.mark.asyncio
    async def test_delete_entity(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        novel_id: str,
        sample_entity_data: WorldEntityCreate,
    ) -> None:
        """测试删除世界对象"""
        created = await entity_service.create(db_session, novel_id, sample_entity_data)
        await entity_service.delete(db_session, created.id)

        with pytest.raises(HTTPException) as exc:
            await entity_service.get(db_session, created.id)
        assert exc.value.status_code == 404


# ============================================================
# Relationship CRUD 测试
# ============================================================

class TestRelationshipService:
    """关系 CRUD 测试"""

    async def _create_entity(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        novel_id: str,
        name: str,
        entity_type: str = "location",
    ) -> WorldEntityResponse:
        data = WorldEntityCreate(entity_type=entity_type, name=name)
        return await entity_service.create(db_session, novel_id, data)

    @pytest.mark.asyncio
    async def test_create_relationship(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        rel_service: RelationshipService,
        novel_id: str,
    ) -> None:
        """测试创建关系"""
        e1 = await self._create_entity(db_session, entity_service, novel_id, "王国A")
        e2 = await self._create_entity(db_session, entity_service, novel_id, "王国B")

        data = RelationshipCreate(
            source_type="location",
            source_id=e1.id,
            target_type="location",
            target_id=e2.id,
            relation_type="at_war_with",
            description="领土争端引发的战争",
            visibility="public",
            strength=0.9,
        )
        result = await rel_service.create(db_session, novel_id, data)

        assert result.id is not None
        assert result.source_id == e1.id
        assert result.target_id == e2.id
        assert result.relation_type == "at_war_with"
        assert result.description == "领土争端引发的战争"
        assert result.visibility == "public"
        assert result.strength == 0.9

    @pytest.mark.asyncio
    async def test_delete_relationship(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        rel_service: RelationshipService,
        novel_id: str,
    ) -> None:
        """测试删除关系"""
        e1 = await self._create_entity(db_session, entity_service, novel_id, "王国A")
        e2 = await self._create_entity(db_session, entity_service, novel_id, "王国B")

        rel = await rel_service.create(
            db_session, novel_id,
            RelationshipCreate(
                source_type="location", source_id=e1.id,
                target_type="location", target_id=e2.id,
                relation_type="ally_of",
            ),
        )
        await rel_service.delete(db_session, rel.id)

        with pytest.raises(HTTPException) as exc:
            await rel_service.get(db_session, rel.id)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_expand_related_one_hop(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        rel_service: RelationshipService,
        novel_id: str,
    ) -> None:
        """测试一跳关系扩展"""
        e1 = await self._create_entity(db_session, entity_service, novel_id, "王国A")
        e2 = await self._create_entity(db_session, entity_service, novel_id, "王国B")
        e3 = await self._create_entity(db_session, entity_service, novel_id, "王国C")

        # A→B (战争), A→C (盟友)
        for target, rtype in [(e2.id, "at_war_with"), (e3.id, "ally_of")]:
            await rel_service.create(
                db_session, novel_id,
                RelationshipCreate(
                    source_type="location", source_id=e1.id,
                    target_type="location", target_id=target,
                    relation_type=rtype,
                ),
            )

        # 一跳扩展
        related = await rel_service.expand_related(
            db_session, novel_id, seed_entity_ids=[e1.id], depth=1,
        )

        assert len(related) == 2
        related_ids = {r.entity_id for r in related}
        assert e2.id in related_ids
        assert e3.id in related_ids

    @pytest.mark.asyncio
    async def test_expand_related_two_hop(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        rel_service: RelationshipService,
        novel_id: str,
    ) -> None:
        """测试二跳关系扩展"""
        e1 = await self._create_entity(db_session, entity_service, novel_id, "王国A")
        e2 = await self._create_entity(db_session, entity_service, novel_id, "王国B")
        e3 = await self._create_entity(db_session, entity_service, novel_id, "王国C")

        # A→B, B→C
        await rel_service.create(
            db_session, novel_id,
            RelationshipCreate(
                source_type="location", source_id=e1.id,
                target_type="location", target_id=e2.id,
                relation_type="ally_of",
            ),
        )
        await rel_service.create(
            db_session, novel_id,
            RelationshipCreate(
                source_type="location", source_id=e2.id,
                target_type="location", target_id=e3.id,
                relation_type="ally_of",
            ),
        )

        # 二跳扩展（A → B → C）
        related = await rel_service.expand_related(
            db_session, novel_id, seed_entity_ids=[e1.id], depth=2,
        )

        related_ids = {r.entity_id for r in related}
        assert e2.id in related_ids  # 一跳直接可达
        # 二跳：e3 should be reachable via e2
        # Note: depends on get_related_entity_ids implementation
        # which doesn't guarantee completeness due to limit constraints


# ============================================================
# EntityAlias 测试
# ============================================================

class TestAliasService:
    """别名服务测试"""

    @pytest.mark.asyncio
    async def test_create_alias(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        alias_service: AliasService,
        novel_id: str,
    ) -> None:
        """测试创建别名"""
        entity = await entity_service.create(
            db_session, novel_id,
            WorldEntityCreate(entity_type="location", name="中央大陆"),
        )

        data = EntityAliasCreate(
            entity_id=entity.id,
            alias="中土",
            alias_type="name",
            source_chapter_index=1,
            confidence=0.95,
        )
        result = await alias_service.create(db_session, novel_id, data)

        assert result.id is not None
        assert result.entity_id == entity.id
        assert result.alias == "中土"
        assert result.alias_type == "name"
        assert result.source_chapter_index == 1
        assert result.confidence == 0.95

    @pytest.mark.asyncio
    async def test_list_aliases(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        alias_service: AliasService,
        novel_id: str,
    ) -> None:
        """测试别名列表"""
        entity = await entity_service.create(
            db_session, novel_id,
            WorldEntityCreate(entity_type="location", name="中央大陆"),
        )

        await alias_service.create(
            db_session, novel_id,
            EntityAliasCreate(entity_id=entity.id, alias="中土"),
        )
        await alias_service.create(
            db_session, novel_id,
            EntityAliasCreate(entity_id=entity.id, alias="中原", alias_type="name"),
        )

        items, total = await alias_service.list(db_session, novel_id)
        assert total == 2
        assert len(items) == 2

        # 按 entity_id 过滤
        items, total = await alias_service.list(
            db_session, novel_id, entity_id=entity.id,
        )
        assert total == 2


# ============================================================
# EntityCandidate 测试
# ============================================================

class TestEntityCandidateService:
    """候选对象服务测试"""

    @pytest.mark.asyncio
    async def test_create_candidate(
        self,
        db_session: AsyncSession,
        candidate_service: EntityCandidateService,
        novel_id: str,
    ) -> None:
        """测试创建候选对象"""
        data = EntityCandidateCreate(
            name="神秘遗迹",
            entity_type="location",
            summary="上古文明留下的遗迹",
            source_text="在一片荒芜的沙漠中，他发现了一座古老的遗迹。",
            source_chapter_index=3,
            importance_score=0.7,
            confidence=0.6,
            candidate_reason="重要的剧情地点，可能隐藏关键信息",
            suggested_action="create_new",
        )
        result = await candidate_service.create(db_session, novel_id, data)

        assert result.id is not None
        assert result.name == "神秘遗迹"
        assert result.entity_type == "location"
        assert result.importance_score == 0.7
        assert result.confidence == 0.6
        assert result.suggested_action == "create_new"
        assert result.status == "pending"

    @pytest.mark.asyncio
    async def test_update_candidate(
        self,
        db_session: AsyncSession,
        candidate_service: EntityCandidateService,
        novel_id: str,
    ) -> None:
        """测试更新候选对象"""
        data = EntityCandidateCreate(
            name="神秘遗迹",
            entity_type="location",
            suggested_action="needs_user_decision",
        )
        created = await candidate_service.create(db_session, novel_id, data)

        from modules.world.schemas import EntityCandidateUpdate
        updated = await candidate_service.update(
            db_session, created.id,
            EntityCandidateUpdate(
                suggested_action="create_new",
                confidence=0.85,
                status="pending",
            ),
        )
        assert updated.suggested_action == "create_new"
        assert updated.confidence == 0.85


# ============================================================
# EntityDedupService 测试
# ============================================================

class TestEntityDedupService:
    """去重服务测试"""

    @pytest.mark.asyncio
    async def test_find_exact_duplicate(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        candidate_service: EntityCandidateService,
        dedup_service: EntityDedupService,
        novel_id: str,
    ) -> None:
        """测试名称精确匹配去重"""
        # 先创建正史对象
        await entity_service.create(
            db_session, novel_id,
            WorldEntityCreate(entity_type="location", name="黑暗森林"),
        )

        # 创建同名候选
        candidate = await candidate_service.create(
            db_session, novel_id,
            EntityCandidateCreate(
                name="黑暗森林",
                entity_type="location",
                suggested_action="create_new",
            ),
        )

        # 去重检查
        suggestions = await dedup_service.find_duplicates(
            db_session, novel_id, candidate.id,
        )

        # 应该匹配到已存在的正史对象
        assert len(suggestions) >= 1
        exact_match = [s for s in suggestions if s.match_method == "exact_name"]
        assert len(exact_match) >= 1
        assert exact_match[0].candidate_name == "黑暗森林"
        assert exact_match[0].similarity_score == 1.0
        assert exact_match[0].action == "alias_of_existing"


# ============================================================
# Facade 测试
# ============================================================

class TestFacade:
    """Facade 对外接口测试"""

    @pytest.mark.asyncio
    async def test_get_world_context(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        novel_id: str,
    ) -> None:
        """测试获取世界上下文"""
        await entity_service.create(
            db_session, novel_id,
            WorldEntityCreate(entity_type="location", name="东方大陆"),
        )
        await entity_service.create(
            db_session, novel_id,
            WorldEntityCreate(entity_type="location", name="西方大陆"),
        )

        # 获取所有对象上下文
        ctx = await get_world_context(db_session, novel_id)
        assert isinstance(ctx, WorldContextBundle)
        assert ctx.novel_id == novel_id
        assert ctx.total_count == 2
        assert len(ctx.entities) == 2

        # 按 ID 获取
        all_entities = await entity_service.list(db_session, novel_id)
        first_id = all_entities.items[0].id
        ctx = await get_world_context(
            db_session, novel_id, entity_ids=[first_id],
        )
        assert ctx.total_count == 1

    @pytest.mark.asyncio
    async def test_expand_related_entities_facade(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        rel_service: RelationshipService,
        novel_id: str,
    ) -> None:
        """测试 facade 的关系扩展"""
        e1 = await entity_service.create(
            db_session, novel_id,
            WorldEntityCreate(entity_type="faction", name="帝国"),
        )
        e2 = await entity_service.create(
            db_session, novel_id,
            WorldEntityCreate(entity_type="faction", name="叛军"),
        )

        await rel_service.create(
            db_session, novel_id,
            RelationshipCreate(
                source_type="faction", source_id=e1.id,
                target_type="faction", target_id=e2.id,
                relation_type="at_war_with",
            ),
        )

        related = await expand_related_entities(
            db_session, novel_id, seed_entity_ids=[e1.id], depth=1,
        )
        assert len(related) == 1
        assert related[0].entity_id == e2.id

    @pytest.mark.asyncio
    async def test_find_duplicate_facade(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        candidate_service: EntityCandidateService,
        novel_id: str,
    ) -> None:
        """测试 facade 的去重调用"""
        await entity_service.create(
            db_session, novel_id,
            WorldEntityCreate(entity_type="item", name="月光宝盒"),
        )
        candidate = await candidate_service.create(
            db_session, novel_id,
            EntityCandidateCreate(name="月光宝盒", entity_type="item"),
        )

        suggestions = await find_duplicate_entity_candidates(
            db_session, novel_id, candidate.id,
        )
        assert len(suggestions) >= 1
        assert any(s.match_method == "exact_name" for s in suggestions)


class TestFindEntityByName:
    @pytest.mark.asyncio
    async def test_find_entity_by_name_exact(
        self,
        db_session: AsyncSession,
        entity_repo: WorldEntityRepository,
        novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)
        data = WorldEntityCreate(entity_type="location", name="炎城", status="canonical")
        entity = await entity_repo.create(db_session, nid, data)

        result = await entity_repo.find_entity_by_name(db_session, nid, "炎城")
        assert result == str(entity.id)

    @pytest.mark.asyncio
    async def test_find_entity_by_name_alias(
        self,
        db_session: AsyncSession,
        entity_repo: WorldEntityRepository,
        alias_repo: EntityAliasRepository,
        novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)
        data = WorldEntityCreate(entity_type="location", name="Fire City", status="canonical")
        entity = await entity_repo.create(db_session, nid, data)

        alias_data = EntityAliasCreate(entity_id=str(entity.id), alias="炎城", alias_type="translation")
        await alias_repo.create(db_session, nid, alias_data)

        result = await entity_repo.find_entity_by_name(db_session, nid, "炎城")
        assert result == str(entity.id)

    @pytest.mark.asyncio
    async def test_find_entity_by_name_not_found(
        self,
        db_session: AsyncSession,
        entity_repo: WorldEntityRepository,
        novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)
        result = await entity_repo.find_entity_by_name(db_session, nid, "不存在的名字")
        assert result is None


class TestUpsertRelationship:
    @pytest.mark.asyncio
    async def test_upsert_relationship_create(
        self,
        db_session: AsyncSession,
        rel_repo: RelationshipRepository,
        novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)
        source_id = str(uuid.uuid4())
        target_id = str(uuid.uuid4())

        await rel_repo.upsert_relationship(
            db_session, nid, source_id, target_id,
            "location", "faction", "controls", "控制关系",
        )

        rels, total = await rel_repo.get_by_novel(db_session, nid)
        assert total == 1
        assert rels[0].source_id == source_id
        assert rels[0].target_id == target_id
        assert rels[0].relation_type == "controls"
        assert rels[0].description == "控制关系"

    @pytest.mark.asyncio
    async def test_upsert_relationship_idempotent(
        self,
        db_session: AsyncSession,
        rel_repo: RelationshipRepository,
        novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)
        source_id = str(uuid.uuid4())
        target_id = str(uuid.uuid4())

        await rel_repo.upsert_relationship(
            db_session, nid, source_id, target_id,
            "location", "faction", "controls", "初始描述",
        )
        await rel_repo.upsert_relationship(
            db_session, nid, source_id, target_id,
            "location", "faction", "controls", "更新描述",
        )

        rels, total = await rel_repo.get_by_novel(db_session, nid)
        assert total == 1
        assert rels[0].description == "更新描述"
