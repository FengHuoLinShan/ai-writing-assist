"""当前 Scene 卡加载器"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from modules.evidence.compilation.contracts import CompileOptions, StructureContextBundle
from modules.evidence.compilation.services.protocol import Loader

_GetSceneContractFn = Callable[..., Awaitable[Any]]


async def _default_get_scene_contract(*args: Any, **kwargs: Any) -> Any:
    from modules.story.facade import get_scene_contract

    return await get_scene_contract(*args, **kwargs)


class SceneLoader(Loader):
    """加载当前 Scene 卡作为 Scene Blueprint 来源"""

    def __init__(
        self,
        get_scene_contract_fn: _GetSceneContractFn = _default_get_scene_contract,
    ) -> None:
        self._get_scene_contract = get_scene_contract_fn

    @property
    def name(self) -> str:
        return "scene"

    async def load(
        self,
        db: AsyncSession,
        options: CompileOptions,
        bundle: StructureContextBundle,
    ) -> None:
        if not options.scene_id:
            bundle.budget_used["scene"] = 0
            return

        scene_contract = await self._get_scene_contract(
            db,
            options.novel_id,
            options.scene_id,
        )
        scene = (
            scene_contract
            if isinstance(scene_contract, dict)
            else asdict(scene_contract)
            if scene_contract is not None
            else None
        )
        if scene is None:
            bundle.budget_used["scene"] = 0
            bundle.warnings.append(f"Scene {options.scene_id} 不存在")
            return

        bundle.scene = scene
        bundle.budget_used["scene"] = 1
        if scene.get("pov_character_id") and not options.viewpoint_character_id:
            bundle.warnings.append("当前 Scene 有默认 POV 人物，但请求未指定视角人物")
