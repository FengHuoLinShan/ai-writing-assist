"""派生消费者有效性缝（V4 G2 / 验收 T17）。

建议不持有独立事实（A 审计边界）：它的"有效资格"来自所声称的来源指纹
是否仍是当前已索引的来源。原文撤回/修改后，证据索引的 requested 与
indexed 指纹分叉——旧建议立即失去有效资格，历史记录仍可查看（失效不
删历史）。

指纹读取经 ``modules.evidence.facade`` 的薄缝
（``read_chapter_index_fingerprint``），不触碰 evidence 内部模块。

world 知识与地图册资产的有效性缝仍属 V/MI 系列（见
``invalidation.UNSUPPORTED_CONSUMERS``），不以本模块冒充全量接线。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

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
    from modules.evidence.facade import read_chapter_index_fingerprint

    fingerprint = await read_chapter_index_fingerprint(
        db,
        novel_id,
        chapter_index,
        content_mode=content_mode,
    )
    if fingerprint is None:
        return SuggestionValidity(
            verdict="unknown",
            claimed_hash=claimed_hash,
            detail="该章尚无索引状态，无法证明来源有效",
        )
    requested = fingerprint.get("requested_hash")
    indexed = fingerprint.get("indexed_hash")
    if requested != indexed or (
        indexed is not None
        and (
            not fingerprint.get("requested_source_id")
            or fingerprint.get("requested_source_id")
            != fingerprint.get("indexed_source_id")
        )
    ):
        # 新来源已请求、尚未完成重建：任何旧来源的派生物立即失效。
        return SuggestionValidity(
            verdict="stale",
            claimed_hash=claimed_hash,
            indexed_hash=indexed,
            requested_hash=requested,
            detail="来源已变化待重建：旧建议立即失效，历史可查看",
        )
    if indexed is None:
        # 有索引状态但没有任何已索引指纹：无法证明一致（返修 P2）。
        return SuggestionValidity(
            verdict="unknown",
            claimed_hash=claimed_hash,
            indexed_hash=indexed,
            requested_hash=requested,
            detail="索引状态存在但尚无已索引指纹，无法证明来源有效",
        )
    if claimed_hash is None:
        # 声称侧为空：没有可对照的指纹就不能宣称一致（返修 P2）。
        return SuggestionValidity(
            verdict="unknown",
            claimed_hash=claimed_hash,
            indexed_hash=indexed,
            requested_hash=requested,
            detail="建议未声称来源指纹，无法证明一致",
        )
    if claimed_hash != indexed:
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
