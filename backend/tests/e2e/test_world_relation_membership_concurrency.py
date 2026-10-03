"""Concurrent membership batches against real PostgreSQL row locking.

Covers the world relation grouping merge-gate scenarios: two concurrent
adds of the same edge collapse to one canonical row, cross-ordered batches
do not deadlock (stable UUID lock order), a mid-batch failure rolls the
whole batch back while an independent transaction survives, and an
edit/remove race is caught by the execution fingerprint.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError, NotFoundError
from modules.project.models import Project
from modules.world.models import CoreEntity, EntityRelation
from modules.world.relation_schemas import WorldRelationMembershipBatchRequest
from modules.world.schemas import EntityRelationReviewEditRequest
from modules.world.services.common import entity_relation_execution_fingerprint
from modules.world.services.core.entity_relation_service import EntityRelationService
from modules.world.tests.helpers import _create_project
from tests.e2e.config import DATABASE_URL

pytestmark = pytest.mark.e2e


def _add_request(novel_id: str, group_id: str, member_ids: list[str]):
    return WorldRelationMembershipBatchRequest.model_validate(
        {
            "novel_id": novel_id,
            "action": "add",
            "group_view": "affiliation",
            "group_id": group_id,
            "member_ids": member_ids,
            "confirmed": True,
        }
    )


def _remove_request(
    novel_id: str,
    group_id: str,
    member_id: str,
    relation_id: str,
    fingerprint: str,
):
    return WorldRelationMembershipBatchRequest.model_validate(
        {
            "novel_id": novel_id,
            "action": "remove",
            "group_view": "affiliation",
            "group_id": group_id,
            "member_ids": [member_id],
            "confirmed": True,
            "relation_refs": [
                {
                    "id": relation_id,
                    "expected_execution_fingerprint": fingerprint,
                }
            ],
        }
    )


async def _seed(db, novel_id: uuid.UUID) -> tuple[str, str, str, str, str]:
    await _create_project(db, str(novel_id))

    async def add_entity(entity_type: str, name: str) -> CoreEntity:
        entity = CoreEntity(
            novel_id=novel_id,
            entity_type=entity_type,
            name=name,
            status="canonical",
        )
        db.add(entity)
        await db.flush()
        return entity

    group = await add_entity("faction", "并发测试势力")
    first = await add_entity("character", "并发成员一")
    second = await add_entity("character", "并发成员二")
    third = await add_entity("character", "并发成员三")
    # 类型不属于 affiliation 成员范畴：用于中途失败场景。
    outsider = await add_entity("item", "不属于成员类型的对象")
    return (
        str(group.id),
        str(first.id),
        str(second.id),
        str(third.id),
        str(outsider.id),
    )


@pytest.mark.asyncio
async def test_concurrent_add_same_edge_yields_single_canonical_row():
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    service = EntityRelationService()
    try:
        async with sessions.begin() as db:
            group_id, first_id, *_ = await _seed(db, novel_id)

        async def worker(member_id: str) -> tuple[int, int]:
            async with sessions.begin() as db:
                result = await service.membership_batch(
                    db,
                    str(novel_id),
                    _add_request(str(novel_id), group_id, [member_id]),
                )
                return result.added_count, result.reused_count

        outcomes = await asyncio.gather(worker(first_id), worker(first_id))
        # 实体行锁串行化两个批次：一个新建、一个复用，canonical 行总数为 1。
        assert sorted(outcomes) == [(0, 1), (1, 0)]
        async with sessions() as db:
            rows = (
                (
                    await db.execute(
                        select(EntityRelation).where(EntityRelation.novel_id == novel_id)
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert rows[0].status == "canonical"
            assert rows[0].relation_type == "member_of"
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()


@pytest.mark.asyncio
async def test_cross_ordered_batches_complete_without_deadlock():
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    service = EntityRelationService()
    try:
        async with sessions.begin() as db:
            group_id, first_id, second_id, third_id, _ = await _seed(db, novel_id)

        async def worker(member_ids: list[str]) -> int:
            async with sessions.begin() as db:
                result = await service.membership_batch(
                    db,
                    str(novel_id),
                    _add_request(str(novel_id), group_id, member_ids),
                )
                return result.added_count

        # 成员顺序相反的两批在实体行锁的稳定 UUID 顺序下交错执行，不死锁。
        added = await asyncio.wait_for(
            asyncio.gather(
                worker([first_id, second_id]),
                worker([second_id, first_id]),
                worker([third_id]),
            ),
            timeout=60,
        )
        # gather 只保证返回顺序，不保证获锁顺序：重叠两批在实体行锁下必然
        # 一批全新增、一批全复用，独立批次必然新增 1；按计数集合断言，
        # 避免把合法的锁赢家反序（如 [0,2,1]）误判为失败。
        assert sorted(added) == [0, 1, 2]
        async with sessions() as db:
            total = await db.scalar(
                select(func.count()).select_from(EntityRelation).where(
                    EntityRelation.novel_id == novel_id
                )
            )
            assert int(total) == 3
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()


@pytest.mark.asyncio
async def test_mid_batch_failure_rolls_back_whole_batch():
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    service = EntityRelationService()
    try:
        async with sessions.begin() as db:
            group_id, first_id, _, _, outsider_id = await _seed(db, novel_id)

        async def failing_batch() -> None:
            # 合法成员 + 类型不符成员：任何失败都撤回整批。
            async with sessions.begin() as db:
                await service.membership_batch(
                    db,
                    str(novel_id),
                    _add_request(str(novel_id), group_id, [first_id, outsider_id]),
                )

        async def surviving_batch() -> int:
            async with sessions.begin() as db:
                result = await service.membership_batch(
                    db,
                    str(novel_id),
                    _add_request(str(novel_id), group_id, [first_id]),
                )
                return result.added_count

        results = await asyncio.gather(
            failing_batch(),
            surviving_batch(),
            return_exceptions=True,
        )
        assert any(isinstance(item, NotFoundError) for item in results)
        assert any(isinstance(item, int) for item in results)
        async with sessions() as db:
            rows = (
                (
                    await db.execute(
                        select(EntityRelation).where(EntityRelation.novel_id == novel_id)
                    )
                )
                .scalars()
                .all()
            )
            # 失败批次零残留；独立事务的写入保留。
            assert len(rows) == 1
            assert str(rows[0].source_id) == first_id
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()


@pytest.mark.asyncio
async def test_edit_endpoint_swap_interleaved_with_remove_avoids_deadlock():
    """review_edit 与 membership 移出的最不利交错：移出先持实体行锁。

    编辑把关系两端对调（source/target 都变化，flush 的外键 KEY SHARE
    落在移出已 FOR UPDATE 的两行上）。修复前编辑先持关系行锁，外键
    检查等待移出的实体锁，移出又等待关系锁，PG 报 40P01 死锁。
    统一 entity-first 锁序后：编辑阻塞在实体锁上，移出正常完成提交，
    编辑锁后重验指纹命中移出改动，按 stale_execution 拒绝。
    """
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    service = EntityRelationService()
    try:
        async with sessions.begin() as db:
            group_id, first_id, _second_id, _third_id, _ = await _seed(db, novel_id)
            added = await service.membership_batch(
                db,
                str(novel_id),
                _add_request(str(novel_id), group_id, [first_id]),
            )
            relation_id = added.affected_relation_ids[0]

        async with sessions() as db:
            relation = await db.get(EntityRelation, uuid.UUID(relation_id))
            fingerprint = entity_relation_execution_fingerprint(relation)
            await db.commit()

        entities_locked = asyncio.Event()

        async def wait_for_edit_blocked() -> None:
            # 轮询 pg_stat_activity 直到编辑会话进入锁等待，确保编辑已
            # 持有关系锁并卡在外键/实体锁上（最不利交错），移出才继续。
            async with engine.connect() as check:
                for _ in range(200):  # 最多 20s
                    waiters = await check.execute(
                        text(
                            "select count(*) from pg_stat_activity "
                            "where datname = current_database() "
                            "and pid <> pg_backend_pid() "
                            "and wait_event_type = 'Lock'"
                        )
                    )
                    if int(waiters.scalar() or 0) > 0:
                        return
                    await asyncio.sleep(0.1)
            raise AssertionError("编辑未在 20s 内到达锁等待点")

        async def remove_flow() -> None:
            async with sessions.begin() as db:
                # 第一阶段：先持两端实体行锁（membership 的锁序第一阶段），
                # 然后才允许编辑启动，制造编辑无法绕过实体锁的最不利交错。
                await db.execute(
                    select(CoreEntity)
                    .where(
                        CoreEntity.novel_id == novel_id,
                        CoreEntity.id.in_(
                            [uuid.UUID(group_id), uuid.UUID(first_id)]
                        ),
                    )
                    .with_for_update()
                )
                entities_locked.set()
                await wait_for_edit_blocked()
                # 第二阶段：继续锁关系行并完成移出（锁序第二阶段）。
                await service.membership_batch(
                    db,
                    str(novel_id),
                    _remove_request(
                        str(novel_id),
                        group_id,
                        first_id,
                        relation_id,
                        fingerprint,
                    ),
                )

        async def edit_flow() -> None:
            async with sessions.begin() as db:
                await service.review_edit(
                    db,
                    str(novel_id),
                    relation_id,
                    EntityRelationReviewEditRequest(
                        relation_type="member_of",
                        source_id=group_id,
                        target_id=first_id,
                        confirm_review=False,
                        expected_execution_fingerprint=fingerprint,
                    ),
                )

        remove_task = asyncio.create_task(remove_flow())
        await asyncio.wait_for(entities_locked.wait(), timeout=30)
        results = await asyncio.wait_for(
            asyncio.gather(edit_flow(), remove_task, return_exceptions=True),
            timeout=60,
        )
        # 无死锁：移出成功提交，编辑在实体锁释放后以过期指纹被拒。
        assert any(isinstance(item, ConflictError) for item in results)
        assert any(item is None for item in results)
        for item in results:
            assert not isinstance(item, BaseException) or isinstance(
                item, ConflictError
            )
        for item in results:
            if isinstance(item, ConflictError):
                assert item.code == "stale_execution"
        async with sessions() as db:
            relation = await db.get(EntityRelation, uuid.UUID(relation_id))
            assert relation.status == "deprecated"
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()


@pytest.mark.asyncio
async def test_edit_then_remove_with_stale_fingerprint_conflicts():
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    service = EntityRelationService()
    try:
        async with sessions.begin() as db:
            group_id, first_id, *_ = await _seed(db, novel_id)
            added = await service.membership_batch(
                db,
                str(novel_id),
                _add_request(str(novel_id), group_id, [first_id]),
            )
            relation_id = added.affected_relation_ids[0]

        async with sessions() as db:
            relation = await db.get(EntityRelation, uuid.UUID(relation_id))
            stale_fingerprint = entity_relation_execution_fingerprint(relation)
            await db.commit()

        # 作者在另一事务先编辑了描述并提交。
        async with sessions.begin() as db:
            await service.review_edit(
                db,
                str(novel_id),
                relation_id,
                EntityRelationReviewEditRequest(
                    relation_type="member_of",
                    description="并发编辑后的描述",
                    confirm_review=False,
                    expected_execution_fingerprint=stale_fingerprint,
                ),
            )

        # 带旧指纹的移出必须被识别为过期并拒绝。
        async with sessions.begin() as db:
            with pytest.raises(ConflictError) as exc_info:
                await service.membership_batch(
                    db,
                    str(novel_id),
                    _remove_request(
                        str(novel_id),
                        group_id,
                        first_id,
                        relation_id,
                        stale_fingerprint,
                    ),
                )
            assert exc_info.value.code == "stale_execution"
            await db.rollback()

        async with sessions() as db:
            relation = await db.get(EntityRelation, uuid.UUID(relation_id))
            assert relation.status == "canonical"
            assert relation.description == "并发编辑后的描述"
    finally:
        async with sessions.begin() as db:
            await db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()
