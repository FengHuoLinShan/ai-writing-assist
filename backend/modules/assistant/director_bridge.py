"""Validate an ordinary author Assistant turn before a Director-budget bridge."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select

from infrastructure.tasks.models import AsyncTask
from modules.assistant.models import AssistantRun


async def is_author_turn_run(db, *, novel_id: str, run_id: str, owner_id: str) -> bool:
    try:
        run_uuid, novel_uuid, owner_uuid = map(UUID, (run_id, novel_id, owner_id))
    except (TypeError, ValueError):
        return False
    run = await db.scalar(
        select(AssistantRun).where(
            AssistantRun.id == run_uuid,
            AssistantRun.novel_id == novel_uuid,
            AssistantRun.owner_id == owner_uuid,
        )
    )
    if (
        run is None
        or run.mode != "author"
        or run.session_id is None
        or run.task_id is None
    ):
        return False
    task = await db.get(AsyncTask, run.task_id)
    return bool(task and task.task_type == "assistant_turn")
