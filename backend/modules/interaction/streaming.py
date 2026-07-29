"""Owner-scoped persisted SSE projection for interaction attempts."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from time import monotonic

from sqlalchemy import select

from core.database import get_manager
from modules.interaction.models import (
    InteractionGenerationAttempt,
    InteractionJourney,
)

TERMINAL_ATTEMPT_STATUSES = {
    "awaiting_continue",
    "completed",
    "failed",
    "cancelled",
    "stopped",
}


def _event(
    event: str,
    data: dict,
    *,
    event_id: int | None = None,
) -> str:
    parts = []
    if event_id is not None:
        parts.append(f"id: {event_id}")
    parts.append(f"event: {event}")
    parts.append(
        "data: "
        + json.dumps(
            data,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return "\n".join(parts) + "\n\n"


async def stream_attempt_events(
    *,
    owner_id: uuid.UUID,
    journey_id: uuid.UUID,
    attempt_id: uuid.UUID,
    offset: int,
) -> AsyncIterator[str]:
    current_offset = max(0, offset)
    last_status: str | None = None
    last_keepalive = monotonic()
    while True:
        async with get_manager().session_factory() as db:
            row = (
                await db.execute(
                    select(
                        InteractionGenerationAttempt.visible_text,
                        InteractionGenerationAttempt.visible_offset,
                        InteractionGenerationAttempt.status,
                        InteractionGenerationAttempt.finish_reason,
                        InteractionGenerationAttempt.error_kind,
                        InteractionGenerationAttempt.error_message,
                        InteractionGenerationAttempt.result_node_id,
                    )
                    .join(
                        InteractionJourney,
                        InteractionJourney.id
                        == InteractionGenerationAttempt.journey_id,
                    )
                    .where(
                        InteractionJourney.id == journey_id,
                        InteractionJourney.owner_id == owner_id,
                        InteractionJourney.novel_id
                        == InteractionGenerationAttempt.novel_id,
                        InteractionGenerationAttempt.id == attempt_id,
                        InteractionGenerationAttempt.journey_id == journey_id,
                        InteractionGenerationAttempt.owner_id == owner_id,
                    )
                )
            ).one_or_none()
        if row is None:
            yield _event("error", {"code": "not_found"})
            return
        visible_text = str(row.visible_text or "")
        persisted_offset = int(row.visible_offset or 0)
        if current_offset > persisted_offset:
            current_offset = 0
            yield _event("reset", {"offset": 0})
        if persisted_offset > current_offset:
            text = visible_text[current_offset:persisted_offset]
            current_offset = persisted_offset
            yield _event(
                "chunk",
                {"offset": current_offset, "text": text},
                event_id=current_offset,
            )
        status = str(row.status)
        if status != last_status:
            last_status = status
            yield _event(
                "status",
                {
                    "status": status,
                    "offset": persisted_offset,
                    "finish_reason": row.finish_reason,
                    "error_kind": row.error_kind,
                    "error_message": row.error_message,
                    "result_node_id": (
                        str(row.result_node_id) if row.result_node_id else None
                    ),
                },
                event_id=current_offset,
            )
        if status in TERMINAL_ATTEMPT_STATUSES:
            yield _event(
                "done",
                {
                    "status": status,
                    "offset": persisted_offset,
                    "result_node_id": (
                        str(row.result_node_id) if row.result_node_id else None
                    ),
                },
                event_id=current_offset,
            )
            return
        now = monotonic()
        if now - last_keepalive >= 15:
            yield ": keep-alive\n\n"
            last_keepalive = now
        await asyncio.sleep(0.35)
