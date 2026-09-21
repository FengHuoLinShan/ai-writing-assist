"""E2E（真实 PostgreSQL）：演化 run 单写者并发门禁（PR #158 评审 R5）。

两个会话并发注册不同 run_key 的 live run——部分唯一索引保证恰好一个
合法 owner；落败会话得到 single_writer_violation，而非两个都能写入。
排空/停止后的旧任务不能经重复注册重入。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from modules.evolution.commit import CommitConflictError
from modules.evolution.models import EvolutionRun
from modules.evolution.store import PostgresAttemptStore
from modules.project.models import Project
from tests.e2e.config import DATABASE_URL

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def test_two_sessions_race_exactly_one_live_writer_wins() -> None:
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()

    async with sessions() as setup:
        setup.add(
            Project(
                id=novel_id,
                title="演化单写者并发 e2e",
                genre="奇幻",
                tone="测试",
                language="zh",
                target_length="novel",
                current_stage="writing",
            )
        )
        await setup.commit()

    async def _register(run_key: str) -> tuple[bool, str | None]:
        async with sessions() as session:
            store = PostgresAttemptStore(session, novel_id)
            try:
                await store.register_run(
                    run_key, mode="append", budget_total=5, execution_mode="live"
                )
                await session.commit()
                return True, None
            except CommitConflictError as exc:
                await session.rollback()
                return False, exc.code

    try:
        outcomes = await asyncio.gather(
            _register("run-race-a"),
            _register("run-race-b"),
        )
        winners = [ok for ok, _ in outcomes if ok]
        assert len(winners) == 1, f"恰好一个合法 owner，实际 {outcomes}"
        loser_code = next(code for ok, code in outcomes if not ok)
        assert loser_code == "single_writer_violation"

        async with sessions() as verify:
            live_rows = await verify.execute(
                select(EvolutionRun).where(
                    EvolutionRun.novel_id == novel_id,
                    EvolutionRun.execution_mode == "live",
                    EvolutionRun.status == "active",
                )
            )
            rows = live_rows.scalars().all()
            assert len(rows) == 1

            # 排空释放写入位；排空后的 run 不能经重复注册复活。
            drained = await PostgresAttemptStore(verify, novel_id).switch_project_engine(
                rows[0].run_key, to_engine="evolution"
            )
            assert drained.status == "drained"
            await verify.commit()

        ok, code = await _register("run-race-c")
        assert ok and code is None  # 排空后新 live run 可注册

        store_check = PostgresAttemptStore
        async with sessions() as revive:
            with pytest.raises(CommitConflictError, match="run_not_active"):
                await store_check(revive, novel_id).register_run(
                    rows[0].run_key, mode="append", budget_total=5
                )
            await revive.rollback()
    finally:
        async with sessions() as cleanup:
            await cleanup.execute(
                delete(EvolutionRun).where(EvolutionRun.novel_id == novel_id)
            )
            await cleanup.execute(
                delete(Project).where(Project.id == novel_id)
            )
            await cleanup.commit()
        await engine.dispose()
