"""
Timeline 模块测试

测试 TimelineEvent CRUD、时间线上下文获取、冲突检查。
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from modules.timeline.facade import (
    check_timeline_conflicts,
    get_geo_effects_up_to_chapter,
    get_relevant_timeline_context,
)
from modules.timeline.repositories import TimelineEventRepository
from modules.timeline.schemas import (
    TimelineEventCreate,
    TimelineEventUpdate,
)
from modules.timeline.services import TimelineService

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def repo() -> TimelineEventRepository:
    return TimelineEventRepository()


@pytest.fixture
def service() -> TimelineService:
    return TimelineService()


@pytest.fixture
def sample_event_data_1() -> TimelineEventCreate:
    return TimelineEventCreate(
        title="主角出发",
        summary="主角离开村庄开始冒险",
        order_index=100,
        chapter_index=1,
        event_type="plot",
        related_character_ids=[str(uuid.uuid4())],
        related_location_ids=[str(uuid.uuid4())],
        status="canonical",
    )


@pytest.fixture
def sample_event_data_2() -> TimelineEventCreate:
    return TimelineEventCreate(
        title="到达古城",
        summary="主角抵达古城遗迹",
        order_index=200,
        chapter_index=3,
        event_type="travel",
        status="canonical",
    )


@pytest.fixture
def sample_event_data_3() -> TimelineEventCreate:
    return TimelineEventCreate(
        title="发现秘密入口",
        summary="主角在古城中发现秘密入口",
        order_index=300,
        chapter_index=5,
        event_type="discovery",
        status="canonical",
    )


# ============================================================
# TimelineEventRepository 测试
# ============================================================


class TestTimelineEventRepository:
    """测试时间线事件数据访问层"""

    @pytest.mark.asyncio
    async def test_create(
        self,
        repo: TimelineEventRepository,
        db_session: AsyncSession,
        novel_id: str,
        sample_event_data_1: TimelineEventCreate,
    ) -> None:
        """测试创建时间线事件"""
        nid = uuid.UUID(hex=novel_id)
        event = await repo.create(db_session, nid, sample_event_data_1)
        assert event.id is not None
        assert event.title == "主角出发"
        assert event.order_index == 100
        assert event.chapter_index == 1
        assert event.event_type == "plot"
        assert event.status == "canonical"

    @pytest.mark.asyncio
    async def test_get(
        self,
        repo: TimelineEventRepository,
        db_session: AsyncSession,
        novel_id: str,
        sample_event_data_1: TimelineEventCreate,
    ) -> None:
        """测试根据 ID 获取事件"""
        nid = uuid.UUID(hex=novel_id)
        created = await repo.create(db_session, nid, sample_event_data_1)
        fetched = await repo.get(db_session, created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.title == "主角出发"

    @pytest.mark.asyncio
    async def test_get_not_found(
        self,
        repo: TimelineEventRepository,
        db_session: AsyncSession,
    ) -> None:
        """测试获取不存在的事件"""
        fake_id = uuid.uuid4()
        fetched = await repo.get(db_session, fake_id)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_get_multi(
        self,
        repo: TimelineEventRepository,
        db_session: AsyncSession,
        novel_id: str,
        sample_event_data_1: TimelineEventCreate,
        sample_event_data_2: TimelineEventCreate,
        sample_event_data_3: TimelineEventCreate,
    ) -> None:
        """测试分页获取事件列表"""
        nid = uuid.UUID(hex=novel_id)
        await repo.create(db_session, nid, sample_event_data_1)
        await repo.create(db_session, nid, sample_event_data_2)
        await repo.create(db_session, nid, sample_event_data_3)
        await db_session.flush()

        # 测试所有事件
        items, total = await repo.get_multi(db_session, nid, limit=10)
        assert total == 3
        assert len(items) == 3

        # 验证按 order_index 升序排列
        assert items[0].order_index == 100
        assert items[1].order_index == 200
        assert items[2].order_index == 300

    @pytest.mark.asyncio
    async def test_get_multi_with_filters(
        self,
        repo: TimelineEventRepository,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        """测试按条件过滤"""
        nid = uuid.UUID(hex=novel_id)
        char_id = str(uuid.uuid4())

        # 创建两个事件，一个关联角色
        await repo.create(
            db_session,
            nid,
            TimelineEventCreate(
                title="事件A",
                summary="关联角色的事件",
                order_index=100,
                chapter_index=1,
                related_character_ids=[char_id],
                status="canonical",
            ),
        )
        await repo.create(
            db_session,
            nid,
            TimelineEventCreate(
                title="事件B",
                summary="普通事件",
                order_index=200,
                chapter_index=3,
                status="candidate",
            ),
        )
        await db_session.flush()

        # 按角色过滤
        items, total = await repo.get_multi(db_session, nid, character_id=char_id)
        assert total == 1
        assert items[0].title == "事件A"

        # 按状态过滤
        items, total = await repo.get_multi(db_session, nid, status="candidate")
        assert total == 1
        assert items[0].title == "事件B"

    @pytest.mark.asyncio
    async def test_update(
        self,
        repo: TimelineEventRepository,
        db_session: AsyncSession,
        novel_id: str,
        sample_event_data_1: TimelineEventCreate,
    ) -> None:
        """测试更新时间线事件"""
        nid = uuid.UUID(hex=novel_id)
        created = await repo.create(db_session, nid, sample_event_data_1)

        updated = await repo.update(
            db_session,
            created.id,
            TimelineEventUpdate(
                title="主角出发（修订）",
                chapter_index=2,
            ),
        )
        assert updated is not None
        assert updated.title == "主角出发（修订）"
        assert updated.chapter_index == 2
        # 未更新字段保持不变
        assert updated.order_index == 100

    @pytest.mark.asyncio
    async def test_delete(
        self,
        repo: TimelineEventRepository,
        db_session: AsyncSession,
        novel_id: str,
        sample_event_data_1: TimelineEventCreate,
    ) -> None:
        """测试删除时间线事件"""
        nid = uuid.UUID(hex=novel_id)
        created = await repo.create(db_session, nid, sample_event_data_1)
        deleted = await repo.delete(db_session, created.id)
        assert deleted is True
        fetched = await repo.get(db_session, created.id)
        assert fetched is None

    @pytest.mark.asyncio
    async def test_get_max_order_index(
        self,
        repo: TimelineEventRepository,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        """测试获取最大 order_index"""
        nid = uuid.UUID(hex=novel_id)

        # 空表时返回 -1
        max_order = await repo.get_max_order_index(db_session, nid)
        assert max_order == -1

        # 添加事件后
        await repo.create(
            db_session,
            nid,
            TimelineEventCreate(title="事件", summary="测试", order_index=500),
        )
        await db_session.flush()

        max_order = await repo.get_max_order_index(db_session, nid)
        assert max_order == 500

    @pytest.mark.asyncio
    async def test_get_all_by_novel(
        self,
        repo: TimelineEventRepository,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        """测试获取全部事件"""
        nid = uuid.UUID(hex=novel_id)
        e1 = await repo.create(
            db_session,
            nid,
            TimelineEventCreate(title="事件一", summary="第一", order_index=200),
        )
        e2 = await repo.create(
            db_session,
            nid,
            TimelineEventCreate(title="事件二", summary="第二", order_index=100),
        )
        await db_session.flush()

        all_events = await repo.get_all_by_novel(db_session, nid)
        assert len(all_events) == 2
        # 按 order_index 升序
        assert all_events[0].id == e2.id
        assert all_events[1].id == e1.id


# ============================================================
# TimelineService 测试
# ============================================================


class TestTimelineService:
    """测试时间线业务逻辑层"""

    @pytest.mark.asyncio
    async def test_create_event(
        self,
        service: TimelineService,
        db_session: AsyncSession,
        novel_id: str,
        sample_event_data_1: TimelineEventCreate,
    ) -> None:
        """测试服务层创建事件"""
        resp = await service.create_event(db_session, novel_id, sample_event_data_1)
        assert resp.id is not None
        assert resp.title == "主角出发"
        assert resp.order_index == 100

    @pytest.mark.asyncio
    async def test_get_event_not_found(
        self,
        service: TimelineService,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        """测试获取不存在的事件"""
        fake_id = str(uuid.uuid4())
        with pytest.raises(HTTPException) as exc_info:
            await service.get_event(db_session, fake_id, novel_id)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_get_relevant_timeline_context(
        self,
        service: TimelineService,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        """测试获取时间线上下文"""
        nid = uuid.UUID(hex=novel_id)
        repo = TimelineEventRepository()
        char_id = str(uuid.uuid4())

        # 创建事件
        await repo.create(
            db_session,
            nid,
            TimelineEventCreate(
                title="事件一",
                summary="第一章事件",
                order_index=100,
                chapter_index=1,
                status="canonical",
            ),
        )
        await repo.create(
            db_session,
            nid,
            TimelineEventCreate(
                title="事件二",
                summary="第三章事件",
                order_index=200,
                chapter_index=3,
                status="canonical",
                related_character_ids=[char_id],
            ),
        )
        await repo.create(
            db_session,
            nid,
            TimelineEventCreate(
                title="事件三",
                summary="第五章事件（候选）",
                order_index=300,
                chapter_index=5,
                status="candidate",
            ),
        )
        await db_session.flush()

        # 按章节获取（只返回该章节前的事件）
        ctx = await service.get_relevant_timeline_context(
            db_session, novel_id, chapter_index=3
        )
        assert len(ctx) > 0
        for c in ctx:
            assert c.chapter_index is None or c.chapter_index <= 3

        # 按角色获取
        ctx = await service.get_relevant_timeline_context(
            db_session, novel_id, character_id=char_id
        )
        assert len(ctx) == 1
        assert ctx[0].title == "事件二"


# ============================================================
# Facade 测试
# ============================================================


class TestTimelineFacade:
    """测试对外入口"""

    @pytest.mark.asyncio
    async def test_get_relevant_timeline_context(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        """测试 facade 获取时间线上下文"""
        nid = uuid.UUID(hex=novel_id)
        repo = TimelineEventRepository()

        await repo.create(
            db_session,
            nid,
            TimelineEventCreate(
                title="事件一",
                summary="第一章",
                order_index=100,
                chapter_index=1,
                status="canonical",
                visibility="reader_known",
            ),
        )
        await repo.create(
            db_session,
            nid,
            TimelineEventCreate(
                title="事件二",
                summary="第二章",
                order_index=200,
                chapter_index=2,
                status="canonical",
                visibility="reader_known",
            ),
        )
        await db_session.flush()

        ctx = await get_relevant_timeline_context(db_session, novel_id, chapter_index=2)
        assert len(ctx) >= 1

    @pytest.mark.asyncio
    async def test_check_timeline_conflicts(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        """测试冲突检查"""
        nid = uuid.UUID(hex=novel_id)
        repo = TimelineEventRepository()

        # 创建正史事件
        await repo.create(
            db_session,
            nid,
            TimelineEventCreate(
                title="主角出发",
                summary="离开村庄",
                order_index=100,
                chapter_index=1,
                status="canonical",
            ),
        )
        await repo.create(
            db_session,
            nid,
            TimelineEventCreate(
                title="到达古城",
                summary="抵达古城",
                order_index=200,
                chapter_index=3,
                status="canonical",
            ),
        )
        await db_session.flush()

        # 候选结构中包含顺序矛盾的事件
        structure_candidate: dict[str, Any] = {
            "events": [
                {
                    "title": "到达古城",
                    "summary": "抵达古城",
                    "order_index": 200,
                    "chapter_index": 3,
                },
                {
                    "title": "发现秘密",
                    "summary": "在古城发现秘密",
                    "order_index": 150,
                    "chapter_index": 5,
                },
            ]
        }

        warnings = await check_timeline_conflicts(
            db_session, novel_id, structure_candidate
        )

        # 应该检测到"到达古城"与已有事件重复
        duplicate_warnings = [w for w in warnings if w.type == "duplicate_event"]
        assert len(duplicate_warnings) >= 1

    @pytest.mark.asyncio
    async def test_check_no_conflicts(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        """测试无冲突时应返回空列表"""
        # 没有已有事件
        structure_candidate: dict[str, Any] = {
            "events": [
                {
                    "title": "全新事件",
                    "summary": "完全新的事件",
                    "order_index": 10,
                    "chapter_index": 1,
                },
            ]
        }

        warnings = await check_timeline_conflicts(
            db_session, novel_id, structure_candidate
        )
        assert len(warnings) == 0

    @pytest.mark.asyncio
    async def test_order_conflict(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        """测试顺序冲突"""
        nid = uuid.UUID(hex=novel_id)
        repo = TimelineEventRepository()

        await repo.create(
            db_session,
            nid,
            TimelineEventCreate(
                title="古城事件",
                summary="古城",
                order_index=200,
                chapter_index=3,
                status="canonical",
            ),
        )
        await db_session.flush()

        # 候选事件 order_index 在已有事件之后，但 chapter_index 却在之前
        structure_candidate: dict[str, Any] = {
            "events": [
                {
                    "title": "前面的事件",
                    "summary": "应该在前面",
                    "order_index": 300,
                    "chapter_index": 1,
                },
            ]
        }

        warnings = await check_timeline_conflicts(
            db_session, novel_id, structure_candidate
        )
        order_warnings = [w for w in warnings if w.type == "order_conflict"]
        assert len(order_warnings) >= 1


# ============================================================
# get_geo_effects_up_to_chapter 测试
# ============================================================


class TestGetGeoEffects:
    @pytest.mark.asyncio
    async def test_returns_geo_effects_from_canonical_events_up_to_chapter(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)
        repo = TimelineEventRepository()

        await repo.create(
            db_session,
            nid,
            TimelineEventCreate(
                title="桥梁被毁",
                summary="战争摧毁了石桥",
                order_index=100,
                chapter_index=1,
                status="canonical",
                geo_effects=[{"location_id": "loc-1", "effect_type": "destroyed"}],
            ),
        )
        await repo.create(
            db_session,
            nid,
            TimelineEventCreate(
                title="道路修复",
                summary="商人集资修复道路",
                order_index=200,
                chapter_index=3,
                status="canonical",
                geo_effects=[{"location_id": "loc-2", "effect_type": "restored"}],
            ),
        )
        await repo.create(
            db_session,
            nid,
            TimelineEventCreate(
                title="港口封锁",
                summary="港口被军事封锁",
                order_index=300,
                chapter_index=5,
                status="canonical",
                geo_effects=[{"location_id": "loc-3", "effect_type": "blocked"}],
            ),
        )
        await db_session.flush()

        effects = await get_geo_effects_up_to_chapter(
            db_session,
            novel_id,
            chapter_index=3,
        )
        assert len(effects) == 2
        assert effects[0]["location_id"] == "loc-1"
        assert effects[1]["location_id"] == "loc-2"

    @pytest.mark.asyncio
    async def test_excludes_candidate_events(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)
        repo = TimelineEventRepository()

        await repo.create(
            db_session,
            nid,
            TimelineEventCreate(
                title="候选事件",
                summary="尚未确认的地理变化",
                order_index=100,
                chapter_index=1,
                status="candidate",
                geo_effects=[{"location_id": "loc-cand", "effect_type": "changed"}],
            ),
        )
        await db_session.flush()

        effects = await get_geo_effects_up_to_chapter(
            db_session,
            novel_id,
            chapter_index=5,
        )
        assert len(effects) == 0

    @pytest.mark.asyncio
    async def test_excludes_events_with_empty_geo_effects(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)
        repo = TimelineEventRepository()

        await repo.create(
            db_session,
            nid,
            TimelineEventCreate(
                title="无地理影响事件",
                summary="普通剧情事件",
                order_index=100,
                chapter_index=1,
                status="canonical",
                geo_effects=[],
            ),
        )
        await repo.create(
            db_session,
            nid,
            TimelineEventCreate(
                title="有地理影响事件",
                summary="影响地理的事件",
                order_index=200,
                chapter_index=2,
                status="canonical",
                geo_effects=[{"location_id": "loc-1", "effect_type": "destroyed"}],
            ),
        )
        await db_session.flush()

        effects = await get_geo_effects_up_to_chapter(
            db_session,
            novel_id,
            chapter_index=5,
        )
        assert len(effects) == 1
        assert effects[0]["location_id"] == "loc-1"

    @pytest.mark.asyncio
    async def test_facade_returns_same_results(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)
        repo = TimelineEventRepository()
        service = TimelineService()

        await repo.create(
            db_session,
            nid,
            TimelineEventCreate(
                title="桥梁被毁",
                summary="战争摧毁了石桥",
                order_index=100,
                chapter_index=1,
                status="canonical",
                geo_effects=[{"location_id": "loc-1", "effect_type": "destroyed"}],
            ),
        )
        await db_session.flush()

        facade_result = await get_geo_effects_up_to_chapter(
            db_session,
            novel_id,
            chapter_index=3,
        )
        service_result = await service.get_geo_effects_up_to_chapter(
            db_session,
            novel_id,
            chapter_index=3,
        )
        assert facade_result == service_result
        assert len(facade_result) == 1

    @pytest.mark.asyncio
    async def test_includes_events_with_null_chapter_index(
        self,
        db_session: AsyncSession,
        novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)
        repo = TimelineEventRepository()

        await repo.create(
            db_session,
            nid,
            TimelineEventCreate(
                title="全局地理事件",
                summary="影响整个世界的地理变化",
                order_index=50,
                chapter_index=None,
                status="canonical",
                geo_effects=[{"location_id": "loc-global", "effect_type": "shifted"}],
            ),
        )
        await repo.create(
            db_session,
            nid,
            TimelineEventCreate(
                title="章节事件",
                summary="第一章的地理变化",
                order_index=100,
                chapter_index=1,
                status="canonical",
                geo_effects=[{"location_id": "loc-1", "effect_type": "destroyed"}],
            ),
        )
        await db_session.flush()

        effects = await get_geo_effects_up_to_chapter(
            db_session,
            novel_id,
            chapter_index=1,
        )
        assert len(effects) == 2
        assert effects[0]["location_id"] == "loc-global"
        assert effects[1]["location_id"] == "loc-1"
