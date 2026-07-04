"""Context Compiler 加载器协议"""

from __future__ import annotations

from abc import ABC, abstractmethod

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import CompileOptions, StructureContextBundle


class Loader(ABC):
    """数据加载器协议

    每个数据源实现一个 Loader，ContextCompiler 按 scope 调度。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """加载器名称（对应 SCOPE_LOADERS 中的 key）"""
        ...

    @abstractmethod
    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        """加载数据到 bundle"""
        ...
