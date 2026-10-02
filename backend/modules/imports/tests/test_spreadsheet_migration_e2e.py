"""表格迁移真实链路 e2e（L8）— SQLite + 真实 parser/classify/planning/world/story。

流程：上传 xlsx（人物 + 关系 + 细纲）→ 映射 → 预览 → 采用 → 世界库/关系/Scene 可见
→ 撤销 → 状态恢复。不走 LLM（AI 步骤跳过，规则映射）。
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.imports.tests.spreadsheet_fixtures import build_xlsx
from modules.story.outline_state.models import Scene
from modules.world.models import CoreEntity, EntityRelation

OWNER_ID = uuid.uuid4()


def _workbook() -> bytes:
    return build_xlsx(
        [
            {
                "name": "人物表",
                "rows": [
                    ["姓名", "别名", "身份", "简介", "秘密"],
                    ["林昭", "昭昭、小林", "边军斥候", "沉默寡言的老斥候",
                     "曾是先帝暗卫"],
                    ["沈青梧", "", "世家嫡女", "表面娇纵实则隐忍", ""],
                ],
            },
            {
                "name": "关系",
                "rows": [
                    ["甲方", "乙方", "关系", "说明"],
                    ["林昭", "沈青梧", "保护", "受先帝遗命暗中保护"],
                ],
            },
            {
                "name": "细纲",
                "rows": [
                    ["章", "标题", "必须发生"],
                    ["第1章", "雪夜入城", "林昭护送沈青梧入城，遭遇截杀"],
                    ["第2章", "旧案重启", "沈青梧发现家族旧案卷宗"],
                ],
            },
        ]
    )


@pytest_asyncio.fixture
async def project(async_client: AsyncClient, account_llm_connection) -> dict:
    resp = await async_client.post("/api/projects", json={"title": "迁移 e2e"})
    assert resp.status_code == 201
    return resp.json()


async def _upload(async_client: AsyncClient, project: dict) -> dict:
    resp = await async_client.post(
        "/api/imports/migrations",
        data={"novel_id": project["id"]},
        files={
            "files": (
                "设定表.xlsx",
                _workbook(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _mapping_body(project: dict, session: dict) -> dict:
    kinds = {}
    for sheet in session["sheets"]:
        kinds[sheet["sheet_key"]] = sheet
    sheets = []
    for sheet_key, sheet in kinds.items():
        sheets.append(
            {
                "sheet_key": sheet_key,
                "kind": sheet["kind"],
                "header_row": sheet["header_row"],
                "columns": {
                    column["column_key"]: column["target"]
                    for column in sheet["columns"]
                },
            }
        )
    return {
        "novel_id": project["id"],
        "expected_revision": session["revision"],
        "sheets": sheets,
        "options": {
            "written_chapter_policy": "reference_only",
            "outline_head_policy": "skip",
        },
    }


@pytest.mark.asyncio
async def test_full_migration_apply_and_rollback(
    async_client: AsyncClient,
    db_session: AsyncSession,
    project: dict,
) -> None:
    novel_id = project["id"]
    novel_uuid = uuid.UUID(novel_id)

    # 1. 上传 → 识别（真实 parser + classify）
    draft = await _upload(async_client, project)
    kinds = {
        sheet["name"]: (sheet["kind"], sheet["sheet_key"])
        for sheet in draft["sheets"]
    }
    assert kinds["人物表"][0] == "characters"
    assert kinds["关系"][0] == "relations"
    assert kinds["细纲"][0] == "chapter_outline"

    # 2. 映射（真实 planning + world/story plan）
    mapped = await async_client.put(
        f"/api/imports/migrations/{draft['id']}/mapping",
        json=_mapping_body(project, draft),
    )
    assert mapped.status_code == 200, mapped.text
    session = mapped.json()
    preview = session["preview"]
    assert preview, session
    assert preview["counts"]["create"] == 2  # 两个人物
    assert preview["counts"]["relations"] == 1
    assert preview["counts"]["structures"] == 2  # 两个章节细纲
    preview_hash = preview["preview_hash"]

    # 3. 采用（真实 world.apply + story.apply，同一事务）
    applied = await async_client.post(
        f"/api/imports/migrations/{session['id']}/apply",
        json={
            "novel_id": novel_id,
            "expected_preview_hash": preview_hash,
            "confirmed": True,
        },
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["counts"]["created"] == 2

    # 4. 世界库 / 关系 / Scene 可见且带来源
    entities = (
        (
            await db_session.execute(
                select(CoreEntity).where(
                    CoreEntity.novel_id == novel_uuid,
                    CoreEntity.name.in_(["林昭", "沈青梧"]),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(entities) == 2
    by_name = {entity.name: entity for entity in entities}
    assert by_name["林昭"].status == "canonical"
    meta = (by_name["林昭"].content_json or {}).get("_meta") or {}
    assert meta.get("source") == "spreadsheet_migration"
    # 未识别/秘密列进入 hidden_truth 或显式秘密列
    assert "先帝暗卫" in (by_name["林昭"].hidden_truth or "")

    relations = (
        (
            await db_session.execute(
                select(EntityRelation).where(EntityRelation.novel_id == novel_uuid)
            )
        )
        .scalars()
        .all()
    )
    assert len(relations) == 1
    assert relations[0].relation_type in {"保护", "protects"}
    assert relations[0].source_id == by_name["林昭"].id
    assert relations[0].target_id == by_name["沈青梧"].id

    scenes = (
        (
            await db_session.execute(
                select(Scene).where(Scene.novel_id == novel_uuid)
            )
        )
        .scalars()
        .all()
    )
    assert len(scenes) == 2
    assert all(scene.source == "spreadsheet_migration" for scene in scenes)
    def _range(scene: Scene) -> tuple[int, int]:
        span = (scene.structure_meta or {}).get("planned_chapter_range") or {}
        if isinstance(span, dict):
            return (int(span.get("start") or 0), int(span.get("end") or 0))
        values = list(span or [])
        return (int(values[0]), int(values[1])) if len(values) == 2 else (0, 0)

    assert sorted(_range(scene) for scene in scenes) == [(1, 1), (2, 2)]

    # 5. 采用后 rows 清除（410）+ 记录 can_rollback
    rows_resp = await async_client.get(
        f"/api/imports/migrations/{session['id']}/rows",
        params={"novel_id": novel_id, "sheet_key": kinds["人物表"][1]},
    )
    assert rows_resp.status_code == 410
    listing = await async_client.get(
        "/api/imports/migrations", params={"novel_id": novel_id}
    )
    assert listing.json()["items"][0]["can_rollback"] is True

    # 6. 撤销 → 状态恢复（软废弃，实体保留历史）
    rollback = await async_client.post(
        f"/api/imports/migrations/{session['id']}/rollback",
        json={"novel_id": novel_id, "confirmed": True},
    )
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()["reverted_count"] >= 3

    db_session.expire_all()
    kept_entities = (
        (
            await db_session.execute(
                select(CoreEntity).where(
                    CoreEntity.novel_id == novel_uuid,
                    CoreEntity.name.in_(["林昭", "沈青梧"]),
                )
            )
        )
        .scalars()
        .all()
    )
    assert all(
        entity.status == "deprecated" for entity in kept_entities
    ), "回滚后新建实体应软废弃而非硬删"

    detail = await async_client.get(
        f"/api/imports/migrations/{session['id']}", params={"novel_id": novel_id}
    )
    assert detail.json()["status"] == "rolled_back"
