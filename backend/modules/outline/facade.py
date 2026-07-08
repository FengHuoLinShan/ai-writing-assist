"""
Outline Facade — 对外入口 (re-export hub)

其他模块只能从 facade 导入 outline 功能。
Facade 不写复杂业务逻辑，只做稳定的对外代理。

子 facade 按 seam 拆分：
  scene_facade              — Scene 读取、创建和跨模块 SceneContract
  structure_dedup_facade    — outline 结构资产智能去重
  deep_import_repair_facade — deep import 修复与清理
  foreshadowing_facade      — 伏笔只读上下文
"""

from modules.outline.deep_import_repair_facade import (  # noqa: F401
    deprecate_deep_import_scenes_by_workflow,
    deprecate_deep_import_structure_assets_by_workflow,
    ensure_deep_import_structure_minimums,
    ensure_deep_import_structure_outputs,
    get_deep_import_fallback_thread_type,
    get_deep_import_structure_category_counts,
    get_deep_import_structure_category_targets,
    get_deep_import_structure_counts,
    get_deep_import_structure_output_count,
    get_deep_import_structure_payload,
    reindex_scenes_for_deep_import_repair,
)
from modules.outline.foreshadowing_facade import (  # noqa: F401
    get_active_foreshadowing,
)
from modules.outline.scene_facade import (  # noqa: F401
    batch_create_scenes,
    count_scenes_by_novel,
    create_scene,
    get_next_scene_index,
    get_scene,
    get_scene_contract,
    get_scenes_by_chapter,
    get_scenes_by_novel,
    get_scenes_by_provenance_key,
    get_scenes_by_provenance_keys,
    split_scene_chunk_to_new_chapter,
    update_scene,
)
from modules.outline.structure_dedup_facade import (  # noqa: F401
    apply_structure_dedup,
    suggest_structure_dedup,
)

__all__ = [
    "apply_structure_dedup",
    "batch_create_scenes",
    "count_scenes_by_novel",
    "create_scene",
    "deprecate_deep_import_scenes_by_workflow",
    "deprecate_deep_import_structure_assets_by_workflow",
    "ensure_deep_import_structure_minimums",
    "ensure_deep_import_structure_outputs",
    "get_active_foreshadowing",
    "get_deep_import_fallback_thread_type",
    "get_deep_import_structure_category_counts",
    "get_deep_import_structure_category_targets",
    "get_deep_import_structure_counts",
    "get_deep_import_structure_output_count",
    "get_deep_import_structure_payload",
    "get_next_scene_index",
    "get_scene",
    "get_scene_contract",
    "get_scenes_by_chapter",
    "get_scenes_by_novel",
    "get_scenes_by_provenance_key",
    "get_scenes_by_provenance_keys",
    "reindex_scenes_for_deep_import_repair",
    "split_scene_chunk_to_new_chapter",
    "suggest_structure_dedup",
    "update_scene",
]
