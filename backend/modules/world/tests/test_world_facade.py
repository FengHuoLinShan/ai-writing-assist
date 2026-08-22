"""
World 模块测试

测试所有 CRUD 路径、facade、关系扩展、别名、候选和去重功能。
使用 pytest-asyncio 测试异步数据库操作。
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from core.errors import ConflictError, NotFoundError
from core.errors import ValidationError as DomainValidationError
from modules.world.facade import (
    expand_related_entities,
    find_entity_id_by_name,
    get_entity_importance_map,
    get_world_context,
    list_entity_terms,
)
from modules.world.models import CoreEntity, EntityRelation
from modules.world.repositories import (
    CoreEntityRepository,
    EntityRelationRepository,
)
from modules.world.schemas import (
    EntityRelationCreate,
    EntityRelationReviewEditRequest,
    EntityRelationUpdate,
    WorldContextBundle,
    WorldEntityCreate,
)
from modules.world.services import (
    WorldEntityService,
)
from modules.world.services.core.dedup_service import EntityDedupService
from modules.world.services.core.entity_relation_service import EntityRelationService
from modules.world.world_background import WorldBackgroundAggregation


@pytest.fixture
def novel_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def sample_novel_id(novel_id: str) -> str:
    return novel_id


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


@pytest.mark.asyncio
async def test_world_background_preserves_explicit_zero_float_signals(
    db_session: AsyncSession,
    project_novel_id: str,
) -> None:
    nid = uuid.UUID(project_novel_id)
    source = CoreEntity(
        novel_id=nid,
        entity_type="character",
        name="零权重人物",
        summary="明确低权重",
        importance=0.0,
        status="canonical",
    )
    target = CoreEntity(
        novel_id=nid,
        entity_type="location",
        name="零权重地点",
        summary="明确低权重",
        importance=0.0,
        status="canonical",
    )
    db_session.add_all([source, target])
    await db_session.flush()
    relation = EntityRelation(
        novel_id=nid,
        source_id=source.id,
        target_id=target.id,
        relation_type="observes",
        relation_kind="epistemic",
        strength=0.0,
        status="canonical",
    )
    db_session.add(relation)
    await db_session.flush()

    bundle = await WorldBackgroundAggregation().build(
        db_session,
        project_novel_id,
        context_mode="canonical",
    )
    by_id = {entry.asset_id: entry for entry in bundle.entries}

    assert by_id[str(source.id)].importance == 0.0
    assert by_id[str(target.id)].importance == 0.0
    assert by_id[str(relation.id)].importance == 0.0


@pytest.mark.asyncio
async def test_world_background_keeps_status_and_reveal_modes_independent(
    db_session: AsyncSession,
    project_novel_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nid = uuid.UUID(project_novel_id)
    canonical = CoreEntity(
        novel_id=nid,
        entity_type="location",
        name="白塔",
        summary="公开摘要",
        public_info="公开资料",
        hidden_truth="隐藏真相",
        importance=1.0,
        status="canonical",
    )
    draft = CoreEntity(
        novel_id=nid,
        entity_type="location",
        name="工作稿地点",
        summary="未采用",
        importance=0.9,
        status="draft",
    )
    db_session.add_all([canonical, draft])
    await db_session.flush()

    aggregation = WorldBackgroundAggregation()

    async def profile_summaries(_db, _novel_id):
        return {canonical.id: "地点档案"}

    async def event_summaries(_db, _novel_id):
        return {canonical.id: "事件时间线"}

    monkeypatch.setattr(aggregation, "_profile_summaries", profile_summaries)
    monkeypatch.setattr(aggregation, "_event_summaries", event_summaries)

    safe = await aggregation.build(
        db_session,
        project_novel_id,
        context_mode="canonical",
        reveal_mode="author_safe",
    )
    full = await aggregation.build(
        db_session,
        project_novel_id,
        context_mode="canonical",
        reveal_mode="author_full",
    )

    safe_entries = [item for item in safe.entries if item.asset_id == str(canonical.id)]
    full_entries = [item for item in full.entries if item.asset_id == str(canonical.id)]
    assert [item.asset_type for item in safe_entries] == ["entity"]
    assert "隐藏真相" not in safe_entries[0].summary
    assert {item.asset_type for item in full_entries} == {"entity", "profile", "event"}
    assert "隐藏真相" in next(
        item.summary for item in full_entries if item.asset_type == "entity"
    )
    assert all(item.asset_id != str(draft.id) for item in full.entries)

    with pytest.raises(ValueError, match="context_mode"):
        await aggregation.build(
            db_session,
            project_novel_id,
            context_mode="author_full",
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
            relation_kind="state",
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
            relation_kind="state",
        )
        await rel_repo.upsert(
            db_session,
            nid,
            source_id,
            target_id,
            "controls",
            "更新描述",
            relation_kind="state",
        )

        rels, total = await rel_repo.get_by_novel(db_session, nid)
        assert total == 1
        assert rels[0].description == "更新描述"

    @pytest.mark.asyncio
    async def test_list_relationships_excludes_deprecated_relations(
        self,
        db_session: AsyncSession,
        rel_repo: EntityRelationRepository,
        novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)
        source_id = uuid.uuid4()
        target_id = uuid.uuid4()

        rel = await rel_repo.create(
            db_session,
            nid,
            EntityRelationCreate(
                source_id=str(source_id),
                target_id=str(target_id),
                relation_type="controls",
                relation_kind="state",
                status="canonical",
            ),
        )
        await rel_repo.update(
            db_session,
            rel.id,
            EntityRelationUpdate(status="deprecated"),
        )

        rels, total = await rel_repo.get_by_novel(db_session, nid)

        assert total == 0
        assert rels == []
        assert await rel_repo.get(db_session, rel.id) is not None

    @pytest.mark.asyncio
    async def test_duplicate_and_all_for_entity_eager_load_endpoint_names(
        self,
        db_session: AsyncSession,
        entity_repo: CoreEntityRepository,
        rel_repo: EntityRelationRepository,
        novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)
        source = await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name="克莱恩",
            status="canonical",
        )
        target = await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name="伦纳德",
            status="canonical",
        )
        await rel_repo.create(
            db_session,
            nid,
            EntityRelationCreate(
                source_id=str(source.id),
                target_id=str(target.id),
                relation_type="ally_of",
                relation_kind="social",
                status="canonical",
            ),
        )

        duplicate = await rel_repo.find_duplicate_relation(
            db_session,
            nid,
            source.id,
            target.id,
            "ally_of",
        )
        all_for_source = await rel_repo.get_all_for_entity(
            db_session,
            nid,
            source.id,
        )

        assert duplicate is not None
        assert duplicate.source.name == "克莱恩"
        assert duplicate.target.name == "伦纳德"
        assert all_for_source[0].source.name == "克莱恩"
        assert all_for_source[0].target.name == "伦纳德"

    @pytest.mark.asyncio
    async def test_relation_review_edit_updates_endpoints_confirms_and_audits(
        self,
        db_session: AsyncSession,
        entity_repo: CoreEntityRepository,
        rel_repo: EntityRelationRepository,
        novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)
        source = await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name="克莱恩",
            status="canonical",
        )
        old_target = await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name="邓恩",
            status="canonical",
        )
        new_target = await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="organization",
            name="值夜者",
            status="canonical",
        )
        rel = await rel_repo.create(
            db_session,
            nid,
            EntityRelationCreate(
                source_id=str(source.id),
                target_id=str(old_target.id),
                relation_type="member_of",
                description="旧描述",
                strength=0.4,
                quote="证据",
                status="candidate",
            ),
        )
        rel.review_meta = {
            "source": "deep_import",
            "workflow_id": "wf-relation-review",
            "confidence": 0.84,
            "evidence_refs": [{"scene_id": "scene-1"}],
        }
        await db_session.flush()

        result = await EntityRelationService().review_edit(
            db_session,
            novel_id,
            str(rel.id),
            EntityRelationReviewEditRequest(
                target_id=str(new_target.id),
                relation_type="ally_of",
                description="新描述",
                strength=0.8,
                confirm_review=True,
            ),
        )

        await db_session.refresh(rel)
        assert rel.target_id == new_target.id
        assert rel.relation_type == "ally_of"
        assert rel.description == "新描述"
        assert rel.strength == 0.8
        assert rel.status == "canonical"
        assert rel.review_meta["reviewed_by"] == "manual"
        assert rel.review_meta["source"] == "deep_import"
        assert rel.review_meta["workflow_id"] == "wf-relation-review"
        assert rel.review_meta["confidence"] == 0.84
        assert rel.review_meta["evidence_refs"] == [{"scene_id": "scene-1"}]
        assert rel.review_meta["review_before"]["target_id"] == str(old_target.id)
        assert rel.review_meta["review_after"]["target_id"] == str(new_target.id)
        assert result["affected_ids"] == [str(rel.id)]

    @pytest.mark.asyncio
    async def test_relation_review_edit_duplicate_excludes_self_but_rejects_other(
        self,
        db_session: AsyncSession,
        entity_repo: CoreEntityRepository,
        rel_repo: EntityRelationRepository,
        novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)
        source = await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name="克莱恩",
            status="canonical",
        )
        target = await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name="伦纳德",
            status="canonical",
        )
        other = await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name="奥黛丽",
            status="canonical",
        )
        rel = await rel_repo.create(
            db_session,
            nid,
            EntityRelationCreate(
                source_id=str(source.id),
                target_id=str(target.id),
                relation_type="ally_of",
                status="candidate",
            ),
        )
        await EntityRelationService().review_edit(
            db_session,
            novel_id,
            str(rel.id),
            EntityRelationReviewEditRequest(confirm_review=True),
        )
        duplicate = await rel_repo.create(
            db_session,
            nid,
            EntityRelationCreate(
                source_id=str(source.id),
                target_id=str(other.id),
                relation_type="ally_of",
                relation_kind="social",
                status="canonical",
            ),
        )

        with pytest.raises(ConflictError) as exc:
            await EntityRelationService().review_edit(
                db_session,
                novel_id,
                str(duplicate.id),
                EntityRelationReviewEditRequest(target_id=str(target.id)),
            )
        assert "Relation already exists" in str(exc.value)

    @pytest.mark.asyncio
    async def test_relation_review_edit_rejects_retired_endpoint(
        self,
        db_session: AsyncSession,
        entity_repo: CoreEntityRepository,
        rel_repo: EntityRelationRepository,
        novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)
        source = await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name="克莱恩",
            status="canonical",
        )
        target = await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name="伦纳德",
            status="canonical",
        )
        retired = await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name="已合并对象",
            status="merged",
        )
        rel = await rel_repo.create(
            db_session,
            nid,
            EntityRelationCreate(
                source_id=str(source.id),
                target_id=str(target.id),
                relation_type="ally_of",
                status="candidate",
            ),
        )

        with pytest.raises(DomainValidationError):
            await EntityRelationService().review_edit(
                db_session,
                novel_id,
                str(rel.id),
                EntityRelationReviewEditRequest(source_id=str(retired.id)),
            )

    @pytest.mark.asyncio
    async def test_relation_review_edit_rejects_deprecated_relation(
        self,
        db_session: AsyncSession,
        entity_repo: CoreEntityRepository,
        rel_repo: EntityRelationRepository,
        novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)
        source = await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name="克莱恩",
            status="canonical",
        )
        target = await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name="伦纳德",
            status="canonical",
        )
        rel = await rel_repo.create(
            db_session,
            nid,
            EntityRelationCreate(
                source_id=str(source.id),
                target_id=str(target.id),
                relation_type="ally_of",
                status="deprecated",
            ),
        )

        with pytest.raises(DomainValidationError):
            await EntityRelationService().review_edit(
                db_session,
                novel_id,
                str(rel.id),
                EntityRelationReviewEditRequest(confirm_review=True),
            )
        await db_session.refresh(rel)
        assert rel.status == "deprecated"

    @pytest.mark.asyncio
    async def test_relation_update_status_writes_review_meta(
        self,
        db_session: AsyncSession,
        entity_repo: CoreEntityRepository,
        rel_repo: EntityRelationRepository,
        novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)
        source = await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name="克莱恩",
            status="canonical",
        )
        target = await entity_repo.create_raw(
            db_session,
            novel_id=nid,
            entity_type="character",
            name="伦纳德",
            status="canonical",
        )
        rel = await rel_repo.create(
            db_session,
            nid,
            EntityRelationCreate(
                source_id=str(source.id),
                target_id=str(target.id),
                relation_type="ally_of",
                status="candidate",
            ),
        )
        rel.review_meta = {
            "source": "deep_import",
            "workflow_id": "wf-relation-status",
            "confidence": 0.73,
        }
        await db_session.flush()

        updated = await EntityRelationService().update(
            db_session,
            str(rel.id),
            EntityRelationUpdate(status="canonical"),
            novel_id=novel_id,
        )

        assert updated.status == "canonical"
        await db_session.refresh(rel)
        assert rel.review_meta["review_action"] == "relation_status_updated"
        assert rel.review_meta["source"] == "deep_import"
        assert rel.review_meta["workflow_id"] == "wf-relation-status"
        assert rel.review_meta["confidence"] == 0.73
        assert rel.review_meta["review_before"]["status"] == "candidate"
        assert rel.review_meta["review_after"]["status"] == "canonical"

    @pytest.mark.asyncio
    async def test_upsert_relationship_concurrent_calls_are_idempotent(self) -> None:
        from core.base import Base
        from modules.project.models import Project
        from modules.world.models import CoreEntity, EntityRelation

        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(engine, expire_on_commit=False)
        novel_id = uuid.uuid4()
        source_id = uuid.uuid4()
        target_id = uuid.uuid4()
        async with factory() as session:
            session.add(Project(id=novel_id, title="关系并发测试", genre="test"))
            session.add_all(
                [
                    CoreEntity(
                        id=source_id,
                        novel_id=novel_id,
                        entity_type="character",
                        name="甲",
                        status="canonical",
                    ),
                    CoreEntity(
                        id=target_id,
                        novel_id=novel_id,
                        entity_type="character",
                        name="乙",
                        status="canonical",
                    ),
                ]
            )
            await session.commit()

        async def write_relation(description: str) -> None:
            async with factory() as session:
                await EntityRelationRepository().upsert(
                    session,
                    novel_id,
                    source_id,
                    target_id,
                    "knows",
                    description,
                    relation_kind="epistemic",
                )
                await session.commit()

        try:
            await asyncio.gather(write_relation("第一次"), write_relation("第二次"))
            async with factory() as session:
                rels, total = await EntityRelationRepository().get_by_novel(
                    session,
                    novel_id,
                )
                all_rows = (await session.execute(select(EntityRelation))).scalars().all()

            assert total == 1
            assert len(all_rows) == 1
            assert rels[0].description in {"第一次", "第二次"}
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_deprecate_many_relations(
        self,
        db_session: AsyncSession,
        rel_repo: EntityRelationRepository,
        novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)
        first = await rel_repo.create(
            db_session,
            nid,
            EntityRelationCreate(
                source_id=str(uuid.uuid4()),
                target_id=str(uuid.uuid4()),
                relation_type="controls",
                relation_kind="state",
                status="canonical",
            ),
        )
        second = await rel_repo.create(
            db_session,
            nid,
            EntityRelationCreate(
                source_id=str(uuid.uuid4()),
                target_id=str(uuid.uuid4()),
                relation_type="knows",
                relation_kind="epistemic",
                status="canonical",
            ),
        )

        updated = await rel_repo.deprecate_many(
            db_session,
            [first.id, first.id, second.id],
        )

        assert updated == 2
        assert (await rel_repo.get(db_session, first.id)).status == "deprecated"
        assert (await rel_repo.get(db_session, second.id)).status == "deprecated"
        assert await rel_repo.deprecate_many(db_session, []) == 0

    @pytest.mark.asyncio
    async def test_relation_update_reuses_loaded_object(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        rel_repo = EntityRelationRepository()
        relation = MagicMock()
        relation.id = uuid.uuid4()
        relation.description = "old"
        relation.status = "canonical"
        get_calls = 0

        async def fake_get(_db, rel_id):
            nonlocal get_calls
            get_calls += 1
            assert rel_id == relation.id
            return relation

        class Session:
            def __init__(self) -> None:
                self.added = []
                self.flush_count = 0

            def add(self, obj):
                self.added.append(obj)

            async def flush(self) -> None:
                self.flush_count += 1

        monkeypatch.setattr(rel_repo, "get", fake_get)
        db = Session()

        updated = await rel_repo.update(
            db,  # type: ignore[arg-type]
            relation.id,
            EntityRelationUpdate(description="new", status="deprecated"),
        )

        assert updated is relation
        assert relation.description == "new"
        assert relation.status == "deprecated"
        assert get_calls == 1
        assert db.added == [relation]
        assert db.flush_count == 1

    @pytest.mark.asyncio
    async def test_relation_update_loaded_object_does_not_fetch_again(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        rel_repo = EntityRelationRepository()
        relation = MagicMock()
        relation.description = "old"
        relation.status = "canonical"

        async def fail_get(_db, _rel_id):
            raise AssertionError("loaded relation should be reused")

        class Session:
            def __init__(self) -> None:
                self.added = []
                self.flush_count = 0

            def add(self, obj):
                self.added.append(obj)

            async def flush(self) -> None:
                self.flush_count += 1

        monkeypatch.setattr(rel_repo, "get", fail_get)
        db = Session()

        updated = await rel_repo.update(
            db,  # type: ignore[arg-type]
            relation,  # type: ignore[arg-type]
            EntityRelationUpdate(description="new", status="deprecated"),
        )

        assert updated is relation
        assert relation.description == "new"
        assert relation.status == "deprecated"
        assert db.added == [relation]
        assert db.flush_count == 1

    @pytest.mark.asyncio
    async def test_get_related_entity_ids_uses_batched_seed_lookup(
        self,
        db_session: AsyncSession,
        rel_repo: EntityRelationRepository,
        novel_id: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)
        source_id = uuid.uuid4()
        middle_id = uuid.uuid4()
        target_id = uuid.uuid4()
        await rel_repo.upsert(
            db_session,
            nid,
            source_id,
            middle_id,
            "knows",
            "A-B",
            relation_kind="epistemic",
        )
        await rel_repo.upsert(
            db_session,
            nid,
            middle_id,
            target_id,
            "knows",
            "B-C",
            relation_kind="epistemic",
        )

        async def fail_single_hop(*_args, **_kwargs):
            raise AssertionError("single-seed related lookup must use batched helper")

        monkeypatch.setattr(rel_repo, "_get_one_hop_ids", fail_single_hop)

        related = await rel_repo.get_related_entity_ids(
            db_session,
            nid,
            source_id,
            depth=2,
            limit=10,
        )

        assert {middle_id, target_id}.issubset(related)


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
        assert set(by_name.keys()) == {"主城"}
        assert by_name["主城"]["terms"] == ["主城", "王城", "都城"]


@pytest.mark.asyncio
async def test_entity_importance_map_is_canonical_only_and_novel_scoped(
    db_session: AsyncSession,
    two_projects: tuple[str, str],
) -> None:
    novel_id, other_novel_id = two_projects
    adopted = CoreEntity(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(novel_id),
        entity_type="character",
        name="主角",
        status="canonical",
        importance=0.9,
        importance_level="core",
    )
    review = CoreEntity(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(novel_id),
        entity_type="item",
        name="待处理物品",
        status="candidate",
        importance=0.8,
        importance_level="important",
    )
    other_project = CoreEntity(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(other_novel_id),
        entity_type="location",
        name="其他项目的主城",
        status="canonical",
        importance=0.95,
        importance_level="core",
    )
    db_session.add_all([adopted, review, other_project])
    await db_session.flush()

    importance = await get_entity_importance_map(db_session, novel_id)

    assert importance == {
        str(adopted.id): {"importance": 0.9, "importance_level": "core"}
    }


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
        from modules.world.models import Character, CoreEntity

        entity_id = uuid.uuid4()
        owner = CoreEntity(
            id=entity_id,
            novel_id=uuid.UUID(hex=novel_id),
            entity_type="character",
            name="主角",
            status="canonical",
        )
        char = Character(
            entity_id=entity_id,
            novel_id=uuid.UUID(hex=novel_id),
            name="主角",
        )
        db_session.add_all([owner, char])
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
        from modules.world.models import Character, CoreEntity

        entity_id = uuid.uuid4()
        owner = CoreEntity(
            id=entity_id,
            novel_id=uuid.UUID(hex=novel_id),
            entity_type="character",
            name="李白",
            status="canonical",
        )
        char = Character(
            entity_id=entity_id,
            novel_id=uuid.UUID(hex=novel_id),
            name="李白",
            status="canonical",
        )
        db_session.add_all([owner, char])
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
        from modules.world.models import Character, CoreEntity

        entity_id = uuid.uuid4()
        loc_id = uuid.uuid4()
        location = CoreEntity(
            id=loc_id,
            novel_id=uuid.UUID(hex=novel_id),
            entity_type="location",
            name="城门口",
            status="canonical",
        )
        owner = CoreEntity(
            id=entity_id,
            novel_id=uuid.UUID(hex=novel_id),
            entity_type="character",
            name="主角",
            status="canonical",
        )
        char = Character(
            entity_id=entity_id,
            novel_id=uuid.UUID(hex=novel_id),
            name="主角",
            status="canonical",
        )
        db_session.add_all([location, owner, char])
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
        from modules.world.models import Character, CoreEntity

        loc_id = uuid.uuid4()
        character_id = uuid.uuid4()
        location = CoreEntity(
            id=loc_id,
            novel_id=uuid.UUID(hex=novel_id),
            entity_type="location",
            name="城门口",
            status="canonical",
        )
        owner = CoreEntity(
            id=character_id,
            novel_id=uuid.UUID(hex=novel_id),
            entity_type="character",
            name="在城门口的人",
            status="canonical",
        )
        char = Character(
            entity_id=character_id,
            novel_id=uuid.UUID(hex=novel_id),
            name="在城门口的人",
            status="canonical",
            meta={"location_id": str(loc_id)},
        )
        db_session.add_all([location, owner, char])
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
        from modules.world.models import Character, CoreEntity

        loc_id = uuid.uuid4()
        character_id = uuid.uuid4()
        location = CoreEntity(
            id=loc_id,
            novel_id=uuid.UUID(hex=novel_id),
            entity_type="location",
            name="当前地点",
            status="canonical",
        )
        owner = CoreEntity(
            id=character_id,
            novel_id=uuid.UUID(hex=novel_id),
            entity_type="character",
            name="有位置的人",
            status="canonical",
        )
        char = Character(
            entity_id=character_id,
            novel_id=uuid.UUID(hex=novel_id),
            name="有位置的人",
            status="canonical",
            meta={"location_id": str(loc_id)},
        )
        db_session.add_all([location, owner, char])
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
        from modules.world.models import Character, CoreEntity

        character_id = uuid.uuid4()
        owner = CoreEntity(
            id=character_id,
            novel_id=uuid.UUID(hex=novel_id),
            entity_type="character",
            name="无位置",
            status="canonical",
        )
        char = Character(
            entity_id=character_id,
            novel_id=uuid.UUID(hex=novel_id),
            name="无位置",
            status="canonical",
            meta={},
        )
        db_session.add_all([owner, char])
        await db_session.flush()

        result = await get_character_location_id(
            db_session,
            novel_id,
            str(char.entity_id),
        )
        assert result is None


class TestWorldErrorPaths:
    """World 模块 API 错误路径测试"""

    @pytest.mark.asyncio
    async def test_merge_target_not_canonical_gets_promoted(
        self,
        async_client: AsyncClient,
    ) -> None:
        """合并目标不是 canonical 时自动提升为正史"""
        project_resp = await async_client.post(
            "/api/projects",
            json={
                "title": "合并目标非正史测试",
                "genre": "奇幻",
                "tone": "正剧",
                "language": "zh",
            },
        )
        assert project_resp.status_code == 201
        novel_id = project_resp.json()["id"]

        target_resp = await async_client.post(
            f"/api/world/entities?novel_id={novel_id}",
            json={
                "entity_type": "character",
                "name": "目标草稿",
                "status": "draft",
            },
        )
        assert target_resp.status_code == 201
        target_id = target_resp.json()["id"]

        candidate_resp = await async_client.post(
            f"/api/world/entities?novel_id={novel_id}",
            json={
                "entity_type": "character",
                "name": "候选草稿",
                "status": "draft",
                "force_create": True,
            },
        )
        assert candidate_resp.status_code == 201
        candidate_id = candidate_resp.json()["id"]

        merge_resp = await async_client.post(
            f"/api/world/entities/{candidate_id}/merge?novel_id={novel_id}",
            json={"target_entity_id": target_id},
        )
        assert merge_resp.status_code == 200

        target_get = await async_client.get(
            f"/api/world/entities/{target_id}?novel_id={novel_id}"
        )
        assert target_get.json()["status"] == "canonical"

    @pytest.mark.asyncio
    async def test_merge_candidate_not_draft_returns_400_or_422(
        self,
        async_client: AsyncClient,
    ) -> None:
        """合并候选不是 draft/candidate 时返回 400/422"""
        project_resp = await async_client.post(
            "/api/projects",
            json={
                "title": "合并候选非草稿测试",
                "genre": "奇幻",
                "tone": "正剧",
                "language": "zh",
            },
        )
        assert project_resp.status_code == 201
        novel_id = project_resp.json()["id"]

        target_resp = await async_client.post(
            f"/api/world/entities?novel_id={novel_id}",
            json={
                "entity_type": "character",
                "name": "目标正史",
                "status": "canonical",
            },
        )
        assert target_resp.status_code == 201
        target_id = target_resp.json()["id"]

        candidate_resp = await async_client.post(
            f"/api/world/entities?novel_id={novel_id}",
            json={
                "entity_type": "character",
                "name": "候选正史",
                "status": "canonical",
                "force_create": True,
            },
        )
        assert candidate_resp.status_code == 201
        candidate_id = candidate_resp.json()["id"]

        merge_resp = await async_client.post(
            f"/api/world/entities/{candidate_id}/merge?novel_id={novel_id}",
            json={"target_entity_id": target_id},
        )
        assert merge_resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_merge_self_returns_400_or_422(
        self,
        async_client: AsyncClient,
    ) -> None:
        """合并自身时返回 400/422"""
        project_resp = await async_client.post(
            "/api/projects",
            json={
                "title": "合并自身测试",
                "genre": "奇幻",
                "tone": "正剧",
                "language": "zh",
            },
        )
        assert project_resp.status_code == 201
        novel_id = project_resp.json()["id"]

        entity_resp = await async_client.post(
            f"/api/world/entities?novel_id={novel_id}",
            json={
                "entity_type": "character",
                "name": "自身实体",
                "status": "canonical",
            },
        )
        assert entity_resp.status_code == 201
        entity_id = entity_resp.json()["id"]

        merge_resp = await async_client.post(
            f"/api/world/entities/{entity_id}/merge?novel_id={novel_id}",
            json={"target_entity_id": entity_id},
        )
        assert merge_resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_create_knowledge_character_id_mismatch_returns_400(
        self,
        async_client: AsyncClient,
    ) -> None:
        """知识记录 path 与 body 的 character_id 不一致时返回 400"""
        project_resp = await async_client.post(
            "/api/projects",
            json={
                "title": "知识 character_id 不一致测试",
                "genre": "奇幻",
                "tone": "正剧",
                "language": "zh",
            },
        )
        assert project_resp.status_code == 201
        novel_id = project_resp.json()["id"]

        entity_resp = await async_client.post(
            f"/api/world/entities?novel_id={novel_id}",
            json={
                "entity_type": "character",
                "name": "知识角色",
                "status": "canonical",
            },
        )
        assert entity_resp.status_code == 201
        character_id = entity_resp.json()["id"]

        target_resp = await async_client.post(
            f"/api/world/entities?novel_id={novel_id}",
            json={
                "entity_type": "location",
                "name": "目标地点",
                "status": "canonical",
            },
        )
        assert target_resp.status_code == 201
        target_id = target_resp.json()["id"]

        other_id = str(uuid.uuid4())
        knowledge_resp = await async_client.post(
            f"/api/world/characters/{character_id}/knowledge?novel_id={novel_id}",
            json={
                "character_id": other_id,
                "target_type": "entity",
                "target_id": target_id,
                "knowledge_level": "partial",
                "known_content": "知道一点",
            },
        )
        assert knowledge_resp.status_code == 400

    @pytest.mark.asyncio
    async def test_create_knowledge_false_belief_without_misconception_returns_422(
        self,
        async_client: AsyncClient,
    ) -> None:
        """false_belief 知识未提供 misconception 时返回 422"""
        project_resp = await async_client.post(
            "/api/projects",
            json={
                "title": "知识 false_belief 校验测试",
                "genre": "奇幻",
                "tone": "正剧",
                "language": "zh",
            },
        )
        assert project_resp.status_code == 201
        novel_id = project_resp.json()["id"]

        entity_resp = await async_client.post(
            f"/api/world/entities?novel_id={novel_id}",
            json={
                "entity_type": "character",
                "name": "误解角色",
                "status": "canonical",
            },
        )
        assert entity_resp.status_code == 201
        character_id = entity_resp.json()["id"]

        target_resp = await async_client.post(
            f"/api/world/entities?novel_id={novel_id}",
            json={
                "entity_type": "location",
                "name": "误解目标",
                "status": "canonical",
            },
        )
        assert target_resp.status_code == 201
        target_id = target_resp.json()["id"]

        knowledge_resp = await async_client.post(
            f"/api/world/characters/{character_id}/knowledge?novel_id={novel_id}",
            json={
                "character_id": character_id,
                "target_type": "entity",
                "target_id": target_id,
                "knowledge_level": "false_belief",
                "known_content": "错误认知",
            },
        )
        assert knowledge_resp.status_code == 422


class TestEntityRelationServiceUpsert:
    @pytest.mark.asyncio
    async def test_upsert_rejects_cross_novel_source_or_target(
        self,
        db_session: AsyncSession,
        entity_repo: CoreEntityRepository,
    ) -> None:
        novel_id = str(uuid.uuid4())
        other_novel_id = str(uuid.uuid4())
        source = await entity_repo.create_raw(
            db_session,
            novel_id=uuid.UUID(novel_id),
            entity_type="character",
            name="甲",
            status="canonical",
        )
        target = await entity_repo.create_raw(
            db_session,
            novel_id=uuid.UUID(other_novel_id),
            entity_type="character",
            name="乙",
            status="canonical",
        )

        with pytest.raises(NotFoundError) as exc:
            await EntityRelationService().upsert(
                db_session,
                novel_id,
                str(source.id),
                str(target.id),
                "knows",
            )
        assert exc.value.status_code == 404
