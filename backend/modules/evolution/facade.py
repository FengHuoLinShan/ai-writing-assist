"""Stable domain entry points for source mutations; no model work is started."""

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


__all__ = [
    "apply_scene_reorder_invalidation",
    "record_writing_source_change",
    "switch_project_engine",
    "read_committed_understanding",
    "require_current_world_candidate",
    "require_current_structure_candidate",
]
