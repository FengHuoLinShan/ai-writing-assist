"""真实编译验收：克莱恩视角下 hidden_truth 不泄露。"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.database import get_manager
from modules.context.facade import compile_with_tiers
from modules.context.markdown_renderer import render_compiled_context


async def main() -> None:
    manager = get_manager()
    async with manager.session() as db:
        # 1. 创建种子数据
        from tests.e2e.seed_data import create_full_scene

        seed = await create_full_scene(db)
        novel_id = seed["project_id"]
        entity_ids = seed["entity_ids"]
        scene_ids = seed["scene_ids"]
        klein_id = entity_ids["克莱恩·莫雷蒂"]
        scene_0_id = scene_ids[0]

        # 2. 以克莱恩视角编译第 0 幕
        ctx = await compile_with_tiers(
            db,
            novel_id=novel_id,
            task="以克莱恩视角续写第 0 幕",
            scope="chapter",
            scene_id=scene_0_id,
            budget_tokens=4000,
            reveal_mode="character",
            viewpoint_character_id=klein_id,
        )
        md = render_compiled_context(ctx)

        # 3. 验证 hidden_truth 不泄露
        leaked = []
        hidden_truths = {
            "源堡": "诡秘之主的唯一性",
            "克莱恩·莫雷蒂": "来自另一个世界的穿越者",
            "罗塞尔日记": "包含序列途径的秘密",
        }
        for name, secret in hidden_truths.items():
            if secret in md:
                leaked.append(f"{name}: {secret}")

        print(md[:2000])
        print(f"\n总 tokens: {ctx.total_tokens} / {ctx.budget_tokens}")
        print(f"驱逐段: {ctx.evicted_keys}")
        print(f"截断段: {ctx.truncated_keys}")

        if leaked:
            print(f"\n❌ hidden_truth leaked into character context: {leaked}")
            await manager.close()
            sys.exit(1)
        print("\n✅ Acceptance passed: hidden_truth not leaked")

    await manager.close()


if __name__ == "__main__":
    asyncio.run(main())
