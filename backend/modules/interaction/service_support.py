"""Shared deterministic contracts and helpers for InteractionService."""

from __future__ import annotations

import hashlib
import json
import re
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from core.errors import ValidationError
from infrastructure.tasks.facade import (
    enqueue_coalesced_task,
)
from modules.interaction.models import (
    InteractionJourney,
    InteractionMessageNode,
)

MAX_ACTIVE_STORY_ATTEMPTS = 8


RECENT_MESSAGE_LIMIT = 20


SUMMARY_TRIGGER_TOKENS = 16_000


SEE_SEA_HEARTBEAT_TTL_SECONDS = 60


SEE_SEA_MANUAL_CLAIM_SECONDS = 1


def estimate_story_tokens(text: str) -> int:
    # Conservative for Chinese-heavy prose; exact provider tokenizers remain
    # capability-profile concerns rather than user settings.
    return max(1, (len(text) + 1) // 2)


def path_hash(nodes: list[InteractionMessageNode]) -> str:
    payload = "|".join(str(node.id) for node in nodes)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


async def _enqueue_overview_refresh_task(
    db: AsyncSession,
    *,
    journey: InteractionJourney,
    path: list[InteractionMessageNode],
    snapshot: dict,
) -> str:
    contract = await enqueue_coalesced_task(
        db,
        task_type="interaction_summary_refresh",
        novel_id=str(journey.novel_id),
        scope=("interaction_summary", str(journey.id)),
        mode="one_pending_follower",
        meta={
            "novel_id": str(journey.novel_id),
            "journey_id": str(journey.id),
            "path_hash": path_hash(path),
            "selected_leaf_node_id": str(path[-1].id),
            "started_overview_epoch": journey.overview_epoch,
            "llm_execution_snapshot": dict(snapshot),
        },
    )
    journey.summary_refresh_task_id = uuid.UUID(contract.task_id)
    return contract.task_id


def _summary_compressible_prefix_end(
    nodes: list[InteractionMessageNode],
) -> int:
    """Return the exclusive end of the oldest prefix safe to summarize."""
    if len(nodes) <= 2:
        return 0
    protected_tokens = 0
    index = len(nodes)
    while index > 0 and (
        protected_tokens < SUMMARY_TRIGGER_TOKENS or len(nodes) - index < 2
    ):
        index -= 1
        protected_tokens += max(1, nodes[index].token_estimate)
    if index > 0 and nodes[index].role == "assistant" and nodes[index - 1].role == "user":
        index -= 1
    return index


def _parse_uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} 格式无效") from exc


def _fallback_title(opening_text: str) -> str:
    patterns = (
        r"《([^》]{1,40})》",
        r"(?:进入|来到|身处)([^，。！？\n]{1,30}?)(?:世界|宇宙)",
        r"([^，。！？\n]{1,24}?世界)",
    )
    for pattern in patterns:
        match = re.search(pattern, opening_text)
        if match:
            world = match.group(1).strip("“”\"' ")
            if world:
                return f"{world} · 新旅程"[:255]
    return "新旅程"


def persisted_fingerprint(value) -> str:
    """RP frozen fingerprints retain v1 JSON spaces, Unicode and default=str bytes."""
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
