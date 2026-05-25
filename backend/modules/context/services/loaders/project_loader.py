"""项目元信息加载器"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import StructureContextBundle
from modules.context.services.protocol import Loader
from modules.context.services.types import CompileOptions

logger = logging.getLogger(__name__)


class ProjectLoader(Loader):
    """加载项目元信息"""

    @property
    def name(self) -> str:
        return "project"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        from modules.project.facade import get_project_context

        ctx = await get_project_context(db, options.novel_id)
        if ctx is not None:
            bundle.project = ctx.model_dump()
        else:
            bundle.warnings.append(f"项目 {options.novel_id} 不存在")
