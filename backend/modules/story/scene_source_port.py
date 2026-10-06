"""Scene 只读 SPI 适配器 — 低层模块经组合根注入消费 story 场景事实。

依赖方向裁定（AO-5 / ADR-0031）：story 场景事实（Scene contract、在场投影、
读者揭示决策、Scene memory 契约版本）的 owner 方向是
``{evidence, world} → story 只读消费``。该方向不得以顶层 import 实现：
消费方 contracts 声明 Protocol，组合根注册本适配器，运行期经
``core.container.get("story.scene_source")`` 解析。适配器只委托 story
自有 facade（经模块属性晚绑定，测试可按 facade 打桩），调用语义与原
直连一致。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from modules.story import facade as story_facade
from modules.story.continuity import contracts as continuity_contracts
from modules.story.outline_state import facade as outline_facade

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class SceneSourcePort:
    """story 场景事实的稳定只读视图。"""

    @staticmethod
    def scene_memory_current_version() -> int:
        return continuity_contracts.CURRENT_SCENE_MEMORY_CONTRACT_VERSION

    @staticmethod
    def scene_memory_v1_version() -> int:
        return continuity_contracts.SCENE_MEMORY_CONTRACT_V1

    @staticmethod
    def scene_memory_dimensions(contract_version: int) -> tuple[str, ...]:
        return continuity_contracts.scene_memory_dimensions(contract_version)

    @staticmethod
    async def get_scene_contract(
        db: AsyncSession, novel_id: str, scene_id: str
    ):
        return await outline_facade.get_scene_contract(db, novel_id, scene_id)

    @staticmethod
    async def project_scene_presence(
        db: AsyncSession, novel_id: str, *, through_scene_index: int
    ):
        return await story_facade.project_scene_presence(
            db, novel_id, through_scene_index=through_scene_index
        )

    @staticmethod
    async def get_reader_reveal_decision(
        db: AsyncSession,
        *,
        novel_id: str,
        target_type: str,
        target_id: str,
        cutoff_chapter: int,
    ):
        return await story_facade.get_reader_reveal_decision(
            db,
            novel_id=novel_id,
            target_type=target_type,
            target_id=target_id,
            cutoff_chapter=cutoff_chapter,
        )
