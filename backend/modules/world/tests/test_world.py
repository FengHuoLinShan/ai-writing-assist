"""
World 模块测试

测试所有 CRUD 路径、facade、关系扩展、别名、候选和去重功能。
使用 pytest-asyncio 测试异步数据库操作。
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.dml import Update
from sqlalchemy.sql.selectable import Select

from core.errors import NotFoundError
from core.errors import ValidationError as DomainValidationError
from modules.world.models import EntityRevision
from modules.world.repositories import (
    CoreEntityRepository,
    EntityRelationRepository,
    EventRepository,
)
from modules.world.schemas import (
    CharacterCreate,
    CharacterKnowledgeCreate,
    CoreEntityUpdate,
    EntityPromoteRequest,
    EventCreate,
    EventUpdate,
    WorldEntityCreate,
    WorldEntityUpdate,
)
from modules.world.services import (
    CharacterKnowledgeService,
    CharacterService,
    EntityAliasService,
    EventService,
    WorldEntityService,
)
from modules.world.services.core.dedup_service import EntityDedupService


@pytest.mark.asyncio
async def test_deprecate_deep_import_entities_uses_unit_of_work() -> None:
    workflow_id = "wf-cleanup"
    entity = MagicMock()
    entity.content_json = {
        "_meta": {
            "source": "deep_import",
            "workflow_id": workflow_id,
            "auto_ingested": True,
        }
    }
    entity.status = "candidate"

    class Result:
        def scalars(self):  # type: ignore[no-untyped-def]
            return self

        def all(self):  # type: ignore[no-untyped-def]
            return [entity]

    class Session:
        def __init__(self) -> None:
            self.statements: list[object] = []
            self.flushes = 0

        async def execute(self, stmt):  # type: ignore[no-untyped-def]
            self.statements.append(stmt)
            return Result()

        def add(self, item):  # type: ignore[no-untyped-def]
            assert item is entity

        async def flush(self) -> None:
            self.flushes += 1

    session = Session()

    deprecated = await CoreEntityRepository().deprecate_deep_import_entities_by_workflow(
        session,  # type: ignore[arg-type]
        uuid.uuid4(),
        workflow_id,
    )

    assert deprecated == 1
    assert session.flushes == 1
    assert all(isinstance(stmt, Select) for stmt in session.statements)
    assert not any(isinstance(stmt, Update) for stmt in session.statements)
    assert entity.status == "deprecated"
    assert entity.content_json["_meta"]["cleanup_status"] == "deprecated"


@pytest.mark.asyncio
async def test_core_entity_update_reuses_loaded_entity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = CoreEntityRepository()
    entity_id = uuid.uuid4()
    entity = MagicMock()
    entity.id = entity_id
    entity.name = "旧名"
    entity.summary = None
    entity.status = "draft"
    entity.content_json = {}
    get_calls = 0

    async def fake_get(_db, requested_id):
        nonlocal get_calls
        get_calls += 1
        assert requested_id == entity_id
        return entity

    class Session:
        def __init__(self) -> None:
            self.added = []
            self.flush_count = 0

        def add(self, obj):  # type: ignore[no-untyped-def]
            self.added.append(obj)

        async def flush(self) -> None:
            self.flush_count += 1

    monkeypatch.setattr(repo, "get", fake_get)
    db = Session()

    updated = await repo.update(
        db,  # type: ignore[arg-type]
        entity_id,
        CoreEntityUpdate(
            name="新名",
            summary="新摘要",
            content_json={"aliases": []},
        ),
    )

    assert updated is entity
    assert entity.name == "新名"
    assert entity.summary == "新摘要"
    assert entity.content_json == {"aliases": []}
    assert get_calls == 1
    assert db.added == [entity]
    assert db.flush_count == 1


@pytest.mark.asyncio
async def test_core_entity_update_loaded_entity_does_not_fetch_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = CoreEntityRepository()
    entity = MagicMock()
    entity.id = uuid.uuid4()
    entity.name = "旧名"
    entity.summary = None
    entity.status = "draft"
    entity.content_json = {}

    async def fail_get(*_args, **_kwargs):
        raise AssertionError("loaded entity should not be fetched again")

    class Session:
        def __init__(self) -> None:
            self.added = []
            self.flush_count = 0

        def add(self, obj):  # type: ignore[no-untyped-def]
            self.added.append(obj)

        async def flush(self) -> None:
            self.flush_count += 1

    monkeypatch.setattr(repo, "get", fail_get)
    db = Session()

    updated = await repo.update(
        db,  # type: ignore[arg-type]
        entity,
        CoreEntityUpdate(name="新名", summary="新摘要"),
    )

    assert updated is entity
    assert entity.name == "新名"
    assert entity.summary == "新摘要"
    assert db.added == [entity]
    assert db.flush_count == 1


# ============================================================
# Fixtures
# ============================================================


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
        assert result.status == "canonical"
        assert result.display_state == "active"
        assert result.approved_by == "测试用户"
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
        with pytest.raises(NotFoundError) as exc:
            await entity_service.get(
                db_session,
                str(uuid.uuid4()),
                novel_id=novel_id,
            )
        assert exc.value.status_code == 404


class TestWorldNovelIsolation:
    @pytest.mark.asyncio
    async def test_event_update_reuses_loaded_event(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo = EventRepository()
        entity_id = uuid.uuid4()
        location_id = uuid.uuid4()
        event = MagicMock()
        event.entity_id = entity_id
        event.timeline_order = 1
        event.location_entity_id = None
        event.occurrence_time_label = None
        get_calls = 0

        async def fake_get(_db, requested_id):
            nonlocal get_calls
            get_calls += 1
            assert requested_id == entity_id
            return event

        class Session:
            def __init__(self) -> None:
                self.added = []
                self.flush_count = 0

            def add(self, obj):
                self.added.append(obj)

            async def flush(self) -> None:
                self.flush_count += 1

        monkeypatch.setattr(repo, "get", fake_get)
        db = Session()

        updated = await repo.update(
            db,  # type: ignore[arg-type]
            entity_id,
            EventUpdate(
                location_entity_id=str(location_id),
                timeline_order=3,
                occurrence_time_label="第三章夜晚",
            ),
        )

        assert updated is event
        assert event.location_entity_id == location_id
        assert event.timeline_order == 3
        assert event.occurrence_time_label == "第三章夜晚"
        assert get_calls == 1
        assert db.added == [event]
        assert db.flush_count == 1

    @pytest.mark.asyncio
    async def test_event_create_rejects_location_from_another_novel(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        novel_id: str,
    ) -> None:
        other_novel_id = str(uuid.uuid4())
        event_entity = await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(
                entity_type="event",
                name="同项目事件",
                status="draft",
                force_create=True,
            ),
        )
        other_location = await entity_service.create(
            db_session,
            other_novel_id,
            WorldEntityCreate(
                entity_type="location",
                name="其他项目地点",
                status="draft",
                force_create=True,
            ),
        )

        with pytest.raises(NotFoundError) as exc:
            await EventService().create(
                db_session,
                novel_id,
                EventCreate(
                    entity_id=event_entity.id,
                    source_chapter_id=str(uuid.uuid4()),
                    location_entity_id=other_location.id,
                    timeline_order=1,
                ),
            )

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_character_update_location_rejects_other_novel_location(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        novel_id: str,
    ) -> None:
        other_novel_id = str(uuid.uuid4())
        character_entity = await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(
                entity_type="character",
                name="同项目人物",
                status="canonical",
                force_create=True,
            ),
        )
        character = await CharacterService().create(
            db_session,
            novel_id,
            CharacterCreate(entity_id=character_entity.id, name="同项目人物"),
        )
        other_location = await entity_service.create(
            db_session,
            other_novel_id,
            WorldEntityCreate(
                entity_type="location",
                name="其他项目地点",
                status="canonical",
                force_create=True,
            ),
        )

        with pytest.raises(NotFoundError) as exc:
            await CharacterService().update_location(
                db_session,
                novel_id,
                character.id,
                other_location.id,
                "抵达错误地点",
                1,
            )

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_character_knowledge_rejects_target_from_another_novel(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        novel_id: str,
    ) -> None:
        other_novel_id = str(uuid.uuid4())
        character_entity = await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(
                entity_type="character",
                name="同项目人物",
                status="canonical",
                force_create=True,
            ),
        )
        character = await CharacterService().create(
            db_session,
            novel_id,
            CharacterCreate(entity_id=character_entity.id, name="同项目人物"),
        )
        other_target = await entity_service.create(
            db_session,
            other_novel_id,
            WorldEntityCreate(
                entity_type="item",
                name="其他项目秘密",
                status="canonical",
                force_create=True,
            ),
        )

        with pytest.raises(NotFoundError) as exc:
            await CharacterKnowledgeService().create(
                db_session,
                novel_id,
                CharacterKnowledgeCreate(
                    character_id=character.id,
                    target_type="entity",
                    target_id=other_target.id,
                    knowledge_level="full",
                ),
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

    @pytest.mark.asyncio
    async def test_update_entity_rejects_direct_promote_to_canonical(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        novel_id: str,
        sample_entity_data: WorldEntityCreate,
    ) -> None:
        """PUT 不能绕过 promote 将候选资产提升为正史。"""
        created = await entity_service.create(
            db_session,
            novel_id,
            sample_entity_data.model_copy(update={"status": "draft"}),
        )

        with pytest.raises(DomainValidationError) as exc:
            await entity_service.update(
                db_session,
                created.id,
                WorldEntityUpdate(status="canonical", approved_by="审核员"),
                novel_id=novel_id,
            )

        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_promote_entity_applies_author_edits_atomically(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        novel_id: str,
        sample_entity_data: WorldEntityCreate,
    ) -> None:
        created = await entity_service.create(
            db_session,
            novel_id,
            sample_entity_data.model_copy(
                update={
                    "status": "candidate",
                    "name": "旧星门",
                    "content_json": {
                        "_meta": {
                            "source": "deep_import",
                            "needs_review": True,
                        }
                    },
                }
            ),
        )

        result = await entity_service.promote(
            db_session,
            created.id,
            EntityPromoteRequest(
                name="新星门",
                entity_type="location",
                summary="作者微调后的概要",
            ),
            novel_id=novel_id,
        )
        stored = await entity_service.get(db_session, created.id, novel_id=novel_id)

        assert result.status == "canonical"
        assert stored.name == "新星门"
        assert stored.entity_type == "location"
        assert stored.summary == "作者微调后的概要"
        assert stored.content_json["_meta"]["needs_review"] is False
        assert stored.content_json["_meta"]["user_edited"] is True
        assert stored.content_json["_meta"]["reviewed_from"] == "entity_edit_promote"

    @pytest.mark.asyncio
    async def test_update_auto_ingested_entity_marks_user_edited(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        novel_id: str,
    ) -> None:
        created = await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(
                entity_type="location",
                name="自动导入地点",
                content_json={
                    "_meta": {
                        "source": "deep_import",
                        "workflow_id": "wf-world-edit",
                        "auto_ingested": True,
                        "user_edited": False,
                    }
                },
                force_create=True,
            ),
        )

        result = await entity_service.update(
            db_session,
            created.id,
            WorldEntityUpdate(summary="人工修订摘要"),
            novel_id=novel_id,
        )

        meta = result.content_json["_meta"]
        assert meta["user_edited"] is True
        assert meta["edited_at"]

    @pytest.mark.asyncio
    async def test_reviewing_auto_ingested_entity_preserves_submitted_content(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        novel_id: str,
    ) -> None:
        created = await entity_service.create(
            db_session,
            novel_id,
            WorldEntityCreate(
                entity_type="location",
                name="待检查地点",
                content_json={
                    "aliases": ["旧名"],
                    "_meta": {
                        "source": "deep_import",
                        "workflow_id": "wf-world-review",
                        "auto_ingested": True,
                        "needs_review": True,
                    },
                },
                force_create=True,
            ),
        )

        result = await entity_service.update(
            db_session,
            created.id,
            WorldEntityUpdate(
                content_json={
                    "aliases": ["旧名", "新名"],
                    "_meta": {
                        "source": "deep_import",
                        "workflow_id": "wf-world-review",
                        "auto_ingested": True,
                        "needs_review": False,
                        "reviewed_by": "manual",
                    },
                }
            ),
            novel_id=novel_id,
        )

        assert result.content_json["aliases"] == ["旧名", "新名"]
        assert result.content_json["_meta"]["needs_review"] is False
        assert result.content_json["_meta"]["reviewed_by"] == "manual"
        assert result.content_json["_meta"]["user_edited"] is True

    @pytest.mark.asyncio
    async def test_delete_entity(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        novel_id: str,
        sample_entity_data: WorldEntityCreate,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """测试删除世界对象"""
        from modules.context import facade as context_facade

        context_marker = AsyncMock(return_value=0)
        monkeypatch.setattr(
            context_facade,
            "mark_asset_context_changed",
            context_marker,
        )
        created = await entity_service.create(db_session, novel_id, sample_entity_data)
        await entity_service.delete(db_session, created.id, novel_id=novel_id)

        deleted = await entity_service.get(
            db_session,
            created.id,
            novel_id=novel_id,
        )
        assert deleted.status == "deprecated"
        revisions = (
            (
                await db_session.execute(
                    select(EntityRevision).where(
                        EntityRevision.entity_id == uuid.UUID(created.id)
                    )
                )
            )
            .scalars()
            .all()
        )
        assert [revision.revision_reason for revision in revisions] == ["manual_delete"]
        context_marker.assert_awaited_once_with(
            db_session,
            novel_id=novel_id,
            asset_type="world_entity",
            asset_id=created.id,
            reason="entity_deprecated",
        )

    @pytest.mark.asyncio
    async def test_delete_entity_keeps_main_delete_when_auxiliary_markers_fail(
        self,
        db_session: AsyncSession,
        entity_service: WorldEntityService,
        novel_id: str,
        sample_entity_data: WorldEntityCreate,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from modules.context import facade as context_facade
        from modules.world.services.core import entity_revision_service

        created = await entity_service.create(db_session, novel_id, sample_entity_data)

        async def fail_snapshot(*_args, **_kwargs):
            raise RuntimeError("revision unavailable")

        async def fail_context_marker(*_args, **_kwargs):
            raise RuntimeError("context marker unavailable")

        monkeypatch.setattr(
            entity_revision_service.EntityRevisionService,
            "create_snapshot",
            fail_snapshot,
        )
        monkeypatch.setattr(
            context_facade,
            "mark_asset_context_changed",
            fail_context_marker,
        )

        await entity_service.delete(db_session, created.id, novel_id=novel_id)

        deleted = await entity_service.get(
            db_session,
            created.id,
            novel_id=novel_id,
        )
        assert deleted.status == "deprecated"
        assert (await db_session.execute(select(EntityRevision.id))).scalars().all() == []


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

    @pytest.mark.asyncio
    async def test_find_duplicates_cross_novel_candidate_returns_empty(
        self,
        db_session: AsyncSession,
        entity_repo: CoreEntityRepository,
        dedup_service: EntityDedupService,
    ) -> None:
        """candidate_id 不属于当前 novel 时不能泄露名称去查当前 novel。"""
        novel_id = str(uuid.uuid4())
        other_novel_id = str(uuid.uuid4())
        candidate = await entity_repo.create_raw(
            db_session,
            novel_id=uuid.UUID(other_novel_id),
            entity_type="location",
            name="异界地点",
            status="candidate",
        )

        suggestions = await dedup_service.find_duplicates(
            db_session,
            novel_id,
            str(candidate.id),
        )

        assert suggestions == []

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


@pytest.mark.asyncio
async def test_merge_entity_api_service_marks_candidate_merged(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    entity_service = WorldEntityService()
    target = await entity_service.create(
        db_session,
        sample_novel_id,
        WorldEntityCreate(entity_type="character", name="张三", status="canonical"),
    )
    candidate = await entity_service.create(
        db_session,
        sample_novel_id,
        WorldEntityCreate(
            entity_type="character",
            name="张老三",
            status="draft",
            force_create=True,
        ),
    )

    from modules.world.services.core.dedup_service import EntityDedupService

    result = await EntityDedupService().merge_candidate_into_entity(
        db_session,
        sample_novel_id,
        candidate.id,
        target.id,
    )

    assert result.target_entity_id == target.id
    merged = await entity_service.get(db_session, candidate.id, novel_id=sample_novel_id)
    assert merged.status == "merged"


@pytest.mark.asyncio
async def test_merge_entity_into_candidate_target_preserves_review_state(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    entity_service = WorldEntityService()
    source = await entity_service.create(
        db_session,
        sample_novel_id,
        WorldEntityCreate(
            entity_type="character",
            name="候选源",
            status="candidate",
            force_create=True,
        ),
    )
    target = await entity_service.create(
        db_session,
        sample_novel_id,
        WorldEntityCreate(
            entity_type="character",
            name="候选目标",
            status="candidate",
            force_create=True,
        ),
    )

    result = await EntityDedupService().merge_candidate_into_entity(
        db_session,
        sample_novel_id,
        source.id,
        target.id,
    )

    merged_source = await entity_service.get(
        db_session,
        source.id,
        novel_id=sample_novel_id,
    )
    surviving_target = await entity_service.get(
        db_session,
        target.id,
        novel_id=sample_novel_id,
    )
    assert result.candidate_entity_id == source.id
    assert result.target_entity_id == target.id
    assert merged_source is not None and merged_source.status == "merged"
    assert surviving_target is not None and surviving_target.status == "candidate"


@pytest.mark.asyncio
async def test_entity_list_filters_by_author_display_state(
    async_client: AsyncClient,
) -> None:
    project_resp = await async_client.post(
        "/api/projects",
        json={
            "title": "对象作者态筛选",
            "genre": "奇幻",
            "tone": "正剧",
            "language": "zh",
        },
    )
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]
    for name, status in (
        ("已采用地点", "canonical"),
        ("待处理对象", "candidate"),
        ("冲突对象", "conflicted"),
        ("已归档对象", "ignored"),
    ):
        created = await async_client.post(
            f"/api/world/entities?novel_id={novel_id}",
            json={
                "entity_type": "location",
                "name": name,
                "status": status,
                "force_create": True,
            },
        )
        assert created.status_code == 201, created.text

    active = await async_client.get(
        "/api/world/entities",
        params={"novel_id": novel_id, "display_state": "active"},
    )
    review = await async_client.get(
        "/api/world/entities",
        params={"novel_id": novel_id, "display_state": "review"},
    )
    archived = await async_client.get(
        "/api/world/entities",
        params={"novel_id": novel_id, "display_state": "archived"},
    )

    assert [
        (item["status"], item["display_state"]) for item in active.json()["items"]
    ] == [("canonical", "active")]
    assert {
        (item["status"], item["display_state"]) for item in review.json()["items"]
    } == {("candidate", "review"), ("conflicted", "review")}
    assert [
        (item["status"], item["display_state"]) for item in archived.json()["items"]
    ] == [("ignored", "archived")]


@pytest.mark.asyncio
async def test_entity_default_list_hides_every_archived_status(
    async_client: AsyncClient,
) -> None:
    project = await async_client.post(
        "/api/projects",
        json={"title": "归档全集", "language": "zh"},
    )
    novel_id = project.json()["id"]
    archived_statuses = {
        "accepted",
        "deprecated",
        "ignored",
        "merged",
        "rejected",
        "rolled_back",
    }
    for status in ("canonical", "candidate", *sorted(archived_statuses)):
        created = await async_client.post(
            "/api/world/entities",
            params={"novel_id": novel_id},
            json={
                "entity_type": "location",
                "name": f"entity-{status}",
                "status": status,
                "force_create": True,
            },
        )
        assert created.status_code == 201, created.text

    default = await async_client.get(
        "/api/world/entities", params={"novel_id": novel_id, "limit": 50}
    )
    explicit_history = await async_client.get(
        "/api/world/entities",
        params={"novel_id": novel_id, "display_state": "archived", "limit": 50},
    )

    assert {item["status"] for item in default.json()["items"]} == {
        "canonical",
        "candidate",
    }
    assert {item["status"] for item in explicit_history.json()["items"]} == (
        archived_statuses
    )
    assert explicit_history.json()["total"] == len(archived_statuses)


@pytest.mark.asyncio
async def test_alias_list_keeps_novel_isolation(
    async_client: AsyncClient,
) -> None:
    project_ids: list[str] = []
    for title in ("alias-one", "alias-two"):
        project = await async_client.post(
            "/api/projects",
            json={"title": title, "language": "zh"},
        )
        project_ids.append(project.json()["id"])

    for index, novel_id in enumerate(project_ids, start=1):
        created = await async_client.post(
            "/api/world/entities",
            params={"novel_id": novel_id},
            json={
                "entity_type": "location",
                "name": f"owner-{index}",
                "content_json": {"aliases": [f"alias-{index}"]},
                "force_create": True,
            },
        )
        assert created.status_code == 201, created.text

    response = await async_client.get(
        "/api/world/aliases",
        params={"novel_id": project_ids[0]},
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["alias"] == "alias-1"


@pytest.mark.asyncio
async def test_merge_entity_route_marks_candidate_merged(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST /api/world/entities/{candidate_id}/merge 将候选实体标记为 merged"""
    # 创建测试项目
    project_resp = await async_client.post(
        "/api/projects",
        json={
            "title": "合并路由测试",
            "genre": "奇幻",
            "tone": "正剧",
            "language": "zh",
        },
    )
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]

    # 创建目标实体（canonical）
    target_resp = await async_client.post(
        f"/api/world/entities?novel_id={novel_id}",
        json={
            "entity_type": "character",
            "name": " route_target ",
            "status": "canonical",
        },
    )
    assert target_resp.status_code == 201
    target_id = target_resp.json()["id"]

    # 创建候选实体（draft）
    candidate_resp = await async_client.post(
        f"/api/world/entities?novel_id={novel_id}",
        json={
            "entity_type": "character",
            "name": " route_candidate ",
            "status": "draft",
        },
    )
    assert candidate_resp.status_code == 201
    candidate_id = candidate_resp.json()["id"]

    # 调用合并路由
    merge_resp = await async_client.post(
        f"/api/world/entities/{candidate_id}/merge?novel_id={novel_id}",
        json={"target_entity_id": target_id},
    )
    assert merge_resp.status_code == 200
    payload = merge_resp.json()
    assert payload["target_entity_id"] == target_id
    assert payload["candidate_entity_id"] == candidate_id
    assert payload["merged_ids"] == [candidate_id]
    assert set(payload["affected_ids"]) == {candidate_id, target_id}

    # 验证候选实体状态为 merged
    get_resp = await async_client.get(
        f"/api/world/entities/{candidate_id}?novel_id={novel_id}",
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "merged"


@pytest.mark.asyncio
async def test_resolve_candidate_as_alias_marks_candidate_merged_and_migrates_relations(
    db_session: AsyncSession,
    sample_novel_id: str,
) -> None:
    nid = uuid.UUID(sample_novel_id)
    entity_repo = CoreEntityRepository()
    rel_repo = EntityRelationRepository()
    target = await entity_repo.create_raw(
        db_session,
        novel_id=nid,
        entity_type="faction",
        name="值夜者",
        status="canonical",
        content_json={"aliases": []},
    )
    related = await entity_repo.create_raw(
        db_session,
        novel_id=nid,
        entity_type="location",
        name="廷根",
        status="canonical",
    )
    candidate = await entity_repo.create_raw(
        db_session,
        novel_id=nid,
        entity_type="organization",
        name="黑荆棘安保公司",
        status="candidate",
        content_json={
            "_meta": {
                "source": "deep_import",
                "workflow_id": "wf-blackthorn",
                "scene_id": "scene-1",
                "confidence": 0.95,
                "quote": "黑荆棘安保公司",
            },
        },
    )
    await rel_repo.upsert(
        db_session,
        nid,
        candidate.id,
        related.id,
        "located_at",
        "黑荆棘安保公司位于廷根",
    )
    await rel_repo.upsert(
        db_session,
        nid,
        candidate.id,
        target.id,
        "alias_hint",
        "错误提示关系，迁移后会成为自环",
    )

    result = await EntityAliasService().resolve_candidate_as_alias(
        db_session,
        sample_novel_id,
        str(candidate.id),
        target_entity_id=str(target.id),
        alias="黑荆棘安保公司",
        alias_type="name",
    )

    await db_session.refresh(target)
    await db_session.refresh(candidate)
    assert target.status == "canonical"
    assert target.content_json["aliases"][0]["alias"] == "黑荆棘安保公司"
    assert target.content_json["aliases"][0]["type"] == "name"
    assert target.content_json["aliases"][0]["status"] == "canonical"
    assert target.content_json["aliases"][0]["source"] == "deep_import"
    assert target.content_json["aliases"][0]["workflow_id"] == "wf-blackthorn"
    assert target.content_json["aliases"][0]["confidence"] == 0.95
    assert candidate.status == "merged"
    assert candidate.content_json["merged_into"] == str(target.id)
    assert candidate.content_json["resolved_as"] == "alias"
    assert candidate.content_json["resolved_alias"] == "黑荆棘安保公司"
    assert result["merged_ids"] == [str(candidate.id)]
    assert set(result["affected_ids"]) == {str(candidate.id), str(target.id)}
    assert result["relations_migrated"] == 2
    assert result["self_loops_cleaned"] == 1

    all_rels = await rel_repo.get_all_for_entity(db_session, nid, target.id)
    canonical_rels = [
        rel
        for rel in all_rels
        if rel.source_id == target.id
        and rel.target_id == related.id
        and rel.relation_type == "located_at"
        and rel.status == "canonical"
    ]
    assert len(canonical_rels) == 1


@pytest.mark.asyncio
async def test_resolve_candidate_as_alias_route(
    async_client: AsyncClient,
) -> None:
    project_resp = await async_client.post(
        "/api/projects",
        json={
            "title": "别名确认路由测试",
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
            "entity_type": "faction",
            "name": "值夜者",
            "status": "canonical",
        },
    )
    candidate_resp = await async_client.post(
        f"/api/world/entities?novel_id={novel_id}",
        json={
            "entity_type": "organization",
            "name": "黑荆棘安保公司",
            "status": "candidate",
        },
    )
    assert target_resp.status_code == 201
    assert candidate_resp.status_code == 201
    target_id = target_resp.json()["id"]
    candidate_id = candidate_resp.json()["id"]

    resolve_resp = await async_client.post(
        f"/api/world/entities/{candidate_id}/resolve-as-alias?novel_id={novel_id}",
        json={
            "target_entity_id": target_id,
            "alias": "黑荆棘安保公司",
            "alias_type": "name",
        },
    )
    assert resolve_resp.status_code == 200
    payload = resolve_resp.json()
    assert payload["target_entity_id"] == target_id
    assert payload["candidate_entity_id"] == candidate_id
    assert payload["merged_ids"] == [candidate_id]
    assert set(payload["affected_ids"]) == {candidate_id, target_id}

    get_candidate_resp = await async_client.get(
        f"/api/world/entities/{candidate_id}?novel_id={novel_id}",
    )
    assert get_candidate_resp.json()["status"] == "merged"


@pytest.mark.asyncio
async def test_edit_alias_route_moves_alias_between_entities(
    async_client: AsyncClient,
) -> None:
    project_resp = await async_client.post(
        "/api/projects",
        json={
            "title": "别名编辑路由测试",
            "genre": "奇幻",
            "tone": "正剧",
            "language": "zh",
        },
    )
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]
    source_resp = await async_client.post(
        f"/api/world/entities?novel_id={novel_id}",
        json={
            "entity_type": "faction",
            "name": "值夜者",
            "status": "canonical",
        },
    )
    target_resp = await async_client.post(
        f"/api/world/entities?novel_id={novel_id}",
        json={
            "entity_type": "organization",
            "name": "黑荆棘安保公司",
            "status": "canonical",
        },
    )
    source_id = source_resp.json()["id"]
    target_id = target_resp.json()["id"]
    create_alias_resp = await async_client.post(
        f"/api/world/aliases?novel_id={novel_id}",
        json={
            "entity_id": source_id,
            "alias": "黑荆棘安保公司",
            "alias_type": "alias",
        },
    )
    assert create_alias_resp.status_code == 201

    edit_resp = await async_client.patch(
        f"/api/world/entities/{source_id}/aliases/edit",
        params={"novel_id": novel_id, "alias": "黑荆棘安保公司"},
        json={
            "target_entity_id": target_id,
            "alias": "黑荆棘",
            "alias_type": "name",
            "confirm_review": True,
        },
    )

    assert edit_resp.status_code == 200
    payload = edit_resp.json()
    assert payload["entity_id"] == target_id
    assert payload["alias"] == "黑荆棘"
    assert payload["alias_type"] == "name"
    assert set(payload["affected_ids"]) == {source_id, target_id}


@pytest.mark.asyncio
async def test_relation_review_edit_route_confirms_and_returns_audit(
    async_client: AsyncClient,
) -> None:
    project_resp = await async_client.post(
        "/api/projects",
        json={
            "title": "关系复核路由测试",
            "genre": "奇幻",
            "tone": "正剧",
            "language": "zh",
        },
    )
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]
    source_resp = await async_client.post(
        f"/api/world/entities?novel_id={novel_id}",
        json={"entity_type": "character", "name": "克莱恩", "status": "canonical"},
    )
    target_resp = await async_client.post(
        f"/api/world/entities?novel_id={novel_id}",
        json={"entity_type": "faction", "name": "值夜者", "status": "canonical"},
    )
    relation_resp = await async_client.post(
        f"/api/world/relations?novel_id={novel_id}",
        json={
            "source_id": source_resp.json()["id"],
            "target_id": target_resp.json()["id"],
            "relation_type": "member_of",
            "description": "旧描述",
            "strength": 0.5,
            "status": "candidate",
        },
    )
    assert relation_resp.status_code == 201
    rel_id = relation_resp.json()["id"]

    review_resp = await async_client.patch(
        f"/api/world/relations/{rel_id}/review-edit",
        params={"novel_id": novel_id},
        json={
            "relation_type": "ally_of",
            "description": "新描述",
            "strength": 0.9,
            "confirm_review": True,
        },
    )

    assert review_resp.status_code == 200, review_resp.text
    payload = review_resp.json()
    assert payload["affected_ids"] == [rel_id]
    assert payload["relation"]["status"] == "canonical"
    assert payload["relation"]["relation_type"] == "ally_of"
    assert payload["review_meta"]["reviewed_by"] == "manual"


@pytest.mark.asyncio
async def test_relation_review_edit_route_rejects_blank_relation_type(
    async_client: AsyncClient,
) -> None:
    project_resp = await async_client.post(
        "/api/projects",
        json={
            "title": "关系复核空类型测试",
            "genre": "奇幻",
            "tone": "正剧",
            "language": "zh",
        },
    )
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]
    source_resp = await async_client.post(
        f"/api/world/entities?novel_id={novel_id}",
        json={"entity_type": "character", "name": "克莱恩", "status": "canonical"},
    )
    target_resp = await async_client.post(
        f"/api/world/entities?novel_id={novel_id}",
        json={"entity_type": "faction", "name": "值夜者", "status": "canonical"},
    )
    relation_resp = await async_client.post(
        f"/api/world/relations?novel_id={novel_id}",
        json={
            "source_id": source_resp.json()["id"],
            "target_id": target_resp.json()["id"],
            "relation_type": "member_of",
            "status": "candidate",
        },
    )
    assert relation_resp.status_code == 201

    review_resp = await async_client.patch(
        f"/api/world/relations/{relation_resp.json()['id']}/review-edit",
        params={"novel_id": novel_id},
        json={"relation_type": "   ", "confirm_review": True},
    )

    assert review_resp.status_code == 422


@pytest.mark.asyncio
async def test_rollback_entity_route_uses_scene_index(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST /api/world/entities/{entity_id}/rollback 接收 scene_index 并恢复归档字段"""
    import uuid

    from modules.world.models import TextArchive

    # 创建测试项目
    project_resp = await async_client.post(
        "/api/projects",
        json={
            "title": "回滚路由测试",
            "genre": "奇幻",
            "tone": "正剧",
            "language": "zh",
        },
    )
    assert project_resp.status_code == 201
    novel_id = project_resp.json()["id"]

    # 创建实体
    entity_resp = await async_client.post(
        f"/api/world/entities?novel_id={novel_id}",
        json={
            "entity_type": "location",
            "name": "回滚测试地点",
            "summary": "当前摘要",
            "status": "canonical",
        },
    )
    assert entity_resp.status_code == 201
    entity_id = entity_resp.json()["id"]

    # 写入 TextArchive 归档值
    db_session.add(
        TextArchive(
            novel_id=uuid.UUID(hex=novel_id),
            entity_id=uuid.UUID(hex=entity_id),
            field_name="summary",
            text_content="归档摘要",
            scene_index=5,
            source="manual_edit",
        )
    )
    await db_session.flush()

    # 调用回滚路由
    rollback_resp = await async_client.post(
        f"/api/world/entities/{entity_id}/rollback?novel_id={novel_id}",
        json={"target_scene_index": 5},
    )
    assert rollback_resp.status_code == 200
    data = rollback_resp.json()
    assert data["entity_id"] == entity_id
    assert data["target_scene_index"] == 5
    assert "summary" in data["restored_fields"]

    # 验证实体已恢复
    get_resp = await async_client.get(
        f"/api/world/entities/{entity_id}?novel_id={novel_id}",
    )
    assert get_resp.status_code == 200
    assert get_resp.json()["summary"] == "归档摘要"
