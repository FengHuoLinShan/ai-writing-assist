"""Stable domain entry points for source mutations; no model work is started."""

from modules.evolution.consumption import (
    CONSUMPTION_REGISTRY_STATE_KEY,
    read_consumption_records,
)
from modules.evolution.impact import receipt_view
from modules.evolution.invalidation import (
    apply_scene_reorder_invalidation,
    record_writing_source_change,
)
from modules.evolution.ownership import switch_project_engine
from modules.evolution.reading import (
    read_committed_understanding,
    require_current_world_candidate,
)


async def require_current_structure_candidate(db, novel_id, reference, asset_id):
    from modules.evolution.structure import require_current_structure_candidate as require

    await require(db, novel_id, reference, asset_id)


def register_scene_consumption(
    state: dict,
    *,
    novel_id: str,
    scene_id: str,
    scene_index: int,
    dimension: str,
    chapters: list[dict],
    method_version: str,
    checkpoint_id: str | None = None,
    content_mode: str = "working",
) -> list[dict]:
    """Story 侧（B 类接线）实际消费登记出口：写入产物行 state JSON。

    story→evolution 无顶层依赖边（写入端函数在调用点导入），本出口把
    ``registration`` 的构建与幂等合并暴露给投影写入路径——投影每建一行
    checkpopint 就登记它实际读取的稿件范围/版本与所依据的 checkpoint 锚，
    失效评估才有真实登记可查（不再只靠锚定结构合成）。
    """
    from modules.evolution.registration import (
        register_consumption,
        scene_checkpoint_registration,
    )

    record = scene_checkpoint_registration(
        novel_id,
        scene_id=scene_id,
        scene_index=scene_index,
        dimension=dimension,
        chapters=chapters,
        method_version=method_version,
        content_mode=content_mode,
        checkpoint_id=checkpoint_id,
    )
    return register_consumption(state, record)


__all__ = [
    "apply_scene_reorder_invalidation",
    "record_writing_source_change",
    "receipt_view",
    "register_scene_consumption",
    "CONSUMPTION_REGISTRY_STATE_KEY",
    "read_consumption_records",
    "switch_project_engine",
    "read_committed_understanding",
    "require_current_world_candidate",
    "require_current_structure_candidate",
]
