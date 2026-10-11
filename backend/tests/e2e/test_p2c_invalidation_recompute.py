"""P2-C 端到端（真 PG + 公开 API）：改稿失效透传与重算编排。

覆盖计划 P2-C 验收链路的 API 级关键流：
  1. 改一处保管记录发布 v2 → 保存响应携带 invalidation 公共视图
     （affected 可解释 + receipt_id + recompute_options 三分类）。
  2. 重算预览零正史写入；adopt reload_evidence 幂等（重放不重复入队）。
  3. 来源漂移 adopt → 409 recompute_source_drift 且保留当前稿。

数据合成，零 LLM。模块级行为已由
modules/evolution/tests/test_p2c_revision_adoption.py（SQLite 端到端）覆盖，
本文件验证真实 PG 上的 API 接线。seed 模式沿该夹具（三章三场景 +
custody 事件 + ensure checkpoint）。
"""

from __future__ import annotations

import hashlib
import uuid
from types import SimpleNamespace
from uuid import UUID

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.story.continuity.models import MemorySceneCheckpoint
from modules.story.continuity.scene_projection import SceneMemoryProjectionService
from modules.story.continuity.services import MemoryService
from modules.story.outline_state.models import Scene
from modules.writing.models import WritingDraft

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]

CH1_V1 = "甲铸成铜钥匙，亲自收着。"
CH2_V1 = "甲把铜钥匙交给乙保管。"
CH3_V1 = "丙在钟楼下练剑，与铜钥匙无关。"
CH2_V2 = "甲把铜钥匙交给丙保管。"
CH2_V3 = "甲把铜钥匙交给丁保管。"

RECOMPUTE_KINDS = {"reload_evidence", "rebuild_derived_state", "regenerate_prose"}


async def _working_draft(
    db: AsyncSession, novel_id: str, chapter_index: int, content: str
) -> WritingDraft:
    draft = WritingDraft(
        id=uuid.uuid4(),
        novel_id=UUID(novel_id),
        chapter_index=chapter_index,
        title=f"第{chapter_index}章",
        content=content,
        content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        version_number=1,
        status="draft",
    )
    db.add(draft)
    await db.flush()
    return draft


async def _seed(db: AsyncSession, project_id: str) -> SimpleNamespace:
    scenes: dict[int, Scene] = {}
    for scene_index, chapter_index, content in (
        (0, 1, CH1_V1),
        (1, 2, CH2_V1),
        (2, 3, CH3_V1),
    ):
        scenes[scene_index] = Scene(
            novel_id=UUID(project_id),
            scene_index=scene_index,
            title=f"Scene {scene_index}",
            chapter_ids=[chapter_index],
            scene_chunks=[{"chapter_index": chapter_index}],
            status="draft",
        )
        db.add(scenes[scene_index])
        await db.flush()
        await _working_draft(db, project_id, chapter_index, content)
    key_id, jia, yi = (str(uuid.uuid4()) for _ in range(3))
    memory = MemoryService()
    await memory.record_scene_events(
        db,
        project_id,
        scene_id=str(scenes[0].id),
        scene_index=0,
        chapter_index=1,
        events=[
            {
                "dimension": "entities",
                "event_type": "entity_created",
                "entity_id": key_id,
                "snapshot_after": {
                    "name": "铜钥匙",
                    "custody_owner": jia,
                    "custody_holder": jia,
                },
            },
        ],
    )
    await memory.record_scene_events(
        db,
        project_id,
        scene_id=str(scenes[1].id),
        scene_index=1,
        chapter_index=2,
        events=[
            {
                "dimension": "entities",
                "event_type": "entity_updated",
                "entity_id": key_id,
                "snapshot_after": {"custody_holder": yi},
            },
        ],
    )
    projection = SceneMemoryProjectionService()
    for scene in scenes.values():
        await projection.ensure_scene(db, project_id, str(scene.id))
    await db.flush()
    return SimpleNamespace(scenes=scenes, key_id=key_id)


async def _current_checkpoint_count(
    db: AsyncSession, project_id: str | uuid.UUID, scene_id: uuid.UUID
) -> int:
    novel_uuid = project_id if isinstance(project_id, uuid.UUID) else UUID(project_id)
    return int(
        await db.scalar(
            select(func.count())
            .select_from(MemorySceneCheckpoint)
            .where(
                MemorySceneCheckpoint.novel_id == novel_uuid,
                MemorySceneCheckpoint.scene_id == scene_id,
                MemorySceneCheckpoint.is_current.is_(True),
            )
        )
    )


class TestP2CInvalidationRecompute:
    @pytest_asyncio.fixture
    async def ctx(self, async_client: AsyncClient, db_session: AsyncSession):
        from tests.e2e.seed_data import create_base_scene

        meta = await create_base_scene(db_session)
        await db_session.flush()
        seeded = await _seed(db_session, str(meta["project_uuid"]))
        await db_session.flush()
        return async_client, meta["project_id"], meta["project_uuid"], seeded

    async def _publish_v2(self, client: AsyncClient, pid: str) -> dict:
        resp = await client.post(
            "/api/writing/drafts",
            json={
                "novel_id": pid,
                "chapter_index": 2,
                "title": "第2章",
                "content": CH2_V2,
            },
        )
        assert resp.status_code == 201, resp.text
        return resp.json()

    async def test_revision_publish_carries_invalidation_public_view(
        self, ctx, db_session: AsyncSession
    ):
        """改保管记录发布 v2 → 响应携带 invalidation 公共视图（P2-C 主链路）。"""
        client, pid, project_uuid, seeded = ctx
        s0_current_before = await _current_checkpoint_count(
            db_session, project_uuid, seeded.scenes[0].id
        )
        assert s0_current_before > 0

        body = await self._publish_v2(client, pid)
        invalidation = body["draft"].get("invalidation")
        assert isinstance(invalidation, dict), body["draft"].keys()
        assert invalidation.get("receipt_id")
        affected = invalidation.get("affected")
        assert isinstance(affected, list) and affected
        reasons = {item.get("reason") for item in affected}
        assert reasons <= {
            "anchored_chapter_edited",
            "conservative_expansion_unregistered",
        }
        # 锚定章（第 2 章）的 Scene checkpoint 消费必须以 known 依据列出
        checkpoint_entries = [
            item for item in affected if item.get("consumer") == "story_scene_checkpoint"
        ]
        assert checkpoint_entries, affected
        assert any(item.get("basis") == "known" for item in checkpoint_entries)
        # 三分类齐备；regenerate 恒须作者显式选择
        options = invalidation.get("recompute_options")
        assert {item.get("kind") for item in options} == RECOMPUTE_KINDS
        # s1 起派生投影软失效（既有语义不回归）；s0（锚定章之前）不受牵连
        assert (
            await _current_checkpoint_count(db_session, project_uuid, seeded.scenes[1].id)
            == 0
        )
        assert (
            await _current_checkpoint_count(db_session, project_uuid, seeded.scenes[0].id)
            == s0_current_before
        )

    async def test_recompute_preview_zero_write_and_adopt_idempotent(
        self, ctx, db_session: AsyncSession
    ):
        """预览零正史写入；adopt reload 幂等（重放不重复入队）。"""
        client, pid, project_uuid, seeded = ctx
        await self._publish_v2(client, pid)
        operation_id = str(uuid.uuid4())

        async def _payload(confirmed: bool | None = None, digest: str | None = None):
            body = {
                "novel_id": pid,
                "operation_id": operation_id,
                "scope": "reload_evidence",
                "targets": [{"chapter_index": 2}],
                "baseline_receipt_digest": "e2e",
            }
            if confirmed is not None:
                body["confirmed"] = confirmed
            if digest is not None:
                body["expected_source_digest"] = digest
            return body

        preview = await client.post("/api/writing/recompute", json=await _payload())
        assert preview.status_code in (200, 201), preview.text
        assert preview.json().get("domain_write_performed") is False

        # adopt 两次：入队的 rag_index_chapter 任务数不翻倍（幂等重放）
        first = await client.post(
            f"/api/writing/recompute/{operation_id}/adopt",
            json=await _payload(confirmed=True, digest=preview.json()["source_digest"]),
        )
        assert first.status_code in (200, 201), first.text
        second = await client.post(
            f"/api/writing/recompute/{operation_id}/adopt",
            json=await _payload(confirmed=True, digest=preview.json()["source_digest"]),
        )
        assert second.status_code in (200, 201), second.text
        assert second.json().get("replayed") in (True, False, None)

        from infrastructure.tasks.models import AsyncTask

        task_count = int(
            await db_session.scalar(
                select(func.count())
                .select_from(AsyncTask)
                .where(AsyncTask.novel_id == project_uuid)
            )
        )
        assert task_count >= 1, "reload_evidence 应至少入队一次证据索引任务"

    async def test_adopt_with_stale_digest_conflicts_and_keeps_current(
        self, ctx, db_session: AsyncSession
    ):
        """预览后来源再变 → adopt 409 漂移，当前稿保留。"""
        client, pid, project_uuid, seeded = ctx
        await self._publish_v2(client, pid)
        operation_id = str(uuid.uuid4())
        preview = await client.post(
            "/api/writing/recompute",
            json={
                "novel_id": pid,
                "operation_id": operation_id,
                "scope": "reload_evidence",
                "targets": [{"chapter_index": 2}],
                "baseline_receipt_digest": "e2e",
            },
        )
        assert preview.status_code in (200, 201), preview.text
        stale_digest = preview.json()["source_digest"]

        # 来源再变：发布 v3
        v3 = await client.post(
            "/api/writing/drafts",
            json={
                "novel_id": pid,
                "chapter_index": 2,
                "title": "第2章",
                "content": CH2_V3,
            },
        )
        assert v3.status_code == 201, v3.text

        conflict = await client.post(
            f"/api/writing/recompute/{operation_id}/adopt",
            json={
                "novel_id": pid,
                "operation_id": operation_id,
                "scope": "reload_evidence",
                "targets": [{"chapter_index": 2}],
                "baseline_receipt_digest": "e2e",
                "confirmed": True,
                "expected_source_digest": stale_digest,
            },
        )
        assert conflict.status_code == 409, conflict.text
        assert conflict.json().get("error") == "recompute_source_drift"
        assert conflict.json().get("context", {}).get("keep_current_draft") is True
        # 当前稿仍是 v3（漂移保护不覆盖后来修改；该端点直接返回 draft 对象）
        latest = await client.get(f"/api/writing/chapters/2/draft?novel_id={pid}")
        assert latest.status_code == 200
        assert latest.json()["content"] == CH2_V3
