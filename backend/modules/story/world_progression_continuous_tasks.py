"""Free outbox worker for a successfully committed Evolution chapter read."""

from __future__ import annotations

from infrastructure.tasks.registry import task_handler
from modules.story.world_progression_continuous import (
    _READ_COMMIT_CHECK_TASK,
    consider_progression_after_chapter_commit,
)


@task_handler(_READ_COMMIT_CHECK_TASK, recovery_policy="restart_origin")
async def handle_progression_chapter_commit_check(db, task) -> dict:
    novel_id = str((task.meta or {}).get("novel_id") or "")
    if not novel_id or novel_id != str(task.novel_id):
        raise ValueError("章节推进检查缺少作品身份")
    return await consider_progression_after_chapter_commit(
        db, novel_id=novel_id, latest_effective_chapter=0
    )
