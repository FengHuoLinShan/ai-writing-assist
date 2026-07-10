"""
E2E：Outline 模块真实环境 AI 生成验证。

用真实 PostgreSQL + 真实 DeepSeek LLM 验证 PlotStructureGenerator。
覆盖：生成完整性、内容正确性、范围覆盖、重复检测、契约遗漏。

复用 LOTM 种子数据（project + world entities + characters with role/desire）。
"""

from __future__ import annotations

import logging
import os
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from tests.e2e.seed_data import create_base_scene

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]

real_llm_required = pytest.mark.skipif(
    os.getenv("RUN_REAL_LLM_TESTS") != "1",
    reason="真实 LLM E2E 验收默认跳过；设置 RUN_REAL_LLM_TESTS=1 才运行",
)

logger = logging.getLogger(__name__)

VALID_THREAD_TYPES = frozenset(
    {"main", "secondary", "hidden", "relationship", "villain", "foreshadowing"}
)

# 提示词定义的输出字段中代码已消费 vs 未消费的
THREAD_CONSUMED_FIELDS = {
    "name",
    "thread_type",
    "summary",
    "visible_goal",
    "hidden_truth",
    "start_chapter",
    "planned_payoff_chapter",
    "current_stage",
    "status",
}
THREAD_UNCONSUMED_FIELDS = {
    "reader_known_state",
    "author_known_state",
    "related_character_names",
    "related_entity_names",
}
ARC_CONSUMED_FIELDS = {
    "title",
    "arc_index",
    "start_chapter",
    "end_chapter",
    "arc_goal",
    "core_conflict",
    "main_opposition",
    "entry_hook",
    "midpoint_turn",
    "climax",
    "result",
    "next_hook",
    "status",
}
ARC_UNCONSUMED_FIELDS = {
    "related_thread_names",
    "related_character_names",
    "related_entity_names",
}
TOP_LEVEL_SECTIONS = {
    "foreshadowing_plans",
    "reveal_plans",
    "offscreen_progress",
    "risks",
    "questions_for_user",
}

MAX_LLM_RETRIES = 3


async def _generate_with_retry(
    db: AsyncSession,
    novel_id: str,
    start_chapter: int,
    end_chapter: int,
) -> dict[str, Any]:
    """调用生成器，如果 LLM 返回空则重试（LLM 输出不稳定）。"""
    from modules.outline.services import PlotStructureGenerator

    _generator = PlotStructureGenerator()
    result: dict[str, Any] = {}
    for attempt in range(1, MAX_LLM_RETRIES + 1):
        result = await _generator.generate(
            db,
            novel_id,
            start_chapter,
            end_chapter,
            persist=True,
        )
        total = result.get("total_threads", 0)
        if total > 0:
            return result
        logger.warning(
            "LLM 返回空结果（attempt %d/%d），重试...",
            attempt,
            MAX_LLM_RETRIES,
        )
    return result


# ============================================================
# Fixtures
# ============================================================


@pytest_asyncio.fixture
async def project_with_world(db_session: AsyncSession) -> dict[str, Any]:
    """LOTM 项目 + 世界实体 + 关系 + 人物角色表 + 第 1-3 章真实正文草稿。"""
    from modules.world.models import Character
    from tests.e2e.seed_data import create_writing_drafts

    scene = await create_base_scene(db_session)
    pid = scene["project_uuid"]
    eids = scene["entity_ids"]

    character_data = [
        {
            "name": "克莱恩·莫雷蒂",
            "entity_name": "克莱恩·莫雷蒂",
            "role": "protagonist",
            "desire": "寻找序列晋升之路，保护家人",
        },
        {
            "name": "罗塞尔·古斯塔夫",
            "entity_name": "罗塞尔·古斯塔夫",
            "role": "mentor",
            "desire": "留下记录指引后来者",
        },
        {
            "name": "邓恩·史密斯",
            "entity_name": "邓恩·史密斯",
            "role": "supporting",
            "desire": "守护廷根市完成值夜者职责",
        },
    ]

    for cd in character_data:
        eid = eids.get(cd["entity_name"])
        if eid is None:
            continue
        char = Character(
            entity_id=eid,
            novel_id=pid,
            name=cd["name"],
            role=cd["role"],
            desire=cd["desire"],
            status="canonical",
        )
        db_session.add(char)

    await create_writing_drafts(db_session, pid)
    await db_session.flush()
    return {
        "project_id": scene["project_id"],
        "project_uuid": pid,
        "entity_ids": eids,
    }


# ============================================================
# Test: 生成完整性
# ============================================================


@pytest.mark.real_llm
@real_llm_required
class TestRealOutlineGeneration:
    """真实 LLM 验证——生成完整性 + 内容正确性。"""

    async def test_outline_generate_real_llm_creates_threads_and_arcs(
        self,
        db_session: AsyncSession,
        project_with_world: dict[str, Any],
    ) -> None:
        """调用真实 LLM 生成，验证剧情线 + 篇章纲产出完整（含 LLM 空结果重试）。"""
        # Arrange
        novel_id = project_with_world["project_id"]

        # Act
        result = await _generate_with_retry(
            db_session,
            novel_id,
            start_chapter=1,
            end_chapter=3,
        )

        # Assert
        total_threads = result.get("total_threads", 0)
        total_arcs = result.get("total_arcs", 0)
        threads = result.get("threads", [])
        arcs = result.get("arcs", [])

        logger.info("=== Outline Generation Result (chapters 1-3) ===")
        logger.info("Threads: %d, Arcs: %d", total_threads, total_arcs)
        for t in threads:
            logger.info("  Thread: %s (type=%s)", t.get("name"), t.get("thread_type"))
        for a in arcs:
            logger.info("  Arc: %s (idx=%s)", a.get("title"), a.get("arc_index"))

        assert total_threads > 0, (
            f"LLM 重试 {MAX_LLM_RETRIES} 次后仍返回空结果——提示词或 LLM 兼容性可能有问题"
        )
        assert total_arcs > 0, "应生成至少 1 个篇章纲"

        for t in threads:
            name = t.get("name") or ""
            assert name, "Thread name 不能为空"
            tt = t.get("thread_type") or ""
            assert tt, "Thread type 不能为空"
            assert tt in VALID_THREAD_TYPES, f"非法 thread_type '{tt}' for '{name}'"

        names = [t["name"] for t in threads if t.get("name")]
        assert len(names) == len(set(names)), f"重复 name: {names}"
        titles = [a["title"] for a in arcs if a.get("title")]
        assert len(titles) == len(set(titles)), f"重复 title: {titles}"

    async def test_outline_generate_real_llm_persists_to_db(
        self,
        db_session: AsyncSession,
        project_with_world: dict[str, Any],
    ) -> None:
        """生成的数据持久化到 DB 且可回读。"""
        # Arrange
        from modules.outline.services import OutlineArcService, PlotThreadService

        _thread_svc = PlotThreadService()
        _arc_svc = OutlineArcService()
        novel_id = project_with_world["project_id"]

        # Act
        await _generate_with_retry(db_session, novel_id, start_chapter=1, end_chapter=3)
        thread_list = await _thread_svc.list_with_response(db_session, novel_id)
        arc_list = await _arc_svc.list_with_response(db_session, novel_id)

        # Assert
        logger.info("=== Persisted ===")
        logger.info("Threads: %d (total %d)", len(thread_list.items), thread_list.total)
        logger.info("Arcs: %d (total %d)", len(arc_list.items), arc_list.total)

        assert thread_list.total > 0, "DB 应有 plot_threads"
        assert arc_list.total > 0, "DB 应有 outline_arcs"

        for t in thread_list.items:
            assert t.name, f"Thread name 为空: {t.id}"
            assert t.thread_type in VALID_THREAD_TYPES, f"非法 type: {t.thread_type}"
        for a in arc_list.items:
            assert a.title, f"Arc title 为空: {a.id}"

    async def test_outline_generate_real_llm_multiple_calls_no_crash(
        self,
        db_session: AsyncSession,
        project_with_world: dict[str, Any],
    ) -> None:
        """多次调用不崩溃，目前无 dedup。"""
        # Arrange
        from modules.outline.services import PlotThreadService

        _thread_svc = PlotThreadService()
        novel_id = project_with_world["project_id"]

        # Act
        r1 = await _generate_with_retry(
            db_session, novel_id, start_chapter=1, end_chapter=3
        )
        r2 = await _generate_with_retry(
            db_session, novel_id, start_chapter=1, end_chapter=3
        )

        # Assert
        assert r1.get("total_threads", 0) > 0
        assert r1.get("total_arcs", 0) > 0
        assert r1.get("existing_threads_count", 0) == 0
        assert r1.get("existing_arcs_count", 0) == 0

        assert r2.get("total_threads", 0) > 0
        assert r2.get("existing_threads_count", -1) == r1["total_threads"]
        assert r2.get("existing_arcs_count", -1) == r1["total_arcs"]
        assert any("已有" in w for w in r2.get("warnings", [])), (
            "第二次生成应携带重复范围警告"
        )

        after = await _thread_svc.list_with_response(db_session, novel_id)
        expected = r1["total_threads"] + r2["total_threads"]
        assert after.total >= expected, (
            f"期望 >= {expected}，实际 {after.total}——可能有重复"
        )


# ============================================================
# Test: 输出契约覆盖度
# ============================================================


class TestOutputContractCoverage:
    """提示词 vs 代码——字段级覆盖度检查（仅报告，不断言失败）。"""

    def test_outline_thread_contract_logs_consumed_and_unconsumed_fields(self) -> None:
        """PlotThread 字段覆盖。"""
        # Arrange & Act
        logger.info("=== Thread Contract ===")
        logger.info("Consumed: %s", sorted(THREAD_CONSUMED_FIELDS))
        logger.info("Unconsumed: %s", sorted(THREAD_UNCONSUMED_FIELDS))

        # Assert
        if "related_character_names" in THREAD_UNCONSUMED_FIELDS:
            logger.warning(
                "KNOWN BUG: related_character_names 未映射到 "
                "PlotThreadCreate.related_character_ids — AI 角色关联丢失"
            )

    def test_outline_arc_contract_logs_consumed_and_unconsumed_fields(self) -> None:
        """OutlineArc 字段覆盖。"""
        # Arrange & Act
        logger.info("=== Arc Contract ===")
        logger.info("Consumed: %s", sorted(ARC_CONSUMED_FIELDS))
        logger.info("Unconsumed: %s", sorted(ARC_UNCONSUMED_FIELDS))

        # Assert (logging only)

    def test_outline_top_level_sections_logs_known_gaps(self) -> None:
        """_GenerationOutput 未消费的顶层章节。"""
        # Arrange & Act
        logger.info("=== Top-Level Sections ===")
        logger.info("_GenerationOutput only consumes: plot_threads, outline_arcs")
        logger.info("Unconsumed (silently dropped): %s", sorted(TOP_LEVEL_SECTIONS))

        # Assert
        logger.warning(
            "KNOWN GAP: 提示词定义了 %s 等输出章节，"
            "但 _GenerationOutput 只提取 plot_threads + outline_arcs——"
            "这些数据被 LLM 生成后静默丢弃",
            ", ".join(sorted(TOP_LEVEL_SECTIONS)),
        )

    async def test_outline_related_ids_in_db_are_empty_known_bug(
        self,
        db_session: AsyncSession,
        project_with_world: dict[str, Any],
    ) -> None:
        """验证 DB 中 related_character_ids / related_entity_ids 为空。"""
        # Arrange
        from modules.outline.services import PlotThreadService

        _thread_svc = PlotThreadService()
        novel_id = project_with_world["project_id"]

        # Act
        await _generate_with_retry(db_session, novel_id, start_chapter=1, end_chapter=3)
        thread_list = await _thread_svc.list_with_response(db_session, novel_id)
        filled = [
            (t.name, t.related_character_ids, t.related_entity_ids)
            for t in thread_list.items
            if t.related_character_ids or t.related_entity_ids
        ]

        # Assert
        if filled:
            logger.info("有线程意外填充了 related_*_ids: %s", filled)
        else:
            logger.warning(
                "KNOWN BUG: 所有线程 related_character_ids/related_entity_ids "
                "均为空 — LLM 输出的名称关联未映射到 UUID"
            )
