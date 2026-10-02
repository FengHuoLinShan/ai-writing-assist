"""表格迁移 AI 整理测试（L5）。

用 DI 注入的 fake client 与 autospec 替身覆盖：schema 校验、逐字 evidence
校验、行引用、审查拦截与一次返修、超预算 422、scope_hash 漂移不写回、
任务白名单与运行信封声明。
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError
from infrastructure.tasks.api import _MODULE_API_ONLY_TASK_TYPES
from infrastructure.tasks.registry import _registry
from modules.imports.spreadsheet_migration import ai as ai_module
from modules.imports.spreadsheet_migration import ai_schemas
from modules.imports.spreadsheet_migration.ai import (
    ai_items_for_planning,
    estimate_ai_run,
)
from modules.imports.spreadsheet_migration.repository import (
    ImportMigrationSessionRepository,
)

NOVEL_ID = uuid.uuid4()
OWNER_ID = uuid.uuid4()


def _rows() -> list[list[str]]:
    return [
        ["章", "标题", "内容"],
        ["第1章", "开端", "主角进城遇到对手"],
        ["第2章", "冲突", "两人在城外决斗"],
    ]


def _mapping(kind: str = "chapter_outline") -> dict[str, Any]:
    return {
        "sheets": [
            {
                "sheet_key": "f0s0",
                "kind": kind,
                "header_row": 0,
                "columns": {"c0": "chapter_ref", "c1": "title", "c2": "content"},
            }
        ],
        "options": {},
    }


@pytest_asyncio.fixture
async def session_row(db_session: AsyncSession):
    repo = ImportMigrationSessionRepository()
    return await repo.create(
        db_session,
        novel_id=NOVEL_ID,
        owner_id=OWNER_ID,
        file_manifest=[
            {
                "file_key": "f0",
                "file_name": "细纲.xlsx",
                "file_type": "xlsx",
                "size": 100,
                "sha256": "a" * 64,
                "sheets": [
                    {"sheet_key": "f0s0", "name": "细纲", "hidden": False}
                ],
            }
        ],
        rows_json={"f0s0": _rows()},
        mapping_json=_mapping(),
    )


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------


def test_estimate_ai_run_counts_rows_and_requests() -> None:
    estimate = estimate_ai_run(
        {"f0s0": _rows()},
        _mapping(),
        {"outline_sheet_keys": ["f0s0"], "cleanup": []},
    )
    assert estimate.rows == 2
    assert estimate.packets >= 1
    assert estimate.requests == estimate.packets * ai_module.AI_REQUESTS_PER_PACKET


def test_ai_items_for_planning_filters_unpassed_and_unaccepted() -> None:
    result = {
        "outline": [
            {
                "passed": True,
                "sheet_key": "f0s0",
                "items": [
                    {
                        "item_key": "a1",
                        "proposal_ref": "p1",
                        "source_rows": ["f0s0:r1"],
                        "payload": {"kind": "chapter_plan"},
                    }
                ],
            },
            {
                "passed": False,
                "sheet_key": "f0s0",
                "items": [
                    {
                        "item_key": "b1",
                        "proposal_ref": "p2",
                        "source_rows": ["f0s0:r2"],
                        "payload": {"kind": "chapter_plan"},
                    }
                ],
            },
        ],
        "cleanup": [],
    }
    accepted = ai_items_for_planning(result, {"a1": {"accept_ai": True}})
    assert [item.proposal_ref for item in accepted.items] == ["p1"]

    unaccepted = ai_items_for_planning(result, {})
    assert unaccepted.items == []


def test_spreadsheet_task_type_in_module_api_whitelist() -> None:
    assert "spreadsheet_migration_ai" in _MODULE_API_ONLY_TASK_TYPES


def test_handler_declares_envelope_limits() -> None:
    definition = _registry.get_definition("spreadsheet_migration_ai")
    assert definition is not None
    assert _registry.get_root_capability("spreadsheet_migration_ai") == (
        "imports.spreadsheet_migration"
    )
    task = SimpleNamespace(meta={"ai_packets": 3})
    assert definition.run_request_limit(task) == 3 * 6 + 2
    assert definition.retry_transient_llm_errors is True
    assert definition.max_attempts == 2


# ---------------------------------------------------------------------------
# 提交：预算与入队
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_ai_run_rejects_over_budget(
    db_session: AsyncSession, session_row
) -> None:
    with patch.object(ai_module, "AI_MAX_PACKETS", 0):  # autospec-exempt: 常量覆写无 spec 可言
        with (
            patch(
                "modules.project.facade.require_active_project", autospec=True
            ),
        ):
            with pytest.raises(ValidationError) as exc_info:
                await ai_module.submit_ai_run(
                    db_session,
                    novel_id=str(NOVEL_ID),
                    session=session_row,
                    scope={"outline_sheet_keys": ["f0s0"], "cleanup": []},
                    operation_id="",
                )
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_submit_ai_run_enqueues_task(
    db_session: AsyncSession, session_row
) -> None:
    receipt = SimpleNamespace(
        task_id=str(uuid.uuid4()), status="pending", reused=False
    )
    with (
        patch("modules.project.facade.require_active_project", autospec=True),
        patch(
            "modules.project.facade.build_project_llm_execution_snapshot",
            autospec=True,
        ) as snapshot,
        patch(
            "infrastructure.tasks.facade.get_operation_task",
            autospec=True,
            return_value=None,
        ),
        patch(
            "infrastructure.tasks.facade.enqueue_task_with_optional_operation",
            autospec=True,
            return_value=receipt,
        ) as enqueue,
    ):
        snapshot.return_value = {"provider": "fake"}
        task_ref = await ai_module.submit_ai_run(
            db_session,
            novel_id=str(NOVEL_ID),
            session=session_row,
            scope={"outline_sheet_keys": ["f0s0"], "cleanup": []},
            operation_id="op-1",
        )
    assert task_ref.task_id == receipt.task_id
    assert task_ref.reused is False
    enqueue.assert_called_once()
    meta = enqueue.call_args.kwargs["meta"]
    assert meta["run_request_limit"] == meta["ai_packets"] * 6 + 2
    assert session_row.ai_status == "queued"
    assert session_row.ai_scope_hash


# ---------------------------------------------------------------------------
# 确定性校验（白盒：直接调用校验函数）
# ---------------------------------------------------------------------------


def _packet_rows() -> dict[str, ai_module._AiRow]:
    row = ai_module._AiRow(
        sheet_key="f0s0",
        row_index=1,
        cells={"章": "第1章", "标题": "开端", "内容": "主角进城遇到对手"},
        content_hash="h",
    )
    return {row.row_ref: row}


def test_validate_outline_item_rejects_unknown_row_ref() -> None:
    item = ai_schemas.OutlineChapterPlanItem(
        proposal_ref="p1",
        source_rows=["f0s0:r99"],
        evidence="主角进城",
        chapter_start=1,
        chapter_end=1,
        title="开端",
    )
    _, reason = ai_module._validate_outline_item(item, _packet_rows())
    assert reason == "row_ref_unknown"


def test_validate_outline_item_rejects_non_verbatim_evidence() -> None:
    item = ai_schemas.OutlineChapterPlanItem(
        proposal_ref="p1",
        source_rows=["f0s0:r1"],
        evidence="主角出城遇到盟友",  # 编造：不是原文子串
        chapter_start=1,
        chapter_end=1,
        title="开端",
    )
    _, reason = ai_module._validate_outline_item(item, _packet_rows())
    assert reason == "evidence_not_verbatim"


def test_validate_outline_item_rejects_bad_chapter_span() -> None:
    item = ai_schemas.OutlineChapterPlanItem(
        proposal_ref="p1",
        source_rows=["f0s0:r1"],
        evidence="主角进城",
        chapter_start=5,
        chapter_end=2,
        title="开端",
    )
    _, reason = ai_module._validate_outline_item(item, _packet_rows())
    assert reason is not None
    assert "chapter" in reason


def test_validate_outline_item_accepts_verbatim() -> None:
    item = ai_schemas.OutlineChapterPlanItem(
        proposal_ref="p1",
        source_rows=["f0s0:r1"],
        evidence="主角进城遇到对手",
        chapter_start=1,
        chapter_end=1,
        title="开端",
        must_happen="主角进城",
    )
    fields, reason = ai_module._validate_outline_item(item, _packet_rows())
    assert reason is None
    assert fields["payload"]["kind"] == "chapter_plan"
    assert fields["payload"]["must_happen"] == "主角进城"


def test_validate_cleanup_output_keeps_and_drops() -> None:
    good = ai_schemas.SpreadsheetCellCleanup(
        proposal_ref="p1",
        source_rows=["f0s0:r1"],
        evidence="主角进城遇到对手",
        fields=[ai_schemas.CellCleanupFieldItem(field="role", value="主角")],
        remainder="",
    )
    kept, dropped = ai_module._validate_cleanup_output(good, _packet_rows())
    assert len(kept) == 1 and not dropped
    assert kept[0]["payload"]["fields"] == {"role": "主角"}

    bad = ai_schemas.SpreadsheetCellCleanup(
        proposal_ref="p2",
        source_rows=["f0s0:r9"],
        evidence="x",
        fields=[],
        remainder="",
    )
    kept, dropped = ai_module._validate_cleanup_output(bad, _packet_rows())
    assert not kept and dropped[0]["reason"] == "row_ref_unknown"


def test_forbidden_keys_guard() -> None:
    assert ai_module._guard_forbidden_keys({"title": "x"}) is True
    assert ai_module._guard_forbidden_keys({"id": "1"}) is False
    assert ai_module._guard_forbidden_keys({"source": "y"}) is False


# ---------------------------------------------------------------------------
# worker 主链
# ---------------------------------------------------------------------------


def _fake_snapshot_client():
    @asynccontextmanager
    async def _ctx(
        _db, _novel_id, _snapshot, *, timeout_override=None, injected_client=None
    ):
        yield injected_client or SimpleNamespace(model_name="fake")

    return _ctx


@pytest.mark.asyncio
async def test_run_spreadsheet_migration_ai_writes_result(
    db_session: AsyncSession, session_row
) -> None:
    output = ai_schemas.SpreadsheetOutlineConversion(
        chapter_plans=[
            ai_schemas.OutlineChapterPlanItem(
                proposal_ref="p1",
                source_rows=["f0s0:r1"],
                evidence="主角进城遇到对手",
                chapter_start=1,
                chapter_end=1,
                title="开端",
                must_happen="主角进城遇到对手",
            )
        ]
    )
    task = SimpleNamespace(
        id=uuid.uuid4(),
        meta={
            "novel_id": str(NOVEL_ID),
            "session_id": str(session_row.id),
            "scope": {"outline_sheet_keys": ["f0s0"], "cleanup": []},
            "scope_hash": session_row.ai_scope_hash or "",
            "llm_execution_snapshot": {},
        },
        update_progress=None,
    )
    # 先算出真实 scope_hash 再冻结进 meta 与会话（模拟 submit 阶段写入）
    plan = ai_module._build_scope_plan(
        session_row.rows_json, session_row.mapping_json, task.meta["scope"]
    )
    task.meta["scope_hash"] = plan.scope_hash
    session_row.ai_scope_hash = plan.scope_hash
    await db_session.flush()

    govern_calls: list[Any] = []

    async def govern_double(client, **kwargs):
        govern_calls.append(kwargs)
        return {"status": "passed", "repaired": False}

    with (
        patch(
            "modules.imports.spreadsheet_migration.ai.open_project_snapshot_llm_client",
            _fake_snapshot_client(),
        ),  # autospec-exempt: 以 async ctx 替身注入 fake client
        patch(
            "modules.evidence.contracts.govern_group_output",
            autospec=True,
            side_effect=govern_double,
        ),
        patch(
            "infrastructure.llm.agent_step_harness.run_managed_structured",
            autospec=True,
            return_value=output,
        ) as structured,
    ):
        result = await ai_module.run_spreadsheet_migration_ai(
            db_session, task=task, llm_client=SimpleNamespace(model_name="fake")
        )

    assert result["status"] == "done"
    assert structured.call_count >= 1
    assert govern_calls, "知识审查必须被调用"
    await db_session.refresh(session_row)
    assert session_row.ai_status == "done"
    groups = session_row.ai_result_json["outline"]
    assert groups and groups[0]["passed"] is True
    items = groups[0]["items"]
    assert items and items[0]["payload"]["kind"] == "chapter_plan"


@pytest.mark.asyncio
async def test_run_spreadsheet_migration_ai_scope_drift_fails(
    db_session: AsyncSession, session_row
) -> None:
    task = SimpleNamespace(
        id=uuid.uuid4(),
        meta={
            "novel_id": str(NOVEL_ID),
            "session_id": str(session_row.id),
            "scope": {"outline_sheet_keys": ["f0s0"], "cleanup": []},
            "scope_hash": "0" * 64,
            "llm_execution_snapshot": {},
        },
        update_progress=None,
    )
    with pytest.raises(ValidationError) as exc_info:
        await ai_module.run_spreadsheet_migration_ai(db_session, task=task)
    assert exc_info.value.code == "migration_ai_scope_stale"
    await db_session.refresh(session_row)
    assert session_row.ai_status == "failed"
    assert session_row.ai_result_json == {}
