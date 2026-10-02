"""表格迁移 PostgreSQL 关键路径（L8）。

覆盖（计划 §4 L8）：
1. 并发 apply：只有一个成功，另一个 409；
2. 项目行被排他锁持有时 apply 失败关闭且零写入；
3. 预览后被匹配实体修改 → apply 判 stale（409 附新 hash）；
4. 回滚与编辑竞争：被改动项保留（modified_after_migration）；
5. mapping 的 revision CAS；
6. 1000 行 apply 计时（记录时长；超硬上限才失败）。
"""

from __future__ import annotations

import asyncio
import time
import uuid

import pytest
from httpx import ASGITransport
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app
from core.database import get_manager
from modules.imports.tests.spreadsheet_fixtures import build_xlsx
from modules.project.models import Project
from modules.world.models import CoreEntity
from tests.e2e.config import DATABASE_URL
from tests.support.http import XhrAsyncClient

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e]


def _character_sheet(rows: int = 2) -> bytes:
    data = [["姓名", "身份"]]
    for index in range(rows):
        data.append([f"测试人物{index:04d}", "配角"])
    return build_xlsx([{"name": "人物", "rows": data}])


async def _create_project(client: XhrAsyncClient, title: str) -> str:
    resp = await client.post("/api/projects", json={"title": title})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _upload_and_map(client: XhrAsyncClient, novel_id: str, workbook: bytes) -> dict:
    upload = await client.post(
        "/api/imports/migrations",
        data={"novel_id": novel_id},
        files={"files": ("人物.xlsx", workbook, "application/vnd.ms-excel")},
    )
    assert upload.status_code == 201, upload.text
    session = upload.json()
    sheets = [
        {
            "sheet_key": sheet["sheet_key"],
            "kind": sheet["kind"],
            "header_row": sheet["header_row"],
            "columns": {
                column["column_key"]: column["target"] for column in sheet["columns"]
            },
        }
        for sheet in session["sheets"]
    ]
    mapped = await client.put(
        f"/api/imports/migrations/{session['id']}/mapping",
        json={
            "novel_id": novel_id,
            "expected_revision": session["revision"],
            "sheets": sheets,
            "options": {
                "written_chapter_policy": "reference_only",
                "outline_head_policy": "skip",
            },
        },
    )
    assert mapped.status_code == 200, mapped.text
    return mapped.json()


async def _apply(client: XhrAsyncClient, novel_id: str, session: dict):
    return await client.post(
        f"/api/imports/migrations/{session['id']}/apply",
        json={
            "novel_id": novel_id,
            "expected_preview_hash": session["preview"]["preview_hash"],
            "confirmed": True,
        },
    )


async def _entity_count(novel_uuid: uuid.UUID) -> int:
    async with get_manager().session_factory() as observer:
        return await observer.scalar(
            select(func.count())
            .select_from(CoreEntity)
            .where(CoreEntity.novel_id == novel_uuid)
        )


async def test_concurrent_apply_single_winner() -> None:
    transport = ASGITransport(app=app)
    async with XhrAsyncClient(transport=transport, base_url="http://test") as client:
        novel_id = await _create_project(client, "迁移并发采用")
        session = await _upload_and_map(client, novel_id, _character_sheet(2))

        first, second = await asyncio.gather(
            _apply(client, novel_id, session),
            _apply(client, novel_id, session),
        )
        statuses = sorted([first.status_code, second.status_code])
        assert statuses == [200, 409], (
            first.status_code,
            second.status_code,
            first.text,
            second.text,
        )

        assert await _entity_count(uuid.UUID(novel_id)) == 2


async def test_apply_waits_for_exclusive_lock_and_serializes() -> None:
    """深度导入式排他锁持有期间 apply 阻塞等待；锁释放后串行完成，不并发写。"""
    transport = ASGITransport(app=app)
    async with XhrAsyncClient(transport=transport, base_url="http://test") as client:
        novel_id = await _create_project(client, "迁移排他锁")
        session = await _upload_and_map(client, novel_id, _character_sheet(2))
        novel_uuid = uuid.UUID(novel_id)

        engine = create_async_engine(DATABASE_URL, pool_size=2)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessions() as holder:
                await holder.execute(
                    select(Project).where(Project.id == novel_uuid).with_for_update()
                )
                apply_task = asyncio.create_task(_apply(client, novel_id, session))
                # 持锁期间 apply 不得完成（阻塞在项目排他锁上）
                done, _ = await asyncio.wait({apply_task}, timeout=2.0)
                assert not done, "项目行被持有时 apply 不应完成"
            # 锁释放后 apply 继续并成功
            resp = await apply_task
            assert resp.status_code == 200, resp.text
        finally:
            await engine.dispose()

        assert await _entity_count(novel_uuid) == 2


async def test_preview_stale_when_entity_modified_after_preview() -> None:
    transport = ASGITransport(app=app)
    async with XhrAsyncClient(transport=transport, base_url="http://test") as client:
        novel_id = await _create_project(client, "迁移预览过期")
        novel_uuid = uuid.UUID(novel_id)

        # 预置同名实体：预览会给出 existing/fill 类动作并纳入指纹
        engine = create_async_engine(DATABASE_URL, pool_size=2)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sessions() as seeder:
                seeder.add(
                    CoreEntity(
                        novel_id=novel_uuid,
                        name="测试人物0000",
                        entity_type="character",
                        summary="旧简介",
                        status="canonical",
                    )
                )
                await seeder.commit()
        finally:
            await engine.dispose()

        session = await _upload_and_map(client, novel_id, _character_sheet(2))

        # 预览后作者直接修改该实体（updated_at 变化 → 指纹漂移）
        async with get_manager().session_factory() as editor:
            entity = await editor.scalar(
                select(CoreEntity).where(
                    CoreEntity.novel_id == novel_uuid,
                    CoreEntity.name == "测试人物0000",
                )
            )
            entity.summary = "被作者改过的简介"
            await editor.commit()

        resp = await _apply(client, novel_id, session)
        assert resp.status_code == 409, resp.text
        body = resp.json()
        assert body["error"] == "migration_preview_stale"
        assert body.get("context", {}).get("preview_hash")


async def test_rollback_keeps_modified_items() -> None:
    transport = ASGITransport(app=app)
    async with XhrAsyncClient(transport=transport, base_url="http://test") as client:
        novel_id = await _create_project(client, "迁移回滚竞争")
        novel_uuid = uuid.UUID(novel_id)
        session = await _upload_and_map(client, novel_id, _character_sheet(2))
        applied = await _apply(client, novel_id, session)
        assert applied.status_code == 200, applied.text

        async with get_manager().session_factory() as editor:
            entity = await editor.scalar(
                select(CoreEntity).where(
                    CoreEntity.novel_id == novel_uuid,
                    CoreEntity.name == "测试人物0000",
                )
            )
            entity.summary = "回滚前作者改写"
            await editor.commit()

        rollback = await client.post(
            f"/api/imports/migrations/{session['id']}/rollback",
            json={"novel_id": novel_id, "confirmed": True},
        )
        assert rollback.status_code == 200, rollback.text
        body = rollback.json()
        assert body["reverted_count"] >= 1
        reasons = [kept.get("reason") or "" for kept in body["kept"]]
        assert any("修改" in reason for reason in reasons), body["kept"]

        async with get_manager().session_factory() as observer:
            edited = await observer.scalar(
                select(CoreEntity).where(
                    CoreEntity.novel_id == novel_uuid,
                    CoreEntity.name == "测试人物0000",
                )
            )
        assert edited.status == "canonical", "被作者改过的实体应保留不废弃"


async def test_mapping_revision_cas() -> None:
    transport = ASGITransport(app=app)
    async with XhrAsyncClient(transport=transport, base_url="http://test") as client:
        novel_id = await _create_project(client, "迁移CAS")
        upload = await client.post(
            "/api/imports/migrations",
            data={"novel_id": novel_id},
            files={
                "files": ("人物.xlsx", _character_sheet(1), "application/vnd.ms-excel")
            },
        )
        session = upload.json()
        sheet = session["sheets"][0]
        payload = {
            "novel_id": novel_id,
            "expected_revision": 99,
            "sheets": [
                {
                    "sheet_key": sheet["sheet_key"],
                    "kind": sheet["kind"],
                    "header_row": sheet["header_row"],
                    "columns": {
                        column["column_key"]: column["target"]
                        for column in sheet["columns"]
                    },
                }
            ],
            "options": {
                "written_chapter_policy": "reference_only",
                "outline_head_policy": "skip",
            },
        }
        resp = await client.put(
            f"/api/imports/migrations/{session['id']}/mapping", json=payload
        )
        assert resp.status_code == 409
        payload["expected_revision"] = 1
        resp = await client.put(
            f"/api/imports/migrations/{session['id']}/mapping", json=payload
        )
        assert resp.status_code == 200


async def test_thousand_row_apply_timing() -> None:
    transport = ASGITransport(app=app)
    async with XhrAsyncClient(transport=transport, base_url="http://test") as client:
        novel_id = await _create_project(client, "迁移千行计时")
        session = await _upload_and_map(client, novel_id, _character_sheet(1000))
        started = time.monotonic()
        resp = await _apply(client, novel_id, session)
        elapsed = time.monotonic() - started
        assert resp.status_code == 200, resp.text
        assert resp.json()["counts"]["created"] == 1000
        assert await _entity_count(uuid.UUID(novel_id)) == 1000
        # 计时供批量优化决策；300s 为保护性上限而非性能承诺
        print(f"\n1000 行 apply 用时 {elapsed:.1f}s")
        assert elapsed < 300, f"1000 行 apply 用时 {elapsed:.1f}s，需要批量通道评估"
