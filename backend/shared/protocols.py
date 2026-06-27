"""
跨模块共享协议（Seam 定义）

放置需要被多个模块共同依赖的抽象协议。
实现放在各自模块中，通过注册/注入方式绑定。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


class DraftProvider(ABC):
    """正文草稿提供者协议

    用于反转 world → writing/rag 的依赖方向。
    world 模块只依赖此协议，不依赖具体实现。
    """

    @abstractmethod
    async def load_chapters(
        self,
        db: AsyncSession,
        novel_id: str,
        start_chapter: int,
        end_chapter: int,
    ) -> list[dict[str, Any]]:
        """加载指定范围的章节正文"""
        ...
