"""Manuscript 只读 SPI 适配器 — 低层模块经组合根注入消费 writing 正文稿。

依赖方向裁定（AO-5 / ADR-0031）：writing 拥有草稿/正文事实源（ADR-0004），
evidence 编译只读消费稿源区间与清单。该消费不得以 evidence→writing 顶层
import 实现：evidence 侧 contracts 声明 Protocol，组合根注册本适配器，
运行期经 ``core.container.get("writing.manuscript_source")`` 解析。适配器
只委托 writing 自有 facade（经模块属性晚绑定，测试可按 facade 打桩），
参数与返回值保持一致。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from modules.writing import facade as writing_facade

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from modules.evidence.contracts import SourceRangeRefContract


class ManuscriptSourcePort:
    """writing 正文稿的稳定只读视图（区间读取、引用构造、清单、字面扫描）。"""

    @staticmethod
    async def read_range(
        db: AsyncSession,
        novel_id: str,
        source_ref: SourceRangeRefContract,
        *,
        before: int = 3,
        after: int = 3,
        max_end_offset: int | None = None,
    ):
        return await writing_facade.read_manuscript_range(
            db,
            novel_id,
            source_ref,
            before=before,
            after=after,
            max_end_offset=max_end_offset,
        )

    @staticmethod
    async def build_range_ref(
        db: AsyncSession,
        novel_id: str,
        *,
        draft_id: str,
        start_offset: int,
        end_offset: int,
        content_mode: str,
    ):
        return await writing_facade.build_manuscript_range_ref(
            db,
            novel_id,
            draft_id=draft_id,
            start_offset=start_offset,
            end_offset=end_offset,
            content_mode=content_mode,
        )

    @staticmethod
    async def source_manifest(
        db: AsyncSession, novel_id: str, **kwargs: Any
    ) -> list[dict]:
        return await writing_facade.get_manuscript_source_manifest(db, novel_id, **kwargs)

    @staticmethod
    async def scan_terms(
        db: AsyncSession, novel_id: str, terms: list[str], **kwargs: Any
    ):
        return await writing_facade.scan_manuscript_terms(db, novel_id, terms, **kwargs)
