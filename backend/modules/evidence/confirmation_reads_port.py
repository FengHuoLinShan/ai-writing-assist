"""确认记录只读 SPI 适配器 — 跨模块进度投影与用量归因经组合根注入消费。

依赖方向裁定（AO-5 / ADR-0031）：确认记录失效信号与任务结果归属的 owner
是 evidence；writing（作品进度投影，BR-1b）与 project（用量归因，BR-7）
只读消费该方向为冻结合法边，但单点 facade 消费按 AO-5 口径改 DI 键，
不新增函数内 import 语句（依赖方向棘轮只降不升）。组合根注册本适配器，
运行期经 ``core.container.get("evidence.confirmation_reads")`` 解析；
适配器只委托 evidence 自有 facade（经模块属性晚绑定，测试可按 facade
打桩），调用语义与原直连一致。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from modules.evidence.compilation import facade as compilation_facade

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession


class ConfirmationReadsPort:
    """确认记录只读视图：失效信号与任务结果归属。"""

    @staticmethod
    async def get_staleness_map(
        db: AsyncSession,
        *,
        novel_id: str,
        confirmation_ids: Sequence[str],
    ) -> dict[str, dict[str, Any]]:
        return await compilation_facade.get_confirmation_staleness(
            db,
            novel_id=novel_id,
            confirmation_ids=confirmation_ids,
        )

    @staticmethod
    async def describe_task_outcomes(
        db: AsyncSession,
        *,
        novel_id: str,
        task_ids: list[str],
    ) -> dict[str, dict]:
        return await compilation_facade.describe_confirmed_task_outcomes(
            db,
            novel_id=novel_id,
            task_ids=task_ids,
        )
