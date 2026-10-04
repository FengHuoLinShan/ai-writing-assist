"""世界修订历史 PG 端到端测试（路线图阶段 0 · G1）。

覆盖（TASK.md §8 PG 端到端）：

- 加列后 ``world_bible_page_revisions`` 仍拒绝 UPDATE（不可变触发器）。
- 地图 ``protect_map_revision_content`` 触发器覆盖两列新元数据。
- ``entity_revisions`` 新列可事后 UPDATE（record_change_summary 依赖）。
- 时间线的 UNION ALL 与游标翻页在 PG 上正确（不重不漏）。
- 同一基线两次恢复：第一次成功，第二次 409（基线并发保护）。
- 同一条备注的重复/覆盖写入收敛到唯一行。
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from modules.world.map_atlas_models import MapAtlasNode, MapAtlasRevision
from modules.world.models import (
    CoreEntity,
    EntityRevision,
    WorldBiblePage,
    WorldBiblePageRevision,
)
from tests.e2e.seed_data import create_base_scene

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


async def _insert_entity_with_revision(
    db: AsyncSession, novel_id: str, name: str
) -> tuple[str, str]:
    eid = uuid.uuid4()
    db.add(
        CoreEntity(
            id=eid,
            novel_id=uuid.UUID(novel_id),
            entity_type="character",
            name=name,
            status="canonical",
        )
    )
    rid = uuid.uuid4()
    db.add(
        EntityRevision(
            id=rid,
            novel_id=uuid.UUID(novel_id),
            entity_id=eid,
            snapshot={"entity_type": "character", "name": name},
            revision_reason="manual_update",
        )
    )
    await db.flush()
    return str(eid), str(rid)


async def _insert_page_revision(db: AsyncSession, novel_id: str, version: int) -> str:
    pid = uuid.uuid4()
    db.add(
        WorldBiblePage(
            id=pid,
            novel_id=uuid.UUID(novel_id),
            page_type="lore",
            page_key=f"pg-e2e-{version}-{uuid.uuid4().hex[:6]}",
            title=f"页面 v{version}",
        )
    )
    prid = uuid.uuid4()
    db.add(
        WorldBiblePageRevision(
            id=prid,
            novel_id=uuid.UUID(novel_id),
            page_id=pid,
            version_number=version,
            snapshot_json={"title": f"页面 v{version}"},
            revision_digest=f"digest-{version}",
            revision_reason="manual_publish",
        )
    )
    await db.flush()
    return str(prid)


async def _insert_map_revision(
    db: AsyncSession, novel_id: str, *, status: str, with_confirmation: bool = False
) -> str:
    node = MapAtlasNode(
        id=uuid.uuid4(),
        novel_id=uuid.UUID(novel_id),
        semantic_key=f"pg-e2e-{uuid.uuid4().hex[:8]}",
        title="世界",
        level="world",
    )
    db.add(node)
    await db.flush()
    mrid = uuid.uuid4()
    db.add(
        MapAtlasRevision(
            id=mrid,
            novel_id=uuid.UUID(novel_id),
            node_id=node.id,
            status=status,
            document={},
            geometry_hash="hash",
            problems=[],
            confirmation_id=uuid.uuid4() if with_confirmation else None,
        )
    )
    await db.flush()
    return str(mrid)


@pytest_asyncio.fixture
async def seeded_novel(db_session: AsyncSession) -> str:
    meta = await create_base_scene(db_session)
    await db_session.flush()
    return meta["project_id"]


async def test_entity_revision_metadata_columns_updatable(
    db_session: AsyncSession, seeded_novel: str
) -> None:
    """entity_revisions 无触发器：新列可事后 UPDATE（record_change_summary 依赖）。"""
    _, rid = await _insert_entity_with_revision(db_session, seeded_novel, "甲")
    await db_session.execute(
        text(
            "UPDATE entity_revisions SET change_summary = :summary, "
            "writing_chapter_index = :chapter WHERE id = :rid"
        ),
        {"summary": '{"fields": ["name"]}', "chapter": 3, "rid": rid},
    )
    row = (
        await db_session.execute(
            text(
                "SELECT change_summary -> 'fields' ->> 0 AS field, "
                "writing_chapter_index AS chapter FROM entity_revisions WHERE id = :rid"
            ),
            {"rid": rid},
        )
    ).first()
    assert row.field == "name"
    assert row.chapter == 3


async def test_page_revision_still_immutable_after_new_columns(
    db_session: AsyncSession, seeded_novel: str
) -> None:
    """加列后页面历史表仍拒绝 UPDATE（BEFORE UPDATE 触发器，55000）。"""
    prid = await _insert_page_revision(db_session, seeded_novel, version=1)
    with pytest.raises(DBAPIError):
        await db_session.execute(
            text(
                "UPDATE world_bible_page_revisions SET writing_chapter_index = 2 "
                "WHERE id = :rid"
            ),
            {"rid": prid},
        )
    await db_session.rollback()


async def test_map_trigger_protects_new_columns(
    db_session: AsyncSession, seeded_novel: str
) -> None:
    """地图内容保护触发器覆盖 change_summary 与 writing_chapter_index。"""
    mrid = await _insert_map_revision(db_session, seeded_novel, status="saved")
    for assignment in (
        'change_summary = \'{"fields": ["x"]}\'::json',
        "writing_chapter_index = 5",
    ):
        # savepoint 隔离每次失败尝试：异常只回滚 savepoint，
        # 不把测试前面插入的数据一起回滚。
        with pytest.raises(DBAPIError):
            async with db_session.begin_nested():
                await db_session.execute(
                    text(f"UPDATE map_atlas_revisions SET {assignment} WHERE id = :rid"),
                    {"rid": mrid},
                )


async def test_change_history_union_and_cursor_pagination(
    async_client: AsyncClient,
    db_session: AsyncSession,
    seeded_novel: str,
) -> None:
    """三类混排 + 游标翻页在 PG 上正确：不重不漏、地图确认行被排除。"""
    # 实体编辑走 API（真实写作进度查询链路）；页面与地图直接插修订行。
    created = await async_client.post(
        f"/api/world/entities?novel_id={seeded_novel}",
        json={"entity_type": "faction", "name": "青云门", "summary": "第一版"},
    )
    assert created.status_code == 201, created.text
    entity = created.json()

    updated = await async_client.put(
        f"/api/world/entities/{entity['id']}?novel_id={seeded_novel}",
        json={"summary": "第二版", "expected_updated_at": entity["updated_at"]},
    )
    assert updated.status_code == 200, updated.text

    await _insert_page_revision(db_session, seeded_novel, version=1)
    await _insert_map_revision(db_session, seeded_novel, status="saved")
    await _insert_map_revision(
        db_session, seeded_novel, status="saved", with_confirmation=True
    )

    first = await async_client.get(
        f"/api/world/change-history?novel_id={seeded_novel}&limit=2"
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert len(body["items"]) == 2
    assert body["next_cursor"], "还有更多记录"

    times = [item["created_at"] for item in body["items"]]
    assert times == sorted(times, reverse=True), "按时间倒序"

    collected = list(body["items"])
    cursor = body["next_cursor"]
    while cursor:
        page = await async_client.get(
            f"/api/world/change-history?novel_id={seeded_novel}&cursor={cursor}&limit=2"
        )
        assert page.status_code == 200, page.text
        collected.extend(page.json()["items"])
        cursor = page.json()["next_cursor"]

    revision_ids = [item["revision_id"] for item in collected]
    assert len(revision_ids) == len(set(revision_ids)), "翻页不重不漏"

    # 只插入了两行地图修订：一行无确认标记的 saved（应收录），一行带确认标记的
    # saved（整份采用 AI 候选的确认行，不应收录）。
    map_entries = [item for item in collected if item["kind"] == "map"]
    assert len(map_entries) == 1, "带确认标记的地图保存行不应进时间线"

    entity_entries = [item for item in collected if item["kind"] == "entity"]
    assert any(item["changed_fields"] for item in entity_entries), (
        "实体编辑应带改动字段（本环境写作进度可能为 0，但 diff 应存在）"
    )


async def test_rollback_same_baseline_second_attempt_409(
    async_client: AsyncClient,
    db_session: AsyncSession,
    seeded_novel: str,
) -> None:
    """同一基线的第二次恢复被 409 拒绝，且第一次恢复结果保留。"""
    created = await async_client.post(
        f"/api/world/entities?novel_id={seeded_novel}",
        json={"entity_type": "character", "name": "白砚", "summary": "初版摘要"},
    )
    assert created.status_code == 201, created.text
    entity = created.json()

    updated = await async_client.put(
        f"/api/world/entities/{entity['id']}?novel_id={seeded_novel}",
        json={"summary": "第二版", "expected_updated_at": entity["updated_at"]},
    )
    assert updated.status_code == 200, updated.text
    baseline = updated.json()["updated_at"]

    revisions = await async_client.get(
        f"/api/world/entities/{entity['id']}/revisions?novel_id={seeded_novel}"
    )
    assert revisions.status_code == 200, revisions.text
    target = revisions.json()["items"][0]["revision_id"]
    url = (
        f"/api/world/entities/{entity['id']}/rollback-by-revision?novel_id={seeded_novel}"
    )

    first = await async_client.post(
        url,
        json={"revision_id": target, "expected_updated_at": baseline},
    )
    assert first.status_code == 200, first.text
    assert first.json()["summary"] == "初版摘要"

    second = await async_client.post(
        url,
        json={"revision_id": target, "expected_updated_at": baseline},
    )
    assert second.status_code == 409, second.text

    current = await async_client.get(
        f"/api/world/entities/{entity['id']}?novel_id={seeded_novel}"
    )
    assert current.json()["summary"] == "初版摘要", "第一次恢复的结果保留"


async def test_note_writes_settle_and_are_idempotent(
    async_client: AsyncClient,
    db_session: AsyncSession,
    seeded_novel: str,
) -> None:
    """同一修订的备注重复/覆盖写入收敛到唯一行；同内容幂等。"""
    _, rid = await _insert_entity_with_revision(db_session, seeded_novel, "乙")
    url = f"/api/world/revision-notes?novel_id={seeded_novel}"
    payload = {"target_kind": "entity", "revision_id": rid, "note": "  第一次备注  "}

    first = await async_client.put(url, json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["note"] == "第一次备注"

    again = await async_client.put(url, json=payload)
    assert again.status_code == 200
    assert again.json()["note"] == "第一次备注"

    overwrite = await async_client.put(
        url,
        json={"target_kind": "entity", "revision_id": rid, "note": "改成第二条"},
    )
    assert overwrite.status_code == 200
    assert overwrite.json()["note"] == "改成第二条"

    rows = (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM world_revision_notes "
                "WHERE novel_id = :nid AND target_kind = 'entity' AND revision_id = :rid"
            ),
            {"nid": seeded_novel, "rid": rid},
        )
    ).scalar_one()
    assert rows == 1, "覆盖写入收敛到唯一行"

    deleted = await async_client.put(
        url,
        json={"target_kind": "entity", "revision_id": rid, "note": "   "},
    )
    assert deleted.status_code == 200
    assert deleted.json()["note"] is None


async def test_concurrent_first_note_writes_settle() -> None:
    """两个连接并发首次补写同一条备注：都不报错，收敛到唯一行。

    写者 A 先落备注但保持事务打开；写者 B 的插入阻塞在唯一索引上，
    A 提交后 B 撞约束，经 savepoint 转为更新先落库的那一行。
    """
    import asyncio

    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from modules.project.models import Project
    from modules.world.models import WorldRevisionNote
    from modules.world.services.revision_notes import set_revision_note
    from tests.e2e.config import DATABASE_URL

    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    try:
        eid = uuid.uuid4()
        rid = uuid.uuid4()
        async with sessions.begin() as db:
            db.add(Project(id=novel_id, title="revision note concurrency"))
            db.add(
                CoreEntity(
                    id=eid,
                    novel_id=novel_id,
                    entity_type="character",
                    name="并发备注对象",
                    status="canonical",
                )
            )
            db.add(
                EntityRevision(
                    id=rid,
                    novel_id=novel_id,
                    entity_id=eid,
                    snapshot={"entity_type": "character", "name": "并发备注对象"},
                    revision_reason="manual_update",
                )
            )

        a_flushed = asyncio.Event()
        release_a = asyncio.Event()

        async def writer_a() -> str:
            async with sessions() as db:
                async with db.begin():
                    result = await set_revision_note(
                        db, str(novel_id), "entity", str(rid), "A 的备注"
                    )
                    a_flushed.set()
                    await release_a.wait()
                    return str(result.note)

        async def writer_b() -> str:
            await a_flushed.wait()
            async with sessions() as db:
                async with db.begin():
                    result = await set_revision_note(
                        db, str(novel_id), "entity", str(rid), "B 的备注"
                    )
                    return str(result.note)

        task_a = asyncio.create_task(writer_a())
        task_b = asyncio.create_task(writer_b())
        await asyncio.sleep(0.2)
        assert not task_b.done(), "B 应阻塞在 A 的唯一索引项上，而不是先行完成"
        release_a.set()
        notes = await asyncio.gather(task_a, task_b)
        assert notes == ["A 的备注", "B 的备注"]

        async with sessions() as db:
            note = (
                await db.execute(
                    text(
                        "SELECT note FROM world_revision_notes "
                        "WHERE novel_id = :nid AND revision_id = :rid"
                    ),
                    {"nid": novel_id, "rid": rid},
                )
            ).scalar_one()
        assert note == "B 的备注", "后到方的更新胜出，且收敛到唯一行"
    finally:
        async with sessions.begin() as db:
            await db.execute(
                delete(WorldRevisionNote).where(WorldRevisionNote.novel_id == novel_id)
            )
            await db.execute(
                delete(EntityRevision).where(EntityRevision.novel_id == novel_id)
            )
            await db.execute(delete(CoreEntity).where(CoreEntity.novel_id == novel_id))
            await db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()


async def test_concurrent_rollback_same_baseline_exactly_one_wins() -> None:
    """同一基线并发恢复：行锁串行化，恰好一个成功、另一个 409，结果保留。"""
    import asyncio

    from sqlalchemy import delete
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from core.errors import ConflictError
    from modules.project.models import Project
    from modules.world.services.core.entity_service import WorldEntityService
    from tests.e2e.config import DATABASE_URL

    engine = create_async_engine(DATABASE_URL, pool_size=3, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    novel_id = uuid.uuid4()
    try:
        eid = uuid.uuid4()
        rid = uuid.uuid4()
        async with sessions.begin() as db:
            db.add(Project(id=novel_id, title="rollback concurrency"))
            db.add(
                CoreEntity(
                    id=eid,
                    novel_id=novel_id,
                    entity_type="character",
                    name="恢复后的名字",
                    status="canonical",
                )
            )
            db.add(
                EntityRevision(
                    id=rid,
                    novel_id=novel_id,
                    entity_id=eid,
                    snapshot={"entity_type": "character", "name": "恢复前的名字"},
                    revision_reason="manual_update",
                )
            )

        async with sessions() as db:
            baseline = (await db.get(CoreEntity, eid)).updated_at

        service = WorldEntityService()
        winner_flushed = asyncio.Event()
        release_winner = asyncio.Event()

        async def winner():
            async with sessions() as db:
                async with db.begin():
                    result = await service.rollback_to_revision(
                        db,
                        str(eid),
                        str(rid),
                        novel_id=str(novel_id),
                        expected_updated_at=baseline,
                    )
                    winner_flushed.set()
                    await release_winner.wait()
                    return result

        async def loser() -> str:
            await winner_flushed.wait()
            try:
                async with sessions() as db:
                    async with db.begin():
                        await service.rollback_to_revision(
                            db,
                            str(eid),
                            str(rid),
                            novel_id=str(novel_id),
                            expected_updated_at=baseline,
                        )
                return "ok"
            except ConflictError:
                return "conflict"

        winner_task = asyncio.create_task(winner())
        loser_task = asyncio.create_task(loser())
        await asyncio.sleep(0.2)
        assert not loser_task.done(), "后到方应阻塞在行锁上，而不是与胜者并发通过"
        release_winner.set()
        winner_result, loser_result = await asyncio.gather(winner_task, loser_task)
        assert winner_result.name == "恢复前的名字"
        assert loser_result == "conflict"

        async with sessions() as db:
            stored = await db.get(CoreEntity, eid)
            assert stored.name == "恢复前的名字", "胜者的恢复结果保留"
    finally:
        async with sessions.begin() as db:
            await db.execute(
                delete(EntityRevision).where(EntityRevision.novel_id == novel_id)
            )
            await db.execute(delete(CoreEntity).where(CoreEntity.novel_id == novel_id))
            await db.execute(delete(Project).where(Project.id == novel_id))
        await engine.dispose()
