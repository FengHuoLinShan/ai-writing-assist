#!/usr/bin/env python3
"""存量实体拼音回填脚本。

扫描 core_entities 中 pinyin_string IS NULL 的记录，
用 pypinyin.lazy_pinyin(name) 生成拼音字符串并批量更新。
部署模型前必须执行，否则 f2 退化为 0。
"""

from __future__ import annotations

import asyncio
import logging
import sys

from pypinyin import lazy_pinyin
from sqlalchemy import select, update

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from core.database import get_manager
from modules.world.models import CoreEntity

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BATCH_SIZE = 500


async def backfill() -> int:
    manager = get_manager()
    total_updated = 0

    async with manager.session_factory() as session:
        while True:
            stmt = (
                select(CoreEntity.id, CoreEntity.name)
                .where(CoreEntity.pinyin_string.is_(None))
                .limit(BATCH_SIZE)
            )
            result = await session.execute(stmt)
            rows = result.all()
            if not rows:
                break

            updates = []
            for entity_id, name in rows:
                try:
                    py = "".join(lazy_pinyin(name or ""))
                except Exception:
                    py = ""
                updates.append({"id": entity_id, "pinyin_string": py})

            if updates:
                await session.execute(
                    update(CoreEntity),
                    updates,
                )
                await session.commit()
                total_updated += len(updates)
                logger.info("Updated batch: %s (total %s)", len(updates), total_updated)

    logger.info("Backfill complete. Total updated: %s", total_updated)

    # 校验
    async with manager.session_factory() as session:
        stmt = select(CoreEntity).where(CoreEntity.pinyin_string.is_(None))
        result = await session.execute(stmt)
        remaining = len(result.all())
        if remaining:
            logger.error("Remaining rows with NULL pinyin_string: %s", remaining)
            return 1
        logger.info("Validation passed: no NULL pinyin_string remaining.")

    await manager.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(backfill()))
