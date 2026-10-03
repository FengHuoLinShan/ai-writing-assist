"""关系分组大库读路径合成性能回归（PG e2e，无真实稿件依赖）。

规模：1027 个 CoreEntity + 约 1200 条 EntityRelation（含候选/废弃/噪音边）。
门禁三层（不依赖易抖动的纯 wall-clock 作为唯一依据）：

1. 查询数（N+1 回归）：组列表固定 3 条 SELECT；组内成员页固定 4 条；
   未关联成员页固定 2 条。实现一旦退化为逐组/逐成员查询即失败。
2. EXPLAIN ANALYZE 形状：组列表主查询必须在数据库内聚合
   （HashAggregate/GroupAggregate 节点），成员计数不能搬回 Python。
   执行时间上限（1s）仅作粗粒度护栏，单独超限才有意义。
3. 千对象正确性：去重成员数、未关联数、分页切片与 relation_refs 装配。
"""

from __future__ import annotations

import re
import uuid

import pytest
from sqlalchemy import event, insert, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from modules.project.models import Project
from modules.world.models import CoreEntity, EntityRelation
from modules.world.services.worldbuilding.world_library_service import (
    WorldLibraryService,
)
from modules.world.tests.helpers import _create_project
from tests.e2e.config import DATABASE_URL

pytestmark = pytest.mark.e2e

GROUP_COUNT = 60
MEMBERS_PER_GROUP = 15
UNLINKED_CHARACTERS = 60

_service = WorldLibraryService()

_PARAM_RE = re.compile(r"\$(\d+)")


def _literalize(statement: str, parameters: tuple | list) -> str:
    """把 asyncpg $N 参数按编号渲染为字面量，供 EXPLAIN 重放（仅 UUID/str/int）。"""
    params = list(parameters or ())

    def render(match: re.Match) -> str:
        value = params[int(match.group(1)) - 1]
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        return "'" + str(value).replace("'", "''") + "'"

    return _PARAM_RE.sub(render, statement)


async def _explain_analyze(db, statement: str, parameters) -> list[str]:
    sql = _literalize(statement, parameters)
    rows = (
        await db.execute(text("EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT) " + sql))
    ).scalars().all()
    return list(rows)


def _execution_time_ms(plan_lines: list[str]) -> float:
    for line in plan_lines:
        if "Execution Time" in line:
            return float(line.rsplit(" ", 2)[-2])
    raise AssertionError(f"EXPLAIN 输出缺少 Execution Time：{plan_lines[:3]}")


class _StatementRecorder:
    """记录 session 所属 engine 上的 SELECT/WITH 语句（N+1 检测）。"""

    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple]] = []

    def attach(self, sync_engine) -> None:
        event.listen(
            sync_engine,
            "before_cursor_execute",
            self._record,
        )

    def detach(self, sync_engine) -> None:
        event.remove(sync_engine, "before_cursor_execute", self._record)

    def _record(self, conn, cursor, statement, parameters, context, executemany):
        normalized = statement.lstrip().lower()
        if normalized.startswith(("select", "with")):
            self.statements.append((statement, parameters))

    def count(self) -> int:
        return len(self.statements)

    def longest(self) -> tuple[str, tuple]:
        return max(self.statements, key=lambda item: len(item[0]))


async def _seed_large_library(db) -> str:
    novel_id = uuid.uuid4().hex
    await _create_project(db, novel_id)
    nid = uuid.UUID(hex=novel_id)

    entity_rows: list[dict] = []
    for i in range(GROUP_COUNT):
        entity_rows.append(
            {
                "id": uuid.uuid4(),
                "novel_id": nid,
                "entity_type": "faction",
                "name": f"势力{i:03d}",
                "status": "canonical",
                "summary": f"势力{i:03d}概要",
                "content_json": {"aliases": []},
            }
        )
    # 归档势力：不得作为分组出现。
    for i in range(2):
        entity_rows.append(
            {
                "id": uuid.uuid4(),
                "novel_id": nid,
                "entity_type": "faction",
                "name": f"归档势力{i}",
                "status": "archived",
                "summary": "",
                "content_json": {"aliases": []},
            }
        )
    # working 状态人物：不计入未关联成员。
    for i in range(5):
        entity_rows.append(
            {
                "id": uuid.uuid4(),
                "novel_id": nid,
                "entity_type": "character",
                "name": f"在途人物{i}",
                "status": "working",
                "summary": "",
                "content_json": {"aliases": []},
            }
        )
    for i in range(UNLINKED_CHARACTERS):
        entity_rows.append(
            {
                "id": uuid.uuid4(),
                "novel_id": nid,
                "entity_type": "character",
                "name": f"散人{i:03d}",
                "status": "canonical",
                "summary": "",
                "content_json": {"aliases": []},
            }
        )
    for i in range(GROUP_COUNT * MEMBERS_PER_GROUP):
        entity_rows.append(
            {
                "id": uuid.uuid4(),
                "novel_id": nid,
                "entity_type": "character",
                "name": f"成员{i:04d}",
                "status": "canonical",
                "summary": "",
                "content_json": {"aliases": []},
            }
        )
    for start in range(0, len(entity_rows), 200):
        await db.execute(insert(CoreEntity).values(entity_rows[start : start + 200]))

    groups = [
        row
        for row in entity_rows
        if row["entity_type"] == "faction" and row["status"] == "canonical"
    ]
    members = [row for row in entity_rows if row["name"].startswith("成员")]

    relation_rows: list[dict] = []
    for gi, group in enumerate(groups):
        chunk = members[gi * MEMBERS_PER_GROUP : (gi + 1) * MEMBERS_PER_GROUP]
        for mi, member in enumerate(chunk):
            if mi < 12:
                relation_rows.append(_relation_row(nid, member, group, "member_of"))
            else:
                relation_rows.append(_relation_row(nid, member, group, "leader_of"))
            if mi < 3:
                # 跨关系类型重复：member_count 必须按成员去重。
                relation_rows.append(_relation_row(nid, member, group, "belongs_to"))
    # 噪音边：候选/废弃状态与视角外类型，均不构成成员资格。
    for i in range(50):
        relation_rows.append(
            _relation_row(nid, members[i], groups[0], "member_of", status="candidate")
        )
    for i in range(30):
        relation_rows.append(
            _relation_row(
                nid, members[500 + i], groups[1], "leader_of", status="deprecated"
            )
        )
    for i in range(40):
        relation_rows.append(
            _relation_row(nid, members[i], members[(i + 1) % 900], "ally_of")
        )
    for start in range(0, len(relation_rows), 200):
        await db.execute(
            insert(EntityRelation).values(relation_rows[start : start + 200])
        )
    await db.commit()
    return novel_id


def _relation_row(
    nid: uuid.UUID,
    source: dict,
    target: dict,
    relation_type: str,
    *,
    status: str = "canonical",
) -> dict:
    return {
        "id": uuid.uuid4(),
        "novel_id": nid,
        "source_id": source["id"],
        "target_id": target["id"],
        "relation_type": relation_type,
        "relation_kind": "social",
        "status": status,
        "strength": 0.8,
    }


@pytest.fixture
async def seeded_library():
    engine = create_async_engine(DATABASE_URL, pool_size=5, max_overflow=0)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        novel_id = await _seed_large_library(db)
    yield engine, sessions, novel_id
    async with sessions() as db:
        nid = uuid.UUID(hex=novel_id)
        await db.execute(
            EntityRelation.__table__.delete().where(EntityRelation.novel_id == nid)
        )
        await db.execute(
            CoreEntity.__table__.delete().where(CoreEntity.novel_id == nid)
        )
        await db.execute(Project.__table__.delete().where(Project.id == nid))
        await db.commit()
    await engine.dispose()


async def test_group_list_statement_count_and_correctness(seeded_library):
    engine, sessions, novel_id = seeded_library
    async with sessions() as db:
        recorder = _StatementRecorder()
        recorder.attach(engine.sync_engine)
        try:
            page1 = await _service.list_relation_groups(
                db, novel_id, group_view="affiliation", skip=0, limit=25
            )
        finally:
            recorder.detach(engine.sync_engine)

        assert recorder.count() == 3, [
            s[0][:120] for s in recorder.statements
        ]
        assert page1.total == GROUP_COUNT
        assert page1.unlinked_total == UNLINKED_CHARACTERS
        assert len(page1.items) == 25
        assert all(item.member_count == MEMBERS_PER_GROUP for item in page1.items)
        # 全部同 member_count → name 升序稳定分页。
        assert [item.name for item in page1.items[:3]] == [
            "势力000",
            "势力001",
            "势力002",
        ]

        page3 = await _service.list_relation_groups(
            db, novel_id, group_view="affiliation", skip=50, limit=25
        )
        assert len(page3.items) == 10
        assert page3.items[0].name == "势力050"

        # EXPLAIN ANALYZE：主查询必须在库内聚合，成员计数不得搬回 Python。
        plan = await _explain_analyze(db, *recorder.longest())
        plan_text = "\n".join(plan)
        assert "Aggregate" in plan_text, plan_text
        assert _execution_time_ms(plan) < 1000.0, plan_text


async def test_group_member_page_statement_count_and_refs(seeded_library):
    engine, sessions, novel_id = seeded_library
    async with sessions() as db:
        groups = await _service.list_relation_groups(
            db, novel_id, group_view="affiliation", skip=0, limit=1
        )
        group = groups.items[0]

        recorder = _StatementRecorder()
        recorder.attach(engine.sync_engine)
        try:
            members = await _service.list_library(
                db,
                novel_id,
                group_view="affiliation",
                group_id=group.id,
                skip=0,
                limit=10,
            )
        finally:
            recorder.detach(engine.sync_engine)

        assert recorder.count() == 4, [
            s[0][:120] for s in recorder.statements
        ]
        assert members.total == MEMBERS_PER_GROUP
        assert len(members.items) == 10
        for item in members.items:
            assert item.relation_refs, f"成员 {item.title} 缺 relation_refs"
            for ref in item.relation_refs:
                assert len(ref.execution_fingerprint) == 64

        plan = await _explain_analyze(db, *recorder.longest())
        plan_text = "\n".join(plan)
        assert _execution_time_ms(plan) < 1000.0, plan_text


async def test_unlinked_member_page_statement_count(seeded_library):
    engine, sessions, novel_id = seeded_library
    async with sessions() as db:
        recorder = _StatementRecorder()
        recorder.attach(engine.sync_engine)
        try:
            unlinked = await _service.list_library(
                db,
                novel_id,
                group_view="affiliation",
                group_unlinked=True,
                skip=0,
                limit=10,
            )
        finally:
            recorder.detach(engine.sync_engine)

        assert recorder.count() == 2, [
            s[0][:120] for s in recorder.statements
        ]
        assert unlinked.total == UNLINKED_CHARACTERS
        assert {item.title for item in unlinked.items} <= {
            f"散人{i:03d}" for i in range(UNLINKED_CHARACTERS)
        }
        assert all(not item.relation_refs for item in unlinked.items)
