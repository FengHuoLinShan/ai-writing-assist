"""当前 Scene 卡加载器"""

from __future__ import annotations

from dataclasses import asdict

from sqlalchemy.ext.asyncio import AsyncSession

from modules.context.contracts import CompileOptions, StructureContextBundle
from modules.context.services.protocol import Loader


class SceneLoader(Loader):
    """加载当前 Scene 卡作为 Scene Blueprint 来源"""

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
            return

        from modules.outline.facade import get_scene_contract

        scene_contract = await get_scene_contract(db, options.novel_id, options.scene_id)
        scene = (
            scene_contract
            if isinstance(scene_contract, dict)
            else asdict(scene_contract)
            if scene_contract is not None
            else None
        )
        if scene is None:
            bundle.warnings.append(f"Scene {options.scene_id} 不存在")
            return

        bundle.scene = scene
        if scene.get("pov_character_id") and not options.viewpoint_character_id:
            bundle.warnings.append("当前 Scene 有默认 POV 人物，但请求未指定视角人物")
