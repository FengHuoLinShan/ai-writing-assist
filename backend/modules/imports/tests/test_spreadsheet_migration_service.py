"""表格迁移会话服务测试（L4）。

world/story/AI facade 与解析/识别在本车道一律 autospec 替身（L8 换真实链路）。
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ConflictError, ValidationError
from modules.imports.models import ImportMigrationSession
from modules.imports.spreadsheet_migration.classify import (
    ColumnSuggestion,
    SheetSuggestion,
)
from modules.imports.spreadsheet_migration.parsing import ParsedSheet, ParsedUpload
from modules.imports.spreadsheet_migration.repository import (
    ImportMigrationSessionRepository,
)
from modules.imports.spreadsheet_migration.service import SpreadsheetMigrationService
from modules.story.outline_state.contracts import (
    StoryMigrationPlan,
    StoryMigrationReceipt,
)
from modules.world.contracts import (
    MigrationAppliedChange,
    WorldMigrationItemPlan,
    WorldMigrationPlan,
    WorldMigrationReceipt,
)

OWNER_ID = uuid.uuid4()
NOVEL_ID = uuid.uuid4()


def _upload(sheet_key: str = "f0s0", name: str = "人物") -> ParsedUpload:
    return ParsedUpload(
        file_key="f0",
        file_name="人物表.xlsx",
        file_type="xlsx",
        size=128,
        sha256="a" * 64,
        sheets=[
            ParsedSheet(
                sheet_key=sheet_key,
                file_key="f0",
                name=name,
                hidden=False,
                rows=[["姓名", "简介"], ["张三", "主角，剑客"], ["李四", "对手"]],
                warnings=[],
            )
        ],
    )


def _suggestion(sheet_key: str = "f0s0") -> SheetSuggestion:
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
        items=[
            WorldMigrationItemPlan(
                item_key="f0s0r1-zhang-san",
                kind="entity",
                action="create",
            ),
            WorldMigrationItemPlan(
                item_key="f0s0r2-li-si",
                kind="entity",
                action="conflict",
                conflicts=[],
                reason_code="field_conflict",
            ),
        ],
        validation_policy_active=False,
        fingerprint="world-fp-1",
    )


def _story_plan() -> StoryMigrationPlan:
    return StoryMigrationPlan(items=[], outline_action=None, fingerprint="story-fp-1")


def _world_receipt() -> WorldMigrationReceipt:
    return WorldMigrationReceipt(
        applied_changes=[
            MigrationAppliedChange(
                item_key="f0s0r1-zhang-san",
                kind="entity",
                target_id=str(uuid.uuid4()),
                operation="create",
                after_hash="h1",
            )
        ],
        entity_ids={"f0s0r1-zhang-san": str(uuid.uuid4())},
    )


@contextmanager
def _plan_facades():
    with (
        patch(
            "modules.world.facade.plan_author_migration_world",
            autospec=True,
        ) as world_plan,
        patch(
            "modules.story.outline_state.facade.plan_author_migration_structures",
            autospec=True,
        ) as story_plan,
    ):
        world_plan.return_value = _world_plan()
        story_plan.return_value = _story_plan()
        yield world_plan, story_plan


@contextmanager
def _apply_facades(world_receipt=None, story_receipt=None):
    with (
        patch(
            "modules.world.facade.apply_author_migration_world",
            autospec=True,
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
        world_apply.return_value = world_receipt or _world_receipt()
        story_apply.return_value = story_receipt or StoryMigrationReceipt()
        yield world_apply, story_apply


@contextmanager
def _parse_and_classify(upload: ParsedUpload | None = None, suggestion=None):
    # L1 未合入：parsers.parse_spreadsheet_file 在本分支尚不存在，autospec 无法
    # 替身缺失属性（create=True 与 autospec 互斥），故用 new= 显式替身；L8 换真实链路。
    parse_double = MagicMock(return_value=upload or _upload())
    with (
        patch(
            "modules.imports.parsers.parse_spreadsheet_file",
            parse_double,
            create=True,
        ) as parse,  # autospec-exempt: L1 未合入时属性不存在，new= 显式替身
        patch(
            "modules.imports.spreadsheet_migration.classify.classify_sheet",
            autospec=True,
        ) as classify_sheet,
    ):
        parse.return_value = upload or _upload()
        classify_sheet.return_value = suggestion or _suggestion()
        yield parse, classify_sheet


@pytest_asyncio.fixture
async def session_row(db_session: AsyncSession) -> ImportMigrationSession:
    """直接经 repository 建一个最小会话，供读取类用例复用。"""
    with _parse_and_classify():
        service = SpreadsheetMigrationService()
        return await service.create_session(
            db_session,
            novel_id=str(NOVEL_ID),
            owner_id=str(OWNER_ID),
            files=[("人物表.xlsx", b"fake-bytes")],
        )


@pytest.mark.asyncio
async def test_create_session_builds_manifest_and_mapping(
    db_session: AsyncSession,
) -> None:
    service = SpreadsheetMigrationService()
    with _parse_and_classify() as (parse, classify_sheet):
        session = await service.create_session(
            db_session,
            novel_id=str(NOVEL_ID),
            owner_id=str(OWNER_ID),
            files=[("人物表.xlsx", b"fake-bytes")],
        )
        parse.assert_called_once()
        classify_sheet.assert_called_once()

    assert session.status == "draft"
    assert session.revision == 1
    assert session.file_manifest[0]["file_name"] == "人物表.xlsx"
    assert session.file_manifest[0]["sheets"][0]["headers"] == ["姓名", "简介"]
    assert session.rows_json["f0s0"][1] == ["张三", "主角，剑客"]
    assert session.mapping_json["sheets"][0]["kind"] == "characters"
    assert session.mapping_json["sheets"][0]["columns"] == {"c0": "name", "c1": "summary"}


@pytest.mark.asyncio
async def test_create_session_rejects_extension_and_empty(
    db_session: AsyncSession,
) -> None:
    service = SpreadsheetMigrationService()
    with pytest.raises(ValidationError):
        await service.create_session(
            db_session,
            novel_id=str(NOVEL_ID),
            owner_id=str(OWNER_ID),
            files=[("chapter.xls", b"bytes")],
        )
    with pytest.raises(ValidationError):
        await service.create_session(
            db_session,
            novel_id=str(NOVEL_ID),
            owner_id=str(OWNER_ID),
            files=[("空.csv", b"")],
        )


@pytest.mark.asyncio
async def test_create_session_rejects_oversize(db_session: AsyncSession) -> None:
    service = SpreadsheetMigrationService()
    with pytest.raises(ValidationError) as exc_info:
        await service.create_session(
            db_session,
            novel_id=str(NOVEL_ID),
            owner_id=str(OWNER_ID),
            files=[("big.csv", b"x" * (10 * 1024 * 1024 + 1))],
        )
    assert exc_info.value.status_code == 413


@pytest.mark.asyncio
async def test_get_session_isolates_owner_and_novel(
    db_session: AsyncSession, session_row: ImportMigrationSession
) -> None:
    service = SpreadsheetMigrationService()
    got = await service.get_session(
        db_session,
        session_id=str(session_row.id),
        novel_id=str(NOVEL_ID),
        owner_id=str(OWNER_ID),
    )
    assert got.id == session_row.id

    with pytest.raises(Exception) as other_owner:
        await service.get_session(
            db_session,
            session_id=str(session_row.id),
            novel_id=str(NOVEL_ID),
            owner_id=str(uuid.uuid4()),
        )
    assert other_owner.value.status_code == 404
    with pytest.raises(Exception) as other_novel:
        await service.get_session(
            db_session,
            session_id=str(session_row.id),
            novel_id=str(uuid.uuid4()),
            owner_id=str(OWNER_ID),
        )
    assert other_novel.value.status_code == 404


@pytest.mark.asyncio
async def test_save_mapping_uses_revision_cas(
    db_session: AsyncSession, session_row: ImportMigrationSession
) -> None:
    service = SpreadsheetMigrationService()
    mapping_sheets = session_row.mapping_json["sheets"]
    options = session_row.mapping_json["options"]
    with pytest.raises(ConflictError):
        await service.save_mapping(
            db_session,
            session=session_row,
            expected_revision=99,
            sheets=mapping_sheets,
            options=options,
        )
    with _plan_facades():
        updated = await service.save_mapping(
            db_session,
            session=session_row,
            expected_revision=1,
            sheets=mapping_sheets,
            options=options,
        )
    assert updated.revision == 2
    assert updated.preview_hash


@pytest.mark.asyncio
async def test_save_mapping_rejects_invalid_target(
    db_session: AsyncSession, session_row: ImportMigrationSession
) -> None:
    service = SpreadsheetMigrationService()
    sheets = [
        {
            "sheet_key": "f0s0",
            "kind": "characters",
            "header_row": 0,
            "columns": {"c0": "source_name"},
        }
    ]
    with pytest.raises(ValidationError):
        await service.save_mapping(
            db_session,
            session=session_row,
            expected_revision=1,
            sheets=sheets,
            options={"written_chapter_policy": "reference_only"},
        )


@pytest.mark.asyncio
async def test_get_rows_after_apply_returns_410(
    db_session: AsyncSession, session_row: ImportMigrationSession
) -> None:
    session_row.status = "applied"
    session_row.rows_json = {}
    await db_session.flush()
    service = SpreadsheetMigrationService()
    with pytest.raises(ConflictError) as exc_info:
        await service.get_rows(
            session=session_row, sheet_key="f0s0", offset=0, limit=50
        )
    assert exc_info.value.status_code == 410


@pytest.mark.asyncio
async def test_apply_rejects_stale_preview_hash(
    db_session: AsyncSession, session_row: ImportMigrationSession
) -> None:
    service = SpreadsheetMigrationService()
    with _plan_facades():
        with pytest.raises(ConflictError) as exc_info:
            await service.apply_session(
                db_session,
                session=session_row,
                expected_preview_hash="0" * 64,
                authorized_by=str(OWNER_ID),
            )
        assert exc_info.value.code == "migration_preview_stale"
        assert exc_info.value.context["preview_hash"]


@pytest.mark.asyncio
async def test_apply_persists_receipt_and_clears_rows(
    db_session: AsyncSession, session_row: ImportMigrationSession
) -> None:
    service = SpreadsheetMigrationService()
    with _plan_facades(), _apply_facades() as (world_apply, story_apply):
        await service.save_mapping(
            db_session,
            session=session_row,
            expected_revision=1,
            sheets=session_row.mapping_json["sheets"],
            options=session_row.mapping_json["options"],
        )
        assert session_row.preview_hash
        _result = await service.apply_session(
            db_session,
            session=session_row,
            expected_preview_hash=session_row.preview_hash,
            authorized_by=str(OWNER_ID),
        )
        world_apply.assert_called_once()
        story_apply.assert_called_once()
    assert _result["created"] == 1
    assert session_row.status == "applied"
    assert session_row.applied_at is not None
    assert session_row.rows_json == {}
    assert session_row.receipt_json["world"]["entity_ids"]
    # apply 之后再次 apply 被拒绝
    with pytest.raises(ConflictError) as rejected:
        await service.apply_session(
            db_session,
            session=session_row,
            expected_preview_hash=session_row.preview_hash or "0" * 64,
            authorized_by=str(OWNER_ID),
        )
    assert rejected.value.code == "migration_already_applied"


@pytest.mark.asyncio
async def test_rollback_requires_applied_then_marks_status(
    db_session: AsyncSession, session_row: ImportMigrationSession
) -> None:
    service = SpreadsheetMigrationService()
    with pytest.raises(ConflictError):
        await service.rollback_session(db_session, session=session_row, dry_run=True)

    from modules.world.contracts import MigrationRollbackResult

    with _plan_facades(), _apply_facades():
        await service.save_mapping(
            db_session,
            session=session_row,
            expected_revision=1,
            sheets=session_row.mapping_json["sheets"],
            options=session_row.mapping_json["options"],
        )
        await service.apply_session(
            db_session,
            session=session_row,
            expected_preview_hash=session_row.preview_hash,
            authorized_by=str(OWNER_ID),
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
        patch(
            "modules.project.facade.require_active_project_exclusive",
            autospec=True,
        ),
    ):
        story_rollback.return_value = MigrationRollbackResult(
            reverted=["f0s0r1-zhang-san"], kept=[]
        )
        world_rollback.return_value = MigrationRollbackResult(reverted=[], kept=[])
        result = await service.rollback_session(
            db_session, session=session_row, dry_run=False
        )
        story_rollback.assert_called_once()
        world_rollback.assert_called_once()

    assert result["revertible"][0]["item_key"] == "f0s0r1-zhang-san"
    assert session_row.status == "rolled_back"
    assert session_row.rolled_back_at is not None


@pytest.mark.asyncio
async def test_delete_session_removes_row(
    db_session: AsyncSession, session_row: ImportMigrationSession
) -> None:
    service = SpreadsheetMigrationService()
    session_id = str(session_row.id)
    await service.delete_session(db_session, session=session_row)
    repo = ImportMigrationSessionRepository()
    assert (
        await repo.get(
            db_session,
            uuid.UUID(session_id),
            novel_id=NOVEL_ID,
            owner_id=OWNER_ID,
        )
        is None
    )
