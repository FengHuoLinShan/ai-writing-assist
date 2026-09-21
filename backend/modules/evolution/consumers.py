"""派生消费者有效性缝（V4 G2 / 验收 T17）。

建议不持有独立事实（A 审计边界）：它的"有效资格"来自所声称的来源指纹
是否仍是当前已索引的来源。原文撤回/修改后，证据索引的 requested 与
indexed 指纹分叉——旧建议立即失去有效资格，历史记录仍可查看（失效不
删历史）。

world 知识与地图册资产的有效性缝仍属 V/MI 系列（见
``invalidation.UNSUPPORTED_CONSUMERS``），不以本模块冒充全量接线。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.evidence.indexing.models import RagIndexState
from shared.utils import parse_uuid

ValidityVerdict = Literal["valid", "stale", "unknown"]


class SuggestionValidity(BaseModel):
    """一条建议（或任何携带来源指纹的派生物）的当前有效资格。"""

    model_config = ConfigDict(extra="forbid")

    verdict: ValidityVerdict
    claimed_hash: str | None = None
    indexed_hash: str | None = None
    requested_hash: str | None = None
    detail: str = ""


async def check_suggestion_validity(
    db: AsyncSession,
    novel_id: str,
    *,
    chapter_index: int,
    claimed_hash: str | None,
    content_mode: str = "working",
) -> SuggestionValidity:
    """按证据索引指纹判定来源是否仍然有效（T17）。

    - ``valid``：声称指纹 == 当前已索引指纹，且无待处理的新请求；
    - ``stale``：来源已变化（请求指纹分叉或与声称不符）——立即失去
      有效资格，历史可查；
    - ``unknown``：该章尚无索引状态，无法证明有效。
    """
    state = (
        await db.execute(
            select(RagIndexState).where(
                RagIndexState.novel_id == parse_uuid(novel_id, "novel_id"),
                RagIndexState.chapter_index == chapter_index,
                RagIndexState.content_mode == content_mode,
            )
        )
    ).scalar_one_or_none()
    if state is None:
        return SuggestionValidity(
            verdict="unknown",
            claimed_hash=claimed_hash,
            detail="该章尚无索引状态，无法证明来源有效",
        )
    requested = state.requested_hash
    indexed = state.indexed_hash
    if requested is not None and (indexed is None or indexed != requested):
        # 新来源已请求、尚未完成重建：任何旧来源的派生物立即失效。
        return SuggestionValidity(
            verdict="stale",
            claimed_hash=claimed_hash,
            indexed_hash=indexed,
            requested_hash=requested,
            detail="来源已变化待重建：旧建议立即失效，历史可查看",
        )
    if claimed_hash is not None and indexed is not None and claimed_hash != indexed:
        return SuggestionValidity(
            verdict="stale",
            claimed_hash=claimed_hash,
            indexed_hash=indexed,
            requested_hash=requested,
            detail="建议声称的来源指纹已不是当前索引来源",
        )
    return SuggestionValidity(
        verdict="valid",
        claimed_hash=claimed_hash,
        indexed_hash=indexed,
        requested_hash=requested,
        detail="来源指纹一致，建议保持有效资格",
    )
