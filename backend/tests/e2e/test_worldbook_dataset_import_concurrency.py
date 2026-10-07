"""资料集世界书导入 apply 的真实 PostgreSQL 并发/幂等/CAS 行为。

对应 m1-contract.md 第 6 条与 7.6 场景（真并发对照只能在本层实现）：
- 跨 suggestion 并发 apply 在项目+资料集 advisory lock 上串行等待；
- 后到者在锁内重放 ``_analyze`` 复验，预览后目标已变化时返回冲突，
  不产生重复工作稿；
- 同一 suggestion 重复 apply 由 claim CAS 保证只产生一次结果。

互斥证明不使用 Mock：由第三个连接手动持有同一冻结键
``worldbook_import:{novel_id}:{dataset_key}``（``pg_advisory_xact_lock``，
与 publish 链 ``world_bible_pages:{novel_id}`` 键空间独立）。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.errors import ConflictError
from modules.project.models import Project
from modules.world.models import CreationSuggestion, WorldBiblePageDraft
from modules.world.services.worldbuilding.suggestion_queue_service import (
    SuggestionAlreadyProcessedError,
)
from modules.world.services.worldbuilding.worldbook_import_service import (
    WorldbookImportService,
)
from modules.world.worldbook_import_schemas import (
    WorldbookImportApplyRequest,
    WorldbookImportManifest,
)
from tests.e2e.config import DATABASE_URL

pytestmark = pytest.mark.e2e

_LOCK_WAIT_SECONDS = 1.5
_FINISH_TIMEOUT_SECONDS = 30.0


def _ring_files() -> list[dict[str, str]]:
    """合成「理法之环」资料集两页：相对 POSIX 路径 + 受限 frontmatter。"""
    return [
        {
            "path": "理法之环/concepts/真名回响/理法之环.md",
            "content": (
                "---\ntitle: 理法之环\npage_type: concept\n---\n"
                "以理法编织万物的环，维系真名回响的秩序。"
            ),
        },
        {
            "path": "理法之环/concepts/真名回响/星锻环.md",
            "content": (
                "---\ntitle: 星锻环\npage_type: concept\n---\n"
                "环绕双月的星锻之环，记录潮汐节律。"
            ),
        },
    ]


def _ring_manifest() -> WorldbookImportManifest:
    return WorldbookImportManifest(
        schema_version="world_worldbook_import.v2",
        source_format="obsidian",
        dataset_name="理法之环",
        commit_mode="full_snapshot",
        files=_ring_files(),
    )


async def _preview(
    engine, novel_id: uuid.UUID, manifest: WorldbookImportManifest
) -> tuple[str, str]:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as db:
        preview = await WorldbookImportService().preview(db, str(novel_id), manifest)
        return preview.suggestion_id, preview.preview_hash


async def _apply(
    engine,
    novel_id: uuid.UUID,
    suggestion_id: str,
    expected_preview_hash: str,
) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as db:
        await WorldbookImportService().apply(
            db,
            str(novel_id),
            suggestion_id,
            WorldbookImportApplyRequest(expected_preview_hash=expected_preview_hash),
        )


async def _apply_outcome(
    engine,
    novel_id: uuid.UUID,
    suggestion_id: str,
    expected_preview_hash: str,
) -> str:
    try:
        await _apply(engine, novel_id, suggestion_id, expected_preview_hash)
    except ConflictError:
        return "conflict"
    return "accepted"


async def _draft_rows(engine, novel_id: uuid.UUID) -> list[tuple[str, str]]:
    """在事务内物化 (title, page_type)，避免 detached ORM 实例。"""
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions() as db:
        result = await db.execute(
            select(WorldBiblePageDraft).where(WorldBiblePageDraft.novel_id == novel_id)
        )
        return [(row.title, row.page_type) for row in result.scalars().all()]


async def _suggestion_statuses(
    engine, novel_id: uuid.UUID, suggestion_ids: list[str]
) -> dict[str, str]:
    async with engine.connect() as conn:
        result = await conn.execute(
            select(CreationSuggestion.id, CreationSuggestion.status).where(
                CreationSuggestion.novel_id == novel_id,
                CreationSuggestion.id.in_([uuid.UUID(value) for value in suggestion_ids]),
            )
        )
        return {str(row.id): row.status for row in result.all()}


async def _cleanup(engine, novel_id: uuid.UUID) -> None:
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with sessions.begin() as db:
        await db.execute(delete(Project).where(Project.id == novel_id))


async def test_dataset_applies_serialize_on_lock_and_stale_one_conflicts() -> None:
    """两个 suggestion 并发 apply：先在 dataset advisory lock 上排队，后到者锁内
    重放发现目标已被前者写入，返回冲突；最终每页只有一个工作稿。"""
    engine = create_async_engine(DATABASE_URL, pool_size=4, max_overflow=0)
    novel_id = uuid.uuid4()
    manifest = _ring_manifest()
    # 冻结键推导直接取自服务实现，避免测试内复写哈希口径（契约第 6 条）。
    identity = WorldbookImportService()._dataset_identity(manifest)
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions.begin() as db:
            db.add(Project(id=novel_id, title="Ring dataset import lock e2e"))
        sid_a, hash_a = await _preview(engine, novel_id, manifest)
        sid_b, hash_b = await _preview(engine, novel_id, manifest)

        # 第三个连接持有同一 dataset advisory lock：两个 apply 都必须等待。
        holder = await engine.connect()
        holder_tx = await holder.begin()
        await holder.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"worldbook_import:{novel_id}:{identity.key}"},
        )

        task_a = asyncio.create_task(_apply_outcome(engine, novel_id, sid_a, hash_a))
        task_b = asyncio.create_task(_apply_outcome(engine, novel_id, sid_b, hash_b))
        await asyncio.sleep(_LOCK_WAIT_SECONDS)
        assert not task_a.done(), "apply 未在 dataset advisory lock 上等待"
        assert not task_b.done(), "apply 未在 dataset advisory lock 上等待"

        await holder_tx.commit()
        await holder.close()

        outcome_a = await asyncio.wait_for(task_a, _FINISH_TIMEOUT_SECONDS)
        outcome_b = await asyncio.wait_for(task_b, _FINISH_TIMEOUT_SECONDS)
        assert sorted([outcome_a, outcome_b]) == ["accepted", "conflict"]

        drafts = await _draft_rows(engine, novel_id)
        assert len(drafts) == 2
        assert {title for title, _page_type in drafts} == {"理法之环", "星锻环"}
        statuses = await _suggestion_statuses(engine, novel_id, [sid_a, sid_b])
        assert sorted(statuses.values()) == ["accepted", "pending"]
    finally:
        await _cleanup(engine, novel_id)
        await engine.dispose()


async def test_same_suggestion_double_apply_is_claimed_once() -> None:
    """同一 suggestion 重复 apply：claim CAS 只放行一次，工作稿不重复。"""
    engine = create_async_engine(DATABASE_URL, pool_size=2, max_overflow=0)
    novel_id = uuid.uuid4()
    manifest = _ring_manifest()
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions.begin() as db:
            db.add(Project(id=novel_id, title="Ring dataset import CAS e2e"))
        suggestion_id, preview_hash = await _preview(engine, novel_id, manifest)

        await _apply(engine, novel_id, suggestion_id, preview_hash)
        with pytest.raises(SuggestionAlreadyProcessedError):
            await _apply(engine, novel_id, suggestion_id, preview_hash)

        drafts = await _draft_rows(engine, novel_id)
        assert len(drafts) == 2
        statuses = await _suggestion_statuses(engine, novel_id, [suggestion_id])
        assert statuses[suggestion_id] == "accepted"
    finally:
        await _cleanup(engine, novel_id)
        await engine.dispose()


async def test_stale_preview_hash_conflicts_and_retry_succeeds() -> None:
    """过期预览指纹返回冲突且建议保持 pending，随后用新鲜指纹重试可成功。"""
    engine = create_async_engine(DATABASE_URL, pool_size=2, max_overflow=0)
    novel_id = uuid.uuid4()
    manifest = _ring_manifest()
    try:
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions.begin() as db:
            db.add(Project(id=novel_id, title="Ring dataset import stale hash e2e"))
        suggestion_id, preview_hash = await _preview(engine, novel_id, manifest)

        with pytest.raises(ConflictError, match="target changed"):
            await _apply(engine, novel_id, suggestion_id, "0" * 64)
        statuses = await _suggestion_statuses(engine, novel_id, [suggestion_id])
        assert statuses[suggestion_id] == "pending"

        await _apply(engine, novel_id, suggestion_id, preview_hash)
        drafts = await _draft_rows(engine, novel_id)
        assert len(drafts) == 2
    finally:
        await _cleanup(engine, novel_id)
        await engine.dispose()
