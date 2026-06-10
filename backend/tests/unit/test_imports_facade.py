"""Unit tests for modules.imports.facade

覆盖 resume_deep_import 的 happy path、边界条件与异常路径。
所有外部依赖（任务队列）均通过 mock 隔离。
"""

from __future__ import annotations

import uuid
from unittest import mock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from infrastructure.tasks.models import AsyncTask
from modules.imports.facade import resume_deep_import

pytestmark = [pytest.mark.asyncio]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


async def _create_prev_task(
    db_session,
    *,
    meta: dict | None = None,
) -> AsyncTask:
    """在 db_session 中创建一个作为 prev_task 的 AsyncTask 记录。"""
    task = AsyncTask(
        id=uuid.uuid4(),
        task_type="deep_import",
        status="done",
        meta=meta,
    )
    db_session.add(task)
    await db_session.flush()
    return task


# ------------------------------------------------------------------
# resume_deep_import
# ------------------------------------------------------------------


@mock.patch("infrastructure.tasks.enqueuer.enqueue_task")
async def test_resume_deep_import_with_valid_prev_task_returns_new_task(
    mock_enqueue,
    db_session,
):
    """Happy path — 前一个任务存在且 meta 正常，成功提交 resume 任务。"""
    # Arrange
    prev_task = await _create_prev_task(
        db_session,
        meta={"novel_id": str(uuid.uuid4()), "start_chapter": 1, "end_chapter": 5},
    )
    prev_task_id = str(prev_task.id)
    new_task_id = str(uuid.uuid4())
    mock_enqueue.return_value = new_task_id

    # Act
    result = await resume_deep_import(db_session, prev_task_id)

    # Assert
    assert result["task_id"] == new_task_id
    assert result["status"] == "pending"
    assert "继续" in result["message"]

    mock_enqueue.assert_called_once()
    call_args, call_kwargs = mock_enqueue.call_args
    assert call_args[0] is db_session
    assert call_args[1] == "deep_import_resume"
    assert call_kwargs["meta"]["prev_task_id"] == prev_task_id
    assert call_kwargs["meta"]["start_chapter"] == 1
    assert call_kwargs["meta"]["end_chapter"] == 5


@mock.patch("infrastructure.tasks.enqueuer.enqueue_task")
async def test_resume_deep_import_with_none_meta_treats_as_empty_dict(
    mock_enqueue,
    db_session,
):
    """边界条件 — prev_task.meta 为 None 时，应退化为空 dict 并继续执行。"""
    # Arrange
    prev_task = await _create_prev_task(db_session, meta=None)
    prev_task_id = str(prev_task.id)
    new_task_id = str(uuid.uuid4())
    mock_enqueue.return_value = new_task_id

    # Act
    result = await resume_deep_import(db_session, prev_task_id)

    # Assert
    assert result["task_id"] == new_task_id
    assert result["status"] == "pending"

    call_kwargs = mock_enqueue.call_args.kwargs
    assert call_kwargs["meta"] == {"prev_task_id": prev_task_id}


@mock.patch("infrastructure.tasks.enqueuer.enqueue_task")
async def test_resume_deep_import_with_empty_meta_includes_prev_task_id(
    mock_enqueue,
    db_session,
):
    """边界条件 — prev_task.meta 为空 dict 时，结果 meta 应只包含 prev_task_id。"""
    # Arrange
    prev_task = await _create_prev_task(db_session, meta={})
    prev_task_id = str(prev_task.id)
    new_task_id = str(uuid.uuid4())
    mock_enqueue.return_value = new_task_id

    # Act
    result = await resume_deep_import(db_session, prev_task_id)

    # Assert
    assert result["task_id"] == new_task_id
    assert result["status"] == "pending"

    call_kwargs = mock_enqueue.call_args.kwargs
    assert call_kwargs["meta"] == {"prev_task_id": prev_task_id}


async def test_resume_deep_import_with_missing_prev_task_raises_404(
    db_session,
):
    """异常路径 — 当 prev_task_id 对应记录不存在时，应抛出 HTTP 404。"""
    # Arrange
    non_existent_id = str(uuid.uuid4())

    # Act & Assert
    with pytest.raises(HTTPException) as excinfo:
        await resume_deep_import(db_session, non_existent_id)

    assert excinfo.value.status_code == 404
    assert "not found" in excinfo.value.detail.lower()


async def test_resume_deep_import_with_invalid_uuid_raises_422(
    db_session,
):
    """异常路径 — prev_task_id 不是有效 UUID 时，parse_uuid 应抛出 HTTP 422。"""
    # Arrange
    invalid_id = "not-a-valid-uuid"

    # Act & Assert
    with pytest.raises(HTTPException) as excinfo:
        await resume_deep_import(db_session, invalid_id)

    assert excinfo.value.status_code == 422
