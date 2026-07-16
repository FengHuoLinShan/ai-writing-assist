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

from modules.outline.analysis_context_facade import (  # noqa: F401
    get_outline_analysis_context,
)
from modules.outline.deep_import_repair_facade import (  # noqa: F401
    deprecate_deep_import_scenes_by_workflow,
    deprecate_deep_import_structure_assets_by_workflow,
    ensure_deep_import_structure_outputs,
    get_deep_import_fallback_thread_type,
    get_deep_import_structure_category_counts,
    get_deep_import_structure_category_targets,
    get_deep_import_structure_output_count,
    select_deep_import_fallback_reveal_target,
)
from modules.outline.foreshadowing_facade import (  # noqa: F401
    get_active_foreshadowing,
)
from modules.outline.reveal_facade import get_reader_reveal_decision  # noqa: F401
from modules.outline.scene_facade import (  # noqa: F401
    batch_create_scenes,
    bind_scene_spans_to_source,
    commit_deep_import_scene_candidates,
    count_scenes_by_novel,
    create_scene,
    get_next_scene_index,
    get_scene,
    get_scene_context_window,
    get_scene_contract,
    get_scene_span_coverage,
    get_scene_spans_by_chapter,
    get_scene_spans_for_scene,
    get_scene_summary_checkpoint,
    get_scenes_by_chapter,
    get_scenes_by_novel,
    get_scenes_by_provenance_key,
    get_scenes_by_provenance_keys,
    persist_deep_import_fusion_suggestions,
    rebuild_scene_summary_checkpoint,
    split_scene_chunk_to_new_chapter,
    update_scene,
)
from modules.outline.structure_dedup_facade import (  # noqa: F401
    apply_structure_dedup,
    apply_structure_dedup_group,
    suggest_structure_dedup,
)
from modules.outline.thread_facade import get_plot_threads_for_context  # noqa: F401

# Frozen cross-module API. New names require a deletion test, contract/README
# update, and an explicit change to the public-surface regression test.
__all__ = [
    "apply_structure_dedup",
    "apply_structure_dedup_group",
    "bind_scene_spans_to_source",
    "batch_create_scenes",
    "count_scenes_by_novel",
    "create_scene",
    "commit_deep_import_scene_candidates",
    "deprecate_deep_import_scenes_by_workflow",
    "deprecate_deep_import_structure_assets_by_workflow",
    "ensure_deep_import_structure_outputs",
    "get_active_foreshadowing",
    "get_deep_import_fallback_thread_type",
    "get_deep_import_structure_category_counts",
    "get_deep_import_structure_category_targets",
    "get_deep_import_structure_output_count",
    "get_next_scene_index",
    "get_outline_analysis_context",
    "get_plot_threads_for_context",
    "get_reader_reveal_decision",
    "get_scene",
    "get_scene_context_window",
    "get_scene_contract",
    "get_scene_spans_by_chapter",
    "get_scene_spans_for_scene",
    "get_scene_span_coverage",
    "get_scene_summary_checkpoint",
    "get_scenes_by_chapter",
    "get_scenes_by_novel",
    "get_scenes_by_provenance_key",
    "get_scenes_by_provenance_keys",
    "persist_deep_import_fusion_suggestions",
    "rebuild_scene_summary_checkpoint",
    "select_deep_import_fallback_reveal_target",
    "split_scene_chunk_to_new_chapter",
    "suggest_structure_dedup",
    "update_scene",
]
