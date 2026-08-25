from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.outline_state.schemas import OutlineArcCreate, PlotThreadCreate


@pytest_asyncio.fixture
async def sample_novel_id(db_session: AsyncSession) -> str:
    from modules.project.models import Project

    novel_id = uuid.uuid4()
    db_session.add(Project(id=novel_id, title="Outline sample project"))
    await db_session.flush()
    return str(novel_id)


@pytest_asyncio.fixture
async def other_novel_id(db_session: AsyncSession) -> str:
    from modules.project.models import Project

    novel_id = uuid.uuid4()
    db_session.add(Project(id=novel_id, title="Outline other project"))
    await db_session.flush()
    return str(novel_id)


@pytest.fixture
def thread_data() -> PlotThreadCreate:
    return PlotThreadCreate(
        name="主角成长之路",
        thread_type="main",
        summary="主角从平凡到强大的主线",
        visible_goal="寻找传说中的古剑",
        hidden_truth="古剑中封印着上古魔神",
        start_chapter=1,
        planned_payoff_chapter=30,
        current_stage="初期探索",
        related_character_ids=[],
        related_entity_ids=[],
        reader_known_state="主角出发寻找古剑",
        author_known_state="古剑实为魔神封印",
        status="draft",
    )


@pytest.fixture
def arc_data() -> OutlineArcCreate:
    return OutlineArcCreate(
        title="第一卷：启程",
        arc_index=1,
        start_chapter=1,
        end_chapter=10,
        arc_goal="建立世界观，主角踏上旅途",
        core_conflict="主角与家族的宿命冲突",
        main_opposition="保守派长老",
        entry_hook="山村少年捡到神秘古玉",
        midpoint_turn="古玉引来追杀者",
        climax="主角被迫离开家乡",
        result="主角踏上寻找真相之路",
        next_hook="远方的古城中隐藏着父亲的秘密",
        status="draft",
    )


@pytest_asyncio.fixture
async def sample_thread(
    db_session: AsyncSession,
    sample_novel_id: str,
    thread_data: PlotThreadCreate,
) -> tuple[str, PlotThreadCreate]:
    from modules.story.outline_state.repositories import PlotThreadRepository

    nid = uuid.UUID(hex=sample_novel_id)
    repo = PlotThreadRepository()
    thread = await repo.create(db_session, nid, thread_data)
    await db_session.flush()
    return str(thread.id), thread_data


@pytest_asyncio.fixture
async def sample_arc(
    db_session: AsyncSession,
    sample_novel_id: str,
    arc_data: OutlineArcCreate,
) -> tuple[str, OutlineArcCreate]:
    from modules.story.outline_state.repositories import OutlineArcRepository

    nid = uuid.UUID(hex=sample_novel_id)
    repo = OutlineArcRepository()
    arc = await repo.create(db_session, nid, arc_data)
    await db_session.flush()
    return str(arc.id), arc_data
