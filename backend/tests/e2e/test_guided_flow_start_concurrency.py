"""在真实 PostgreSQL 双连接中验证空集合启动竞争。"""

import asyncio
import uuid
from dataclasses import replace

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.config import get_settings
from core.errors import ConflictError
from modules.assistant.guided_flow import runtime
from modules.assistant.guided_flow.contracts import GuidedFlowStartRequest
from modules.assistant.models import AssistantRun
from modules.project.facade import require_active_project
from modules.project.models import Project
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


@pytest.mark.parametrize("different", [False, True])
@pytest.mark.parametrize("representation", ["canonical", "upper", "hex"])
async def test_concurrent_start_has_one_active_run(
    monkeypatch, different, representation
):
    monkeypatch.setattr(
        runtime,
        "get_settings",
        lambda: replace(
            get_settings(), assistant_enabled=True, assistant_guided_flows_enabled=True
        ),
    )
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    nid = uuid.uuid4()
    owner = "00000000-0000-0000-0000-000000000000"
    arrived = 0
    release = asyncio.Event()

    async def start(index):
        nonlocal arrived
        try:
            async with sessions.begin() as db:
                # 公共入口的共享锁也纳入竞争，防止升级锁导致死锁。
                await require_active_project(db, str(nid))
                arrived += 1
                if arrived == 2:
                    release.set()
                await release.wait()
                supplied_id = (
                    str(nid)
                    if index == 0 or representation == "canonical"
                    else (str(nid).upper() if representation == "upper" else nid.hex)
                )
                return await runtime.start(
                    db,
                    supplied_id,
                    owner,
                    GuidedFlowStartRequest(
                        novel_id=supplied_id,
                        flow_id="new_book_opening",
                        input={"vision": f"潮城{index if different else 0}"},
                    ),
                )
        except ConflictError:
            return None

    try:
        async with sessions.begin() as db:
            db.add(Project(id=nid, title="引导流程并发合成作品"))
        results = await asyncio.wait_for(asyncio.gather(start(0), start(1)), timeout=15)
        if different:
            assert sum(result is None for result in results) == 1
        else:
            assert results[0]["run_id"] == results[1]["run_id"]
        async with sessions() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(AssistantRun)
                    .where(AssistantRun.novel_id == nid)
                )
                == 1
            )
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(AssistantRun).where(AssistantRun.novel_id == nid))
            await db.execute(delete(Project).where(Project.id == nid))
        await engine.dispose()
