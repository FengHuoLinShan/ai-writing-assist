"""Scene checkpoint 来源基线（M4 契约 §3）。

系统行构建时记录的环境基线：重放窗口（scene_index ≤ 目标）内各 Scene 罩住的
working 稿指纹切片 + 窗口内场景结构 + Scene memory 契约版本。视图读时用同一
helper 重算比对，绕过失效钩子的正文/结构变更不再静默供给旧投影。

设计约束：
- 不参与 ``source_hash`` 投影链语义与幂等短路；``replace_system`` 的无变化短路
  保留旧行旧基线，待核对标记因此保持到事件层追上后重建换行。
- 稿源取 working 模式（scene memory 事件链派生自 working 稿，evolution 失效钩子
  也只挂 working 变更）；发布口径的章快照不在本基线范围。
- manual/confirmed 作者行不记基线、不参与比对（作者决定不因环境漂移降级）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.stable_hash import stable_hash
from modules.story.continuity.contracts import CURRENT_SCENE_MEMORY_CONTRACT_VERSION
from modules.writing.facade import get_manuscript_source_manifest


async def compute_scene_basis(
    db: AsyncSession,
    novel_id: str,
    scenes: list[dict[str, Any]],
    *,
    up_to_scene_index: int,
) -> dict[str, Any]:
    """计算 scene_index ≤ up_to_scene_index 重放窗口的环境基线。"""
    window = [
        scene for scene in scenes if int(scene["scene_index"]) <= int(up_to_scene_index)
    ]
    chapters = sorted(
        {int(chapter) for scene in window for chapter in (scene.get("chapter_ids") or [])}
    )
    manuscript: dict[str, str] = {}
    if chapters:
        manifest = await get_manuscript_source_manifest(
            db,
            novel_id,
            content_mode="working",
            chapter_from=chapters[0],
            chapter_to=chapters[-1],
        )
        for row in manifest:
            manuscript[str(row["chapter_index"])] = str(row["source_hash"])
    return {
        "contract_version": CURRENT_SCENE_MEMORY_CONTRACT_VERSION,
        "manuscript": manuscript,
        "scenes": [
            [
                str(scene["id"]),
                int(scene["scene_index"]),
                [int(chapter) for chapter in (scene.get("chapter_ids") or [])],
            ]
            for scene in window
        ],
    }


def basis_hash(basis: dict[str, Any] | None) -> str | None:
    """基线缺失返回 None；否则返回稳定指纹供比对。"""
    if not basis:
        return None
    return stable_hash(basis)
