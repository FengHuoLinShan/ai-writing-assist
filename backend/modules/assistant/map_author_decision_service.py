"""Read an author statement bound to one persisted Assistant turn."""

from __future__ import annotations

import hashlib
import uuid

from sqlalchemy import select

from core.errors import ConflictError, NotFoundError
from modules.assistant.models import AssistantMessage, AssistantRun
from modules.project.facade import get_any_project_context, require_active_project
from modules.world.map_structure_schemas import MapAuthorDecision


async def read_map_author_decision(
    db,
    novel_id: str,
    run_id: str,
    *,
    message_id: str | None = None,
) -> MapAuthorDecision:
    """Return only the verified message identity and exact-text digest."""
    await require_active_project(db, novel_id, allow_demo_readonly=False)
    project = await get_any_project_context(db, novel_id)
    run = await db.scalar(
        select(AssistantRun).where(
            AssistantRun.novel_id == uuid.UUID(str(novel_id)),
            AssistantRun.id == uuid.UUID(str(run_id)),
        )
    )
    if (
        project is None
        or project.project_kind != "author"
        or run is None
        or run.mode != "author"
        or run.session_id is None
        or run.task_id is None
        or str(run.owner_id) != str(project.owner_id)
    ):
        raise NotFoundError("没有找到当前作品中可核验的作者安排")

    query = select(AssistantMessage).where(
        AssistantMessage.novel_id == uuid.UUID(str(novel_id)),
        AssistantMessage.session_id == run.session_id,
        AssistantMessage.task_id == run.task_id,
        AssistantMessage.role == "author",
        AssistantMessage.kind == "message",
    )
    if message_id is not None:
        query = query.where(AssistantMessage.id == uuid.UUID(str(message_id)))
    message = await db.scalar(
        query.order_by(AssistantMessage.created_at.desc(), AssistantMessage.id.desc())
    )
    if message is None:
        raise ConflictError("助手运行中没有可核验的作者安排来源")
    if message_id is not None and str(message.id) != str(message_id):
        raise ConflictError("作者安排消息不属于这次助手运行")
    return MapAuthorDecision(
        origin="assistant",
        run_id=run.id,
        message_id=message.id,
        statement_hash=hashlib.sha256(message.content.encode("utf-8")).hexdigest(),
    )


__all__ = ["read_map_author_decision"]
