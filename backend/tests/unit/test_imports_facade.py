"""Unit tests for modules.imports.facade

覆盖 deep import facade 的 happy path、边界条件与异常路径。
"""

from __future__ import annotations

import uuid
from unittest import mock

import pytest

from infrastructure.tasks.models import AsyncTask
from modules.imports.contracts import TaskNotFoundError
from modules.imports.facade import (
    abandon_deep_import,
    resume_deep_import,
    start_deep_import,
)

pytestmark = [pytest.mark.asyncio]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


async def _create_prev_task(
    db_session,
    *,
    task_type: str = "deep_import",
    status: str = "running",
    meta: dict | None = None,
    result: dict | None = None,
) -> AsyncTask:
    """在 db_session 中创建一个作为 prev_task 的 AsyncTask 记录。"""
    recovery_flags = {
        "interrupted": True,
        "recoverable": True,
        "recovery_required": True,
    }
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type=task_type,
        status=status,
        meta=(
            meta
            if meta is not None
            else {"novel_id": str(uuid.uuid4()), **recovery_flags}
        ),
        result=result if result is not None else dict(recovery_flags),
    )
    db_session.add(task)
    await db_session.flush()
    return task


# ------------------------------------------------------------------
# start_deep_import
# ------------------------------------------------------------------


@mock.patch("modules.imports.facade._orchestrator")
async def test_start_deep_import_duplicate_requires_confirmation_without_enqueue(
    mock_orchestrator,
    db_session,
):
    """重复导入默认只返回确认要求，不应提前把 deep_import 任务入队。"""
    warning = "第 1-5 章已有数据。重新导入将覆盖现有数据。是否继续？"
    expected = {
        "workflow_id": None,
        "task_id": None,
        "status": "requires_confirmation",
        "requires_confirmation": True,
        "warning": warning,
        "message": warning,
    }
    mock_orchestrator.start = mock.AsyncMock(return_value=expected)
    novel_id = str(uuid.uuid4())

    result = await start_deep_import(
        db_session,
        novel_id=novel_id,
        start_chapter=1,
        end_chapter=5,
    )

    assert result == expected
    assert result["status"] == "requires_confirmation"
    assert result["requires_confirmation"] is True
    assert "覆盖现有数据" in result["warning"]
    assert result["task_id"] is None
    mock_orchestrator.start.assert_awaited_once_with(
        db_session,
        novel_id,
        1,
        5,
        force=False,
    )


@mock.patch("modules.imports.facade._orchestrator")
async def test_start_deep_import_force_enqueues_after_duplicate_confirmation(
    mock_orchestrator,
    db_session,
):
    """用户确认覆盖后，force=True 才允许创建 deep_import 任务。"""
    task_id = str(uuid.uuid4())
    novel_id = str(uuid.uuid4())
    expected = {
        "workflow_id": task_id,
        "task_id": task_id,
        "status": "pending",
        "requires_confirmation": False,
        "message": "深度导入任务已提交（第1-5章）",
    }
    mock_orchestrator.start = mock.AsyncMock(return_value=expected)

    result = await start_deep_import(
        db_session,
        novel_id=novel_id,
        start_chapter=1,
        end_chapter=5,
        force=True,
    )

    assert result == expected
    assert result["task_id"] == task_id
    assert result["status"] == "pending"
    assert result["requires_confirmation"] is False
    assert "warning" not in result

    mock_orchestrator.start.assert_awaited_once_with(
        db_session,
        novel_id,
        1,
        5,
        force=True,
    )


# ------------------------------------------------------------------
# resume_deep_import
# ------------------------------------------------------------------


async def test_resume_deep_import_with_valid_prev_task_reuses_original_task(
    db_session,
):
    """Happy path — 恢复时复用原 deep_import 任务，不创建 resume 任务。"""
    # Arrange
    prev_task = await _create_prev_task(
        db_session,
        meta={
            "novel_id": str(uuid.uuid4()),
            "start_chapter": 1,
            "end_chapter": 5,
            "recovery_required": True,
            "recoverable": True,
            "interrupted": True,
        },
    )
    prev_task_id = str(prev_task.id)

    # Act
    result = await resume_deep_import(db_session, prev_task_id)

    # Assert
    assert result["task_id"] == prev_task_id
    assert result["workflow_id"] == prev_task_id
    assert result["status"] == "pending"
    assert prev_task.status == "pending"
    assert prev_task.result["recovery_required"] is False
    assert prev_task.meta["recovery_required"] is False


async def test_abandon_deep_import_with_valid_task_cancels_original_task(
    db_session,
):
    """Happy path — 放弃恢复会取消原任务并返回 no-op 清理摘要。"""
    # Arrange
    prev_task = await _create_prev_task(db_session)
    prev_task_id = str(prev_task.id)

    # Act
    result = await abandon_deep_import(db_session, prev_task_id)

    # Assert
    assert result["task_id"] == prev_task_id
    assert result["status"] == "cancelled"
    assert result["cleanup_summary"]["deprecated_scenes"] == 0
    assert result["cleanup_summary"]["hard_deleted_assets"] == 0
    assert prev_task.status == "cancelled"
    assert prev_task.finished_at is not None


async def test_resume_deep_import_with_missing_prev_task_raises_404(
    db_session,
):
    """异常路径 — 当 prev_task_id 对应记录不存在时，应抛出 TaskNotFoundError。"""
    # Arrange
    non_existent_id = str(uuid.uuid4())

    # Act & Assert
    with pytest.raises(TaskNotFoundError) as excinfo:
        await resume_deep_import(db_session, non_existent_id)

    assert excinfo.value.task_id == non_existent_id


async def test_resume_deep_import_with_invalid_uuid_raises_422(
    db_session,
):
    """异常路径 — prev_task_id 不是有效 UUID 时，parse_uuid 应抛出 HTTP 422。"""
    # Arrange
    invalid_id = "not-a-valid-uuid"

    # Act & Assert
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as excinfo:
        await resume_deep_import(db_session, invalid_id)

    assert excinfo.value.status_code == 422
