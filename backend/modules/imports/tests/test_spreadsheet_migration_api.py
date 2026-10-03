"""表格迁移 API 层测试（L4）。

走全部路由；world/story/AI facade 与解析/识别用替身；覆盖鉴权隔离、
上传拒绝、CAS 409、stale 409、Literal[True] 校验与日志不含正文。
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient

from modules.account.middleware import _DEMO_CORE_READ_PREFIXES
from modules.imports.spreadsheet_migration.classify import (
    ColumnSuggestion,
    SheetSuggestion,
)
from modules.imports.spreadsheet_migration.parsing import ParsedSheet, ParsedUpload
from modules.story.outline_state.contracts import (
    StoryMigrationPlan,
    StoryMigrationReceipt,
)
from modules.world.contracts import (
    MigrationAppliedChange,
    MigrationRollbackResult,
    WorldMigrationItemPlan,
    WorldMigrationPlan,
    WorldMigrationReceipt,
)

OWNER_ID = uuid.uuid4()


def _upload() -> ParsedUpload:
    return ParsedUpload(
        file_key="f0",
        file_name="人物表.xlsx",
        file_type="xlsx",
        size=128,
        sha256="a" * 64,
        sheets=[
            ParsedSheet(
                sheet_key="f0s0",
                file_key="f0",
                name="人物",
                hidden=False,
                rows=[["姓名", "简介"], ["张三", "主角"]],
                warnings=[],
            )
        ],
    )


def _suggestion() -> SheetSuggestion:
    return SheetSuggestion(
        kind="characters",
        header_row=0,
        columns=[
            ColumnSuggestion(
                column_key="c0", header="姓名", target="name", confident=True
            ),
            ColumnSuggestion(
                column_key="c1", header="简介", target="summary", confident=True
            ),
        ],
    )


def _world_plan() -> WorldMigrationPlan:
    return WorldMigrationPlan(
        items=[WorldMigrationItemPlan(item_key="k1", kind="entity", action="create")],
        validation_policy_active=False,
        fingerprint="world-fp",
    )


def _story_plan() -> StoryMigrationPlan:
    return StoryMigrationPlan(items=[], outline_action=None, fingerprint="story-fp")


def _world_receipt() -> WorldMigrationReceipt:
    return WorldMigrationReceipt(
        applied_changes=[
            MigrationAppliedChange(
                item_key="k1",
                kind="entity",
                target_id=str(uuid.uuid4()),
                operation="create",
                after_hash="h",
            )
        ],
        entity_ids={"k1": str(uuid.uuid4())},
    )


@pytest.fixture
def parse_and_classify():
    # L1 未合入：parsers.parse_spreadsheet_file 在本分支不存在，autospec 无法
    # 替身缺失属性，故用 new= 显式替身（规则允许，说明见此）；L8 换真实链路。
    parse_double = MagicMock(return_value=_upload())
    with (
        patch(
            "modules.imports.parsers.parse_spreadsheet_file",
            parse_double,
            create=True,
        ),  # autospec-exempt: L1 未合入时属性不存在，new= 显式替身
        patch(
            "modules.imports.spreadsheet_migration.classify.classify_sheet",
            autospec=True,
        ) as classify_sheet,
    ):
        classify_sheet.return_value = _suggestion()
        yield parse_double, classify_sheet


@pytest.fixture
def plan_facades():
    with (
        patch(
            "modules.world.facade.plan_author_migration_world", autospec=True
        ) as world_plan,
        patch(
            "modules.story.outline_state.facade.plan_author_migration_structures",
            autospec=True,
        ) as story_plan,
    ):
        world_plan.return_value = _world_plan()
        story_plan.return_value = _story_plan()
        yield world_plan, story_plan


@pytest.fixture
def apply_facades():
    with (
        patch(
            "modules.world.facade.apply_author_migration_world", autospec=True
        ) as world_apply,
        patch(
            "modules.story.outline_state.facade.apply_author_migration_structures",
            autospec=True,
        ) as story_apply,
        patch(
            "modules.project.facade.require_active_project_exclusive",
            autospec=True,
        ),
    ):
        world_apply.return_value = _world_receipt()
        story_apply.return_value = StoryMigrationReceipt()
        yield world_apply, story_apply


@pytest_asyncio.fixture
async def project(async_client: AsyncClient, account_llm_connection) -> dict:
    resp = await async_client.post("/api/projects", json={"title": "迁移 API 测试"})
    assert resp.status_code == 201
    return resp.json()


@pytest_asyncio.fixture
async def draft_session(
    async_client: AsyncClient,
    project: dict,
    parse_and_classify,
) -> dict:
    resp = await async_client.post(
        "/api/imports/migrations",
        data={"novel_id": project["id"]},
        files={"files": ("人物表.xlsx", b"fake", "application/vnd.ms-excel")},
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.asyncio
async def test_demo_anonymous_cannot_reach_migrations() -> None:
    """/api/imports 不在匿名 demo 只读白名单中，钉住这一点。"""
    assert not "/api/imports/migrations".startswith(_DEMO_CORE_READ_PREFIXES)


@pytest.mark.asyncio
async def test_create_and_get_session(
    async_client: AsyncClient, project: dict, draft_session: dict
) -> None:
    assert draft_session["status"] == "draft"
    assert draft_session["revision"] == 1
    assert draft_session["files"][0]["file_name"] == "人物表.xlsx"
    sheet = draft_session["sheets"][0]
    assert sheet["kind"] == "characters"
    assert sheet["kind_suggested"] is True
    assert sheet["columns"][0]["target"] == "name"
    assert sheet["sample_rows"] == [["张三", "主角"]]

    detail = await async_client.get(
        f"/api/imports/migrations/{draft_session['id']}",
        params={"novel_id": project["id"]}
    )
    assert detail.status_code == 200
    assert detail.json()["id"] == draft_session["id"]

    listing = await async_client.get(
        "/api/imports/migrations", params={"novel_id": project["id"]}
    )
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["total"] >= 1
    assert body["items"][0]["file_names"] == ["人物表.xlsx"]


@pytest.mark.asyncio
async def test_mapping_keeps_default_entity_type(
    async_client: AsyncClient, project: dict, draft_session: dict, plan_facades
) -> None:
    novel_id = project["id"]
    detail = await async_client.get(
        f"/api/imports/migrations/{draft_session['id']}",
        params={"novel_id": novel_id},
    )
    assert detail.json()["sheets"][0]["default_entity_type"] == "character"

    # 客户端整体保存但不携带 default_entity_type 时不得被静默清掉
    mapping = await async_client.put(
        f"/api/imports/migrations/{draft_session['id']}/mapping",
        json={
            "novel_id": novel_id,
            "expected_revision": 1,
            "sheets": [
                {
                    "sheet_key": "f0s0",
                    "kind": "characters",
                    "header_row": 0,
                    "columns": {"c0": "name", "c1": "summary"},
                }
            ],
            "options": {
                "written_chapter_policy": "reference_only",
                "outline_head_policy": "create_if_missing",
            },
        },
    )
    assert mapping.status_code == 200, mapping.text
    assert mapping.json()["sheets"][0]["default_entity_type"] == "character"

    detail = await async_client.get(
        f"/api/imports/migrations/{draft_session['id']}",
        params={"novel_id": novel_id},
    )
    assert detail.json()["sheets"][0]["default_entity_type"] == "character"


@pytest.mark.asyncio
async def test_cross_novel_and_unknown_ids_return_404(
    async_client: AsyncClient, project: dict, draft_session: dict
) -> None:
    other_novel = str(uuid.uuid4())
    resp = await async_client.get(
        f"/api/imports/migrations/{draft_session['id']}", params={"novel_id": other_novel}
    )
    assert resp.status_code == 404
    resp = await async_client.get(
        f"/api/imports/migrations/{uuid.uuid4()}", params={"novel_id": project["id"]}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_upload_rejects_extension_and_oversize(
    async_client: AsyncClient, project: dict
) -> None:
    resp = await async_client.post(
        "/api/imports/migrations",
        data={"novel_id": project["id"]},
        files={"files": ("chapter.xls", b"bytes", "application/vnd.ms-excel")},
    )
    assert resp.status_code == 400
    assert ".xlsx" in resp.json()["detail"]

    resp = await async_client.post(
        "/api/imports/migrations",
        data={"novel_id": project["id"]},
        files={"files": ("big.csv", b"x" * (10 * 1024 * 1024 + 1), "text/csv")},
    )
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_get_rows_and_410_after_apply(
    async_client: AsyncClient,
    project: dict,
    draft_session: dict,
    plan_facades,
    apply_facades,
) -> None:
    novel_id = project["id"]
    rows = await async_client.get(
        f"/api/imports/migrations/{draft_session['id']}/rows",
        params={"novel_id": novel_id, "sheet_key": "f0s0"},
    )
    assert rows.status_code == 200
    body = rows.json()
    assert body["header"] == ["姓名", "简介"]
    assert body["total"] == 1
    assert body["rows"][0]["cells"] == ["张三", "主角"]

    mapping = await async_client.put(
        f"/api/imports/migrations/{draft_session['id']}/mapping",
        json={
            "novel_id": novel_id,
            "expected_revision": 1,
            "sheets": [
                {
                    "sheet_key": "f0s0",
                    "kind": "characters",
                    "header_row": 0,
                    "columns": {"c0": "name", "c1": "summary"},
                }
            ],
            "options": {
                "written_chapter_policy": "reference_only",
                "outline_head_policy": "create_if_missing",
            },
        },
    )
    assert mapping.status_code == 200
    mapped = mapping.json()
    assert mapped["revision"] == 2
    preview_hash = mapped["preview"]["preview_hash"]

    applied = await async_client.post(
        f"/api/imports/migrations/{draft_session['id']}/apply",
        json={
            "novel_id": novel_id,
            "expected_preview_hash": preview_hash,
            "confirmed": True,
        },
    )
    assert applied.status_code == 200
    assert applied.json()["counts"]["created"] == 1

    cleared = await async_client.get(
        f"/api/imports/migrations/{draft_session['id']}/rows",
        params={"novel_id": novel_id, "sheet_key": "f0s0"},
    )
    assert cleared.status_code == 410


@pytest.mark.asyncio
async def test_mapping_conflict_on_stale_revision(
    async_client: AsyncClient, project: dict, draft_session: dict, plan_facades
) -> None:
    resp = await async_client.put(
        f"/api/imports/migrations/{draft_session['id']}/mapping",
        json={
            "novel_id": project["id"],
            "expected_revision": 99,
            "sheets": [
                {
                    "sheet_key": "f0s0",
                    "kind": "characters",
                    "header_row": 0,
                    "columns": {"c0": "name"},
                }
            ],
            "options": {
                "written_chapter_policy": "reference_only",
                "outline_head_policy": "create_if_missing",
            },
        },
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_apply_stale_hash_returns_409_with_new_hash(
    async_client: AsyncClient, project: dict, draft_session: dict, plan_facades
) -> None:
    resp = await async_client.post(
        f"/api/imports/migrations/{draft_session['id']}/apply",
        json={
            "novel_id": project["id"],
            "expected_preview_hash": "0" * 64,
            "confirmed": True,
        },
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"] == "migration_preview_stale"
    assert body.get("context", {}).get("preview_hash")


@pytest.mark.asyncio
async def test_apply_requires_confirmed_true(
    async_client: AsyncClient, project: dict, draft_session: dict, plan_facades
) -> None:
    resp = await async_client.post(
        f"/api/imports/migrations/{draft_session['id']}/apply",
        json={"novel_id": project["id"], "expected_preview_hash": "0" * 64},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_decisions_save(
    async_client: AsyncClient, project: dict, draft_session: dict, plan_facades
) -> None:
    resp = await async_client.put(
        f"/api/imports/migrations/{draft_session['id']}/decisions",
        json={
            "novel_id": project["id"],
            "expected_revision": 1,
            "decisions": [{"item_key": "k1", "action": "skip"}],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["revision"] == 2


@pytest.mark.asyncio
async def test_rollback_flow(
    async_client: AsyncClient,
    db_session,
    project: dict,
    draft_session: dict,
    plan_facades,
    apply_facades,
):
    novel_id = project["id"]
    mapping = await async_client.put(
        f"/api/imports/migrations/{draft_session['id']}/mapping",
        json={
            "novel_id": novel_id,
            "expected_revision": 1,
            "sheets": [
                {
                    "sheet_key": "f0s0",
                    "kind": "characters",
                    "header_row": 0,
                    "columns": {"c0": "name", "c1": "summary"},
                }
            ],
            "options": {
                "written_chapter_policy": "reference_only",
                "outline_head_policy": "create_if_missing",
            },
        },
    )
    preview_hash = mapping.json()["preview"]["preview_hash"]
    await async_client.post(
        f"/api/imports/migrations/{draft_session['id']}/apply",
        json={
            "novel_id": novel_id,
            "expected_preview_hash": preview_hash,
            "confirmed": True,
        },
    )

    with (
        patch(
            "modules.story.outline_state.facade.rollback_author_migration_structures",
            autospec=True,
        ) as story_rollback,
        patch(
            "modules.world.facade.rollback_author_migration_world",
            autospec=True,
        ) as world_rollback,
    ):
        # require_active_project_exclusive 已由 apply_facades fixture 覆盖
        story_rollback.return_value = MigrationRollbackResult(reverted=["k1"], kept=[])
        world_rollback.return_value = MigrationRollbackResult(reverted=[], kept=[])
        preview = await async_client.get(
            f"/api/imports/migrations/{draft_session['id']}/rollback-preview",
            params={"novel_id": novel_id},
        )
        assert preview.status_code == 200
        result = await async_client.post(
            f"/api/imports/migrations/{draft_session['id']}/rollback",
            json={"novel_id": novel_id, "confirmed": True},
        )
    assert result.status_code == 200
    body = result.json()
    assert body["status"] == "rolled_back"
    assert body["reverted_count"] == 1


@pytest.mark.asyncio
async def test_delete_requires_confirmation(
    async_client: AsyncClient, project: dict, draft_session: dict
) -> None:
    novel_id = project["id"]
    resp = await async_client.delete(
        f"/api/imports/migrations/{draft_session['id']}", params={"novel_id": novel_id}
    )
    assert resp.status_code == 422
    resp = await async_client.delete(
        f"/api/imports/migrations/{draft_session['id']}",
        params={"novel_id": novel_id, "confirmed": True},
    )
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_ai_run_endpoint_validates(
    async_client: AsyncClient, project: dict, draft_session: dict
) -> None:
    novel_id = project["id"]
    resp = await async_client.post(
        f"/api/imports/migrations/{draft_session['id']}/ai-runs",
        json={
            "novel_id": novel_id,
            "expected_revision": 99,
            "authorization_confirmed": True,
            "operation_id": "op-1",
            "scope": {"outline_sheet_keys": [], "cleanup": []},
        },
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_logs_do_not_leak_cell_content(
    async_client: AsyncClient,
    project: dict,
    draft_session: dict,
    plan_facades,
    caplog,
) -> None:
    import logging

    with caplog.at_level(logging.INFO):
        await async_client.get(
            f"/api/imports/migrations/{draft_session['id']}",
            params={"novel_id": project["id"]},
        )
    for record in caplog.records:
        assert "张三" not in record.getMessage()
        assert "主角" not in record.getMessage()
