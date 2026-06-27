"""
Outline 模块测试

测试所有 CRUD 路径、facade、剧情线查询、章节卡按索引查询、候选批量创建。
使用 pytest-asyncio 测试异步数据库操作。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.outline.facade import (
    create_chapter_cards_from_candidate,
    get_active_threads,
    get_arc_context,
    get_chapter_card,
)
from modules.outline.repositories import (
    ChapterCardRepository,
    ForeshadowingPlanRepository,
    OutlineArcRepository,
    PlotThreadRepository,
    RevealPlanRepository,
)
from modules.outline.schemas import (
    ChapterCardCandidateItem,
    ChapterCardCreate,
    ChapterCardUpdate,
    ForeshadowingPlanCreate,
    ForeshadowingPlanUpdate,
    OutlineArcCreate,
    OutlineArcUpdate,
    PlotThreadCreate,
    PlotThreadUpdate,
    RevealPlanCreate,
    RevealPlanUpdate,
)
from modules.outline.services import (
    ChapterCardService,
    ForeshadowingPlanService,
    OutlineArcService,
    PlotThreadService,
    RevealPlanService,
)

CHARACTER_TARGET_ID = "a1111111-1111-1111-1111-111111111111"
ENTITY_TARGET_ID = "b2222222-2222-2222-2222-222222222222"

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def novel_id() -> str:
    return str(uuid.uuid4())


@pytest.fixture
def thread_repo() -> PlotThreadRepository:
    return PlotThreadRepository()


@pytest.fixture
def arc_repo() -> OutlineArcRepository:
    return OutlineArcRepository()


@pytest.fixture
def chapter_repo() -> ChapterCardRepository:
    return ChapterCardRepository()


@pytest.fixture
def foreshadowing_repo() -> ForeshadowingPlanRepository:
    return ForeshadowingPlanRepository()


@pytest.fixture
def reveal_repo() -> RevealPlanRepository:
    return RevealPlanRepository()


@pytest.fixture
def thread_service() -> PlotThreadService:
    return PlotThreadService()


@pytest.fixture
def arc_service() -> OutlineArcService:
    return OutlineArcService()


@pytest.fixture
def chapter_service() -> ChapterCardService:
    return ChapterCardService()


@pytest.fixture
def foreshadowing_service() -> ForeshadowingPlanService:
    return ForeshadowingPlanService()


@pytest.fixture
def reveal_service() -> RevealPlanService:
    return RevealPlanService()


@pytest.fixture
def sample_thread_data() -> PlotThreadCreate:
    return PlotThreadCreate(
        name="主角的复仇之路",
        thread_type="main",
        summary="主角从被背叛到最终复仇的主线故事",
        visible_goal="查明真相并复仇",
        hidden_truth="主角的仇人实际上是他的亲生父亲",
        start_chapter=1,
        planned_payoff_chapter=50,
        current_stage="第一阶段：觉醒",
        related_character_ids=["char-001", "char-002"],
        related_entity_ids=["ent-001", "ent-002"],
        reader_known_state="第一章：主角被背叛",
        author_known_state="全程",
    )


@pytest.fixture
def sample_thread_data2() -> PlotThreadCreate:
    return PlotThreadCreate(
        name="皇室阴谋",
        thread_type="hidden",
        summary="隐藏的皇室权力斗争",
        start_chapter=5,
        planned_payoff_chapter=40,
    )


@pytest.fixture
def sample_arc_data() -> OutlineArcCreate:
    return OutlineArcCreate(
        title="第一卷：觉醒",
        arc_index=1,
        start_chapter=1,
        end_chapter=12,
        arc_goal="建立主角的基本设定和初期冲突",
        core_conflict="主角与背叛者的对抗",
        main_opposition="背叛者联盟",
        entry_hook="主角在重要仪式上被当众揭发",
        midpoint_turn="主角发现背叛者的真正身份",
        climax="主角与背叛者的第一次正面对决",
        result="主角逃离追捕，获得第一个盟友",
        next_hook="主角发现更大的阴谋正在酝酿",
        related_thread_ids=["thread-001", "thread-002"],
        related_character_ids=["char-001"],
        related_entity_ids=["ent-001"],
    )


@pytest.fixture
def sample_chapter_data() -> ChapterCardCreate:
    return ChapterCardCreate(
        chapter_index=1,
        title="背叛之夜",
        chapter_goal="建立主角初始状态，展示背叛事件",
        main_conflict="主角在仪式上被最信任的人背叛",
        emotional_point="震惊与绝望",
        plot_function="setup",
        must_happen=["主角在仪式上被揭发", "主角失去重要身份"],
        must_not_happen=["主角当场死亡"],
        involved_character_ids=["char-001", "char-002", "char-003"],
        involved_entity_ids=["ent-001"],
        related_thread_ids=["thread-001"],
        visible_progress=["主角被逐出家族"],
        hidden_progress=["背叛者实际上是受某人指使"],
        offscreen_progress=["幕后黑手在观察一切"],
        foreshadowing_actions=[
            {"type": "seed", "target": "主角的隐藏血脉", "chapter": 1},
        ],
        ending_hook="主角在雨中发誓：我一定会回来的",
        scene_cards=[
            {"scene_index": 1, "title": "仪式现场", "location": "大殿"},
            {"scene_index": 2, "title": "逃亡", "location": "后山"},
        ],
    )


@pytest.fixture
def sample_foreshadowing_data() -> ForeshadowingPlanCreate:
    return ForeshadowingPlanCreate(
        name="主角的隐藏血脉",
        summary="主角实际上是上古神族的后代",
        surface_meaning="主角在危机时表现出超常能力",
        hidden_meaning="主角的血脉力量会觉醒",
        planned_seed_chapter=1,
        planned_reinforce_chapters=[10, 20, 30],
        planned_payoff_chapter=50,
        related_entity_ids=["ent-001"],
        related_thread_ids=["thread-001"],
    )


@pytest.fixture
def sample_reveal_data() -> RevealPlanCreate:
    return RevealPlanCreate(
        target_type="character",
        target_id=CHARACTER_TARGET_ID,
        secret_summary="主角是上古神族的后裔",
        reveal_stages=[
            {"chapter_index": 1, "hint_level": "subtle", "content": "偶尔表现出异常"},
            {
                "chapter_index": 10,
                "hint_level": "obvious",
                "content": "有人认出主角的特征",
            },
            {
                "chapter_index": 30,
                "hint_level": "partial",
                "content": "主角被告知身世线索",
            },
            {"chapter_index": 50, "hint_level": "full", "content": "主角完全觉醒"},
        ],
    )


# ============================================================
# PlotThread CRUD 测试
# ============================================================


class TestPlotThreadService:
    """剧情线 CRUD 测试"""

    @pytest.mark.asyncio
    async def test_create_thread(
        self,
        db_session: AsyncSession,
        thread_service: PlotThreadService,
        novel_id: str,
        sample_thread_data: PlotThreadCreate,
    ) -> None:
        """测试创建剧情线"""
        result = await thread_service.create(db_session, novel_id, sample_thread_data)

        assert result.id is not None
        assert result.name == "主角的复仇之路"
        assert result.thread_type == "main"
        assert result.summary == "主角从被背叛到最终复仇的主线故事"
        assert result.hidden_truth == "主角的仇人实际上是他的亲生父亲"
        assert result.start_chapter == 1
        assert result.planned_payoff_chapter == 50
        assert result.current_stage == "第一阶段：觉醒"
        assert result.related_character_ids == ["char-001", "char-002"]
        assert result.related_entity_ids == ["ent-001", "ent-002"]
        assert result.status == "draft"
        assert result.novel_id == novel_id
        assert result.created_at is not None

    @pytest.mark.asyncio
    async def test_get_thread(
        self,
        db_session: AsyncSession,
        thread_service: PlotThreadService,
        novel_id: str,
        sample_thread_data: PlotThreadCreate,
    ) -> None:
        """测试获取剧情线"""
        created = await thread_service.create(db_session, novel_id, sample_thread_data)
        result = await thread_service.get(db_session, created.id, novel_id)

        assert result.id == created.id
        assert result.name == "主角的复仇之路"

    @pytest.mark.asyncio
    async def test_get_thread_not_found(
        self,
        db_session: AsyncSession,
        thread_service: PlotThreadService,
        novel_id: str,
    ) -> None:
        """测试获取不存在的剧情线返回 404"""
        with pytest.raises(HTTPException) as exc:
            await thread_service.get(db_session, str(uuid.uuid4()), novel_id)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_list_threads(
        self,
        db_session: AsyncSession,
        thread_service: PlotThreadService,
        novel_id: str,
        sample_thread_data: PlotThreadCreate,
        sample_thread_data2: PlotThreadCreate,
    ) -> None:
        """测试列表查询"""
        await thread_service.create(db_session, novel_id, sample_thread_data)
        await thread_service.create(db_session, novel_id, sample_thread_data2)

        # 全部列表
        result = await thread_service.list(db_session, novel_id)
        assert result.total == 2
        assert len(result.items) == 2

        # 按类型过滤
        result = await thread_service.list(
            db_session,
            novel_id,
            thread_type="main",
        )
        assert result.total == 1
        assert result.items[0].thread_type == "main"

        # 分页
        result = await thread_service.list(db_session, novel_id, skip=0, limit=1)
        assert len(result.items) == 1

    @pytest.mark.asyncio
    async def test_update_thread(
        self,
        db_session: AsyncSession,
        thread_service: PlotThreadService,
        novel_id: str,
        sample_thread_data: PlotThreadCreate,
    ) -> None:
        """测试更新剧情线"""
        created = await thread_service.create(db_session, novel_id, sample_thread_data)

        update_data = PlotThreadUpdate(
            name="主角的复仇之路（第二版）",
            current_stage="第二阶段：成长",
            status="canonical",
        )
        result = await thread_service.update(
            db_session, created.id, update_data, novel_id
        )

        assert result.name == "主角的复仇之路（第二版）"
        assert result.current_stage == "第二阶段：成长"
        assert result.status == "canonical"

    @pytest.mark.asyncio
    async def test_delete_thread(
        self,
        db_session: AsyncSession,
        thread_service: PlotThreadService,
        novel_id: str,
        sample_thread_data: PlotThreadCreate,
    ) -> None:
        """测试删除剧情线"""
        created = await thread_service.create(db_session, novel_id, sample_thread_data)
        await thread_service.delete(db_session, created.id, novel_id)

        with pytest.raises(HTTPException) as exc:
            await thread_service.get(db_session, created.id, novel_id)
        assert exc.value.status_code == 404


# ============================================================
# OutlineArc CRUD 测试
# ============================================================


class TestOutlineArcService:
    """篇章纲 CRUD 测试"""

    def test_create_arc_requires_result(self) -> None:
        """手动创建篇章纲必须提交结果字段"""
        with pytest.raises(ValidationError, match="result"):
            OutlineArcCreate(
                title="第一卷：觉醒",
                arc_index=1,
                start_chapter=1,
                end_chapter=12,
                arc_goal="建立主角的基本设定和初期冲突",
                core_conflict="主角与背叛者的对抗",
                climax="主角与背叛者的第一次正面对决",
            )

    @pytest.mark.asyncio
    async def test_create_arc(
        self,
        db_session: AsyncSession,
        arc_service: OutlineArcService,
        novel_id: str,
        sample_arc_data: OutlineArcCreate,
    ) -> None:
        """测试创建篇章纲"""
        result = await arc_service.create(db_session, novel_id, sample_arc_data)

        assert result.id is not None
        assert result.title == "第一卷：觉醒"
        assert result.arc_index == 1
        assert result.start_chapter == 1
        assert result.end_chapter == 12
        assert result.arc_goal == "建立主角的基本设定和初期冲突"
        assert result.core_conflict == "主角与背叛者的对抗"
        assert result.entry_hook == "主角在重要仪式上被当众揭发"
        assert result.midpoint_turn == "主角发现背叛者的真正身份"
        assert result.climax == "主角与背叛者的第一次正面对决"
        assert result.next_hook == "主角发现更大的阴谋正在酝酿"
        assert result.related_thread_ids == ["thread-001", "thread-002"]
        assert result.status == "draft"

    @pytest.mark.asyncio
    async def test_get_arc(
        self,
        db_session: AsyncSession,
        arc_service: OutlineArcService,
        novel_id: str,
        sample_arc_data: OutlineArcCreate,
    ) -> None:
        """测试获取篇章纲"""
        created = await arc_service.create(db_session, novel_id, sample_arc_data)
        result = await arc_service.get(db_session, created.id, novel_id)

        assert result.id == created.id
        assert result.title == "第一卷：觉醒"

    @pytest.mark.asyncio
    async def test_get_arc_not_found(
        self,
        db_session: AsyncSession,
        arc_service: OutlineArcService,
        novel_id: str,
    ) -> None:
        """测试获取不存在的篇章纲返回 404"""
        with pytest.raises(HTTPException) as exc:
            await arc_service.get(db_session, str(uuid.uuid4()), novel_id)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_list_arcs(
        self,
        db_session: AsyncSession,
        arc_service: OutlineArcService,
        novel_id: str,
        sample_arc_data: OutlineArcCreate,
    ) -> None:
        """测试篇章纲列表"""
        await arc_service.create(db_session, novel_id, sample_arc_data)

        result = await arc_service.list(db_session, novel_id)
        assert result.total == 1
        assert len(result.items) == 1

    @pytest.mark.asyncio
    async def test_update_arc(
        self,
        db_session: AsyncSession,
        arc_service: OutlineArcService,
        novel_id: str,
        sample_arc_data: OutlineArcCreate,
    ) -> None:
        """测试更新篇章纲"""
        created = await arc_service.create(db_session, novel_id, sample_arc_data)

        update_data = OutlineArcUpdate(
            title="第一卷：觉醒（修订版）",
            status="canonical",
        )
        result = await arc_service.update(db_session, created.id, update_data, novel_id)

        assert result.title == "第一卷：觉醒（修订版）"
        assert result.status == "canonical"

    @pytest.mark.asyncio
    async def test_delete_arc(
        self,
        db_session: AsyncSession,
        arc_service: OutlineArcService,
        novel_id: str,
        sample_arc_data: OutlineArcCreate,
    ) -> None:
        """测试删除篇章纲"""
        created = await arc_service.create(db_session, novel_id, sample_arc_data)
        await arc_service.delete(db_session, created.id, novel_id)

        with pytest.raises(HTTPException) as exc:
            await arc_service.get(db_session, created.id, novel_id)
        assert exc.value.status_code == 404


# ============================================================
# ChapterCard CRUD 测试
# ============================================================


class TestChapterCardService:
    """章节卡 CRUD 测试"""

    @pytest.mark.asyncio
    async def test_create_chapter(
        self,
        db_session: AsyncSession,
        chapter_service: ChapterCardService,
        novel_id: str,
        sample_chapter_data: ChapterCardCreate,
    ) -> None:
        """测试创建章节卡"""
        result = await chapter_service.create(db_session, novel_id, sample_chapter_data)

        assert result.id is not None
        assert result.chapter_index == 1
        assert result.title == "背叛之夜"
        assert result.chapter_goal == "建立主角初始状态，展示背叛事件"
        assert result.main_conflict == "主角在仪式上被最信任的人背叛"
        assert result.emotional_point == "震惊与绝望"
        assert result.plot_function == "setup"
        assert len(result.must_happen) == 2
        assert result.ending_hook == "主角在雨中发誓：我一定会回来的"
        assert len(result.scene_cards) == 2
        assert result.status == "draft"

    @pytest.mark.asyncio
    async def test_get_chapter(
        self,
        db_session: AsyncSession,
        chapter_service: ChapterCardService,
        novel_id: str,
        sample_chapter_data: ChapterCardCreate,
    ) -> None:
        """测试获取章节卡"""
        created = await chapter_service.create(db_session, novel_id, sample_chapter_data)
        result = await chapter_service.get(db_session, created.id, novel_id)

        assert result.id == created.id
        assert result.chapter_index == 1

    @pytest.mark.asyncio
    async def test_get_chapter_by_index(
        self,
        db_session: AsyncSession,
        chapter_service: ChapterCardService,
        novel_id: str,
        sample_chapter_data: ChapterCardCreate,
    ) -> None:
        """测试按章节索引获取章节卡"""
        await chapter_service.create(db_session, novel_id, sample_chapter_data)
        result = await chapter_service.get_by_chapter_index(db_session, novel_id, 1)

        assert result is not None
        assert result.chapter_index == 1
        assert result.title == "背叛之夜"

        # 不存在的章节
        result = await chapter_service.get_by_chapter_index(db_session, novel_id, 999)
        assert result is None

    @pytest.mark.asyncio
    async def test_list_chapters(
        self,
        db_session: AsyncSession,
        chapter_service: ChapterCardService,
        novel_id: str,
        sample_chapter_data: ChapterCardCreate,
    ) -> None:
        """测试章节卡列表"""
        await chapter_service.create(db_session, novel_id, sample_chapter_data)

        result = await chapter_service.list(db_session, novel_id)
        assert result.total == 1
        assert len(result.items) == 1

    @pytest.mark.asyncio
    async def test_update_chapter(
        self,
        db_session: AsyncSession,
        chapter_service: ChapterCardService,
        novel_id: str,
        sample_chapter_data: ChapterCardCreate,
    ) -> None:
        """测试更新章节卡"""
        created = await chapter_service.create(db_session, novel_id, sample_chapter_data)

        update_data = ChapterCardUpdate(
            title="背叛之夜（修订版）",
            status="canonical",
        )
        result = await chapter_service.update(
            db_session, created.id, update_data, novel_id
        )

        assert result.title == "背叛之夜（修订版）"
        assert result.status == "canonical"

    @pytest.mark.asyncio
    async def test_delete_chapter(
        self,
        db_session: AsyncSession,
        chapter_service: ChapterCardService,
        novel_id: str,
        sample_chapter_data: ChapterCardCreate,
    ) -> None:
        """测试删除章节卡"""
        created = await chapter_service.create(db_session, novel_id, sample_chapter_data)
        await chapter_service.delete(db_session, created.id, novel_id)

        with pytest.raises(HTTPException) as exc:
            await chapter_service.get(db_session, created.id, novel_id)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_create_from_candidate(
        self,
        db_session: AsyncSession,
        chapter_service: ChapterCardService,
        novel_id: str,
    ) -> None:
        """测试从候选创建章节卡"""
        cards = [
            ChapterCardCandidateItem(
                chapter_index=1,
                chapter_goal="开篇",
                main_conflict="冲突A",
                title="第一章",
                involved_character_ids=["c1"],
            ),
            ChapterCardCandidateItem(
                chapter_index=2,
                chapter_goal="发展",
                main_conflict="冲突B",
                title="第二章",
                involved_character_ids=["c2"],
            ),
        ]
        results = await chapter_service.create_from_candidate(
            db_session,
            novel_id,
            cards,
        )

        assert len(results) == 2
        assert results[0].chapter_index == 1
        assert results[0].chapter_goal == "开篇"
        assert results[1].chapter_index == 2
        assert results[1].chapter_goal == "发展"

        # 重复创建应跳过已存在章节
        results2 = await chapter_service.create_from_candidate(
            db_session,
            novel_id,
            cards,
        )
        assert len(results2) == 0


# ============================================================
# ForeshadowingPlan CRUD 测试
# ============================================================


class TestForeshadowingPlanService:
    """伏笔计划 CRUD 测试"""

    @pytest.mark.asyncio
    async def test_create_foreshadowing(
        self,
        db_session: AsyncSession,
        foreshadowing_service: ForeshadowingPlanService,
        novel_id: str,
        sample_foreshadowing_data: ForeshadowingPlanCreate,
    ) -> None:
        """测试创建伏笔计划"""
        result = await foreshadowing_service.create(
            db_session,
            novel_id,
            sample_foreshadowing_data,
        )

        assert result.id is not None
        assert result.name == "主角的隐藏血脉"
        assert result.summary == "主角实际上是上古神族的后代"
        assert result.surface_meaning == "主角在危机时表现出超常能力"
        assert result.hidden_meaning == "主角的血脉力量会觉醒"
        assert result.planned_seed_chapter == 1
        assert result.planned_reinforce_chapters == [10, 20, 30]
        assert result.planned_payoff_chapter == 50
        assert result.related_entity_ids == ["ent-001"]
        assert result.related_thread_ids == ["thread-001"]
        assert result.status == "draft"

    @pytest.mark.asyncio
    async def test_get_foreshadowing(
        self,
        db_session: AsyncSession,
        foreshadowing_service: ForeshadowingPlanService,
        novel_id: str,
        sample_foreshadowing_data: ForeshadowingPlanCreate,
    ) -> None:
        """测试获取伏笔计划"""
        created = await foreshadowing_service.create(
            db_session,
            novel_id,
            sample_foreshadowing_data,
        )
        result = await foreshadowing_service.get(db_session, created.id, novel_id)

        assert result.id == created.id
        assert result.name == "主角的隐藏血脉"

    @pytest.mark.asyncio
    async def test_get_foreshadowing_not_found(
        self,
        db_session: AsyncSession,
        foreshadowing_service: ForeshadowingPlanService,
        novel_id: str,
    ) -> None:
        """测试获取不存在的伏笔计划返回 404"""
        with pytest.raises(HTTPException) as exc:
            await foreshadowing_service.get(db_session, str(uuid.uuid4()), novel_id)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_foreshadowing(
        self,
        db_session: AsyncSession,
        foreshadowing_service: ForeshadowingPlanService,
        novel_id: str,
        sample_foreshadowing_data: ForeshadowingPlanCreate,
    ) -> None:
        """测试更新伏笔计划"""
        created = await foreshadowing_service.create(
            db_session,
            novel_id,
            sample_foreshadowing_data,
        )

        update_data = ForeshadowingPlanUpdate(
            name="主角的隐藏血脉（修订版）",
            status="seeded",
        )
        result = await foreshadowing_service.update(
            db_session, created.id, update_data, novel_id
        )

        assert result.name == "主角的隐藏血脉（修订版）"
        assert result.status == "seeded"

    @pytest.mark.asyncio
    async def test_delete_foreshadowing(
        self,
        db_session: AsyncSession,
        foreshadowing_service: ForeshadowingPlanService,
        novel_id: str,
        sample_foreshadowing_data: ForeshadowingPlanCreate,
    ) -> None:
        """测试删除伏笔计划"""
        created = await foreshadowing_service.create(
            db_session,
            novel_id,
            sample_foreshadowing_data,
        )
        await foreshadowing_service.delete(db_session, created.id, novel_id)

        with pytest.raises(HTTPException) as exc:
            await foreshadowing_service.get(db_session, created.id, novel_id)
        assert exc.value.status_code == 404


# ============================================================
# RevealPlan CRUD 测试
# ============================================================


class TestRevealPlanService:
    """揭示计划 CRUD 测试"""

    @pytest.mark.asyncio
    async def test_create_reveal(
        self,
        db_session: AsyncSession,
        reveal_service: RevealPlanService,
        novel_id: str,
        sample_reveal_data: RevealPlanCreate,
    ) -> None:
        """测试创建揭示计划"""
        result = await reveal_service.create(db_session, novel_id, sample_reveal_data)

        assert result.id is not None
        assert result.target_type == "character"
        assert result.target_id == CHARACTER_TARGET_ID
        assert result.secret_summary == "主角是上古神族的后裔"
        assert len(result.reveal_stages) == 4
        assert result.status == "draft"

    @pytest.mark.asyncio
    async def test_get_reveal(
        self,
        db_session: AsyncSession,
        reveal_service: RevealPlanService,
        novel_id: str,
        sample_reveal_data: RevealPlanCreate,
    ) -> None:
        """测试获取揭示计划"""
        created = await reveal_service.create(db_session, novel_id, sample_reveal_data)
        result = await reveal_service.get(db_session, created.id, novel_id)

        assert result.id == created.id
        assert result.target_type == "character"

    @pytest.mark.asyncio
    async def test_get_reveal_not_found(
        self,
        db_session: AsyncSession,
        reveal_service: RevealPlanService,
        novel_id: str,
    ) -> None:
        """测试获取不存在的揭示计划返回 404"""
        with pytest.raises(HTTPException) as exc:
            await reveal_service.get(db_session, str(uuid.uuid4()), novel_id)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_reveal(
        self,
        db_session: AsyncSession,
        reveal_service: RevealPlanService,
        novel_id: str,
        sample_reveal_data: RevealPlanCreate,
    ) -> None:
        """测试更新揭示计划"""
        created = await reveal_service.create(db_session, novel_id, sample_reveal_data)

        update_data = RevealPlanUpdate(
            secret_summary="主角是上古神族的后裔（已确认）",
            status="canonical",
        )
        result = await reveal_service.update(
            db_session, created.id, update_data, novel_id
        )

        assert result.secret_summary == "主角是上古神族的后裔（已确认）"
        assert result.status == "canonical"

    @pytest.mark.asyncio
    async def test_delete_reveal(
        self,
        db_session: AsyncSession,
        reveal_service: RevealPlanService,
        novel_id: str,
        sample_reveal_data: RevealPlanCreate,
    ) -> None:
        """测试删除揭示计划"""
        created = await reveal_service.create(db_session, novel_id, sample_reveal_data)
        await reveal_service.delete(db_session, created.id, novel_id)

        with pytest.raises(HTTPException) as exc:
            await reveal_service.get(db_session, created.id, novel_id)
        assert exc.value.status_code == 404


# ============================================================
# Facade 功能测试
# ============================================================


class TestOutlineFacade:
    """Outline Facade 功能测试"""

    @pytest.mark.asyncio
    async def test_get_chapter_card(
        self,
        db_session: AsyncSession,
        chapter_service: ChapterCardService,
        novel_id: str,
        sample_chapter_data: ChapterCardCreate,
    ) -> None:
        """测试 facade get_chapter_card"""
        await chapter_service.create(db_session, novel_id, sample_chapter_data)

        result = await get_chapter_card(db_session, novel_id, 1)
        assert result is not None
        assert result.chapter_index == 1
        assert result.card_id is not None
        assert result.chapter_goal == "建立主角初始状态，展示背叛事件"

        # 不存在返回 None
        result = await get_chapter_card(db_session, novel_id, 999)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_active_threads(
        self,
        db_session: AsyncSession,
        thread_service: PlotThreadService,
        novel_id: str,
        sample_thread_data: PlotThreadCreate,
        sample_thread_data2: PlotThreadCreate,
    ) -> None:
        """测试 facade get_active_threads"""
        await thread_service.create(db_session, novel_id, sample_thread_data)
        await thread_service.create(db_session, novel_id, sample_thread_data2)

        # 不传 chapter_index，返回所有
        result = await get_active_threads(db_session, novel_id)
        assert len(result) == 2

        # 传 chapter=3，只有主线（start=1）活跃
        result = await get_active_threads(db_session, novel_id, chapter_index=3)
        assert len(result) >= 1

        # 检查返回格式
        thread = result[0]
        assert thread.thread_id is not None
        assert thread.name is not None
        assert thread.thread_type is not None

    @pytest.mark.asyncio
    async def test_get_arc_context(
        self,
        db_session: AsyncSession,
        arc_service: OutlineArcService,
        novel_id: str,
        sample_arc_data: OutlineArcCreate,
    ) -> None:
        """测试 facade get_arc_context"""
        created = await arc_service.create(db_session, novel_id, sample_arc_data)

        result = await get_arc_context(db_session, novel_id, created.id)
        assert result.arc_id == created.id
        assert result.title == "第一卷：觉醒"
        assert result.arc_goal == "建立主角的基本设定和初期冲突"
        assert result.core_conflict == "主角与背叛者的对抗"

        # 不存在的 arc 返回 404
        with pytest.raises(HTTPException) as exc:
            await get_arc_context(db_session, novel_id, str(uuid.uuid4()))
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_create_chapter_cards_from_candidate(
        self,
        db_session: AsyncSession,
        chapter_service: ChapterCardService,
        novel_id: str,
    ) -> None:
        """测试 facade create_chapter_cards_from_candidate"""
        # 先创建一个章节卡
        card1 = ChapterCardCreate(
            chapter_index=1,
            chapter_goal="开篇",
            main_conflict="冲突A",
        )
        await chapter_service.create(db_session, novel_id, card1)

        # 候选包含已存在的章节和新章节
        candidate_payload = {
            "cards": [
                {
                    "chapter_index": 1,
                    "chapter_goal": "开篇",
                    "main_conflict": "冲突A",
                    "title": "第一章",
                },
                {
                    "chapter_index": 2,
                    "chapter_goal": "发展",
                    "main_conflict": "冲突B",
                    "title": "第二章",
                },
                {
                    "chapter_index": 3,
                    "chapter_goal": "高潮",
                    "main_conflict": "冲突C",
                    "title": "第三章",
                },
            ],
        }

        results = await create_chapter_cards_from_candidate(
            db_session,
            novel_id,
            candidate_payload,
        )

        # 只有 2 和 3 是新创建的（1 已存在）
        assert len(results) == 2
        indices = [c.chapter_index for c in results]
        assert 2 in indices
        assert 3 in indices
        assert 1 not in indices


# ============================================================
# Repository 层测试
# ============================================================


class TestPlotThreadRepository:
    """剧情线 Repository 测试"""

    @pytest.mark.asyncio
    async def test_get_active_by_novel(
        self,
        db_session: AsyncSession,
        thread_repo: PlotThreadRepository,
        novel_id: str,
    ) -> None:
        """测试活跃剧情线查询"""
        nid = uuid.UUID(hex=novel_id)

        # 创建一条主线（ch1-50）
        t1 = await thread_repo.create(
            db_session,
            nid,
            PlotThreadCreate(
                name="主线",
                thread_type="main",
                start_chapter=1,
                planned_payoff_chapter=50,
            ),
        )
        # 创建一条暗线（ch10-40）
        t2 = await thread_repo.create(
            db_session,
            nid,
            PlotThreadCreate(
                name="暗线",
                thread_type="hidden",
                start_chapter=10,
                planned_payoff_chapter=40,
            ),
        )
        # 创建一条支线（ch5-8）
        t3 = await thread_repo.create(
            db_session,
            nid,
            PlotThreadCreate(
                name="支线",
                thread_type="secondary",
                start_chapter=5,
                planned_payoff_chapter=8,
            ),
        )

        # ch3: 只有主线活跃
        active_ch3 = await thread_repo.get_active_by_novel(
            db_session,
            nid,
            chapter_index=3,
        )
        active_ids_ch3 = [str(t.id) for t in active_ch3]
        assert str(t1.id) in active_ids_ch3
        assert str(t2.id) not in active_ids_ch3  # 未开始
        assert str(t3.id) not in active_ids_ch3  # 未开始

        # ch15: 主线+暗线活跃
        active_ch15 = await thread_repo.get_active_by_novel(
            db_session,
            nid,
            chapter_index=15,
        )
        active_ids_ch15 = [str(t.id) for t in active_ch15]
        assert str(t1.id) in active_ids_ch15
        assert str(t2.id) in active_ids_ch15
        assert str(t3.id) not in active_ids_ch15  # 已结束


class TestOutlineArcRepository:
    """篇章纲 Repository 测试"""

    @pytest.mark.asyncio
    async def test_get_by_chapter(
        self,
        db_session: AsyncSession,
        arc_repo: OutlineArcRepository,
        novel_id: str,
    ) -> None:
        """测试按章节查找篇章"""
        nid = uuid.UUID(hex=novel_id)

        arc1 = await arc_repo.create(
            db_session,
            nid,
            OutlineArcCreate(
                title="第一卷",
                arc_index=1,
                start_chapter=1,
                end_chapter=12,
                arc_goal="起步",
                core_conflict="初始冲突",
                climax="高潮对决",
                result="主角获胜",
            ),
        )
        arc2 = await arc_repo.create(
            db_session,
            nid,
            OutlineArcCreate(
                title="第二卷",
                arc_index=2,
                start_chapter=13,
                end_chapter=24,
                arc_goal="发展",
                core_conflict="中期冲突",
                climax="中期转折",
                result="陷入更大危机",
            ),
        )

        # ch5 -> 第一卷
        found1 = await arc_repo.get_by_chapter(db_session, nid, 5)
        assert found1 is not None
        assert found1.title == "第一卷"
        assert str(found1.id) == str(arc1.id)

        # ch20 -> 第二卷
        found2 = await arc_repo.get_by_chapter(db_session, nid, 20)
        assert found2 is not None
        assert found2.title == "第二卷"
        assert str(found2.id) == str(arc2.id)

        # ch999 -> None
        found3 = await arc_repo.get_by_chapter(db_session, nid, 999)
        assert found3 is None


class TestChapterCardRepository:
    """章节卡 Repository 测试"""

    @pytest.mark.asyncio
    async def test_unique_constraint(
        self,
        db_session: AsyncSession,
        chapter_repo: ChapterCardRepository,
        novel_id: str,
    ) -> None:
        """测试同小说内 chapter_index 唯一性"""
        nid = uuid.UUID(hex=novel_id)

        await chapter_repo.create(
            db_session,
            nid,
            ChapterCardCreate(chapter_index=1, chapter_goal="目标", main_conflict="冲突"),
        )

        # 同一 novel_id + chapter_index 应触发错误
        with pytest.raises(Exception):
            await chapter_repo.create(
                db_session,
                nid,
                ChapterCardCreate(
                    chapter_index=1,
                    chapter_goal="目标2",
                    main_conflict="冲突2",
                ),
            )

    @pytest.mark.asyncio
    async def test_get_range_by_chapter(
        self,
        db_session: AsyncSession,
        chapter_repo: ChapterCardRepository,
        novel_id: str,
    ) -> None:
        """测试按范围查询章节卡"""
        nid = uuid.UUID(hex=novel_id)

        for i in range(1, 11):
            await chapter_repo.create(
                db_session,
                nid,
                ChapterCardCreate(
                    chapter_index=i,
                    chapter_goal=f"目标{i}",
                    main_conflict=f"冲突{i}",
                ),
            )

        # ch3-7
        range_result = await chapter_repo.get_range_by_chapter(
            db_session,
            nid,
            3,
            7,
        )
        assert len(range_result) == 5
        indices = [c.chapter_index for c in range_result]
        assert 3 <= min(indices) and max(indices) <= 7


class TestRevealPlanRepository:
    """揭示计划 Repository 测试"""

    @pytest.mark.asyncio
    async def test_get_by_target(
        self,
        db_session: AsyncSession,
        reveal_repo: RevealPlanRepository,
        novel_id: str,
    ) -> None:
        """测试按目标查询揭示计划"""
        nid = uuid.UUID(hex=novel_id)

        await reveal_repo.create(
            db_session,
            nid,
            RevealPlanCreate(
                target_type="character",
                target_id=CHARACTER_TARGET_ID,
                secret_summary="秘密A",
            ),
        )
        await reveal_repo.create(
            db_session,
            nid,
            RevealPlanCreate(
                target_type="character",
                target_id=CHARACTER_TARGET_ID,
                secret_summary="秘密B",
            ),
        )
        await reveal_repo.create(
            db_session,
            nid,
            RevealPlanCreate(
                target_type="world_entity",
                target_id=ENTITY_TARGET_ID,
                secret_summary="秘密C",
            ),
        )

        char_reveals = await reveal_repo.get_by_target(
            db_session,
            nid,
            "character",
            CHARACTER_TARGET_ID,
        )
        assert len(char_reveals) == 2

        entity_reveals = await reveal_repo.get_by_target(
            db_session,
            nid,
            "world_entity",
            ENTITY_TARGET_ID,
        )
        assert len(entity_reveals) == 1


class TestMergeInvolvedIds:
    @pytest.mark.asyncio
    async def test_merge_involved_ids_dedup(
        self,
        db_session: AsyncSession,
        chapter_repo: ChapterCardRepository,
        novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)
        card = await chapter_repo.create(
            db_session,
            nid,
            ChapterCardCreate(
                chapter_index=1,
                chapter_goal="目标",
                main_conflict="冲突",
                involved_character_ids=["c1", "c2"],
                involved_entity_ids=["e1"],
            ),
        )

        await chapter_repo.merge_involved_ids(
            db_session,
            nid,
            1,
            character_ids=["c2", "c3"],
            entity_ids=["e1", "e2"],
        )

        updated = await chapter_repo.get(db_session, card.id)
        assert set(updated.involved_character_ids) == {"c1", "c2", "c3"}
        assert set(updated.involved_entity_ids) == {"e1", "e2"}

    @pytest.mark.asyncio
    async def test_merge_involved_ids_no_card(
        self,
        db_session: AsyncSession,
        chapter_repo: ChapterCardRepository,
        novel_id: str,
    ) -> None:
        nid = uuid.UUID(hex=novel_id)
        await chapter_repo.merge_involved_ids(
            db_session,
            nid,
            999,
            character_ids=["c1"],
            entity_ids=["e1"],
        )
