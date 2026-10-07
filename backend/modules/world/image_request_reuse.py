"""图片请求幂等复用（B9）。

幂等键 = sha256(novel_id + owner + 状态快照哈希 + prompt + 模型 + 参数)，
必须含租户维度；查询必带 novel_id 过滤。资产层读时校验（字节数 +
SHA-256），不符即删记录按未命中处理。同参数「重新生成」走 force
路径：跳过查询并作废旧记录。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.stable_hash import stable_hash
from modules.world.models.image_request_reuse import ImageRequestReuse


def compute_request_hash(
    *,
    novel_id: str,
    owner_id: str,
    state_snapshot_hash: str,
    prompt: str,
    model: str,
    params: dict[str, Any] | None = None,
) -> str:
    """租户维度内的请求内容指纹：任何影响生成结果的输入都进哈希。"""
    return stable_hash(
        {
            "novel_id": str(novel_id),
            "owner_id": str(owner_id),
            "state": str(state_snapshot_hash),
            "prompt": str(prompt),
            "model": str(model),
            "params": params or {},
        },
        stringify_unknown=False,
    )


# 资产校验器：返回 (bytes, sha256, width, height) 或 None（资产缺失/损坏）。
AssetValidator = Callable[[ImageRequestReuse], Awaitable[tuple | None]]


async def find_reusable_asset(
    db: AsyncSession,
    *,
    novel_id: str,
    owner_id: str,
    request_hash: str,
    validate_asset: AssetValidator,
) -> dict | None:
    """命中且资产校验通过时返回复用信息；损坏即删记录按未命中。"""
    row = (
        await db.execute(
            select(ImageRequestReuse)
            .where(
                ImageRequestReuse.novel_id == UUID(str(novel_id)),
                ImageRequestReuse.request_hash == request_hash,
                ImageRequestReuse.owner_id == UUID(str(owner_id)),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    verified = await validate_asset(row)
    if verified is None:
        # 损坏对象不被复用：删除登记，下次重新生成并重新登记。
        await db.execute(delete(ImageRequestReuse).where(ImageRequestReuse.id == row.id))
        await db.flush()
        return None
    data, sha256, width, height = verified
    if sha256 and row.asset_sha256 and sha256 != row.asset_sha256:
        await db.execute(delete(ImageRequestReuse).where(ImageRequestReuse.id == row.id))
        await db.flush()
        return None
    row.reuse_count += 1
    row.reused_at = datetime.now(UTC)
    await db.flush()
    return {
        "object_key": row.object_key,
        "asset": data,
        "asset_sha256": sha256,
        "byte_size": len(data) if data is not None else row.byte_size,
        "width": width,
        "height": height,
        "provider": row.provider,
        "model": row.model,
        "created_from_id": str(row.created_from_id) if row.created_from_id else None,
    }


async def record_reusable_asset(
    db: AsyncSession,
    *,
    novel_id: str,
    owner_id: str,
    request_hash: str,
    source_type: str,
    object_key: str,
    provider: str = "",
    model: str = "",
    asset_sha256: str | None = None,
    asset_data: bytes | None = None,
    byte_size: int | None = None,
    width: int | None = None,
    height: int | None = None,
    created_from_id: str | UUID | None = None,
) -> ImageRequestReuse:
    """登记（或覆盖）一条可复用资产。同参数重新生成时覆盖旧记录。"""
    novel_uuid = UUID(str(novel_id))
    owner_uuid = UUID(str(owner_id))
    row = (
        await db.execute(
            select(ImageRequestReuse)
            .where(
                ImageRequestReuse.novel_id == novel_uuid,
                ImageRequestReuse.owner_id == owner_uuid,
                ImageRequestReuse.request_hash == request_hash,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if row is None:
        row = ImageRequestReuse(
            novel_id=novel_uuid,
            owner_id=owner_uuid,
            request_hash=request_hash,
            source_type=source_type,
            object_key=object_key,
        )
        try:
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError:
            # 只撤回本次插入，保留调用方已写入的图片与完成状态。
            row = (
                await db.execute(
                    select(ImageRequestReuse)
                    .where(
                        ImageRequestReuse.novel_id == novel_uuid,
                        ImageRequestReuse.owner_id == owner_uuid,
                        ImageRequestReuse.request_hash == request_hash,
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalar_one_or_none()
            if row is None:
                raise
    row.owner_id = owner_uuid
    row.source_type = source_type
    row.object_key = object_key
    row.provider = provider
    row.model = model
    row.asset_sha256 = asset_sha256
    row.asset_data = asset_data
    row.byte_size = byte_size
    row.width = width
    row.height = height
    row.created_from_id = UUID(str(created_from_id)) if created_from_id else None
    row.reuse_count = 0
    row.reused_at = None
    await db.flush()
    return row


async def invalidate_reusable_asset(
    db: AsyncSession,
    *,
    novel_id: str,
    request_hash: str,
) -> None:
    """作废一条复用登记（force 重新生成前调用，避免命中旧资产）。"""
    await db.execute(
        delete(ImageRequestReuse).where(
            ImageRequestReuse.novel_id == UUID(str(novel_id)),
            ImageRequestReuse.request_hash == request_hash,
        )
    )
    await db.flush()
