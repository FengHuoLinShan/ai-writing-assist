"""Review 检查策略协议"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.review.schemas import ReviewWarning


class CheckStrategy(ABC):
    """复查检查策略基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """策略唯一标识"""
        ...

    @abstractmethod
    async def check(
        self,
        db: AsyncSession,
        novel_id: str,
        candidate_payload: dict[str, Any],
    ) -> list[ReviewWarning]:
        """执行检查，返回警告列表"""
        ...
