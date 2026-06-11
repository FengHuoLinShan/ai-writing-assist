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
    find_entity_id_by_name,
    get_world_context,
    list_entity_terms,
)
from modules.world.repositories import (
    CoreEntityRepository,
    EntityRelationRepository,
)
from modules.world.schemas import (
    EntityRelationCreate,
    WorldContextBundle,
    WorldEntityCreate,
    WorldEntityUpdate,
)
from modules.world.services import (
    WorldEntityService,
)
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
        result = await entity_service.get(
            db_session,
            created.id,
            novel_id=novel_id,
        )

        assert result.id == created.id
        assert result.name == "创世大陆"

    @pytest.mark.asyncio
    async def test_get_entity_not_found(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        novel_id: str,
    ) -> None:
        """测试获取不存在的对象返回 404"""
        with pytest.raises(HTTPException) as exc:
            await entity_service.get(
                db_session,
                str(uuid.uuid4()),
                novel_id=novel_id,
            )
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
            db_session,
            novel_id,
            entity_type="location",
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
        result = await entity_service.update(
            db_session,
            created.id,
            update_data,
            novel_id=novel_id,
        )

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
        await entity_service.delete(db_session, created.id, novel_id=novel_id)

        with pytest.raises(HTTPException) as exc:
            await entity_service.get(
                db_session,
                created.id,
                novel_id=novel_id,
            )
        assert exc.value.status_code == 404


class TestEntityDedupService:
    """去重服务测试"""

    @pytest.mark.asyncio
    async def test_find_exact_duplicate(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        dedup_service: EntityDedupService,
        novel_id: str,
    ) -> None:
        """测试名称精确匹配去重。

        minimal-core 后, "候选" 不再是独立表 — AI 抽取直接入库为 draft,
        然后 dedup_service 对 draft 实体做去重检查。
        """
        import uuid as _uuid

        from modules.world.models import CoreEntity

        # 先创建正史对象
        await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="location", name="黑暗森林"),
        )

        # 创建同名 draft 实体 (模拟 AI 抽取直接入库)
        draft = CoreEntity(
            id=_uuid.uuid4(),
            novel_id=_uuid.UUID(hex=novel_id),
            entity_type="location",
            name="黑暗森林",
            status="draft",
        )
        db_session.add(draft)
        await db_session.flush()

        # 去重检查
        suggestions = await dedup_service.find_duplicates(
            db_session,
            novel_id,
            str(draft.id),
        )

        # 应该匹配到已存在的正史对象
        assert len(suggestions) >= 1
        exact_match = [s for s in suggestions if s.match_method == "exact_name"]
        assert len(exact_match) >= 1
        assert exact_match[0].candidate_name == "黑暗森林"
        assert exact_match[0].similarity_score == 1.0
        assert exact_match[0].action in ("merge_with_existing", "alias_of_existing")

    # ============================================================
    # TDD 路径 1.1：高置信度静默合并
    # ============================================================

    @pytest.mark.asyncio
    async def test_high_confidence_silent_merge(
        self,
        db_session: AsyncSession,
        entity_repo: CoreEntityRepository,
        dedup_service: EntityDedupService,
        novel_id: str,
    ) -> None:
        """路径 1.1：精确名称匹配 → 自动合并，别名继承，无需 LLM 仲裁"""
        import uuid as _uuid

        nid = _uuid.UUID(novel_id)

        # Given: 正史实体 "李四"
        target = await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name="李四",
            status="canonical",
        )

        # Given: 候选实体 "李四"（带别名）
        candidate = await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name="李四",
            status="draft",
            content_json={"aliases": [{"alias": "四哥", "type": "nickname"}]},
        )

        # When: 去重检测
        suggestions = await dedup_service.find_similar_entities(
            db_session,
            novel_id,
            name="李四",
            entity_type="character",
        )

        # Then: 高置信度匹配
        assert len(suggestions) >= 1
        exact = [s for s in suggestions if s.match_method == "exact_name"]
        assert len(exact) >= 1
        assert exact[0].similarity_score == 1.0
        assert exact[0].action == "merge_with_existing"

        # When: 执行合并
        result = await dedup_service.merge_candidate_into_entity(
            db_session,
            novel_id,
            str(candidate.id),
            str(target.id),
        )

        # Then: 合并统计
        assert result.aliases_inherited >= 1
        assert result.target_entity_id == str(target.id)
        assert result.candidate_entity_id == str(candidate.id)

        # Then: candidate 状态 → merged
        await db_session.refresh(candidate)
        assert candidate.status == "merged"
        assert candidate.content_json.get("merged_into") == str(target.id)
        assert "merged_at" in candidate.content_json

        # Then: target 别名增加
        await db_session.refresh(target)
        target_aliases = target.content_json.get("aliases", [])
        alias_texts = [
            a.get("alias", "") if isinstance(a, dict) else str(a) for a in target_aliases
        ]
        assert "四哥" in alias_texts
        assert target.status == "canonical"

    # ============================================================
    # TDD 路径 1.2：低置信度独立建档
    # ============================================================

    @pytest.mark.asyncio
    async def test_low_confidence_independent_filing(
        self,
        db_session: AsyncSession,
        entity_repo: CoreEntityRepository,
        dedup_service: EntityDedupService,
        novel_id: str,
    ) -> None:
        """路径 1.2：无匹配候选 → 自动提升为 canonical"""
        import uuid as _uuid

        nid = _uuid.UUID(novel_id)

        # Given: 正史实体 "李四"
        await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name="李四",
            status="canonical",
        )

        # Given: 候选实体 "王五"（完全无关的名字）
        candidate = await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name="王五",
            status="draft",
        )

        # When: 自动决议
        result = await dedup_service.resolve_candidate(
            db_session,
            novel_id,
            str(candidate.id),
        )

        # Then: 无匹配 → 提升为 canonical
        assert result.action == "promoted"
        assert result.merge_result is None
        assert result.promoted_entity_id == str(candidate.id)

        # Then: candidate 状态已变更
        await db_session.refresh(candidate)
        assert candidate.status == "canonical"

    # ============================================================
    # TDD 路径 1.3：事务性关系重定向与自环清理
    # ============================================================

    @pytest.mark.asyncio
    async def test_relation_redirection_and_self_loop_cleanup(
        self,
        db_session: AsyncSession,
        entity_repo: CoreEntityRepository,
        rel_repo: EntityRelationRepository,
        dedup_service: EntityDedupService,
        novel_id: str,
    ) -> None:
        """路径 1.3：A' 合并入 A，关系重定向，迁移自环被清理"""
        import uuid as _uuid

        nid = _uuid.UUID(novel_id)

        # Given: 正史实体 A, B, C
        entity_a = await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name="A",
            status="canonical",
        )
        entity_b = await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name="B",
            status="canonical",
        )
        entity_c = await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name="C",
            status="canonical",
        )

        # Given: 候选实体 A'（draft）
        candidate_a = await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name="A'",
            status="draft",
        )

        # Given: A → B（A 认识 B）
        await rel_repo.upsert(
            db_session,
            nid,
            entity_a.id,
            entity_b.id,
            "knows",
            "A 认识 B",
        )
        # Given: A' → C（A' 认识 C）
        await rel_repo.upsert(
            db_session,
            nid,
            candidate_a.id,
            entity_c.id,
            "knows",
            "A' 认识 C",
        )
        # Given: A' → A（A' 怀疑 A — 合并后会变自环）
        await rel_repo.upsert(
            db_session,
            nid,
            candidate_a.id,
            entity_a.id,
            "suspects",
            "A' 怀疑 A",
        )

        # When: 合并 A' → A
        result = await dedup_service.merge_candidate_into_entity(
            db_session,
            novel_id,
            str(candidate_a.id),
            str(entity_a.id),
        )

        # Then: 关系迁移统计
        assert result.relations_migrated == 2  # A'→C 重定向为 A→C, A'→A 重定向为 A→A
        assert result.self_loops_cleaned == 1  # A→A 自环被标记 deprecated

        # Then: A 的关系查询
        all_rels = await rel_repo.get_all_for_entity(db_session, nid, entity_a.id)
        # A→B (canonical) + A→C (canonical) + 可能的 A→A (deprecated)
        canonical_rels = [r for r in all_rels if r.status == "canonical"]
        assert len(canonical_rels) >= 2

        # Then: A→C 重定向成功
        a_to_c = [
            r
            for r in all_rels
            if r.source_id == entity_a.id
            and r.target_id == entity_c.id
            and r.status == "canonical"
        ]
        assert len(a_to_c) == 1
        assert a_to_c[0].relation_type == "knows"

        # Then: A→B 不受影响
        a_to_b = [
            r
            for r in all_rels
            if r.source_id == entity_a.id
            and r.target_id == entity_b.id
            and r.status == "canonical"
        ]
        assert len(a_to_b) == 1

        # Then: 自环关系被标记 deprecated
        self_loops = [
            r
            for r in all_rels
            if r.source_id == entity_a.id and r.target_id == entity_a.id
        ]
        for sl in self_loops:
            assert sl.status == "deprecated", (
                f"自环 {sl.id} 应为 deprecated，实际为 {sl.status}"
            )

    # ============================================================
    # TDD 路径 1.4：设定冲突的静默归档
    # ============================================================

    @pytest.mark.asyncio
    async def test_conflict_silent_archiving(
        self,
        db_session: AsyncSession,
        entity_repo: CoreEntityRepository,
        dedup_service: EntityDedupService,
        novel_id: str,
    ) -> None:
        """路径 1.4：content_json 冲突字段 → 正史值保留，候选值写入 conflict_notes"""
        import uuid as _uuid

        nid = _uuid.UUID(novel_id)

        # Given: 正史实体 A（使用长剑、御剑术）
        entity_a = await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name="剑客A",
            status="canonical",
            content_json={
                "weapon": "使用长剑",
                "ability": "御剑术",
            },
        )

        # Given: 候选实体 A'（使用断刀、御剑术）
        candidate_a = await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name="剑客A",
            status="draft",
            content_json={
                "weapon": "使用断刀",
                "ability": "御剑术",
            },
        )

        # When: 合并 A' → A
        result = await dedup_service.merge_candidate_into_entity(
            db_session,
            novel_id,
            str(candidate_a.id),
            str(entity_a.id),
        )

        # Then: 冲突统计
        assert result.conflicts_archived == 1  # 只有 weapon 冲突

        # Then: target weapon 保持正史值
        await db_session.refresh(entity_a)
        assert entity_a.content_json.get("weapon") == "使用长剑"

        # Then: conflict_notes 记录冲突
        conflict_notes = entity_a.content_json.get("meta", {}).get("conflict_notes", [])
        assert len(conflict_notes) == 1
        assert conflict_notes[0]["field"] == "weapon"
        assert conflict_notes[0]["canonical_value"] == "使用长剑"
        assert conflict_notes[0]["candidate_value"] == "使用断刀"
        assert conflict_notes[0]["candidate_id"] == str(candidate_a.id)

        # Then: ability 不产生冲突（双方一致）
        assert entity_a.content_json.get("ability") == "御剑术"


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
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="location", name="东方大陆"),
        )
        await entity_service.create(
            db_session,
            novel_id,
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
            db_session,
            novel_id,
            entity_ids=[first_id],
        )
        assert ctx.total_count == 1

    @pytest.mark.asyncio
    async def test_expand_related_entities_facade(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        novel_id: str,
    ) -> None:
        """测试 facade 的 expand_related_entities 委派到新 EntityRelationService"""
        from modules.world.services import EntityRelationService

        rel_service = EntityRelationService()

        e1 = await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="location", name="A"),
        )
        e2 = await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(entity_type="location", name="B"),
        )
        await rel_service.create(
            db_session,
            novel_id,
            EntityRelationCreate(
                source_id=e1.id,
                target_id=e2.id,
                relation_type="ally_of",
            ),
        )

        related = await expand_related_entities(
            db_session,
            novel_id,
            seed_entity_ids=[e1.id],
            depth=1,
        )
        assert len(related) == 1
        assert related[0].entity_id == e2.id


class TestFindEntityByName:
    @pytest.mark.asyncio
    async def test_find_entity_by_name_exact(
        self,
        db_session: AsyncSession,
        entity_repo: CoreEntityRepository,
        novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)
        data = WorldEntityCreate(entity_type="location", name="炎城", status="canonical")
        entity = await entity_repo.create(db_session, nid, data)

        result = await entity_repo.find_entity_by_name(db_session, nid, "炎城")
        assert result == str(entity.id)

    @pytest.mark.asyncio
    async def test_find_entity_by_name_not_found(
        self,
        db_session: AsyncSession,
        entity_repo: CoreEntityRepository,
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
        rel_repo: EntityRelationRepository,
        novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)
        source_id = uuid.uuid4()
        target_id = uuid.uuid4()

        await rel_repo.upsert(
            db_session,
            nid,
            source_id,
            target_id,
            "controls",
            "控制关系",
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
        rel_repo: EntityRelationRepository,
        novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)
        source_id = uuid.uuid4()
        target_id = uuid.uuid4()

        await rel_repo.upsert(
            db_session,
            nid,
            source_id,
            target_id,
            "controls",
            "初始描述",
        )
        await rel_repo.upsert(
            db_session,
            nid,
            source_id,
            target_id,
            "controls",
            "更新描述",
        )

        rels, total = await rel_repo.get_by_novel(db_session, nid)
        assert total == 1
        assert rels[0].description == "更新描述"


# ============================================================
# Characterization tests for facade leaks (PR 2)
# 锁定行为, 后续 leak 下沉到 service 时不能破
# ============================================================


class TestFacadeLeakListEntityTerms:
    @pytest.mark.asyncio
    async def test_returns_canonical_and_draft_with_aliases(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        """list_entity_terms 返 canonical + draft 实体, 包含 content_json.aliases。"""
        from modules.world.models import CoreEntity

        nid = uuid.UUID(hex=novel_id)
        canonical = CoreEntity(
            id=uuid.uuid4(),
            novel_id=nid,
            entity_type="location",
            name="主城",
            status="canonical",
            content_json={"aliases": [{"alias": "王城"}, {"alias": "都城"}]},
        )
        draft = CoreEntity(
            id=uuid.uuid4(),
            novel_id=nid,
            entity_type="item",
            name="草稿宝物",
            status="draft",
        )
        deprecated = CoreEntity(
            id=uuid.uuid4(),
            novel_id=nid,
            entity_type="item",
            name="已废弃物",
            status="deprecated",
        )
        db_session.add_all([canonical, draft, deprecated])
        await db_session.flush()

        terms = await list_entity_terms(db_session, novel_id)

        by_name = {t["name"]: t for t in terms}
        assert set(by_name.keys()) == {"主城", "草稿宝物"}
        assert by_name["主城"]["terms"] == ["主城", "王城", "都城"]
        assert by_name["草稿宝物"]["terms"] == ["草稿宝物"]


class TestFacadeLeakFindEntityIdByName:
    @pytest.mark.asyncio
    async def test_finds_canonical_entity_id(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        from modules.world.models import CoreEntity

        nid = uuid.UUID(hex=novel_id)
        entity = CoreEntity(
            id=uuid.uuid4(),
            novel_id=nid,
            entity_type="location",
            name="炎城",
            status="canonical",
        )
        db_session.add(entity)
        await db_session.flush()

        result = await find_entity_id_by_name(db_session, novel_id, "炎城")

        assert result == str(entity.id)

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        result = await find_entity_id_by_name(
            db_session,
            novel_id,
            "不存在的名字",
        )
        assert result is None


# 5 character leak characterization tests
from modules.world.facade import (  # noqa: E402
    find_character_id_by_name,
    get_character_id_by_world_entity,
    get_character_location_id,
    get_characters_at_location,
    update_character_location,
)


class TestFacadeLeakGetCharacterIdByWorldEntity:
    @pytest.mark.asyncio
    async def test_returns_str_entity_id_when_character_exists(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        from modules.world.models import Character

        entity_id = uuid.uuid4()
        char = Character(
            entity_id=entity_id,
            novel_id=uuid.UUID(hex=novel_id),
            name="主角",
        )
        db_session.add(char)
        await db_session.flush()

        result = await get_character_id_by_world_entity(
            db_session,
            novel_id,
            str(entity_id),
        )
        assert result == str(entity_id)

    @pytest.mark.asyncio
    async def test_returns_none_when_character_missing(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        result = await get_character_id_by_world_entity(
            db_session,
            novel_id,
            str(uuid.uuid4()),
        )
        assert result is None


class TestFacadeLeakFindCharacterIdByName:
    @pytest.mark.asyncio
    async def test_finds_character_id_by_name(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        from modules.world.models import Character

        entity_id = uuid.uuid4()
        char = Character(
            entity_id=entity_id,
            novel_id=uuid.UUID(hex=novel_id),
            name="李白",
            status="canonical",
        )
        db_session.add(char)
        await db_session.flush()

        result = await find_character_id_by_name(db_session, novel_id, "李白")
        assert result == str(entity_id)

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        result = await find_character_id_by_name(
            db_session,
            novel_id,
            "不存在的角色",
        )
        assert result is None


class TestFacadeLeakUpdateCharacterLocation:
    @pytest.mark.asyncio
    async def test_updates_meta_location(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        from modules.world.models import Character

        entity_id = uuid.uuid4()
        loc_id = uuid.uuid4()
        char = Character(
            entity_id=entity_id,
            novel_id=uuid.UUID(hex=novel_id),
            name="主角",
            status="canonical",
        )
        db_session.add(char)
        await db_session.flush()

        await update_character_location(
            db_session,
            novel_id,
            str(entity_id),
            str(loc_id),
            "在城门口",
            3,
        )

        # 验证 meta 写入 — 用 repo 直接读
        from modules.world.repositories import CharacterRepository

        repo = CharacterRepository()
        refreshed = await repo.get(db_session, entity_id)
        assert refreshed is not None
        assert refreshed.meta.get("location_id") == str(loc_id)
        assert refreshed.meta.get("text_state") == "在城门口"
        assert refreshed.meta.get("chapter_index") == 3


class TestFacadeLeakGetCharactersAtLocation:
    @pytest.mark.asyncio
    async def test_finds_characters_at_location(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        from modules.world.models import Character

        loc_id = uuid.uuid4()
        char = Character(
            entity_id=uuid.uuid4(),
            novel_id=uuid.UUID(hex=novel_id),
            name="在城门口的人",
            status="canonical",
            meta={"location_id": str(loc_id)},
        )
        db_session.add(char)
        await db_session.flush()

        result = await get_characters_at_location(
            db_session,
            novel_id,
            str(loc_id),
        )
        assert len(result) == 1
        assert result[0]["name"] == "在城门口的人"


class TestFacadeLeakGetCharacterLocationId:
    @pytest.mark.asyncio
    async def test_returns_location_id_when_set(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        from modules.world.models import Character

        loc_id = uuid.uuid4()
        char = Character(
            entity_id=uuid.uuid4(),
            novel_id=uuid.UUID(hex=novel_id),
            name="有位置的人",
            status="canonical",
            meta={"location_id": str(loc_id)},
        )
        db_session.add(char)
        await db_session.flush()

        result = await get_character_location_id(
            db_session,
            novel_id,
            str(char.entity_id),
        )
        assert result == str(loc_id)

    @pytest.mark.asyncio
    async def test_returns_none_when_no_location(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        from modules.world.models import Character

        char = Character(
            entity_id=uuid.uuid4(),
            novel_id=uuid.UUID(hex=novel_id),
            name="无位置",
            status="canonical",
            meta={},
        )
        db_session.add(char)
        await db_session.flush()

        result = await get_character_location_id(
            db_session,
            novel_id,
            str(char.entity_id),
        )
        assert result is None
