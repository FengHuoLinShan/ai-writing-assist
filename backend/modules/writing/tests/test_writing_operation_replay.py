"""写作生成 operation 幂等用例（BR-0b 交接 P0-4「确认回包丢失后重复点击」）。

同 operation_id + 同请求指纹的重放必须返回原任务回执，不得生成第二个任务；
同 operation_id + 不同请求必须拒绝，防止键串用。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from core.errors import ConflictError
from infrastructure.tasks.models import AsyncTask
from modules.evidence.contracts import ContextConfirmationRequest
from modules.evidence.facade import bind_confirmed_action_result, confirm_context
from modules.writing.schemas import WritingGenerateRequest
from modules.writing.services import WritingGenerationService


async def _confirmed_generation(db_session, novel_id: str, chapter: int):
    confirmation = await confirm_context(
        db_session,
        ContextConfirmationRequest(
            novel_id=novel_id,
            action="writing.generate",
            task=f"operation 重放第 {chapter} 章",
            scope="chapter",
            chapter_index=chapter,
        ),
    )
    await bind_confirmed_action_result(
        db_session,
        novel_id=novel_id,
        confirmation_id=confirmation.id,
        result_type="task",
        result_id=str(uuid.uuid4()),
        status="running",
    )
    return confirmation


async def _task_count(db_session, novel_id: str) -> int:
    result = await db_session.execute(
        select(func.count(AsyncTask.id)).where(
            AsyncTask.novel_id == uuid.UUID(str(novel_id)),
            AsyncTask.task_type == "writing_generate",
        )
    )
    return int(result.scalar() or 0)


@pytest.mark.asyncio
async def test_submit_generation_replays_same_operation_without_second_task(
    db_session,
    test_project_id,
    monkeypatch,
) -> None:
    async def restore_settings(*_args, **_kwargs) -> dict:
        return {"llm": {"model": "frozen-model"}}

    monkeypatch.setattr(
        "modules.project.facade.restore_project_llm_execution_settings",
        restore_settings,
    )

    async def build_snapshot(*_args, **_kwargs) -> dict:
        return {"profile": {"model": "frozen-model"}}

    monkeypatch.setattr(
        "modules.project.facade.build_project_llm_execution_snapshot",
        build_snapshot,
    )
    confirmation = await _confirmed_generation(db_session, test_project_id, 2)
    operation_id = uuid.uuid4()
    service = WritingGenerationService()

    def _request(instruction: str) -> WritingGenerateRequest:
        return WritingGenerateRequest(
            novel_id=test_project_id,
            chapter_index=2,
            instruction=instruction,
            context_confirmation_id=confirmation.id,
            operation_id=operation_id,
        )

    first = await service.submit_generation(db_session, _request("第一版要求"))
    assert first["task_id"] == str(operation_id)
    assert await _task_count(db_session, test_project_id) == 1

    # 回包丢失后作者重试：同 operation + 同指纹 → 原回执，不产生第二个任务
    replay = await service.submit_generation(db_session, _request("第一版要求"))
    assert replay["task_id"] == first["task_id"]
    assert await _task_count(db_session, test_project_id) == 1

    # 同 operation + 不同请求 → 拒绝键串用
    with pytest.raises(ConflictError):
        await service.submit_generation(db_session, _request("改成了别的要求"))
    assert await _task_count(db_session, test_project_id) == 1
